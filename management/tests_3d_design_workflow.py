from unittest.mock import patch
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.exceptions import ValidationError, PermissionDenied
from django.test import TestCase, Client
from django.urls import reverse

from management.models import (
    ApprovalRoles,
    Brand,
    Model,
    PatternDesignFolder,
    PatternDesignImage,
    PatternDesignApproval,
    Notification,
    SubModel,
    WorkflowRoles,
    YearRange,
)
from management.services.design_approvals import (
    submit_design_for_approval,
    record_design_review_decision,
    get_latest_approval_request,
)


class ThreeDDesignWorkflowTests(TestCase):
    def setUp(self):
        self.client = Client()
        tiny_gif = b'GIF89a\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00\xff\xff\xff!\xf9\x04\x01\x00\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;'
        self.upload_patcher = patch('management.storage_backends.upload_content', return_value='ok')
        self.url_patcher = patch('management.storage_backends.create_signed_download_url', return_value='/media/test.gif')
        self.download_patcher = patch('management.storage_backends.download_content', return_value=tiny_gif)
        self.upload_patcher.start()
        self.url_patcher.start()
        self.download_patcher.start()
        self.addCleanup(self.upload_patcher.stop)
        self.addCleanup(self.url_patcher.stop)
        self.addCleanup(self.download_patcher.stop)

        # 1. Superuser
        self.admin = User.objects.create_user(
            username='admin_3d_test',
            email='admin_3d@fabro.test',
            is_staff=True,
            is_superuser=True,
        )

        # 2. Designer
        self.designer = User.objects.create_user(
            username='designer_3d_test',
            email='designer_3d@fabro.test',
        )
        self.designer.workflow_profile.role = WorkflowRoles.FREELANCE_3D_DESIGNER
        self.designer.workflow_profile.save()

        # 3. CAD Reviewer
        self.cad_user = User.objects.create_user(
            username='cad_3d_test',
            email='cad_3d@fabro.test',
        )
        self.cad_user.workflow_profile.role = WorkflowRoles.APPROVER
        self.cad_user.workflow_profile.approval_role = ApprovalRoles.CAD
        self.cad_user.workflow_profile.save()

        # 4. ED Reviewer
        self.ed_user = User.objects.create_user(
            username='ed_3d_test',
            email='ed_3d@fabro.test',
        )
        self.ed_user.workflow_profile.role = WorkflowRoles.APPROVER
        self.ed_user.workflow_profile.approval_role = ApprovalRoles.ED
        self.ed_user.workflow_profile.save()

        # 5. MD Reviewer
        self.md_user = User.objects.create_user(
            username='md_3d_test',
            email='md_3d@fabro.test',
        )
        self.md_user.workflow_profile.role = WorkflowRoles.APPROVER
        self.md_user.workflow_profile.approval_role = ApprovalRoles.MD
        self.md_user.workflow_profile.save()

        # 6. PM User (Not an authorized 3D reviewer)
        self.pm_user = User.objects.create_user(
            username='pm_3d_test',
            email='pm_3d@fabro.test',
        )
        self.pm_user.workflow_profile.role = WorkflowRoles.APPROVER
        self.pm_user.workflow_profile.approval_role = ApprovalRoles.PM
        self.pm_user.workflow_profile.save()

        # Vehicle hierarchy
        self.brand = Brand.objects.create(name='Haval 3D')
        self.model = Model.objects.create(brand=self.brand, name='H9')
        self.submodel = SubModel.objects.create(model=self.model, name='Luxury')
        self.year = YearRange.objects.create(
            sub_model=self.submodel,
            year_start=2025,
            year_end=2026,
            layout_code='H9-2526-N1',
        )
        self.folder = PatternDesignFolder.objects.create(
            vehicle=self.year,
            name='Seat Covers 3D',
            created_by=self.designer,
        )

    def _create_sample_design(self):
        img_file = SimpleUploadedFile("seat_3d_model.obj", b"v 0 0 0\nv 1 1 1", content_type="application/octet-stream")
        img = PatternDesignImage.objects.create(
            folder=self.folder,
            image=img_file,
            title='Seat 3D Model',
            uploaded_by=self.designer,
            approval_status='pending',
        )
        submit_design_for_approval(img, self.designer)
        return img

    def test_change_type_recording_for_cad_ed_md(self):
        """Verify CAD, ED, and MD record change_type ('minor' / 'major') accurately."""
        img = self._create_sample_design()

        # CAD approves with minor change
        record_design_review_decision(img, self.cad_user, 'approved', comment='CAD OK', change_type='minor')
        appr = get_latest_approval_request(img)
        self.assertEqual(appr.cad_status, 'approved')
        self.assertEqual(appr.cad_change_type, 'minor')
        self.assertEqual(appr.cad_comment, 'CAD OK')

        # ED approves with major change
        record_design_review_decision(img, self.ed_user, 'approved', comment='ED OK', change_type='major')
        appr.refresh_from_db()
        self.assertEqual(appr.ed_status, 'approved')
        self.assertEqual(appr.ed_change_type, 'major')
        self.assertEqual(appr.ed_comment, 'ED OK')
        img.refresh_from_db()
        self.assertEqual(img.approval_status, 'pending')

        # MD approves with minor change -> triggers full unanimous approval
        record_design_review_decision(img, self.md_user, 'approved', comment='MD OK', change_type='minor')
        appr.refresh_from_db()
        img.refresh_from_db()
        self.assertEqual(appr.md_status, 'approved')
        self.assertEqual(appr.md_change_type, 'minor')
        self.assertEqual(appr.status, 'approved')
        self.assertEqual(img.approval_status, 'approved')
        self.assertIsNotNone(appr.md_decided_at)

    def test_invalid_change_type_rejected(self):
        """Invalid change_type string raises ValidationError."""
        img = self._create_sample_design()
        with self.assertRaises(ValidationError):
            record_design_review_decision(img, self.cad_user, 'approved', comment='CAD OK', change_type='invalid_type')

    def test_rejection_requires_comment(self):
        """Rejection by any reviewer strictly requires a non-empty comment."""
        img = self._create_sample_design()
        with self.assertRaises(ValidationError):
            record_design_review_decision(img, self.cad_user, 'rejected', comment='', change_type='minor')

    def test_rejection_marks_overall_status_rejected(self):
        """Any reviewer rejection shifts overall approval_status to rejected."""
        img = self._create_sample_design()
        record_design_review_decision(img, self.cad_user, 'rejected', comment='Needs 20mm seam gap', change_type='major')
        img.refresh_from_db()
        self.assertEqual(img.approval_status, 'rejected')
        appr = get_latest_approval_request(img)
        self.assertEqual(appr.status, 'rejected')
        self.assertEqual(appr.cad_status, 'rejected')
        self.assertEqual(appr.cad_change_type, 'major')

    def test_unauthorized_pm_cannot_review(self):
        """PM is not authorized to review 3D designs (only CAD, ED, MD)."""
        img = self._create_sample_design()
        with self.assertRaises(PermissionDenied):
            record_design_review_decision(img, self.pm_user, 'approved', comment='PM Review', change_type='minor')

    def test_design_approval_detail_view(self):
        """View endpoint /design-approvals/<id>/ renders complete review cycle and change types."""
        img = self._create_sample_design()
        record_design_review_decision(img, self.cad_user, 'approved', comment='CAD Check', change_type='minor')

        self.client.force_login(self.admin)
        url = reverse('design_approval_detail', args=[img.id])
        res = self.client.get(url)
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, 'CAD Check')

    @patch('management.views._ensure_pattern_thumbnail', return_value='/media/reference.png')
    def test_reference_gallery_excludes_non_image_design_files(self, _thumbnail):
        PatternDesignImage.objects.create(
            vehicle=self.year,
            image='pattern_designs/reference.png',
            title='Reference Photo.png',
            is_reference=True,
            uploaded_by=self.designer,
            approval_status='approved',
        )
        PatternDesignImage.objects.create(
            vehicle=self.year,
            image='pattern_designs/pattern.obj',
            title='Pattern.obj',
            uploaded_by=self.designer,
            approval_status='approved',
        )
        self.client.force_login(self.admin)
        response = self.client.get(reverse('get_design_folders_api'), {'vehicle_id': self.year.id})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual([item['title'] for item in data['reference_images']], ['Reference Photo.png'])
        self.assertEqual({item['title'] for item in data['design_files']}, {'Pattern.obj'})

    def test_design_file_types_include_native_3d_formats_without_treating_unknown_files_as_images(self):
        from management.views import ALLOWED_DESIGN_EXTENSIONS, _get_design_file_info
        for extension in ('.obj', '.fbx', '.blend', '.stl', '.3ds'):
            self.assertIn(extension, ALLOWED_DESIGN_EXTENSIONS)
            self.assertEqual(_get_design_file_info('model' + extension)[0], 'cad')
        self.assertEqual(_get_design_file_info('notes.txt')[0], 'file')

    def test_stale_reviewer_flag_does_not_expose_design_approval_controls(self):
        from management.models import ApprovalRoles, WorkflowRoles
        self.designer.workflow_profile.role = WorkflowRoles.FACTORY_VIEWER
        self.designer.workflow_profile.approval_role = ApprovalRoles.CAD
        self.designer.workflow_profile.save(update_fields=['role', 'approval_role'])
        self.client.force_login(self.designer)
        response = self.client.get(reverse('get_design_folders_api'), {'vehicle_id': self.year.pk})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()['can_approve_designs'])

    def test_legacy_approved_review_is_preserved_without_fabricated_md_vote(self):
        import importlib
        from django.apps import apps
        img = self._create_sample_design()
        approval = get_latest_approval_request(img)
        approval.status = 'approved'
        approval.save(update_fields=['status'])
        migration = importlib.import_module('management.migrations.0047_patterndesignapproval_cad_change_type_and_more')
        migration.preserve_historical_design_approvals(apps, None)
        approval.refresh_from_db()
        self.assertEqual(approval.md_status, 'not_required')
        self.assertIsNone(approval.md_reviewer)
        self.assertIsNone(approval.md_decided_at)

    def test_approval_drawer_submission_api(self):
        """POST to approve_design_image_api with change_type records successfully."""
        img = self._create_sample_design()
        self.client.force_login(self.ed_user)
        url = reverse('approve_design_image_api', args=[img.id])
        res = self.client.post(url, {
            'comment': 'Approved by ED via Drawer',
            'change_type': 'major',
        })
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data['status'], 'success')
        self.assertEqual(data['ed_status'], 'approved')
        self.assertEqual(data['ed_change_type'], 'major')

    def test_change_classification_is_required_by_service_and_api(self):
        img = self._create_sample_design()
        with self.assertRaises(ValidationError):
            record_design_review_decision(img, self.cad_user, 'approved', comment='Ready')
        self.client.force_login(self.cad_user)
        response = self.client.post(reverse('approve_design_image_api', args=[img.id]), {'comment': 'Ready'})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(get_latest_approval_request(img).cad_status, 'pending')

    @patch('management.services.push_notifications.send_push_to_user')
    def test_submission_notifies_each_reviewer_once_with_local_destination(self, push):
        with self.captureOnCommitCallbacks(execute=True):
            img = self._create_sample_design()
        self.assertEqual(
            set(Notification.objects.filter(design_image=img).values_list('recipient_id', flat=True)),
            {self.cad_user.id, self.ed_user.id, self.md_user.id},
        )
        self.assertFalse(Notification.objects.filter(design_image=img, recipient=self.pm_user).exists())
        self.assertEqual(push.call_count, 3)
        self.assertEqual(
            {call.args[0].id for call in push.call_args_list},
            {self.cad_user.id, self.ed_user.id, self.md_user.id},
        )
        self.assertTrue(all(
            call.kwargs['url'] == reverse('design_approval_detail', args=[img.id])
            for call in push.call_args_list
        ))
        push.reset_mock()
        with self.captureOnCommitCallbacks(execute=True):
            submit_design_for_approval(img, self.designer)
        self.assertEqual(Notification.objects.filter(design_image=img).count(), 3)
        self.assertEqual(push.call_count, 0)

    @patch('management.services.push_notifications.send_push_to_user')
    def test_md_decision_notifies_only_designer_and_duplicate_is_blocked(self, push):
        img = self._create_sample_design()
        before = Notification.objects.filter(design_image=img).count()
        self.client.force_login(self.md_user)
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(reverse('approve_design_image_api', args=[img.id]), {
                'change_type': 'major', 'comment': 'MD opinion',
            })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Notification.objects.filter(design_image=img).count(), before + 1)
        notification = Notification.objects.filter(design_image=img).latest('id')
        self.assertEqual(notification.recipient, self.designer)
        self.assertEqual(push.call_count, 1)
        self.assertEqual(push.call_args.args[0], self.designer)
        self.assertEqual(push.call_args.kwargs['url'], reverse('design_approval_detail', args=[img.id]))
        self.assertNotIn('MD opinion', push.call_args.args[2])
        repeated = self.client.post(reverse('approve_design_image_api', args=[img.id]), {
            'change_type': 'major', 'comment': 'Again',
        })
        self.assertEqual(repeated.status_code, 409)
        self.assertEqual(Notification.objects.filter(design_image=img).count(), before + 1)

    def test_md_can_open_both_review_workspaces_and_review_form(self):
        img = self._create_sample_design()
        self.client.force_login(self.md_user)
        self.assertEqual(self.client.get(reverse('approvals_list') + '?stage=designer').status_code, 200)
        detail = self.client.get(reverse('design_approval_detail', args=[img.id]))
        self.assertEqual(detail.status_code, 200)
        self.assertContains(detail, 'mdChangeType')
        self.assertTrue(detail.context['can_review_as_md'])

    def test_one_files_review_does_not_change_another(self):
        first = self._create_sample_design()
        second = self._create_sample_design()
        record_design_review_decision(first, self.cad_user, 'approved', change_type='minor')
        self.assertEqual(get_latest_approval_request(first).cad_status, 'approved')
        self.assertEqual(get_latest_approval_request(second).cad_status, 'pending')

    @patch('management.services.push_notifications.send_push_to_user', side_effect=RuntimeError('offline'))
    def test_push_failure_does_not_roll_back_md_review(self, push):
        img = self._create_sample_design()
        with self.captureOnCommitCallbacks(execute=True):
            record_design_review_decision(img, self.md_user, 'approved', change_type='minor')
        self.assertEqual(get_latest_approval_request(img).md_status, 'approved')
        self.assertTrue(Notification.objects.filter(design_image=img, recipient=self.designer).exists())
        self.assertEqual(push.call_count, 1)
