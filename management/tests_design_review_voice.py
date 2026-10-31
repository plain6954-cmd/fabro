import io
import math
import wave
from array import array
from pathlib import Path
from unittest.mock import patch

import av
from django.conf import settings
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import transaction
from django.test import TestCase, override_settings
from django.urls import reverse

from management.models import (ApprovalRoles, DesignReviewVoiceNote, Notification,
    PatternDesignImage, WorkflowRoles)
from management.services.design_approvals import record_design_review_decision, submit_design_for_approval
from management.services.design_pdfs import design_file_storage
from management.services.design_review_voice import validate_voice_recording


def recording(seconds=1):
    output = io.BytesIO()
    with wave.open(output, 'wb') as target:
        target.setnchannels(1)
        target.setsampwidth(2)
        target.setframerate(16000)
        target.writeframes(array('h', (int(12000 * (n % 16000) / 16000 * math.sin(n / 12))
            for n in range(int(seconds * 16000)))).tobytes())
    return output.getvalue()


def upload(content=None):
    return SimpleUploadedFile('untrusted-name.webm', recording() if content is None else content, content_type='audio/webm')


class DesignReviewVoiceTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.designer = User.objects.create_user('voice_designer')
        cls.other = User.objects.create_user('voice_other')
        cls.cad = User.objects.create_user('voice_cad', first_name='CAD Reviewer')
        cls.ed = User.objects.create_user('voice_ed')
        cls.md = User.objects.create_user('voice_md')
        cls.om = User.objects.create_user('voice_om')
        cls.factory = User.objects.create_user('voice_factory')
        cls.admin = User.objects.create_superuser('voice_admin', 'admin@example.com', 'unused')
        for user, role in ((cls.designer, None), (cls.other, None), (cls.cad, ApprovalRoles.CAD),
                          (cls.ed, ApprovalRoles.ED), (cls.md, ApprovalRoles.MD), (cls.om, ApprovalRoles.OM)):
            profile = user.workflow_profile
            profile.role = WorkflowRoles.APPROVER if role else WorkflowRoles.FREELANCE_3D_DESIGNER
            profile.approval_role = role or ''
            profile.save()
        profile = cls.factory.workflow_profile
        profile.role = WorkflowRoles.FACTORY_EXECUTIVE
        profile.save()

    def setUp(self):
        self.image = PatternDesignImage.objects.create(uploaded_by=self.designer,
            image='existing.png', title='Voice review design')
        with patch('management.services.push_notifications.send_push_to_user'):
            self.approval = submit_design_for_approval(self.image, self.designer)
        Notification.objects.all().delete()
        self.client.force_login(self.cad)
        self.cleanup_names = []

    def tearDown(self):
        names = self.cleanup_names + list(DesignReviewVoiceNote.objects.values_list('file', flat=True))
        for name in names:
            design_file_storage(name).delete(name)

    def post(self, user=None, decision='approve', **overrides):
        if user:
            self.client.force_login(user)
        payload = dict(stage='cad', change_type='minor', comment='', voice_note=upload())
        payload.update(overrides)
        return self.client.post(reverse('approve_design_image_api' if decision == 'approve' else 'reject_design_image_api',
            args=[self.image.pk]), payload)

    def note(self):
        self.assertEqual(self.post().status_code, 200)
        return DesignReviewVoiceNote.objects.get()

    def test_content_decoded_duration_waveform_and_canonical_wav(self):
        data, duration, bars = validate_voice_recording(upload())
        self.assertEqual(duration, 1000)
        self.assertEqual(len(bars), 32)
        self.assertGreater(len(set(bars)), 10)
        with wave.open(io.BytesIO(data)) as source:
            self.assertEqual((source.getnchannels(), source.getframerate(), source.getnframes()), (1, 16000, 16000))

    def test_browser_webm_ogg_and_mp4_are_decoded(self):
        for container_format, codec in [('webm', 'libopus'), ('ogg', 'libopus'), ('mp4', 'aac')]:
            with self.subTest(format=container_format):
                output = io.BytesIO()
                with av.open(output, 'w', format=container_format) as dest:
                    stream = dest.add_stream(codec, rate=48000)
                    stream.layout = 'mono'
                    resampler = av.AudioResampler(format='fltp' if codec == 'aac' else 's16', layout='mono', rate=48000)
                    with av.open(io.BytesIO(recording())) as source:
                        for frame in source.decode(audio=0):
                            for converted in resampler.resample(frame):
                                for packet in stream.encode(converted):
                                    dest.mux(packet)
                    for converted in resampler.resample(None):
                        for packet in stream.encode(converted):
                            dest.mux(packet)
                    for packet in stream.encode(None):
                        dest.mux(packet)
                data, duration, _ = validate_voice_recording(upload(output.getvalue()))
                self.assertTrue(data.startswith(b'RIFF'))
                self.assertTrue(950 <= duration <= 1100, duration)

    def test_invalid_empty_oversize_and_overlong_rejected_without_mutation(self):
        for content in [b'', b'<html>fake audio</html>', b'x' * (5 * 1024 * 1024 + 1), recording(60.1)]:
            with self.subTest(size=len(content)), patch('management.services.push_notifications.send_push_to_user') as push:
                with self.captureOnCommitCallbacks(execute=True):
                    self.assertEqual(self.post(voice_note=upload(content)).status_code, 400)
                push.assert_not_called()
                self.assertFalse(DesignReviewVoiceNote.objects.exists())
                self.assertFalse(Notification.objects.exists())
                self.approval.refresh_from_db()
                self.assertEqual(self.approval.cad_status, 'pending')

    def test_voice_only_attaches_to_real_reviewer_and_existing_event(self):
        with patch('management.services.push_notifications.send_push_to_user') as push:
            with self.captureOnCommitCallbacks(execute=True):
                response = self.post(reviewer_id=self.ed.pk, reviewer_name='Spoofed')
                push.assert_not_called()
            self.assertEqual(response.status_code, 200)
            push.assert_called_once()
            self.assertEqual(push.call_args.args[0], self.designer)
            self.assertEqual(push.call_args.kwargs['url'], reverse('design_approval_detail', args=[self.image.pk]))
            self.assertNotIn('private_design_voice', str(push.call_args))
        note = DesignReviewVoiceNote.objects.get()
        self.assertEqual((note.approval_id, note.reviewer_id, note.stage), (self.approval.pk, self.cad.pk, 'CAD'))
        self.assertEqual(note.reviewer_name, 'CAD Reviewer')
        self.assertRegex(note.file.name, r'^private_design_voice_notes/[0-9a-f]{32}\.wav$')
        self.assertEqual(Notification.objects.filter(recipient=self.designer).count(), 1)
        self.assertEqual(Notification.objects.count(), 1)
        self.approval.refresh_from_db()
        self.assertEqual(self.approval.cad_comment, '')
        self.assertEqual(self.approval.cad_change_type, 'minor')
        private = Path(design_file_storage(note.file.name).path(note.file.name))
        self.assertFalse(private.is_relative_to(settings.MEDIA_ROOT))

    def test_combined_decline_keeps_exact_remarks_and_classification(self):
        text = '  Keep these dimensions\nSecond line  '
        self.assertEqual(self.post(decision='reject', comment=text, change_type='major').status_code, 200)
        self.approval.refresh_from_db()
        self.image.refresh_from_db()
        self.assertEqual((self.approval.cad_comment, self.approval.cad_change_type), (text, 'major'))
        self.assertEqual(self.image.approval_status, 'rejected')
        self.assertEqual(DesignReviewVoiceNote.objects.count(), 1)

    def test_existing_permissions_and_minor_major_remain_required(self):
        for user in (self.om, self.designer, self.factory):
            self.assertEqual(self.post(user=user).status_code, 403)
        self.assertEqual(self.post(user=self.cad, stage='ed').status_code, 403)
        self.assertEqual(self.post(change_type='').status_code, 400)
        self.assertFalse(DesignReviewVoiceNote.objects.exists())

    def test_duplicate_review_cannot_create_another_note_file_or_notification(self):
        self.note()
        before = Notification.objects.count()
        with patch('management.services.design_review_voice.validate_voice_recording') as decoder:
            self.assertEqual(self.post().status_code, 409)
            decoder.assert_not_called()
        self.assertEqual(DesignReviewVoiceNote.objects.count(), 1)
        self.assertEqual(Notification.objects.count(), before)

    def test_review_completed_during_decode_cleans_the_losing_upload(self):
        def finish_in_another_request(file):
            decoded = validate_voice_recording(file)
            record_design_review_decision(self.image, self.cad, 'approved', change_type='minor')
            return decoded
        from management.services.design_review_voice import delete_voice_file
        with patch('management.services.design_review_voice.validate_voice_recording', side_effect=finish_in_another_request):
            with patch('management.services.design_review_voice.delete_voice_file', wraps=delete_voice_file) as cleanup:
                self.assertEqual(self.post().status_code, 409)
                cleanup.assert_called_once()
                name = cleanup.call_args.args[0]
                self.assertFalse(design_file_storage(name).exists(name))
        self.assertFalse(DesignReviewVoiceNote.objects.exists())
        self.assertEqual(Notification.objects.count(), 1)

    def test_csrf_is_required_for_voice_submission(self):
        from django.test import Client
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.cad)
        response = client.post(reverse('approve_design_image_api', args=[self.image.pk]),
            dict(stage='cad', change_type='minor', voice_note=upload()))
        self.assertEqual(response.status_code, 403)
        self.assertFalse(DesignReviewVoiceNote.objects.exists())

    def test_serialized_audio_history_uses_detail_permissions(self):
        from management.views import _serialize_design_image_details
        self.note()
        # Even an approved image visible in the shared gallery must not expose
        # another designer's private review recording.
        PatternDesignImage.objects.filter(pk=self.image.pk).update(approval_status='approved')
        self.image.refresh_from_db()
        for user, expected in [(self.other, 0), (self.factory, 0), (self.designer, 1), (self.om, 1)]:
            history = _serialize_design_image_details(self.image, user)['history']
            self.assertEqual(len(history[0]['voice_notes']), expected)

    def test_audio_authentication_and_authorization(self):
        note = self.note()
        url = reverse('design_review_voice_audio', args=[note.pk])
        self.client.logout()
        self.assertEqual(self.client.get(url).status_code, 302)
        for user, status in [(self.designer, 200), (self.cad, 200), (self.ed, 200), (self.md, 200),
                             (self.om, 200), (self.admin, 200), (self.factory, 403), (self.other, 404)]:
            self.client.force_login(user)
            response = self.client.get(url)
            self.assertEqual(response.status_code, status)
            response.close()
        PatternDesignImage.objects.filter(pk=self.image.pk).update(approval_status='approved')
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(url).status_code, 404)
        self.assertEqual(self.client.get('/media/' + note.file.name).status_code, 404)

    def test_private_audio_ranges_are_seekable_and_no_store(self):
        note = self.note()
        url = reverse('design_review_voice_audio', args=[note.pk])
        response = self.client.get(url)
        data = b''.join(response.streaming_content)
        self.assertEqual(response['Content-Type'], 'audio/wav')
        self.assertEqual(response['X-Content-Type-Options'], 'nosniff')
        self.assertIn('private', response['Cache-Control'])
        self.assertIn('no-store', response['Cache-Control'])
        for header, expected in [('bytes=0-43', data[:44]), ('bytes=44-', data[44:]), ('bytes=-20', data[-20:])]:
            partial = self.client.get(url, HTTP_RANGE=header)
            self.assertEqual(partial.status_code, 206)
            self.assertEqual(partial.content, expected)
        for header in ['bytes=99999999-', 'bytes=-0', 'bytes=6-2', 'bytes=0-1,3-4', 'bytes=-']:
            self.assertEqual(self.client.get(url, HTTP_RANGE=header).status_code, 416)

    @override_settings(USE_S3_STORAGE=True, STORAGES={
        'default': {'BACKEND': 'management.storage_backends.S3Storage'},
        'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
    })
    def test_existing_private_s3_adapter_is_reused_without_exposing_signed_urls(self):
        with patch('management.storage_backends.get_object_info', side_effect=FileNotFoundError), \
             patch('management.storage_backends.upload_content') as store, \
             patch('management.storage_backends.download_content', return_value=recording()) as read, \
             patch('management.storage_backends.create_signed_download_url') as signed_url:
            note = self.note()
            store.assert_called_once()
            self.assertEqual(store.call_args.args[0], note.file.name)
            self.assertTrue(store.call_args.args[1].startswith(b'RIFF'))
            response = self.client.get(reverse('design_review_voice_audio', args=[note.pk]), HTTP_RANGE='bytes=0-43')
            self.assertEqual(response.status_code, 206)
            self.assertEqual(response.content, recording()[:44])
            read.assert_called_once_with(note.file.name)
            signed_url.assert_not_called()

    def test_native_form_storage_error_is_generic_and_does_not_leak_paths(self):
        with patch('management.services.design_review_voice.design_file_storage') as storage:
            storage.return_value.save.side_effect = OSError('private bucket credentials or path')
            response = self.client.post(reverse('design_approval_detail', args=[self.image.pk]),
                dict(action='review', stage='cad', decision='approved', change_type='minor', voice_note=upload()), follow=True)
        self.assertContains(response, 'Review could not be saved. Please retry.')
        self.assertNotContains(response, 'private bucket credentials or path')
        self.assertFalse(DesignReviewVoiceNote.objects.exists())

    def test_failed_attachment_rolls_back_decision_audit_and_notification_and_deletes_file(self):
        from management.models import ActivityLog
        before = ActivityLog.objects.count()
        with patch('management.services.design_review_voice.DesignReviewVoiceNote.objects.create', side_effect=RuntimeError('save failed')):
            with patch('management.services.design_review_voice.delete_voice_file', wraps=__import__('management.services.design_review_voice', fromlist=['delete_voice_file']).delete_voice_file) as cleanup:
                self.assertEqual(self.post().status_code, 503)
                cleanup.assert_called_once()
                self.assertFalse(design_file_storage(cleanup.call_args.args[0]).exists(cleanup.call_args.args[0]))
        self.approval.refresh_from_db()
        self.assertEqual(self.approval.cad_status, 'pending')
        self.assertEqual(ActivityLog.objects.count(), before)
        self.assertFalse(Notification.objects.exists())

    def test_storage_failure_does_not_record_decision(self):
        with patch('management.services.design_review_voice.design_file_storage') as storage:
            storage.return_value.save.side_effect = OSError('unavailable')
            self.assertEqual(self.post().status_code, 503)
        self.approval.refresh_from_db()
        self.assertEqual(self.approval.cad_status, 'pending')
        self.assertFalse(Notification.objects.exists())

    def test_push_runs_after_note_exists_and_failure_does_not_break_review(self):
        def fail(*args, **kwargs):
            self.assertTrue(DesignReviewVoiceNote.objects.exists())
            raise OSError('delivery unavailable')
        with patch('management.services.push_notifications.send_push_to_user', side_effect=fail) as push:
            with self.captureOnCommitCallbacks(execute=True):
                self.assertEqual(self.post().status_code, 200)
            push.assert_called_once()
        self.assertEqual(DesignReviewVoiceNote.objects.count(), 1)

    def test_committed_deletion_cleans_private_file_but_rollback_keeps_it(self):
        note = self.note()
        name = note.file.name
        self.cleanup_names.append(name)
        with self.assertRaises(RuntimeError), transaction.atomic():
            note.delete()
            raise RuntimeError('rolled back')
        note = DesignReviewVoiceNote.objects.get()
        self.assertTrue(design_file_storage(name).exists(name))
        with self.captureOnCommitCallbacks(execute=True):
            note.delete()
            self.assertTrue(design_file_storage(name).exists(name))
        self.assertFalse(design_file_storage(name).exists(name))

    def test_voice_history_survives_new_cycle_and_details_render(self):
        self.post(decision='reject')
        first = DesignReviewVoiceNote.objects.get()
        submit_design_for_approval(self.image, self.designer, is_resubmission=True)
        self.assertEqual(self.post(comment='Revision reviewed').status_code, 200)
        notes = list(DesignReviewVoiceNote.objects.order_by('pk'))
        self.assertEqual([n.approval.cycle for n in notes], [1, 2])
        self.client.force_login(self.designer)
        response = self.client.get(reverse('design_approval_detail', args=[self.image.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'design-review-voice-notes')
        self.assertEqual(len(response.context['review_voice_notes']), 2)
        self.assertEqual(response.context['review_voice_notes'][0]['url'], reverse('design_review_voice_audio', args=[first.pk]))
        self.assertNotContains(response, first.file.name)

    def test_native_form_multipart_and_text_only_path(self):
        response = self.client.post(reverse('design_approval_detail', args=[self.image.pk]),
            dict(action='review', stage='cad', decision='approved', change_type='minor', comment='With audio', voice_note=upload()))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(DesignReviewVoiceNote.objects.count(), 1)
        self.client.force_login(self.ed)
        response = self.client.post(reverse('approve_design_image_api', args=[self.image.pk]),
            data='{"stage":"ed","change_type":"minor","comment":"Text only"}', content_type='application/json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(DesignReviewVoiceNote.objects.count(), 1)
        record_design_review_decision(self.image, self.md, 'approved', change_type='minor')
        self.image.refresh_from_db()
        self.assertEqual(self.image.approval_status, 'approved')
