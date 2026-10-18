"""Isolated transaction-boundary regressions for media and design uploads.

These tests use Django's disposable test database and mocked object storage.
SQLite verifies ordering and rollback, not PostgreSQL row-lock behavior.
"""

import json
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection, transaction
from django.test import TransactionTestCase, override_settings
from django.urls import reverse

from management.models import (
    ApprovalRoles,
    ComplaintMediaUpload,
    Notification,
    PatternDesignApproval,
    PatternDesignFolder,
    PatternDesignImage,
    UserProfile,
    WorkflowRoles,
)
from management.services.media_uploads import (
    create_upload_batch,
    discard_uploads,
    inspect_pending_uploads,
    verify_pending_uploads,
)
from management.services.s3_storage import S3StorageError


GIF = (
    b'GIF89a\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00\xff\xff\xff!\xf9\x04\x01\x00\x00\x00\x00,'
    b'\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;'
)


@override_settings(
    PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'],
    USE_S3_STORAGE=True,
    S3_STORAGE_CONFIGURED=True,
    S3_ACCESS_KEY_ID='isolated-test-key',
    S3_SECRET_ACCESS_KEY='isolated-test-secret',
)
class ComplaintUploadTransactionTests(TransactionTestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_superuser(
            username='boundary_admin', email='boundary@example.invalid', password=None,
        )
        self.batch = create_upload_batch(self.user)

    def _upload(self):
        upload = ComplaintMediaUpload.objects.create(
            batch=self.batch,
            original_name='photo.png',
            expected_size=12,
            expected_content_type='image/png',
            storage_path='pending',
        )
        upload.storage_path = (
            f'complaint_media/uploads/user_{self.user.pk}/{self.batch.pk}/'
            f'{upload.pk}/photo.png'
        )
        upload.save(update_fields=['storage_path'])
        return upload

    def test_signed_url_is_created_after_ticket_commit(self):
        self.client.force_login(self.user)
        observed = []

        def sign(upload):
            observed.append((connection.in_atomic_block, upload.pk))
            self.assertTrue(ComplaintMediaUpload.objects.filter(pk=upload.pk).exists())
            return 'https://example.invalid/signed'

        with patch('management.views.sign_upload_ticket', side_effect=sign):
            response = self.client.post(
                reverse('complaint_media_signed_upload'),
                data=json.dumps({
                    'batch_id': str(self.batch.pk), 'filename': 'photo.png',
                    'size': 12, 'content_type': 'image/png',
                }),
                content_type='application/json',
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(observed, [(False, ComplaintMediaUpload.objects.get().pk)])

    def test_sign_failure_removes_unsigned_ticket(self):
        self.client.force_login(self.user)
        with patch('management.views.sign_upload_ticket', side_effect=RuntimeError('sign failed')):
            response = self.client.post(
                reverse('complaint_media_signed_upload'),
                data=json.dumps({
                    'batch_id': str(self.batch.pk), 'filename': 'photo.png',
                    'size': 12, 'content_type': 'image/png',
                }),
                content_type='application/json',
            )
        self.assertEqual(response.status_code, 502)
        self.assertFalse(ComplaintMediaUpload.objects.exists())

    def test_remote_head_precedes_atomic_and_changed_ticket_is_rejected(self):
        upload = self._upload()
        observed = []

        def head(_path):
            observed.append(connection.in_atomic_block)
            return {'size': 12, 'contentType': 'image/png'}

        with patch('management.services.media_uploads.get_object_info', side_effect=head) as mock_head:
            inspected = inspect_pending_uploads(self.user, self.batch, [str(upload.pk)])
            upload.expected_size = 13
            upload.save(update_fields=['expected_size'])
            with transaction.atomic(), self.assertRaises(ValidationError):
                verify_pending_uploads(
                    self.user, self.batch, [str(upload.pk)], inspected=inspected,
                )
        self.assertEqual(observed, [False])
        mock_head.assert_called_once_with(upload.storage_path)

    def test_discard_rejects_ticket_before_object_deletion(self):
        upload = self._upload()

        def delete(paths):
            self.assertFalse(connection.in_atomic_block)
            self.assertEqual(paths, [upload.storage_path])
            upload.refresh_from_db()
            self.assertEqual(upload.status, ComplaintMediaUpload.Status.REJECTED)
            with transaction.atomic(), self.assertRaises(ValidationError):
                verify_pending_uploads(self.user, self.batch, [str(upload.pk)])

        with patch('management.services.media_uploads.delete_objects', side_effect=delete):
            self.assertEqual(discard_uploads(self.user, [str(upload.pk)]), 1)

    def test_discard_storage_failure_never_reopens_ticket(self):
        upload = self._upload()
        with patch(
            'management.services.media_uploads.delete_objects',
            side_effect=S3StorageError('storage unavailable'),
        ):
            self.assertEqual(discard_uploads(self.user, [str(upload.pk)]), 1)
        upload.refresh_from_db()
        self.assertEqual(upload.status, ComplaintMediaUpload.Status.REJECTED)


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class DesignerUploadTransactionTests(TransactionTestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username='design_boundary_designer', email='design@example.invalid', password=None,
        )
        UserProfile.objects.filter(user=self.user).update(
            role=WorkflowRoles.FREELANCE_3D_DESIGNER
        )
        self.folder = PatternDesignFolder.objects.create(name='Isolated design folder')
        self.client.force_login(self.user)

    def _file(self, name='sample.gif'):
        return SimpleUploadedFile(name, GIF, content_type='image/gif')

    def test_multiple_files_are_saved_before_atomic_and_retry_reuses_rows(self):
        stored = []

        def save(name, content, max_length=None):
            stored.append((name, connection.in_atomic_block))
            return name

        with patch('django.core.files.storage.default_storage.save', side_effect=save):
            response = self.client.post(
                reverse('upload_design_images_api', args=[self.folder.pk]),
                {'images': [self._file('one.gif'), self._file('two.gif')]},
                HTTP_X_UPLOAD_ID='boundary-batch',
            )
            retry = self.client.post(
                reverse('upload_design_images_api', args=[self.folder.pk]),
                {'images': [self._file('one.gif'), self._file('two.gif')]},
                HTTP_X_UPLOAD_ID='boundary-batch',
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(retry.status_code, 200)
        self.assertEqual(PatternDesignImage.objects.count(), 2)
        self.assertEqual(len(stored), 4)  # Two originals and two thumbnails.
        self.assertTrue(all(not in_atomic for _, in_atomic in stored))

    def test_failed_thumbnail_store_cleans_new_original_without_db_rows(self):
        saved = []

        def save(name, content, max_length=None):
            if saved:
                raise RuntimeError('thumbnail storage failed')
            saved.append(name)
            return name

        with patch('django.core.files.storage.default_storage.save', side_effect=save), patch(
            'management.views.default_storage.delete'
        ) as delete:
            response = self.client.post(
                reverse('upload_design_images_api', args=[self.folder.pk]),
                {'images': [self._file()]},
            )
        self.assertEqual(response.status_code, 503)
        self.assertFalse(PatternDesignImage.objects.exists())
        delete.assert_called_once_with(saved[0])

    def test_permission_change_during_storage_blocks_final_insert(self):
        def save(name, content, max_length=None):
            get_user_model().objects.filter(pk=self.user.pk).update(is_active=False)
            return name

        with patch('django.core.files.storage.default_storage.save', side_effect=save), patch(
            'management.views.default_storage.delete'
        ) as delete:
            response = self.client.post(
                reverse('upload_design_images_api', args=[self.folder.pk]),
                {'images': [self._file()]},
            )
        self.assertEqual(response.status_code, 403)
        self.assertFalse(PatternDesignImage.objects.exists())
        self.assertEqual(delete.call_count, 2)

    def test_database_failure_after_storage_rolls_back_and_cleans_new_files(self):
        UserProfile.objects.filter(user=self.user).update(role=WorkflowRoles.FREELANCE_3D_DESIGNER)
        for role in (ApprovalRoles.CAD, ApprovalRoles.ED):
            approver = get_user_model().objects.create_user(username=f'{role.lower()}_boundary')
            UserProfile.objects.filter(user=approver).update(
                role=WorkflowRoles.APPROVER, approval_role=role,
            )
        stored = []

        def save(name, content, max_length=None):
            stored.append(name)
            return name

        with patch('django.core.files.storage.default_storage.save', side_effect=save), patch(
            'management.views.default_storage.delete'
        ) as delete, patch(
            'management.views._serialize_uploaded_design', side_effect=RuntimeError('response failed')
        ), patch(
            'management.services.push_notifications.send_push_to_user'
        ) as push:
            response = self.client.post(
                reverse('upload_design_images_api', args=[self.folder.pk]),
                {'images': [self._file()]},
            )
        self.assertEqual(response.status_code, 503)
        self.assertFalse(PatternDesignImage.objects.exists())
        self.assertFalse(Notification.objects.exists())
        push.assert_not_called()
        self.assertCountEqual([call.args[0] for call in delete.call_args_list], stored)

    def test_post_commit_failure_keeps_media_referenced_by_committed_row(self):
        UserProfile.objects.filter(user=self.user).update(role=WorkflowRoles.FREELANCE_3D_DESIGNER)

        def fail_after_commit(_image, _actor):
            def callback():
                raise RuntimeError('unexpected post-commit callback failure')

            transaction.on_commit(callback)

        with patch('django.core.files.storage.default_storage.save', side_effect=lambda name, *_args, **_kwargs: name), patch(
            'management.views.default_storage.delete'
        ) as delete, patch(
            'management.views.submit_design_for_approval', side_effect=fail_after_commit
        ):
            response = self.client.post(
                reverse('upload_design_images_api', args=[self.folder.pk]),
                {'images': [self._file()]},
            )
        self.assertEqual(response.status_code, 503)
        self.assertEqual(PatternDesignImage.objects.count(), 1)
        delete.assert_not_called()

    def test_resubmission_stores_replacement_before_lock_and_advances_once(self):
        UserProfile.objects.filter(user=self.user).update(role=WorkflowRoles.FREELANCE_3D_DESIGNER)
        image = PatternDesignImage.objects.create(
            folder=self.folder, image='pattern_designs/original.gif',
            title='Original', uploaded_by=self.user, approval_status='rejected',
        )
        PatternDesignApproval.objects.create(
            design_image=image, designer=self.user, cycle=1,
            status='rejected', cad_status='rejected', ed_status='pending',
        )
        stored = []

        def save(name, content, max_length=None):
            stored.append(connection.in_atomic_block)
            return name

        with patch('django.core.files.storage.default_storage.save', side_effect=save):
            response = self.client.post(
                reverse('resubmit_design_image_api', args=[image.pk]),
                {'image': self._file('replacement.gif')},
            )
            repeat = self.client.post(
                reverse('resubmit_design_image_api', args=[image.pk]),
                {'image': self._file('replacement.gif')},
            )
        image.refresh_from_db()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(repeat.status_code, 409)
        self.assertEqual(stored, [False, False])
        self.assertEqual(image.approval_status, 'pending')
        self.assertEqual(image.approval_requests.count(), 2)
