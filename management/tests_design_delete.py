import json
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, RequestFactory
from django.urls import reverse
from django.utils import timezone

from management.models import (
    ActivityLog,
    ApprovalRoles,
    Brand,
    Model,
    PatternDesignApproval,
    PatternDesignFolder,
    PatternDesignImage,
    SubModel,
    WorkflowRoles,
    YearRange,
)
from management.services.activity_permissions import granted as activity_granted
from management.services.design_approvals import (
    record_design_review_decision,
    submit_design_for_approval,
)
from management.services.design_status import (
    latest_designer_upload,
    status_context,
)

User = get_user_model()


class DesignDeletePermissionAndWorkflowTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        # Users
        cls.admin = User.objects.create_superuser('del-admin', 'admin@example.com', 'TestStrong!369')
        cls.designer = cls._create_account('del-designer', WorkflowRoles.FREELANCE_3D_DESIGNER)
        cls.cad_user = cls._create_account('del-cad', WorkflowRoles.APPROVER, ApprovalRoles.CAD)
        cls.ed_user = cls._create_account('del-ed', WorkflowRoles.APPROVER, ApprovalRoles.ED)
        cls.md_user = cls._create_account('del-md', WorkflowRoles.APPROVER, ApprovalRoles.MD)
        cls.other_user = cls._create_account('del-other', WorkflowRoles.FREELANCE_3D_DESIGNER)

        # Vehicle hierarchy
        brand = Brand.objects.create(name='Test Brand')
        model = Model.objects.create(brand=brand, name='Test Model')
        sub = SubModel.objects.create(model=model, name='Test Sub')
        cls.vehicle1 = YearRange.objects.create(
            sub_model=sub, layout_code='DEL-TEST-01', year_start=2024, serial_number='PAT-DEL-01'
        )
        cls.vehicle2 = YearRange.objects.create(
            sub_model=sub, layout_code='DEL-TEST-02', year_start=2024, serial_number='PAT-DEL-02'
        )

    @classmethod
    def _create_account(cls, username, role, approval_role=''):
        user = User.objects.create_user(username, f'{username}@example.com', 'TestStrong!369')
        profile = user.workflow_profile
        profile.role = role
        profile.approval_role = approval_role
        profile.save()
        return user

    def _grant_delete_perm(self, user, allow=True):
        profile = user.workflow_profile
        overrides = dict(profile.activity_permissions or {})
        overrides['design.delete_uploaded'] = 'allow' if allow else 'deny'
        profile.activity_permissions = overrides
        profile.save(update_fields=['activity_permissions'])
        user.__dict__.pop('_activity_grants', None)
        user.__dict__.pop('_workflow_profile', None)

    def _create_design_file(self, vehicle, user, title='seat_pattern.obj', is_reference=False):
        uploaded_file = SimpleUploadedFile(
            title, b'test content for 3d pattern', content_type='application/octet-stream'
        )
        return PatternDesignImage.objects.create(
            vehicle=vehicle,
            uploaded_by=user,
            title=title,
            image=uploaded_file,
            file_size=len(uploaded_file),
            is_reference=is_reference,
            approval_status='pending',
        )

    def test_01_default_permission_is_disabled_for_all_roles(self):
        """Permission 'design.delete_uploaded' must be disabled by default for all roles."""
        self.assertFalse(activity_granted(self.designer, 'design.delete_uploaded'))
        self.assertFalse(activity_granted(self.cad_user, 'design.delete_uploaded'))
        self.assertFalse(activity_granted(self.ed_user, 'design.delete_uploaded'))
        self.assertFalse(activity_granted(self.md_user, 'design.delete_uploaded'))
        self.assertFalse(activity_granted(self.admin, 'design.delete_uploaded'))

    def test_02_authorized_user_can_delete_pending_upload(self):
        """User with explicit 'design.delete_uploaded' grant can delete a pending upload."""
        file = self._create_design_file(self.vehicle1, self.designer, 'pending_test.obj')
        self._grant_delete_perm(self.designer, allow=True)
        self.assertTrue(activity_granted(self.designer, 'design.delete_uploaded'))

        self.client.force_login(self.designer)
        resp = self.client.post(
            reverse('delete_design_image_api', args=[file.id]),
            {'vehicle_id': self.vehicle1.id},
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data['status'], 'success')

        file.refresh_from_db()
        self.assertTrue(file.is_deleted)
        self.assertIsNotNone(file.deleted_at)
        self.assertEqual(file.deleted_by, self.designer)

        # Audit log verification
        log = ActivityLog.objects.filter(action='deleted', object_type='Design Image').first()
        self.assertIsNotNone(log)
        self.assertIn('Pattern:', log.object_name)

    def test_03_unauthorized_user_receives_403(self):
        """User without 'design.delete_uploaded' receives 403 status code."""
        file = self._create_design_file(self.vehicle1, self.designer, 'forbidden_test.obj')
        # designer has default permissions (no delete_uploaded grant)
        self.assertFalse(activity_granted(self.designer, 'design.delete_uploaded'))

        self.client.force_login(self.designer)
        resp = self.client.post(
            reverse('delete_design_image_api', args=[file.id]),
            {'vehicle_id': self.vehicle1.id},
        )
        self.assertEqual(resp.status_code, 403)
        file.refresh_from_db()
        self.assertFalse(file.is_deleted)

    def test_04_user_with_upload_perm_without_delete_perm_cannot_delete(self):
        """Upload capability does not imply or grant delete capability."""
        file = self._create_design_file(self.vehicle1, self.designer, 'upload_only.obj')
        self.assertTrue(activity_granted(self.designer, 'design.upload'))
        self.assertFalse(activity_granted(self.designer, 'design.delete_uploaded'))

        self.client.force_login(self.designer)
        resp = self.client.post(
            reverse('delete_design_image_api', args=[file.id]),
            {'vehicle_id': self.vehicle1.id},
        )
        self.assertEqual(resp.status_code, 403)
        file.refresh_from_db()
        self.assertFalse(file.is_deleted)

    def test_05_user_with_delete_perm_without_approval_perm_can_delete(self):
        """User granted delete permission can delete even without CAD/ED/MD approval permissions."""
        file = self._create_design_file(self.vehicle1, self.designer, 'no_approval_perm.obj')
        self._grant_delete_perm(self.designer, allow=True)
        self.assertFalse(activity_granted(self.designer, 'design_approval.review_cad'))

        self.client.force_login(self.designer)
        resp = self.client.post(
            reverse('delete_design_image_api', args=[file.id]),
            {'vehicle_id': self.vehicle1.id},
        )
        self.assertEqual(resp.status_code, 200)
        file.refresh_from_db()
        self.assertTrue(file.is_deleted)

    def test_06_approved_file_deletion_preserves_approval_history(self):
        """Deleting an approved file soft-deletes it while preserving approval decisions and reviewer identity."""
        file = self._create_design_file(self.vehicle1, self.designer, 'approved_model.obj')
        submit_design_for_approval(file, self.designer)
        record_design_review_decision(file, self.cad_user, 'approved', 'CAD approved', stage='cad', change_type='minor')
        record_design_review_decision(file, self.ed_user, 'approved', 'ED approved', stage='ed', change_type='minor')
        record_design_review_decision(file, self.md_user, 'approved', 'MD approved', stage='md', change_type='minor')
        file.refresh_from_db()
        self.assertEqual(file.approval_status, 'approved')

        # Grant delete permission to admin
        self._grant_delete_perm(self.admin, allow=True)
        self.client.force_login(self.admin)
        resp = self.client.post(
            reverse('delete_design_image_api', args=[file.id]),
            {'vehicle_id': self.vehicle1.id},
        )
        if resp.status_code != 200:
            print('TEST 07 RESP:', resp.status_code, resp.content)
        self.assertEqual(resp.status_code, 200)

        file.refresh_from_db()
        self.assertTrue(file.is_deleted)
        # Approval record and decisions preserved intact:
        self.assertEqual(file.approval_status, 'approved')
        approvals = PatternDesignApproval.objects.filter(design_image=file)
        self.assertEqual(approvals.count(), 1)
        appr = approvals.first()
        self.assertEqual(appr.cad_status, 'approved')
        self.assertEqual(appr.ed_status, 'approved')
        self.assertEqual(appr.cad_reviewer, self.cad_user)
        self.assertEqual(appr.ed_reviewer, self.ed_user)

    def test_07_rejected_file_deletion_preserves_rejection_history(self):
        """Deleting a rejected file soft-deletes it while preserving rejection comment and reviewer."""
        file = self._create_design_file(self.vehicle1, self.designer, 'rejected_model.obj')
        submit_design_for_approval(file, self.designer)
        record_design_review_decision(file, self.cad_user, 'rejected', 'Seam offset incorrect', stage='cad', change_type='minor')
        file.refresh_from_db()
        self.assertEqual(file.approval_status, 'rejected')

        self._grant_delete_perm(self.admin, allow=True)
        self.client.force_login(self.admin)
        resp = self.client.post(
            reverse('delete_design_image_api', args=[file.id]),
            {'vehicle_id': self.vehicle1.id},
        )
        if resp.status_code != 200:
            print('TEST 07 RESP:', resp.status_code, resp.content)
        self.assertEqual(resp.status_code, 200)

        file.refresh_from_db()
        self.assertTrue(file.is_deleted)
        self.assertEqual(file.approval_status, 'rejected')
        approvals = PatternDesignApproval.objects.filter(design_image=file)
        self.assertEqual(approvals.count(), 1)
        appr = approvals.first()
        self.assertEqual(appr.cad_status, 'rejected')
        self.assertEqual(appr.cad_comment, 'Seam offset incorrect')

    def test_08_other_versions_remain_untouched(self):
        """Deleting one version leaves other versions of the vehicle untouched."""
        file_v1 = self._create_design_file(self.vehicle1, self.designer, 'pattern_v1.obj')
        file_v2 = self._create_design_file(self.vehicle1, self.designer, 'pattern_v2.obj')

        self._grant_delete_perm(self.admin, allow=True)
        self.client.force_login(self.admin)
        resp = self.client.post(
            reverse('delete_design_image_api', args=[file_v2.id]),
            {'vehicle_id': self.vehicle1.id},
        )
        self.assertEqual(resp.status_code, 200)

        file_v2.refresh_from_db()
        file_v1.refresh_from_db()
        self.assertTrue(file_v2.is_deleted)
        self.assertFalse(file_v1.is_deleted)

    def test_09_latest_active_version_and_upload_count_in_3d_status(self):
        """3D Status latest active version and upload counts update correctly after soft deletion."""
        file_v1 = self._create_design_file(self.vehicle1, self.designer, 'model_v1.obj')
        file_v2 = self._create_design_file(self.vehicle1, self.designer, 'model_v2.obj')

        self.assertEqual(latest_designer_upload([file_v1, file_v2]).id, file_v2.id)

        rf = RequestFactory()
        req = rf.get('/car-details/?subwindow=design_status')
        req.user = self.admin
        ctx = status_context(req)
        row = next(r for r in ctx['status_rows'] if r['vehicle'].id == self.vehicle1.id)
        self.assertEqual(row['upload_count'], 2)
        self.assertEqual(row['image'].id, file_v2.id)

        # Soft-delete file_v2
        self._grant_delete_perm(self.admin, allow=True)
        self.client.force_login(self.admin)
        resp = self.client.post(
            reverse('delete_design_image_api', args=[file_v2.id]),
            {'vehicle_id': self.vehicle1.id},
        )
        self.assertEqual(resp.status_code, 200)

        # 3D Status context excludes soft-deleted files from active count and latest version
        ctx_after = status_context(req)
        row_after = next(r for r in ctx_after['status_rows'] if r['vehicle'].id == self.vehicle1.id)
        self.assertEqual(row_after['upload_count'], 1)
        self.assertEqual(row_after['image'].id, file_v1.id)

        # latest_designer_upload excludes soft-deleted files
        file_v2.refresh_from_db()
        self.assertEqual(latest_designer_upload([file_v1, file_v2]).id, file_v1.id)

    def test_10_cross_pattern_and_malformed_requests_rejected(self):
        """Cross-pattern vehicle_id mismatch returns 400 Bad Request."""
        file = self._create_design_file(self.vehicle1, self.designer, 'cross_check.obj')
        self._grant_delete_perm(self.admin, allow=True)
        self.client.force_login(self.admin)

        # Send vehicle2 ID for file belonging to vehicle1
        resp = self.client.post(
            reverse('delete_design_image_api', args=[file.id]),
            {'vehicle_id': self.vehicle2.id},
        )
        self.assertEqual(resp.status_code, 400)
        file.refresh_from_db()
        self.assertFalse(file.is_deleted)

        # Malformed vehicle_id
        resp_bad = self.client.post(
            reverse('delete_design_image_api', args=[file.id]),
            {'vehicle_id': 'invalid-id'},
        )
        self.assertEqual(resp_bad.status_code, 400)

    def test_11_repeated_deletion_requests_return_404(self):
        """Deleting an already-deleted file safely returns 404."""
        file = self._create_design_file(self.vehicle1, self.designer, 'repeat_del.obj')
        self._grant_delete_perm(self.admin, allow=True)
        self.client.force_login(self.admin)

        resp1 = self.client.post(
            reverse('delete_design_image_api', args=[file.id]),
            {'vehicle_id': self.vehicle1.id},
        )
        self.assertEqual(resp1.status_code, 200)

        # Second deletion request
        resp2 = self.client.post(
            reverse('delete_design_image_api', args=[file.id]),
            {'vehicle_id': self.vehicle1.id},
        )
        self.assertEqual(resp2.status_code, 404)

    def test_12_permission_grants_persist_in_workflow_profile(self):
        """Overrides in workflow_profile.activity_permissions grant and revoke delete permission independently."""
        self.assertFalse(activity_granted(self.designer, 'design.delete_uploaded'))

        # Grant
        self._grant_delete_perm(self.designer, allow=True)
        self.designer.workflow_profile.refresh_from_db()
        self.assertTrue(activity_granted(self.designer, 'design.delete_uploaded'))

        # Revoke
        self._grant_delete_perm(self.designer, allow=False)
        self.designer.workflow_profile.refresh_from_db()
        self.assertFalse(activity_granted(self.designer, 'design.delete_uploaded'))

    def test_13_deleted_files_cannot_be_submitted_or_reviewed(self):
        """Soft-deleted files cannot be submitted for approval or reviewed."""
        file = self._create_design_file(self.vehicle1, self.designer, 'cannot_review.obj')
        file.is_deleted = True
        file.deleted_at = timezone.now()
        file.save()

        # Attempt to submit
        with self.assertRaises(ValidationError):
            submit_design_for_approval(file, self.designer)

        # Attempt to review
        with self.assertRaises((ValidationError, PermissionDenied)):
            record_design_review_decision(file, self.cad_user, 'approved', 'Good', stage='cad', change_type='minor')
