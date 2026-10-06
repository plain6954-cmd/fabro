import json
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from management.models import (
    ApprovalRoles,
    Brand,
    ChatMessage,
    Model,
    Notification,
    PatternDesignFolder,
    PatternDesignImage,
    PatternDesignApproval,
    SubModel,
    UserProfile,
    WorkflowRoles,
    YearRange,
)


class DesignApprovalWorkflowTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        # 1. Freelance 3D Designer
        cls.designer = User.objects.create_user(
            username='freelance_designer_1',
            password='Password123!',
            email='designer@fabro.test',
        )
        cls.designer_profile = cls.designer.workflow_profile
        cls.designer_profile.role = WorkflowRoles.FREELANCE_3D_DESIGNER
        cls.designer_profile.save()

        # 2. Second Designer (unrelated)
        cls.other_designer = User.objects.create_user(
            username='other_designer_2',
            password='Password123!',
            email='other_designer@fabro.test',
        )
        cls.other_designer_profile = cls.other_designer.workflow_profile
        cls.other_designer_profile.role = WorkflowRoles.FREELANCE_3D_DESIGNER
        cls.other_designer_profile.save()

        # 3. CAD Approver
        cls.cad_user = User.objects.create_user(
            username='cad_approver_1',
            password='Password123!',
            email='cad@fabro.test',
        )
        cls.cad_profile = cls.cad_user.workflow_profile
        cls.cad_profile.role = WorkflowRoles.APPROVER
        cls.cad_profile.approval_role = ApprovalRoles.CAD
        cls.cad_profile.save()

        # 4. ED Approver
        cls.ed_user = User.objects.create_user(
            username='ed_approver_1',
            password='Password123!',
            email='ed@fabro.test',
        )
        cls.ed_profile = cls.ed_user.workflow_profile
        cls.ed_profile.role = WorkflowRoles.APPROVER
        cls.ed_profile.approval_role = ApprovalRoles.ED
        cls.ed_profile.save()

        # 5. Unrelated users: PM Approver & Country Executive
        cls.pm_user = User.objects.create_user(
            username='pm_approver_1',
            password='Password123!',
            email='pm@fabro.test',
        )
        cls.pm_profile = cls.pm_user.workflow_profile
        cls.pm_profile.role = WorkflowRoles.APPROVER
        cls.pm_profile.approval_role = ApprovalRoles.PM
        cls.pm_profile.save()

        cls.country_user = User.objects.create_user(
            username='country_exec_1',
            password='Password123!',
            email='country@fabro.test',
        )
        cls.country_profile = cls.country_user.workflow_profile
        cls.country_profile.role = WorkflowRoles.COUNTRY_EXECUTIVE
        cls.country_profile.save()

        # Catalog setup
        cls.brand = Brand.objects.create(name='Lexus Design')
        cls.model = Model.objects.create(brand=cls.brand, name='RX')
        cls.sub_model = SubModel.objects.create(model=cls.model, name='350')
        cls.vehicle = YearRange.objects.create(
            sub_model=cls.sub_model,
            year_start=2024,
            year_end=2025,
            layout_code='RX-2425',
        )
        cls.folder = PatternDesignFolder.objects.create(
            vehicle=cls.vehicle,
            name='Seat Patterns 3D',
        )

    def setUp(self):
        super().setUp()
        tiny_gif = b'GIF89a\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00\xff\xff\xff!\xf9\x04\x01\x00\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;'
        self.upload_patcher = patch('management.storage_backends.upload_content', return_value='ok')
        self.url_patcher = patch('management.storage_backends.create_signed_download_url', return_value='/media/test.gif')
        self.download_patcher = patch('management.storage_backends.download_content', return_value=tiny_gif)
        self.upload_mock = self.upload_patcher.start()
        self.url_mock = self.url_patcher.start()
        self.download_mock = self.download_patcher.start()
        self.addCleanup(self.upload_patcher.stop)
        self.addCleanup(self.url_patcher.stop)
        self.addCleanup(self.download_patcher.stop)

    def _create_sample_design_image(self, uploaded_by=None, initial_status='pending'):
        uploaded_by = uploaded_by or self.designer
        tiny_gif = b'GIF89a\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00\xff\xff\xff!\xf9\x04\x01\x00\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;'
        file_obj = SimpleUploadedFile('seat_cushion_3d.gif', tiny_gif, content_type='image/gif')
        img = PatternDesignImage.objects.create(
            folder=self.folder,
            vehicle=self.vehicle,
            image=file_obj,
            title='seat_cushion_3d.gif',
            file_size=len(tiny_gif),
            uploaded_by=uploaded_by,
            approval_status=initial_status,
        )
        return img

    # Test 1 & 2 & 3: Designer submits design → CAD receives request, ED receives request, Unrelated users do NOT receive
    @patch('management.services.push_notifications.send_push_to_user')
    def test_01_02_03_designer_submits_design_notifies_cad_and_ed_only(self, mock_push):
        self.client.force_login(self.designer)
        tiny_gif = b'GIF89a\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00\xff\xff\xff!\xf9\x04\x01\x00\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;'
        file_obj = SimpleUploadedFile('headrest_3d.gif', tiny_gif, content_type='image/gif')

        with self.captureOnCommitCallbacks(execute=True):
            res = self.client.post(
                reverse('upload_design_images_api', args=[self.folder.id]),
                {'images': [file_obj]}
            )
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data['status'], 'success')
        img_id = data['images'][0]['id']

        img = PatternDesignImage.objects.get(id=img_id)
        self.assertEqual(img.approval_status, 'pending')
        self.assertEqual(img.uploaded_by, self.designer)

        # Explicit approval request created
        appr = img.latest_approval
        self.assertIsNotNone(appr)
        self.assertEqual(appr.cycle, 1)
        self.assertEqual(appr.cad_status, 'pending')
        self.assertEqual(appr.ed_status, 'pending')

        # Check notifications: CAD & ED received, PM & Country exec did NOT receive
        notifs = Notification.objects.filter(design_image=img, notification_type='design_approval')
        recipients = set(notifs.values_list('recipient__username', flat=True))
        self.assertIn(self.cad_user.username, recipients)
        self.assertIn(self.ed_user.username, recipients)
        self.assertNotIn(self.pm_user.username, recipients)
        self.assertNotIn(self.country_user.username, recipients)
        self.assertNotIn(self.designer.username, recipients)

        # Web Push mock verified for CAD and ED
        pushed_users = [(call.kwargs.get('user') or (call.args[0] if call.args else None)) for call in mock_push.call_args_list]
        self.assertIn(self.cad_user, pushed_users)
        self.assertIn(self.ed_user, pushed_users)
        self.assertNotIn(self.pm_user, pushed_users)

    # Test 4: CAD can approve
    def test_04_cad_can_approve(self):
        img = self._create_sample_design_image()
        from management.services.design_approvals import submit_design_for_approval
        submit_design_for_approval(img, self.designer)

        self.client.force_login(self.cad_user)
        res = self.client.post(reverse('approve_design_image_api', args=[img.id]), {'comment': 'Pattern matches CAD template'})
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data['status'], 'success')
        self.assertEqual(data['cad_status'], 'approved')

        appr = img.latest_approval
        self.assertEqual(appr.cad_status, 'approved')
        self.assertEqual(appr.cad_reviewer, self.cad_user)
        self.assertEqual(appr.cad_comment, 'Pattern matches CAD template')

    # Test 5: CAD can decline
    def test_05_cad_can_decline(self):
        img = self._create_sample_design_image()
        from management.services.design_approvals import submit_design_for_approval
        submit_design_for_approval(img, self.designer)

        self.client.force_login(self.cad_user)
        decline_reason = "Left bolster seam allowance is insufficient."
        res = self.client.post(
            reverse('reject_design_image_api', args=[img.id]),
            json.dumps({'reason': decline_reason}),
            content_type='application/json'
        )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()['status'], 'success')

        img.refresh_from_db()
        appr = img.latest_approval
        self.assertEqual(appr.cad_status, 'rejected')
        self.assertEqual(appr.cad_comment, decline_reason)
        self.assertEqual(img.approval_status, 'rejected')

    # Test 6: ED can approve
    def test_06_ed_can_approve(self):
        img = self._create_sample_design_image()
        from management.services.design_approvals import submit_design_for_approval
        submit_design_for_approval(img, self.designer)

        self.client.force_login(self.ed_user)
        res = self.client.post(reverse('approve_design_image_api', args=[img.id]), {'comment': 'Engineering dimensions verified'})
        self.assertEqual(res.status_code, 200)

        appr = img.latest_approval
        self.assertEqual(appr.ed_status, 'approved')
        self.assertEqual(appr.ed_reviewer, self.ed_user)
        self.assertEqual(appr.ed_comment, 'Engineering dimensions verified')

    # Test 7: ED can decline
    def test_07_ed_can_decline(self):
        img = self._create_sample_design_image()
        from management.services.design_approvals import submit_design_for_approval
        submit_design_for_approval(img, self.designer)

        self.client.force_login(self.ed_user)
        decline_reason = "Airbag deploy seam notch must be 15mm from center."
        res = self.client.post(
            reverse('reject_design_image_api', args=[img.id]),
            json.dumps({'reason': decline_reason}),
            content_type='application/json'
        )
        self.assertEqual(res.status_code, 200)

        img.refresh_from_db()
        appr = img.latest_approval
        self.assertEqual(appr.ed_status, 'rejected')
        self.assertEqual(appr.ed_comment, decline_reason)
        self.assertEqual(img.approval_status, 'rejected')

    # Test 8 & 9: CAD cannot submit ED decision, ED cannot submit CAD decision
    def test_08_09_reviewer_cannot_submit_other_reviewer_decision(self):
        img = self._create_sample_design_image()
        from management.services.design_approvals import submit_design_for_approval, record_design_review_decision
        submit_design_for_approval(img, self.designer)

        # CAD approves -> only cad_status is affected, ed_status remains pending
        self.client.force_login(self.cad_user)
        self.client.post(reverse('approve_design_image_api', args=[img.id]))
        appr = img.latest_approval
        self.assertEqual(appr.cad_status, 'approved')
        self.assertEqual(appr.ed_status, 'pending')

        # CAD attempting to approve again gets 409 Conflict
        repeat_cad = self.client.post(reverse('approve_design_image_api', args=[img.id]))
        self.assertEqual(repeat_cad.status_code, 409)

    # Test 10: Designer cannot approve their own design
    def test_10_designer_cannot_approve_own_design(self):
        img = self._create_sample_design_image()
        from management.services.design_approvals import submit_design_for_approval
        submit_design_for_approval(img, self.designer)

        self.client.force_login(self.designer)
        res = self.client.post(reverse('approve_design_image_api', args=[img.id]))
        self.assertEqual(res.status_code, 403)

    # Test 11: Unauthorized user cannot approve design
    def test_11_unauthorized_user_cannot_approve_design(self):
        img = self._create_sample_design_image()
        from management.services.design_approvals import submit_design_for_approval
        submit_design_for_approval(img, self.designer)

        # Country Executive
        self.client.force_login(self.country_user)
        res_country = self.client.post(reverse('approve_design_image_api', args=[img.id]))
        self.assertEqual(res_country.status_code, 403)

        # PM Approver (not CAD or ED)
        self.client.force_login(self.pm_user)
        res_pm = self.client.post(reverse('approve_design_image_api', args=[img.id]))
        self.assertEqual(res_pm.status_code, 403)

    # Test 12: Decline without comment is rejected
    def test_12_decline_without_comment_is_rejected(self):
        img = self._create_sample_design_image()
        from management.services.design_approvals import submit_design_for_approval
        submit_design_for_approval(img, self.designer)

        self.client.force_login(self.cad_user)
        res = self.client.post(
            reverse('reject_design_image_api', args=[img.id]),
            json.dumps({'reason': '   '}),
            content_type='application/json'
        )
        self.assertEqual(res.status_code, 400)

        # Image remains pending
        img.refresh_from_db()
        self.assertEqual(img.approval_status, 'pending')

    # Test 13 & 14: CAD and ED comments are visible to submitting Designer
    def test_13_14_cad_and_ed_comments_visible_to_submitting_designer(self):
        img = self._create_sample_design_image()
        from management.services.design_approvals import submit_design_for_approval
        submit_design_for_approval(img, self.designer)

        # CAD approves with comment
        self.client.force_login(self.cad_user)
        self.client.post(reverse('approve_design_image_api', args=[img.id]), {'comment': 'CAD approved dimensions.'})

        # ED declines with comment
        self.client.force_login(self.ed_user)
        self.client.post(
            reverse('reject_design_image_api', args=[img.id]),
            json.dumps({'reason': 'ED requires seat belt cut modification.'}),
            content_type='application/json'
        )

        # Designer visits review detail page
        self.client.force_login(self.designer)
        res = self.client.get(reverse('design_approval_detail', args=[img.id]))
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, 'CAD approved dimensions.')
        self.assertContains(res, 'ED requires seat belt cut modification.')

    # Test 15 & 16: CAD and ED decisions notify submitting Designer
    @patch('management.services.push_notifications.send_push_to_user')
    def test_15_16_cad_and_ed_decisions_notify_submitting_designer(self, mock_push):
        img = self._create_sample_design_image()
        from management.services.design_approvals import submit_design_for_approval
        submit_design_for_approval(img, self.designer)

        # CAD approves
        self.client.force_login(self.cad_user)
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(reverse('approve_design_image_api', args=[img.id]), {'comment': 'Looks solid.'})

        cad_notif = Notification.objects.filter(recipient=self.designer, design_image=img).latest('created_at')
        self.assertIn('CAD', cad_notif.title)

        # ED declines
        self.client.force_login(self.ed_user)
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(
                reverse('reject_design_image_api', args=[img.id]),
                json.dumps({'reason': 'Adjust margin.'}),
                content_type='application/json'
            )

        ed_notif = Notification.objects.filter(recipient=self.designer, design_image=img).latest('created_at')
        self.assertIn('ED', ed_notif.title)

        # Web Push mock verified for designer
        pushed_users = [(call.kwargs.get('user') or (call.args[0] if call.args else None)) for call in mock_push.call_args_list]
        self.assertIn(self.designer, pushed_users)

    # Test 17 & 18: Single approval alone does NOT fully approve design
    def test_17_18_single_approval_alone_does_not_fully_approve(self):
        img = self._create_sample_design_image()
        from management.services.design_approvals import submit_design_for_approval
        submit_design_for_approval(img, self.designer)

        # CAD approves alone
        self.client.force_login(self.cad_user)
        self.client.post(reverse('approve_design_image_api', args=[img.id]))
        img.refresh_from_db()
        self.assertEqual(img.approval_status, 'pending')
        self.assertEqual(img.latest_approval.status, 'partially_approved')

        # Reset and test ED alone
        img2 = self._create_sample_design_image()
        submit_design_for_approval(img2, self.designer)
        self.client.force_login(self.ed_user)
        self.client.post(reverse('approve_design_image_api', args=[img2.id]))
        img2.refresh_from_db()
        self.assertEqual(img2.approval_status, 'pending')
        self.assertEqual(img2.latest_approval.status, 'partially_approved')

    # Test 19: CAD + ED approval results in overall approved state
    def test_19_both_cad_and_ed_approval_results_in_overall_approved(self):
        img = self._create_sample_design_image()
        from management.services.design_approvals import submit_design_for_approval
        submit_design_for_approval(img, self.designer)

        self.client.force_login(self.cad_user)
        self.client.post(reverse('approve_design_image_api', args=[img.id]))

        self.client.force_login(self.ed_user)
        self.client.post(reverse('approve_design_image_api', args=[img.id]))

        img.refresh_from_db()
        self.assertEqual(img.approval_status, 'approved')
        self.assertEqual(img.latest_approval.status, 'approved')

    # Test 20: Either CAD or ED decline results in changes-required state
    def test_20_either_decline_results_in_changes_required(self):
        img = self._create_sample_design_image()
        from management.services.design_approvals import submit_design_for_approval
        submit_design_for_approval(img, self.designer)

        # CAD approves, ED declines
        self.client.force_login(self.cad_user)
        self.client.post(reverse('approve_design_image_api', args=[img.id]))

        self.client.force_login(self.ed_user)
        self.client.post(
            reverse('reject_design_image_api', args=[img.id]),
            json.dumps({'reason': 'Thickness wrong'}),
            content_type='application/json'
        )

        img.refresh_from_db()
        self.assertEqual(img.approval_status, 'rejected')
        self.assertEqual(img.latest_approval.status, 'rejected')

    # Test 21: Designer resubmission notifies both CAD and ED
    @patch('management.services.push_notifications.send_push_to_user')
    def test_21_designer_resubmission_notifies_both_cad_and_ed(self, mock_push):
        img = self._create_sample_design_image()
        from management.services.design_approvals import submit_design_for_approval, record_design_review_decision
        submit_design_for_approval(img, self.designer)
        record_design_review_decision(img, self.cad_user, 'rejected', 'Fix outer border')

        img.refresh_from_db()
        self.assertEqual(img.approval_status, 'rejected')

        # Designer resubmits
        self.client.force_login(self.designer)
        with self.captureOnCommitCallbacks(execute=True):
            res = self.client.post(reverse('resubmit_design_image_api', args=[img.id]))
        self.assertEqual(res.status_code, 200)

        img.refresh_from_db()
        self.assertEqual(img.approval_status, 'pending')
        self.assertEqual(img.latest_approval.cycle, 2)
        self.assertEqual(img.latest_approval.cad_status, 'pending')
        self.assertEqual(img.latest_approval.ed_status, 'pending')

        # Both CAD and ED received new notification
        notifs = Notification.objects.filter(design_image=img).order_by('-created_at')[:2]
        recipients = set(notifs.values_list('recipient__username', flat=True))
        self.assertIn(self.cad_user.username, recipients)
        self.assertIn(self.ed_user.username, recipients)

    # Test 22: Old review comments/history are not incorrectly treated as approval of a new revision
    def test_22_old_history_preserved_and_does_not_approve_new_revision(self):
        img = self._create_sample_design_image()
        from management.services.design_approvals import submit_design_for_approval, record_design_review_decision
        submit_design_for_approval(img, self.designer)

        # CAD approved in Cycle 1, ED rejected in Cycle 1
        record_design_review_decision(img, self.cad_user, 'approved', 'CAD approved in rev 1')
        record_design_review_decision(img, self.ed_user, 'rejected', 'ED rejected in rev 1')

        # Designer resubmits -> Cycle 2
        submit_design_for_approval(img, self.designer, is_resubmission=True)

        img.refresh_from_db()
        self.assertEqual(img.latest_approval.cycle, 2)
        self.assertEqual(img.latest_approval.cad_status, 'pending')
        self.assertEqual(img.latest_approval.ed_status, 'pending')

        # Cycle 1 is preserved
        cycle1 = img.approval_requests.get(cycle=1)
        self.assertEqual(cycle1.cad_status, 'approved')
        self.assertEqual(cycle1.cad_comment, 'CAD approved in rev 1')
        self.assertEqual(cycle1.ed_status, 'rejected')
        self.assertEqual(cycle1.ed_comment, 'ED rejected in rev 1')

        # Current overall status is pending (NOT approved by CAD's cycle 1 approval)
        self.assertEqual(img.approval_status, 'pending')

    # Test 23: Web Push failure does not prevent approval/decline from being saved
    @patch('management.services.push_notifications.send_push_to_user', side_effect=Exception('Network error'))
    def test_23_push_failure_does_not_break_review_operation(self, mock_push):
        img = self._create_sample_design_image()
        from management.services.design_approvals import submit_design_for_approval
        submit_design_for_approval(img, self.designer)

        self.client.force_login(self.cad_user)
        with self.captureOnCommitCallbacks(execute=True):
            res = self.client.post(reverse('approve_design_image_api', args=[img.id]), {'comment': 'All good'})

        self.assertEqual(res.status_code, 200)
        img.refresh_from_db()
        self.assertEqual(img.latest_approval.cad_status, 'approved')

    # Test 24: In-app notification remains available even if Web Push is unavailable
    @patch('management.services.push_notifications.is_web_push_configured', return_value=False)
    def test_24_in_app_notification_available_when_push_unconfigured(self, mock_configured):
        img = self._create_sample_design_image()
        from management.services.design_approvals import submit_design_for_approval, record_design_review_decision
        submit_design_for_approval(img, self.designer)

        with self.captureOnCommitCallbacks(execute=True):
            record_design_review_decision(img, self.cad_user, 'approved', 'Looks good')

        notif = Notification.objects.filter(recipient=self.designer, design_image=img).first()
        self.assertIsNotNone(notif)
        self.assertIn('CAD Review Completed', notif.title)

    # Test 25: Only submitting Designer receives reviewer-result notification
    def test_25_only_submitting_designer_receives_reviewer_result_notification(self):
        img = self._create_sample_design_image(uploaded_by=self.designer)
        from management.services.design_approvals import submit_design_for_approval, record_design_review_decision
        submit_design_for_approval(img, self.designer)

        record_design_review_decision(img, self.cad_user, 'approved', 'Approved!')

        # Submitting designer received notification
        self.assertTrue(Notification.objects.filter(recipient=self.designer, design_image=img).exists())

        # Other designer did NOT receive notification
        self.assertFalse(Notification.objects.filter(recipient=self.other_designer, design_image=img).exists())
