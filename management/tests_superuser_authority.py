import json
from unittest.mock import patch
from django.contrib.auth.models import User
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from management.models import (
    ActivityLog,
    ApprovalRoles,
    ApprovalStages,
    Brand,
    Complaint,
    ComplaintApproval,
    DecisionStatuses,
    FactoryPriorities,
    MasterSetting,
    MaterialVariant,
    Model,
    Notification,
    PatternAlteration,
    PatternDesignApproval,
    PatternDesignImage,
    PatternEditLog,
    SKU,
    SubModel,
    UserProfile,
    WorkflowRoles,
    WorkflowStatuses,
    YearRange,
)
from management.services.design_approvals import (
    record_design_review_decision,
    submit_design_for_approval,
)
from management.services.media_uploads import create_upload_batch
from management.services.workflow import (
    is_active_superuser,
    record_approval_decision,
)


class SuperuserAuthorityTestCase(TestCase):
    def setUp(self):
        tiny_gif = b'GIF89a\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00\xff\xff\xff!\xf9\x04\x01\x00\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;'
        # Storage & push mocks to ensure fast, isolated tests without external network dependencies
        self.patchers = [
            patch('management.storage_backends.upload_content', return_value='ok'),
            patch('management.storage_backends.download_content', return_value=tiny_gif),
            patch('management.storage_backends.create_signed_download_url', return_value='/media/test.gif'),
            patch('management.services.s3_storage.upload_content', return_value='ok'),
            patch('management.services.s3_storage.download_content', return_value=tiny_gif),
            patch('management.services.s3_storage.create_signed_download_url', return_value='/media/test.gif'),
            patch('management.services.push_notifications.send_push_to_user', return_value=True),
            patch('management.services.push_notifications.send_push_on_commit', return_value=True),
        ]
        for p in self.patchers:
            p.start()
            self.addCleanup(p.stop)

        # 1. Superuser
        self.superuser = User.objects.create_superuser(
            username='auth_superuser',
            email='superuser@example.com',
            password='Password123!',
        )
        self.su_profile = self.superuser.workflow_profile
        self.su_profile.role = WorkflowRoles.ADMIN
        self.su_profile.save()

        # 2. Staff user (not superuser)
        self.staff_user = User.objects.create_user(
            username='auth_staff',
            email='staff@example.com',
            password='Password123!',
            is_staff=True,
        )
        self.staff_profile = self.staff_user.workflow_profile
        self.staff_profile.role = WorkflowRoles.ADMIN
        self.staff_profile.save()

        # 3. Regular Country Executive
        self.country_setting = MasterSetting.objects.create(category='Country', name='UAE')
        self.regular_user = User.objects.create_user(
            username='auth_country_exec',
            email='country@example.com',
            password='Password123!',
        )
        self.regular_profile = self.regular_user.workflow_profile
        self.regular_profile.role = WorkflowRoles.COUNTRY_EXECUTIVE
        self.regular_profile.country = self.country_setting
        self.regular_profile.save()

        # 4. Designer Freelancer
        self.designer = User.objects.create_user(
            username='auth_designer',
            email='designer@example.com',
            password='Password123!',
        )
        self.designer_profile = self.designer.workflow_profile
        self.designer_profile.role = WorkflowRoles.FREELANCE_3D_DESIGNER
        self.designer_profile.save()

        # 5. CAD Approver
        self.cad_approver = User.objects.create_user(
            username='auth_cad_approver',
            email='cad@example.com',
            password='Password123!',
        )
        self.cad_profile = self.cad_approver.workflow_profile
        self.cad_profile.role = WorkflowRoles.APPROVER
        self.cad_profile.approval_role = ApprovalRoles.CAD
        self.cad_profile.save()

        # 6. ED Approver
        self.ed_approver = User.objects.create_user(
            username='auth_ed_approver',
            email='ed@example.com',
            password='Password123!',
        )
        self.ed_profile = self.ed_approver.workflow_profile
        self.ed_profile.role = WorkflowRoles.APPROVER
        self.ed_profile.approval_role = ApprovalRoles.ED
        self.ed_profile.save()

        # Master & Catalog Setup
        self.channel = MasterSetting.objects.create(category='Channel', name='TestChannel')
        self.case_type = MasterSetting.objects.create(category='Pattern Complaint Type', name='Cutting Issue')
        self.series = MasterSetting.objects.create(category='Series', name='TestSeries')
        self.material = MasterSetting.objects.create(category='Material', name='TestMaterial')
        self.region = MasterSetting.objects.create(category='Region', name='TestRegion')
        self.sku = SKU.objects.create(code='TEST-SKU-01', description='Test SKU', region=self.region)

        # Vehicle Catalog Setup
        self.brand = Brand.objects.create(name='TestBrand')
        self.model = Model.objects.create(brand=self.brand, name='TestModel')
        self.sub_model = SubModel.objects.create(model=self.model, name='TestSubModel')
        self.year_range = YearRange.objects.create(
            sub_model=self.sub_model,
            year_start=2024,
            year_end=2026,
            number_of_seats=5,
            number_of_doors=4,
            serial_number='S1001',
            fitting_confirmation='Confirmed',
        )

    # =========================================================================
    # 1. Superuser Identification Helper Tests
    # =========================================================================
    def test_is_active_superuser_helper(self):
        self.assertTrue(is_active_superuser(self.superuser))
        self.assertFalse(is_active_superuser(self.staff_user))
        self.assertFalse(is_active_superuser(self.regular_user))
        self.assertFalse(is_active_superuser(None))

        # Inactive superuser must return False
        self.superuser.is_active = False
        self.superuser.save()
        self.assertFalse(is_active_superuser(self.superuser))
        self.superuser.is_active = True
        self.superuser.save()

    # =========================================================================
    # 2. Master Settings Tests
    # =========================================================================
    def test_superuser_creates_master_setting_directly(self):
        self.client.force_login(self.superuser)
        res = self.client.post(reverse('master_settings'), {
            'category': 'Quality Complaint Type',
            'name': 'Stitching Flaw',
        })
        self.assertEqual(res.status_code, 302)
        setting = MasterSetting.objects.filter(category='Quality Complaint Type', name='Stitching Flaw').first()
        self.assertIsNotNone(setting)

        # Audit log verification
        log = ActivityLog.objects.filter(object_type='Master Setting', user=self.superuser).first()
        self.assertIsNotNone(log)
        self.assertIn('Stitching Flaw', log.object_name)

    def test_superuser_edits_master_setting_and_material_variants_directly(self):
        mat = MasterSetting.objects.create(category='Material', name='Original Leather')
        v1 = MaterialVariant.objects.create(material=mat, name='Perforated', display_order=0)

        self.client.force_login(self.superuser)
        payload = {
            'name': 'Updated Leather',
            'variants_json': json.dumps([
                {'id': v1.id, 'name': 'Perforated'},
                {'name': 'Smooth'},
                {'name': 'Quilted'},
            ]),
        }
        res = self.client.post(
            reverse('edit_master_setting', args=[mat.id]),
            payload,
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )
        self.assertEqual(res.status_code, 200)

        mat.refresh_from_db()
        self.assertEqual(mat.name, 'Updated Leather')
        variant_names = list(mat.variants.values_list('name', flat=True).order_by('display_order'))
        self.assertEqual(variant_names, ['Perforated', 'Smooth', 'Quilted'])

    def test_non_superuser_cannot_access_master_settings(self):
        self.client.force_login(self.regular_user)
        res = self.client.get(reverse('master_settings'))
        # Regular country executive redirected with error
        self.assertEqual(res.status_code, 302)

    # =========================================================================
    # 3. Pattern Master Tests
    # =========================================================================
    def test_superuser_creates_pattern_directly(self):
        self.client.force_login(self.superuser)
        res = self.client.post(reverse('car_details'), {
            'brand_name': 'DirectBrand',
            'model_name': 'DirectModel',
            'sub_model_name': 'DirectSubModel',
            'year_start': 2023,
            'year_end': 2025,
            'number_of_seats': 5,
            'number_of_doors': 4,
            'serial_number': 'S2001',
            'fitting_confirmation': 'Confirmed',
        })
        self.assertEqual(res.status_code, 302)
        pattern = YearRange.objects.filter(serial_number='S2001').first()
        self.assertIsNotNone(pattern)
        self.assertEqual(pattern.sub_model.model.brand.name, 'DirectBrand')

        # Audit log verified
        p_log = PatternEditLog.objects.filter(pattern_serial='S2001', user=self.superuser).first()
        self.assertIsNotNone(p_log)
        self.assertEqual(p_log.action, 'created')

    def test_superuser_edits_pattern_directly_without_approval_notification(self):
        self.client.force_login(self.superuser)
        res = self.client.post(
            reverse('edit_car_detail', args=[self.year_range.id]),
            {
                'brand_name': 'TestBrand',
                'model_name': 'TestModel',
                'sub_model_name': 'TestSubModel',
                'year_start': 2024,
                'year_end': 2027,
                'number_of_seats': 5,
                'number_of_doors': 4,
                'fitting_confirmation': 'Confirmed',
                'serial_number': 'S1001',
            },
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )
        self.assertEqual(res.status_code, 200)
        self.year_range.refresh_from_db()
        self.assertEqual(self.year_range.year_end, 2027)

        # Audit log is created
        p_log = PatternEditLog.objects.filter(year_range=self.year_range, action='updated').first()
        self.assertIsNotNone(p_log)

        # Superuser direct edit must not send unnecessary alteration approval notifications to approvers
        pattern_approval_notifs = Notification.objects.filter(
            notification_type='pattern_approval',
            recipient__in=[self.cad_approver, self.ed_approver],
        )
        self.assertFalse(pattern_approval_notifs.exists())

    # =========================================================================
    # 4. Complaints — Preserved Existing Workflow Tests
    # =========================================================================
    def test_superuser_complaint_edits_preserve_workflow_states(self):
        # Create an ordinary complaint
        complaint = Complaint.objects.create(
            complaint_id='PAT-26100001',
            complaint_type='pattern',
            created_by=self.superuser,
            workflow_status=WorkflowStatuses.SUBMITTED,
            status='Open',
            priority='Low',
            channel=self.channel,
            case_sub_category=self.case_type,
            series=self.series,
            material=self.material,
            sku=self.sku,
            brand=self.brand,
            model=self.model,
            sub_model=self.sub_model,
            year=self.year_range,
            serial_no='SN-TEST-001',
            batch_no='BATCH-001',
            complaint_description='Initial issue description',
        )

        self.client.force_login(self.superuser)
        batch = create_upload_batch(self.superuser, complaint=complaint)
        # Superuser edits permitted report fields
        res = self.client.post(reverse('edit_complaint', args=[complaint.complaint_id]), {
            'date': '2026-10-16',
            'channel': self.channel.id,
            'case_sub_category': self.case_type.id,
            'series': self.series.id,
            'material': self.material.id,
            'sku': self.sku.id,
            'brand': self.brand.id,
            'model': self.model.id,
            'sub_model': self.sub_model.id,
            'year': self.year_range.id,
            'status': 'Open',
            'priority': 'High',
            'serial_no': 'SN-TEST-001',
            'batch_no': 'BATCH-001',
            'batch_order': 'BATCH-001',
            'complaint_description': 'Updated issue description by superuser',
            'media_upload_batch': str(batch.id),
        })
        if res.status_code != 302 and 'form' in res.context:
            self.fail(f"Complaint edit form errors: {res.context['form'].errors.as_json()}")
        self.assertEqual(res.status_code, 302)

        complaint.refresh_from_db()
        self.assertEqual(complaint.complaint_description, 'Updated issue description by superuser')
        self.assertEqual(complaint.priority, 'High')
        # Status MUST remain 'submitted' and 'Open' (NO auto-advance or bypass)
        self.assertEqual(complaint.workflow_status, WorkflowStatuses.SUBMITTED)
        self.assertEqual(complaint.status, 'Open')

    def test_superuser_cannot_bypass_complaint_approval_decision(self):
        # Create an approval request assigned specifically to CAD approver
        complaint = Complaint.objects.create(
            complaint_id='PAT-26100002',
            complaint_type='pattern',
            created_by=self.regular_user,
            workflow_status=WorkflowStatuses.AWAITING_APPROVAL,
            status='Open',
        )
        approval = ComplaintApproval.objects.create(
            complaint=complaint,
            approval_round=1,
            approver_role=ApprovalRoles.CAD,
            approver_user=self.cad_approver,
            status=DecisionStatuses.PENDING,
            review_stage=ApprovalStages.INITIAL,
            required=True,
        )

        # Superuser trying to decide complaint approval directly without being the assigned approver
        with self.assertRaises(PermissionError):
            record_approval_decision(approval.id, self.superuser, DecisionStatuses.APPROVED)

        # Complaint approval workflow state remains completely unchanged
        approval.refresh_from_db()
        self.assertEqual(approval.status, DecisionStatuses.PENDING)

    # =========================================================================
    # 5. Designer Verification Tests
    # =========================================================================
    def test_superuser_designer_verification_two_stage_workflow(self):
        tiny_gif = b'GIF89a\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00\xff\xff\xff!\xf9\x04\x01\x00\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;'
        dummy_file = SimpleUploadedFile('test_pattern.gif', tiny_gif, content_type='image/gif')
        design_image = PatternDesignImage.objects.create(
            vehicle=self.year_range,
            image=dummy_file,
            title='Seat Cover 3D Model',
            uploaded_by=self.designer,
            approval_status='pending',
        )
        approval = submit_design_for_approval(design_image, self.designer)

        self.assertEqual(approval.cad_status, 'pending')
        self.assertEqual(approval.ed_status, 'pending')
        self.assertEqual(design_image.approval_status, 'pending')

        # 1. Superuser accesses design approvals list and detail
        self.client.force_login(self.superuser)
        list_res = self.client.get(reverse('design_approvals_list'))
        self.assertEqual(list_res.status_code, 200)
        self.assertContains(list_res, 'Seat Cover 3D Model')

        detail_res = self.client.get(reverse('design_approval_detail', args=[design_image.id]))
        self.assertEqual(detail_res.status_code, 200)
        # Both CAD and ED review forms are visible to superuser
        self.assertTrue(detail_res.context['can_review_as_cad'])
        self.assertTrue(detail_res.context['can_review_as_ed'])

        # 2. Superuser approves CAD stage
        cad_res = self.client.post(reverse('design_approval_detail', args=[design_image.id]), {
            'action': 'review',
            'stage': 'cad',
            'decision': 'approved',
            'comment': 'CAD dimensions verified by Superuser',
        })
        self.assertEqual(cad_res.status_code, 302)

        approval.refresh_from_db()
        design_image.refresh_from_db()

        # CAD approved, but ED remains pending!
        self.assertEqual(approval.cad_status, 'approved')
        self.assertEqual(approval.cad_reviewer, self.superuser)
        self.assertEqual(approval.cad_comment, 'CAD dimensions verified by Superuser')
        self.assertEqual(approval.ed_status, 'pending')
        # Overall status is still pending (partially approved), NOT fully approved!
        self.assertEqual(design_image.approval_status, 'pending')
        self.assertEqual(approval.status, 'partially_approved')

        # 3. Superuser approves ED stage
        ed_res = self.client.post(reverse('design_approval_detail', args=[design_image.id]), {
            'action': 'review',
            'stage': 'ed',
            'decision': 'approved',
            'comment': 'ED engineering verified by Superuser',
        })
        self.assertEqual(ed_res.status_code, 302)

        approval.refresh_from_db()
        design_image.refresh_from_db()

        # Now BOTH CAD and ED are approved -> full approval!
        self.assertEqual(approval.ed_status, 'approved')
        self.assertEqual(approval.ed_reviewer, self.superuser)
        self.assertEqual(approval.status, 'approved')
        self.assertEqual(design_image.approval_status, 'approved')
        self.assertEqual(design_image.approved_by, self.superuser)

        # Audit log verifies superuser actions
        cad_log = ActivityLog.objects.filter(user=self.superuser, action='design_approved_cad').first()
        ed_log = ActivityLog.objects.filter(user=self.superuser, action='design_approved_ed').first()
        self.assertIsNotNone(cad_log)
        self.assertIsNotNone(ed_log)

    def test_superuser_rejects_designer_upload_with_mandatory_comment(self):
        tiny_gif = b'GIF89a\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00\xff\xff\xff!\xf9\x04\x01\x00\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;'
        dummy_file = SimpleUploadedFile('test_pattern_2.gif', tiny_gif, content_type='image/gif')
        design_image = PatternDesignImage.objects.create(
            vehicle=self.year_range,
            image=dummy_file,
            title='Door Trim Pattern',
            uploaded_by=self.designer,
            approval_status='pending',
        )
        submit_design_for_approval(design_image, self.designer)

        # Rejection without comment fails with ValidationError
        with self.assertRaises(ValidationError):
            record_design_review_decision(
                design_image, self.superuser, 'rejected', comment='', stage='cad'
            )

        # Rejection with mandatory comment succeeds
        record_design_review_decision(
            design_image, self.superuser, 'rejected', comment='Needs 5mm seam allowance adjustment', stage='cad'
        )

        approval = design_image.latest_approval
        approval.refresh_from_db()
        design_image.refresh_from_db()
        self.assertEqual(approval.cad_status, 'rejected')
        self.assertEqual(approval.status, 'rejected')
        self.assertEqual(design_image.approval_status, 'rejected')
        self.assertEqual(design_image.rejected_by, self.superuser)

        # Designer receives in-app notification
        notif = Notification.objects.filter(
            recipient=self.designer,
            design_image=design_image,
            notification_type='design_approval',
        ).first()
        self.assertIsNotNone(notif)
        self.assertIn('requested changes', notif.message)

    def test_designer_cannot_self_approve(self):
        tiny_gif = b'GIF89a\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00\xff\xff\xff!\xf9\x04\x01\x00\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;'
        dummy_file = SimpleUploadedFile('su_pattern.gif', tiny_gif, content_type='image/gif')
        design_image = PatternDesignImage.objects.create(
            vehicle=self.year_range,
            image=dummy_file,
            title='SU Uploaded Pattern',
            uploaded_by=self.superuser,
            approval_status='pending',
        )
        submit_design_for_approval(design_image, self.superuser)

        with self.assertRaises(PermissionDenied):
            record_design_review_decision(
                design_image, self.superuser, 'approved', comment='Self approval test', stage='cad'
            )

    def test_unauthorized_user_cannot_review_designer_upload(self):
        tiny_gif = b'GIF89a\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00\xff\xff\xff!\xf9\x04\x01\x00\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;'
        dummy_file = SimpleUploadedFile('unauth_pattern.gif', tiny_gif, content_type='image/gif')
        design_image = PatternDesignImage.objects.create(
            vehicle=self.year_range,
            image=dummy_file,
            title='Sample Design',
            uploaded_by=self.designer,
            approval_status='pending',
        )
        submit_design_for_approval(design_image, self.designer)

        # Regular country executive cannot review design
        with self.assertRaises(PermissionDenied):
            record_design_review_decision(
                design_image, self.regular_user, 'approved', comment='Unauth review', stage='cad'
            )
