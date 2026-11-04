import io
from unittest.mock import patch
from PIL import Image
from django.conf import settings
from django.contrib.auth.models import User
from django.core.files.base import ContentFile
from django.test import TestCase, override_settings
from django.urls import reverse
from management.models import (ApprovalRoles, Brand, Model, SubModel, YearRange,
    WorkflowRoles, PatternDesignFolder, PatternDesignImage, DesignReviewVoiceNote, Notification, ActivityLog)
from management.services.design_approvals import submit_design_for_approval, record_design_review_decision
from management.services.design_pdfs import design_file_storage

class DesignComparisonTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = User.objects.create_user('comparison_owner')
        cls.other = User.objects.create_user('comparison_other')
        cls.cad = User.objects.create_user('comparison_cad')
        cls.factory = User.objects.create_user('comparison_factory')
        for user, role, approval in [(cls.owner,WorkflowRoles.FREELANCE_3D_DESIGNER,''), (cls.other,WorkflowRoles.FREELANCE_3D_DESIGNER,''),
                (cls.cad,WorkflowRoles.APPROVER,ApprovalRoles.CAD), (cls.factory,WorkflowRoles.FACTORY_EXECUTIVE,'')]:
            p=user.workflow_profile;p.role=role;p.approval_role=approval;p.save()
        brand=Brand.objects.create(name='Comparison Brand')
        model=Model.objects.create(brand=brand,name='Actual Model')
        sub=SubModel.objects.create(model=model,name='Touring')
        cls.vehicle=YearRange.objects.create(sub_model=sub,year_start=2024,year_end=2026,layout_code='COMPARE-1')
        cls.unrelated=YearRange.objects.create(sub_model=sub,year_start=2020,year_end=2022,layout_code='COMPARE-2')
        cls.folder=PatternDesignFolder.objects.create(vehicle=cls.vehicle,name='Context folder')
    def setUp(self):
        self.image=self.file(title='Selected.png')
        self.reference=self.file(title='Reference.png',is_reference=True,approval_status='approved',uploaded_by=self.cad)
        self.client.force_login(self.cad)
    def file(self, **overrides):
        data=dict(vehicle=self.vehicle,uploaded_by=self.owner,image='comparison/actual.png',title='Design.png',approval_status='pending')
        data.update(overrides)
        return PatternDesignImage.objects.create(**data)
    def manifest(self,image=None,user=None):
        if user: self.client.force_login(user)
        return self.client.get(reverse('design_comparison_manifest',args=[(image or self.image).pk]))
    def test_actual_context_contains_all_authorized_sets_and_only_same_pattern(self):
        sibling=self.file(vehicle=None,folder=self.folder,title='Folder upload.obj')
        folder_ref=self.file(vehicle=None,folder=self.folder,title='Folder reference.pdf',is_reference=True)
        wrong=self.file(vehicle=self.unrelated,folder=self.folder)
        unrelated=self.file(vehicle=self.unrelated,is_reference=True)
        data=self.manifest().json()
        self.assertEqual({f['id'] for f in data['uploads']},{self.image.pk,sibling.pk})
        self.assertEqual({f['id'] for f in data['references']},{self.reference.pk,folder_ref.pk})
        self.assertNotIn(wrong.pk,{f['id'] for f in data['uploads']})
        self.assertNotIn(unrelated.pk,{f['id'] for f in data['references']})
        self.assertEqual(data['vehicle'],'Comparison Brand Actual Model Touring (2024–2026)')
        self.assertEqual(data['pattern'],self.vehicle.serial_number)
    def test_reference_image_and_pdf_anchor_reuse_authorized_context_and_remarks(self):
        submit_design_for_approval(self.image,self.owner)
        record_design_review_decision(self.image,self.cad,'approved','CAD reference comparison feedback',change_type='minor')
        pdf=self.file(vehicle=None,folder=self.folder,title='Reference.pdf',image='private_design_pdfs/reference.pdf',is_reference=True,approval_status='approved')
        self.file(vehicle=self.unrelated,folder=self.folder)
        self.file(vehicle=self.unrelated,is_reference=True)
        for reference,kind in ((self.reference,'image'),(pdf,'pdf')):
            with self.subTest(kind=kind):
                data=self.manifest(reference).json()
                self.assertEqual(data['selected_id'],reference.pk)
                self.assertEqual({f['id'] for f in data['references']},{self.reference.pk,pdf.pk})
                self.assertEqual(next(f['type'] for f in data['references'] if f['id']==reference.pk),kind)
                self.assertEqual([f['id'] for f in data['uploads']],[self.image.pk])
                self.assertEqual(data['uploads'][0]['history'][0]['stages'][0]['comment'],'CAD reference comparison feedback')
    def test_reference_anchor_filters_private_uploads_and_rejects_hidden_reference(self):
        private=self.file(is_reference=True,uploaded_by=self.cad)
        for user in (self.other,self.factory):
            data=self.manifest(self.reference,user=user).json()
            self.assertEqual(data['uploads'],[])
            self.assertNotIn(private.pk,{f['id'] for f in data['references']})
            for image in (private,self.image):
                self.assertEqual(self.manifest(image).status_code,404)
                self.assertEqual(self.client.get(reverse('design_comparison_file',args=[image.pk])).status_code,404)
    def test_reference_folder_and_unassigned_isolation_with_empty_upload_set(self):
        folder=PatternDesignFolder.objects.create(name='Reference-only folder')
        reference=self.file(vehicle=None,folder=folder,is_reference=True)
        upload=self.file(vehicle=None,folder=folder)
        self.file(vehicle=self.unrelated,folder=folder)
        data=self.manifest(reference).json()
        self.assertEqual([f['id'] for f in data['uploads']],[upload.pk])
        self.assertEqual([f['id'] for f in data['references']],[reference.pk])
        orphan=self.file(vehicle=None,folder=None,is_reference=True)
        self.file(vehicle=None,folder=None)
        data=self.manifest(orphan).json()
        self.assertEqual([f['id'] for f in data['references']],[orphan.pk])
        self.assertEqual(data['uploads'],[])
        self.assertEqual(data['vehicle'],'')
    def test_reference_direct_vehicle_takes_precedence_and_uploads_are_chronological(self):
        from datetime import timedelta
        from django.utils import timezone
        latest=self.file()
        PatternDesignImage.objects.filter(pk=self.image.pk).update(uploaded_at=timezone.now()+timedelta(seconds=1))
        self.reference.folder=PatternDesignFolder.objects.create(vehicle=self.unrelated,name='Conflicting reference folder')
        self.reference.save(update_fields=['folder'])
        data=self.manifest(self.reference).json()
        self.assertEqual([f['id'] for f in data['uploads']],[latest.pk,self.image.pk])
    def test_direct_vehicle_wins_over_conflicting_folder_and_empty_context_is_isolated(self):
        PatternDesignImage.objects.filter(pk=self.image.pk).update(folder=PatternDesignFolder.objects.create(vehicle=self.unrelated,name='Other folder'))
        data=self.manifest().json()
        self.assertEqual([f['id'] for f in data['references']],[self.reference.pk])
        orphan=self.file(vehicle=None,folder=None)
        self.file(vehicle=None,folder=None)
        data=self.manifest(orphan).json()
        self.assertEqual([f['id'] for f in data['uploads']],[orphan.pk])
        self.assertEqual(data['references'],[])
        self.assertEqual(data['vehicle'],'')
    def test_folder_only_unassigned_pattern_never_expands_to_unrelated_files(self):
        folder=PatternDesignFolder.objects.create(name='Unassigned isolated folder')
        anchor=self.file(vehicle=None,folder=folder)
        ref=self.file(vehicle=None,folder=folder,is_reference=True)
        self.file(vehicle=self.unrelated,folder=folder,is_reference=True)
        data=self.manifest(anchor).json()
        self.assertEqual([f['id'] for f in data['references']],[ref.pk])
    def test_pending_file_access_and_inactive_or_anonymous_accounts(self):
        for user in (self.other,self.factory):
            self.assertEqual(self.manifest(user=user).status_code,404)
            self.assertEqual(self.client.get(reverse('design_comparison_file',args=[self.image.pk])).status_code,404)
        self.assertEqual(self.manifest(user=self.owner).status_code,200)
        self.client.logout()
        self.assertEqual(self.manifest().status_code,302)
        self.assertEqual(self.client.get(reverse('design_comparison_file',args=[self.image.pk])).status_code,302)
    def test_visible_shared_approved_upload_does_not_grant_private_remarks(self):
        submit_design_for_approval(self.image,self.owner)
        record_design_review_decision(self.image,self.cad,'approved','Private CAD comment',change_type='minor')
        PatternDesignImage.objects.filter(pk=self.image.pk).update(approval_status='approved')
        for user in (self.other,self.factory):
            data=self.manifest(user=user).json()
            selected=next(f for f in data['uploads'] if f['id']==self.image.pk)
            self.assertFalse(selected['remarks_allowed'])
            self.assertEqual(selected['history'],[])
            self.assertNotIn('Private CAD comment',str(data))
        selected=self.manifest(user=self.owner).json()['uploads'][0]
        self.assertTrue(selected['remarks_allowed'])
        self.assertEqual(selected['history'][0]['stages'][0]['comment'],'Private CAD comment')
    def test_history_and_voice_use_real_review_cycles_without_archived_file_claims(self):
        first=submit_design_for_approval(self.image,self.owner)
        record_design_review_decision(self.image,self.cad,'rejected','Actual old cycle',change_type='major')
        note=DesignReviewVoiceNote.objects.create(approval=first,reviewer=self.cad,reviewer_name=self.cad.username,stage='CAD',file='private_design_voice_notes/test.wav',duration_ms=1000,waveform=[8]*32)
        submit_design_for_approval(self.image,self.owner,is_resubmission=True)
        data=self.manifest().json()['uploads'][0]
        self.assertEqual(data['cycle'],2)
        self.assertEqual([cycle['cycle'] for cycle in data['history']],[2,1])
        stage=data['history'][1]['stages'][0]
        self.assertEqual(stage['classification'],'major')
        self.assertEqual(stage['comment'],'Actual old cycle')
        self.assertEqual(stage['reviewer'],self.cad.username)
        self.assertEqual(stage['voice_notes'][0]['url'],reverse('design_review_voice_audio',args=[note.pk]))
        self.assertNotIn('private_design_voice_notes',str(data))
        self.assertNotIn('archived_url',data)
    def test_no_private_paths_public_storage_urls_or_full_images_in_thumbnail_metadata(self):
        self.image.thumbnail.name='comparison/thumb.png';self.image.save(update_fields=['thumbnail'])
        data=self.manifest().json();record=data['uploads'][0]
        self.assertEqual(record['url'],reverse('design_comparison_file',args=[self.image.pk]))
        self.assertEqual(record['thumbnail'],record['url']+'?thumbnail=1')
        self.assertIsNone(data['references'][0]['thumbnail'])
        self.assertNotIn('comparison/actual.png',str(data))
        self.assertNotIn('/media/',str(data))
        self.assertNotIn('http',str(data))
    def test_binary_original_and_thumbnail_private_range_download_and_cleanup(self):
        output=io.BytesIO();Image.new('RGB',(20,10),'red').save(output,'PNG');raw=output.getvalue()
        self.image.image.name=design_file_storage('comparison/actual.png').save('comparison/actual.png',ContentFile(raw))
        self.image.thumbnail.name=design_file_storage('comparison/thumb.png').save('comparison/thumb.png',ContentFile(raw))
        self.image.save(update_fields=['image','thumbnail'])
        url=reverse('design_comparison_file',args=[self.image.pk])
        response=self.client.get(url)
        self.assertEqual(b''.join(response.streaming_content),raw)
        self.assertEqual(response['Content-Type'],'image/png')
        self.assertIn('private',response['Cache-Control']);self.assertIn('no-store',response['Cache-Control'])
        self.assertEqual(response['X-Content-Type-Options'],'nosniff')
        for header,expected in [('bytes=0-7',raw[:8]),('bytes=-5',raw[-5:])]:
            response=self.client.get(url,HTTP_RANGE=header)
            self.assertEqual(response.status_code,206)
            self.assertEqual(b''.join(response.streaming_content),expected)
            response.close()
        self.assertEqual(self.client.get(url,HTTP_RANGE='bytes=99999999-').status_code,416)
        self.assertEqual(self.client.get(url,HTTP_RANGE='bytes=0-1,2-3').status_code,416)
        response=self.client.get(url+'?thumbnail=1');self.assertEqual(b''.join(response.streaming_content),raw);response.close()
        response=self.client.get(url+'?download=1');self.assertIn('attachment',response['Content-Disposition']);response.close()
    def test_missing_thumbnail_file_and_pdf_or_other_types_remain_safe(self):
        url=reverse('design_comparison_file',args=[self.image.pk])
        self.assertEqual(self.client.get(url+'?thumbnail=1').status_code,404)
        self.image.image.name='comparison/definitely-missing.png'
        self.image.save(update_fields=['image'])
        self.assertEqual(self.client.get(url).status_code,404)
        obj=self.file(image='comparison/design.obj',title='Actual CAD.obj')
        obj.image.name=design_file_storage(obj.image.name).save(obj.image.name,ContentFile(b'v 0 0 0'))
        obj.save(update_fields=['image'])
        response=self.client.get(reverse('design_comparison_file',args=[obj.pk]))
        self.assertEqual(response['Content-Type'],'application/octet-stream')
        self.assertIn('attachment',response['Content-Disposition']);response.close()
        self.assertEqual(self.manifest(self.reference).status_code,200)
    def test_readonly_manifest_does_not_change_notifications_audit_or_decisions(self):
        submit_design_for_approval(self.image,self.owner)
        before=(Notification.objects.count(),ActivityLog.objects.count(),self.image.approval_requests.count())
        for anchor in (self.image,self.reference):
            self.assertEqual(self.manifest(anchor).status_code,200)
        self.assertEqual((Notification.objects.count(),ActivityLog.objects.count(),self.image.approval_requests.count()),before)
        self.assertEqual(self.image.latest_approval.cad_status,'pending')
        self.assertEqual(self.client.post(reverse('design_comparison_manifest',args=[self.image.pk])).status_code,405)

    @override_settings(USE_S3_STORAGE=True, STORAGES={
        'default': {'BACKEND': 'management.storage_backends.S3Storage'},
        'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
    })
    def test_s3_file_bytes_use_existing_private_adapter_not_public_or_signed_urls(self):
        with patch('management.storage_backends.download_content',return_value=b'private image bytes') as read, patch('management.storage_backends.create_signed_download_url') as signed:
            url=reverse('design_comparison_file',args=[self.image.pk])
            response=self.client.get(url)
            self.assertEqual(b''.join(response.streaming_content),b'private image bytes')
            self.assertNotIn('Location',response)
            read.assert_called_once_with(self.image.image.name)
            self.assertIn('no-store',response['Cache-Control'])
            response.close();signed.assert_not_called()

    def test_workspace_fragment_uses_existing_role_permissions_and_forms(self):
        submit_design_for_approval(self.image,self.owner)
        for name,role,approval,heading,form_role in [
            ('ws_cad',WorkflowRoles.APPROVER,ApprovalRoles.CAD,'CAD Approval','cad'),
            ('ws_ed',WorkflowRoles.APPROVER,ApprovalRoles.ED,'ED Approval','ed'),
            ('ws_md',WorkflowRoles.APPROVER,ApprovalRoles.MD,'MD Approval','md'),
            ('ws_admin',WorkflowRoles.ADMIN,'','Design Approval Management','all'),
            ('ws_om',WorkflowRoles.APPROVER,ApprovalRoles.OM,'Approval Details',''),
        ]:
            with self.subTest(role=name):
                user=User.objects.create_user(name)
                profile=user.workflow_profile;profile.role=role;profile.approval_role=approval;profile.save()
                self.client.force_login(user)
                response=self.client.get(reverse('design_approval_detail',args=[self.image.pk])+'?workspace=comparison')
                self.assertContains(response,heading)
                self.assertNotContains(response,'id="app-content"')
                self.assertNotContains(response,'data-review-media')
                for stage in ('cad','ed','md'):
                    (self.assertContains if form_role in (stage,'all') else self.assertNotContains)(response,f'id="{stage}ReviewForm"')
                (self.assertContains if form_role=='all' else self.assertNotContains)(response,'role="tablist"')
                self.assertIn('no-store',response['Cache-Control'])

    def test_workspace_history_uses_only_persisted_cycles_of_the_selected_file(self):
        first=submit_design_for_approval(self.image,self.owner)
        record_design_review_decision(self.image,self.cad,'rejected','Recorded original rejection',change_type='major')
        second=submit_design_for_approval(self.image,self.owner,is_resubmission=True)
        record_design_review_decision(self.image,self.cad,'approved','Recorded revision approval',change_type='minor')
        unrelated=self.file(title='Unrelated lineage.png');submit_design_for_approval(unrelated,self.owner)
        record_design_review_decision(unrelated,self.cad,'approved','Must not leak into selected history',change_type='minor')
        response=self.client.get(reverse('design_approval_detail',args=[self.image.pk])+'?workspace=comparison')
        self.assertContains(response,'Original upload')
        cycles=response.context['workspace_cycles']
        self.assertEqual([item['record'].pk for item in cycles],[first.pk,second.pk])
        self.assertEqual([item['events'][0]['comment'] for item in cycles],['Recorded original rejection','Recorded revision approval'])
        self.assertContains(response,'data-history-cycle="2" open')
        self.assertNotContains(response,'Must not leak into selected history')
        first.cad_decided_at=None;first.save(update_fields=['cad_decided_at'])
        response=self.client.get(reverse('design_approval_detail',args=[self.image.pk])+'?workspace=comparison')
        self.assertEqual(response.context['workspace_cycles'][0]['events'],[])

    @patch('management.services.push_notifications.send_push_to_user')
    def test_workspace_submission_reuses_existing_notification_and_duplicate_guards(self,push):
        submit_design_for_approval(self.image,self.owner)
        Notification.objects.all().delete();push.reset_mock()
        url=reverse('design_approval_detail',args=[self.image.pk])+'?workspace=comparison'
        data=dict(action='review',stage='cad',decision='approved',change_type='minor',comment='Workspace review')
        with self.captureOnCommitCallbacks(execute=True):
            response=self.client.post(url,data,follow=True)
        self.assertContains(response,'Your review decision has been recorded.')
        self.assertEqual(Notification.objects.filter(recipient=self.owner,design_image=self.image).count(),1)
        self.assertEqual(Notification.objects.exclude(recipient=self.owner).count(),0)
        self.assertEqual(push.call_count,1)
        self.assertEqual(push.call_args.kwargs['url'],reverse('design_approval_detail',args=[self.image.pk]))
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(url,data,follow=True)
        self.assertEqual(Notification.objects.count(),1);self.assertEqual(push.call_count,1)
        self.image.refresh_from_db();self.assertEqual(self.image.latest_approval.cad_comment,'Workspace review')

    def test_workspace_fragment_and_posts_do_not_bypass_visibility_or_stage_authority(self):
        submit_design_for_approval(self.image,self.owner)
        url=reverse('design_approval_detail',args=[self.image.pk])+'?workspace=comparison'
        self.client.force_login(self.other);self.assertEqual(self.client.get(url).status_code,403)
        self.assertEqual(self.client.post(url,dict(action='review',stage='cad',decision='approved',change_type='minor')).status_code,403)
        self.client.force_login(self.cad)
        response=self.client.post(url,dict(action='review',stage='md',decision='approved',change_type='minor'),follow=True)
        self.assertContains(response,'error')
        self.assertEqual(self.image.latest_approval.md_status,'pending')
        self.assertTrue(self.manifest().json()['uploads'][0]['workspace_url'].endswith('?workspace=comparison'))
        self.assertIsNone(self.manifest(self.reference,user=self.factory).json()['references'][0]['workspace_url'])
