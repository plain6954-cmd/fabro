from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from management.models import (
    ActivityLog, Notification,
    PatternDesignFolder,
    ApprovalRoles, Brand, Model, PatternDesignApproval,
    PatternDesignImage, SubModel, WorkflowRoles, YearRange,
)


class ReferenceDesignUploadTests(TestCase):
    def setUp(self):
        self.storage = patch(
            'django.core.files.storage.default_storage.save',
            side_effect=lambda name, content, max_length=None: name,
        )
        self.storage.start()
        self.addCleanup(self.storage.stop)

        User = get_user_model()

        self.superuser = User.objects.create_superuser(
            username='ref_superuser', email='super@example.invalid', password='testpass'
        )

        self.designer = User.objects.create_user(username='ref_designer')
        self.designer.workflow_profile.role = WorkflowRoles.FREELANCE_3D_DESIGNER
        self.designer.workflow_profile.save()

        self.reviewers = []
        for role in (ApprovalRoles.MD, ApprovalRoles.CAD, ApprovalRoles.ED):
            user = User.objects.create_user(username='ref_' + role.lower())
            user.workflow_profile.role = WorkflowRoles.APPROVER
            user.workflow_profile.approval_role = role
            user.workflow_profile.save()
            self.reviewers.append(user)

        self.pm = User.objects.create_user(username='ref_pm')
        self.pm.workflow_profile.role = WorkflowRoles.APPROVER
        self.pm.workflow_profile.approval_role = ApprovalRoles.PM
        self.pm.workflow_profile.save()

        self.om = User.objects.create_user(username='ref_om')
        self.om.workflow_profile.role = WorkflowRoles.APPROVER
        self.om.workflow_profile.approval_role = ApprovalRoles.OM
        self.om.workflow_profile.save()

        brand = Brand.objects.create(name='Reference Test Brand')
        model = Model.objects.create(brand=brand, name='Reference Test Model')
        submodel = SubModel.objects.create(model=model, name='Reference Test Submodel')
        self.vehicle = YearRange.objects.create(
            sub_model=submodel, year_start=2025, year_end=2026,
            layout_code='REF-TEST',
        )
        self.url = reverse('upload_vehicle_design_images_api', args=[self.vehicle.pk])

    def upload(self, user, reference, name='sample.obj'):
        self.client.force_login(user)
        return self.client.post(self.url, {
            'is_reference': '1' if reference else '0',
            'images': SimpleUploadedFile(name, b'v 0 0 0\n', content_type='application/octet-stream'),
        })

    def test_reference_upload_permissions_and_no_approval(self):
        for user in [self.superuser] + self.reviewers:
            with self.subTest(user=user.username):
                response = self.upload(user, True)
                self.assertEqual(response.status_code, 200)
                image = PatternDesignImage.objects.latest('pk')
                self.assertTrue(image.is_reference)
                self.assertEqual(PatternDesignApproval.objects.filter(design_image=image).count(), 0)

        for user in (self.designer, self.pm, self.om):
            with self.subTest(user=user.username):
                self.assertEqual(self.upload(user, True).status_code, 403)

    @patch('management.services.push_notifications.send_push_to_user')
    def test_six_upload_roles_visibility_endpoints_and_existing_notifications(self, push):
        from django.core.exceptions import PermissionDenied
        from management.services.design_approvals import record_design_review_decision

        folder = PatternDesignFolder.objects.create(vehicle=self.vehicle, name='Role upload tests')
        for user in [self.designer, self.pm, self.om] + self.reviewers:
            self.client.force_login(user)
            page = self.client.get(reverse('car_details'), {'vehicle_id': self.vehicle.pk})
            self.assertEqual(page.status_code, 200)
            self.assertContains(page, 'id="btnUpload3DDesigns"', count=1)
            self.assertContains(page, 'id="design3DUploadInput"', count=1)
            self.assertEqual(page.context['is_designer'], user == self.designer)
            for url in (self.url, reverse('upload_design_images_api', args=[folder.pk])):
                with self.subTest(user=user.username, url=url):
                    push.reset_mock()
                    with self.captureOnCommitCallbacks(execute=True):
                        response = self.client.post(url, {
                            'is_reference': '0',
                            'images': SimpleUploadedFile('role-design.obj', b'v 0 0 0', content_type='application/octet-stream'),
                        })
                        push.assert_not_called()
                    self.assertEqual(response.status_code, 200)
                    image = PatternDesignImage.objects.get(pk=response.json()['images'][0]['id'])
                    self.assertEqual(image.uploaded_by, user)
                    self.assertFalse(image.is_reference)
                    self.assertEqual(image.approval_status, 'pending')
                    approval = image.latest_approval
                    self.assertEqual(approval.designer, user)
                    own_role = user.workflow_profile.approval_role if user != self.designer else ''
                    for role in ('CAD', 'ED', 'MD'):
                        expected_status = PatternDesignApproval.SKIPPED_UPLOADER if role == own_role else 'pending'
                        self.assertEqual(getattr(approval, role.lower() + '_status'), expected_status)
                    expected = {reviewer.pk for reviewer in self.reviewers if reviewer != user}
                    notifications = Notification.objects.filter(design_image=image)
                    self.assertEqual(set(notifications.values_list('recipient_id', flat=True)), expected)
                    self.assertEqual(notifications.count(), len(expected))
                    self.assertEqual(push.call_count, len(expected))
                    self.assertEqual({call.args[0].pk for call in push.call_args_list}, expected)
                    for call in push.call_args_list:
                        self.assertEqual(call.kwargs['url'], reverse('design_approval_detail', args=[image.pk]))
                    self.assertEqual(ActivityLog.objects.filter(user=user, action='submitted', object_type='Design Image').count(),
                                     1 if url == self.url else 2)
                    with self.assertRaises(PermissionDenied):
                        record_design_review_decision(image, user, 'approved', change_type='minor')

    def test_other_roles_cannot_see_or_use_design_upload(self):
        User = get_user_model()
        users = [self.superuser]
        for role in (WorkflowRoles.ADMIN, WorkflowRoles.COUNTRY_EXECUTIVE, WorkflowRoles.FACTORY_VIEWER,
                     WorkflowRoles.FACTORY_EXECUTIVE, WorkflowRoles.FACTORY_COMPLAINT_REGISTRAR, WorkflowRoles.APPROVER):
            user = User.objects.create_user(username='upload_denied_' + role)
            profile = user.workflow_profile
            profile.role = role
            # A stale approval role on a non-approver must not grant upload access.
            profile.approval_role = '' if role == WorkflowRoles.APPROVER else ApprovalRoles.CAD
            profile.save()
            users.append(user)
        folder = PatternDesignFolder.objects.create(vehicle=self.vehicle, name='Denied uploads')
        for user in users:
            with self.subTest(user=user.username):
                self.client.force_login(user)
                page = self.client.get(reverse('car_details'))
                self.assertEqual(page.status_code, 200)
                self.assertNotContains(page, 'id="btnUpload3DDesigns"')
                self.assertEqual(self.upload(user, False).status_code, 403)
                self.assertEqual(self.client.post(reverse('upload_design_images_api', args=[folder.pk]), {}).status_code, 403)
        from management.views import _can_upload_3d_designs
        self.pm.is_active = False
        self.pm.save(update_fields=['is_active'])
        self.assertFalse(_can_upload_3d_designs(self.pm))
        self.client.logout()
        self.assertEqual(self.client.post(self.url, {}).status_code, 302)

    def test_upload_access_does_not_grant_review_rights_or_block_complaint_reviews(self):
        self.upload(self.designer, False)
        image = PatternDesignImage.objects.latest('pk')
        for user in (self.pm, self.om):
            self.client.force_login(user)
            self.assertEqual(self.client.post(reverse('approve_design_image_api', args=[image.pk]), {'change_type': 'minor'}).status_code, 403)
        # Reaching the lookup (404) preserves complaint-review access for approvers.
        for user in [self.pm, self.om] + self.reviewers:
            self.client.force_login(user)
            self.assertEqual(self.client.get(reverse('approval_review', args=[999999])).status_code, 404)
        self.client.force_login(self.designer)
        self.assertEqual(self.client.get(reverse('approval_review', args=[999999])).status_code, 403)

    @patch('management.services.push_notifications.send_push_to_user', side_effect=RuntimeError('offline'))
    def test_new_uploader_push_failure_does_not_break_upload(self, push):
        with self.captureOnCommitCallbacks(execute=True):
            response = self.upload(self.pm, False)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(push.call_count, 3)

    def test_om_notification_destination_and_pending_gallery_are_readable(self):
        self.upload(self.om, False)
        image = PatternDesignImage.objects.latest('pk')
        self.assertEqual(self.client.get(reverse('design_approval_detail', args=[image.pk])).status_code, 200)
        gallery = self.client.get(reverse('get_design_folders_api'), {'vehicle_id': self.vehicle.pk}).json()
        self.assertIn(image.pk, {entry['id'] for entry in gallery['design_files']})

    def test_new_uploaders_still_require_valid_files_and_csrf(self):
        from django.test import Client
        self.client.force_login(self.pm)
        for filename, content in [('unsafe.exe', b'content'), ('empty.obj', b'')]:
            with self.subTest(filename=filename):
                response = self.client.post(self.url, {'images': SimpleUploadedFile(filename, content)})
                self.assertEqual(response.status_code, 400)
        self.assertEqual(self.client.post(self.url, {}).status_code, 400)
        files = [SimpleUploadedFile(f'file{i}.obj', b'v 0 0 0') for i in range(11)]
        self.assertEqual(self.client.post(self.url, {'images': files}).status_code, 400)
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.pm)
        self.assertEqual(csrf_client.post(self.url, {'images': SimpleUploadedFile('safe.obj', b'v 0 0 0')}).status_code, 403)
        self.assertFalse(PatternDesignImage.objects.exists())

    @patch('management.services.push_notifications.send_push_to_user')
    def test_new_uploaders_receive_existing_review_result_notifications(self, push):
        for uploader in (self.pm, self.om):
            with self.subTest(uploader=uploader.username):
                self.upload(uploader, False)
                image = PatternDesignImage.objects.latest('pk')
                self.client.force_login(self.reviewers[1])  # Existing CAD reviewer.
                push.reset_mock()
                with self.captureOnCommitCallbacks(execute=True):
                    response = self.client.post(reverse('approve_design_image_api', args=[image.pk]), {'change_type': 'minor'})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(Notification.objects.filter(design_image=image, recipient=uploader).count(), 1)
                push.assert_called_once()
                self.assertEqual(push.call_args.args[0], uploader)
                self.assertEqual(push.call_args.kwargs['url'], reverse('design_approval_detail', args=[image.pk]))

    @patch('management.services.push_notifications.send_push_to_user')
    def test_required_stages_complete_for_every_uploader_role(self, push):
        from django.core.exceptions import PermissionDenied
        from management.services.design_approvals import record_design_review_decision, submit_design_for_approval

        for uploader in [self.designer, self.om, self.pm] + self.reviewers:
            with self.subTest(uploader=uploader.username):
                self.upload(uploader, False)
                image = PatternDesignImage.objects.latest('pk')
                approval = image.latest_approval
                statuses = {role: getattr(approval, role + '_status') for role in ('cad', 'ed', 'md')}
                required = [reviewer for reviewer in self.reviewers if statuses[reviewer.workflow_profile.approval_role.lower()] == 'pending']
                self.assertEqual(len(required), 2 if uploader in self.reviewers else 3)
                with self.assertRaises(PermissionDenied):
                    record_design_review_decision(image, uploader, 'approved', stage='ed', change_type='minor')
                for index, reviewer in enumerate(required):
                    record_design_review_decision(image, reviewer, 'approved', 'Optional review text', change_type='major')
                    image.refresh_from_db()
                    self.assertEqual(image.approval_status, 'approved' if index == len(required) - 1 else 'pending')
                approval.refresh_from_db()
                self.assertEqual(approval.status, 'approved')
                self.assertEqual(sum(getattr(approval, role + '_status') == 'approved' for role in statuses), len(required))
                self.client.force_login(self.om)
                detail = self.client.get(reverse('design_approval_detail', args=[image.pk]))
                if len(required) == 2:
                    self.assertContains(detail, 'Skipped — Uploader')
                for role, status in statuses.items():
                    if status == PatternDesignApproval.SKIPPED_UPLOADER:
                        self.assertEqual(getattr(approval, f'get_{role}_status_display')(), 'Skipped — Uploader')
                        self.assertEqual(getattr(approval, role + '_status'), status)
                        self.assertIsNone(getattr(approval, role + '_reviewer'))
                        self.assertIsNone(getattr(approval, role + '_decided_at'))
                        self.assertEqual(getattr(approval, role + '_change_type'), '')
                        self.assertEqual(getattr(approval, role + '_comment'), '')
                # Replaying submission does not re-route or reset the completed cycle.
                before = list(Notification.objects.filter(design_image=image).values_list('pk', flat=True))
                self.assertEqual(submit_design_for_approval(image, uploader).pk, approval.pk)
                self.assertEqual(list(Notification.objects.filter(design_image=image).values_list('pk', flat=True)), before)
                self.assertEqual(image.approval_requests.count(), 1)

    @patch('management.services.push_notifications.send_push_to_user')
    def test_skipped_role_is_not_notified_or_reviewable_by_another_account(self, push):
        from management.services.design_approvals import submit_design_for_approval
        cad = self.reviewers[1]
        alternate = get_user_model().objects.create_user(username='alternate_cad')
        profile = alternate.workflow_profile
        profile.role, profile.approval_role = WorkflowRoles.APPROVER, ApprovalRoles.CAD
        profile.save()
        self.client.force_login(cad)
        def upload():
            return self.client.post(self.url, {'title': 'x' * 255, 'images': SimpleUploadedFile('retry.obj', b'v 0 0 0')}, HTTP_X_UPLOAD_ID='skip-stage-retry')
        with self.captureOnCommitCallbacks(execute=True):
            first = upload()
        with self.captureOnCommitCallbacks(execute=True):
            second = upload()
        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.json()['images'][0]['id'], second.json()['images'][0]['id'])
        image = PatternDesignImage.objects.get(pk=first.json()['images'][0]['id'])
        self.assertEqual(image.approval_requests.count(), 1)
        expected = {self.reviewers[0].pk, self.reviewers[2].pk}
        self.assertEqual(set(Notification.objects.filter(design_image=image).values_list('recipient_id', flat=True)), expected)
        self.assertEqual(push.call_count, 2)
        self.assertEqual({call.args[0].pk for call in push.call_args_list}, expected)
        self.assertTrue(ActivityLog.objects.filter(action='submitted', object_name__contains='CAD: Skipped — Uploader').exists())
        self.assertEqual(len(ActivityLog.objects.get(action='submitted', user=cad).object_name), 255)
        self.client.force_login(alternate)
        for endpoint in ('approve_design_image_api', 'reject_design_image_api'):
            self.assertEqual(self.client.post(reverse(endpoint, args=[image.pk]), {'change_type': 'minor'}).status_code, 409)
        page = self.client.get(reverse('design_approval_detail', args=[image.pk]))
        self.assertContains(page, 'Skipped — Uploader')
        self.assertNotContains(page, 'id="cadReviewForm"')
        # Admin's multi-role capability never bypasses the uploader identity check.
        profile = cad.workflow_profile
        profile.role = WorkflowRoles.ADMIN
        profile.save()
        self.client.force_login(cad)
        self.assertEqual(self.client.post(reverse('approve_design_image_api', args=[image.pk]), {'stage': 'ed', 'change_type': 'minor'}).status_code, 403)
        approval = image.latest_approval
        self.assertEqual(submit_design_for_approval(image, cad).pk, approval.pk)
        self.assertEqual(image.latest_approval.cad_status, PatternDesignApproval.SKIPPED_UPLOADER)

    @patch('management.services.push_notifications.send_push_to_user')
    def test_rejection_and_resubmission_preserve_new_matrix_and_historical_records(self, push):
        from management.services.design_approvals import record_design_review_decision, submit_design_for_approval
        cad, ed, md = self.reviewers[1], self.reviewers[2], self.reviewers[0]
        self.upload(cad, False)
        image = PatternDesignImage.objects.latest('pk')
        record_design_review_decision(image, ed, 'rejected', 'Revise seam', change_type='major')
        first = image.latest_approval
        self.assertEqual(first.status, 'rejected')
        timestamp = first.ed_decided_at
        # A profile change must not alter the matrix chosen when the upload arrived.
        profile = cad.workflow_profile
        profile.approval_role = ApprovalRoles.OM
        profile.save()
        push.reset_mock()
        with self.captureOnCommitCallbacks(execute=True):
            second = submit_design_for_approval(image, cad, is_resubmission=True)
        self.assertEqual(second.cycle, 2)
        self.assertEqual((second.cad_status, second.ed_status, second.md_status), ('skipped_uploader', 'pending', 'pending'))
        self.assertEqual(push.call_count, 2)
        self.assertEqual({call.args[0].pk for call in push.call_args_list}, {ed.pk, md.pk})
        first.refresh_from_db()
        self.assertEqual((first.ed_comment, first.ed_decided_at, first.ed_reviewer), ('Revise seam', timestamp, ed))
        record_design_review_decision(image, md, 'approved', change_type='minor')
        record_design_review_decision(image, ed, 'approved', change_type='minor')
        image.refresh_from_db()
        self.assertEqual(image.approval_status, 'approved')
        legacy = PatternDesignImage.objects.create(vehicle=self.vehicle, image='pattern_designs/legacy.obj', uploaded_by=md)
        historical = PatternDesignApproval.objects.create(design_image=legacy, designer=md)
        submit_design_for_approval(legacy, md)
        historical.refresh_from_db()
        self.assertEqual((historical.cad_status, historical.ed_status, historical.md_status), ('pending',) * 3)

    def test_om_pm_all_design_states_details_media_and_mutation_denials(self):
        from django.utils import timezone
        images = []
        for uploader in [self.designer, self.om, self.pm] + self.reviewers:
            for status in ('pending', 'approved', 'rejected'):
                image = PatternDesignImage.objects.create(vehicle=self.vehicle, uploaded_by=uploader,
                    image='pattern_designs/read-only.png', thumbnail='pattern_design_thumbnails/read-only.webp',
                    title=f'{uploader.username} {status}.png', approval_status=status)
                PatternDesignApproval.objects.create(design_image=image, designer=uploader, status=status,
                    cad_status='approved', cad_reviewer=self.reviewers[1], cad_decided_at=timezone.now(),
                    cad_comment='CAD dimensions verified', cad_change_type='major',
                    ed_status='rejected' if status == 'rejected' else 'approved' if status == 'approved' else 'pending',
                    md_status='approved' if status == 'approved' else 'pending')
                images.append(image)
        expected = {image.pk for image in images}
        for viewer in (self.om, self.pm):
            self.client.force_login(viewer)
            gallery = self.client.get(reverse('get_design_folders_api'), {'vehicle_id': self.vehicle.pk}).json()
            self.assertEqual({item['id'] for item in gallery['design_files']}, expected)
            for image in images:
                with self.subTest(viewer=viewer.username, image=image.pk):
                    detail_url = reverse('design_approval_detail', args=[image.pk])
                    page = self.client.get(detail_url)
                    self.assertEqual(page.status_code, 200)
                    self.assertContains(page, 'CAD dimensions verified')
                    self.assertContains(page, 'Major Change')
                    self.assertContains(page, self.vehicle.serial_number)
                    self.assertContains(page, 'Reference Test Brand')
                    self.assertContains(page, 'id="designImageViewer"')
                    self.assertNotContains(page, 'name="decision"')
                    self.assertFalse(page.context['can_resubmit'])
                    self.assertEqual(self.client.get(reverse('pattern_design_image_download', args=[image.pk])).status_code, 302)
                    before = image.latest_approval.cad_comment
                    for endpoint in ('approve_design_image_api', 'reject_design_image_api', 'resubmit_design_image_api'):
                        self.assertEqual(self.client.post(reverse(endpoint, args=[image.pk]), {'change_type': 'minor'}).status_code, 403)
                    self.assertEqual(self.client.post(detail_url, {'action': 'review', 'decision': 'approved', 'change_type': 'minor'}).status_code, 403)
                    self.assertEqual(image.approval_requests.count(), 1)
                    self.assertEqual(image.latest_approval.cad_comment, before)
            for status in ('pending', 'approved', 'rejected', 'all'):
                page = self.client.get(reverse('design_approvals_list'), {'tab': status})
                self.assertEqual(page.status_code, 200)
                self.assertTrue(all(not item.can_review_by_user for item in page.context['items']))

    def test_reference_and_design_gallery_separation(self):
        self.assertEqual(self.upload(self.superuser, True).status_code, 200)
        self.assertEqual(self.upload(self.designer, False).status_code, 200)

        self.client.force_login(self.superuser)
        response = self.client.get(
            reverse('get_design_folders_api'), {'vehicle_id': self.vehicle.pk}
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()

        reference_ids = {item['id'] for item in data['reference_images']}
        design_ids = {item['id'] for item in data['design_files']}
        self.assertEqual(len(reference_ids), 1)
        self.assertEqual(len(design_ids), 1)
        self.assertFalse(reference_ids & design_ids)

    def test_delete_requires_explicit_permission(self):
        image = PatternDesignImage.objects.create(
            vehicle=self.vehicle, image='pattern_designs/test.obj',
            title='test.obj', uploaded_by=self.designer,
        )
        url = reverse('delete_design_image_api', args=[image.pk])

        # Reviewers and PM cannot delete the designer's uploaded file without permission
        for user in [self.pm] + self.reviewers:
            with self.subTest(user=user.username):
                self.client.force_login(user)
                self.assertEqual(self.client.post(url).status_code, 403)
                self.assertTrue(PatternDesignImage.objects.filter(pk=image.pk).exists())

        # The designer who uploaded it can delete their own uploaded design image
        self.client.force_login(self.designer)
        with patch('management.views.default_storage.delete'):
            self.assertEqual(self.client.post(url).status_code, 200)
        self.assertFalse(PatternDesignImage.objects.filter(pk=image.pk).exists())

        # Manager with explicit delete permission can delete any design image
        image2 = PatternDesignImage.objects.create(
            vehicle=self.vehicle, image='pattern_designs/test2.obj',
            title='test2.obj', uploaded_by=self.designer,
        )
        url2 = reverse('delete_design_image_api', args=[image2.pk])
        permission = Permission.objects.get(
            content_type__app_label='management',
            codename='delete_patterndesignimage',
        )
        manager = get_user_model().objects.create_user(username='ref_asset_manager')
        manager.user_permissions.add(permission)
        self.client.force_login(manager)
        with patch('management.views.default_storage.delete'):
            self.assertEqual(self.client.post(url2).status_code, 200)
        self.assertFalse(PatternDesignImage.objects.filter(pk=image2.pk).exists())

    def test_folder_deletion_requires_explicit_permission(self):
        folder = PatternDesignFolder.objects.create(
            vehicle=self.vehicle,
            name='Protected 3D Designs',
            created_by=self.designer,
        )
        image = PatternDesignImage.objects.create(
            folder=folder,
            image='pattern_designs/protected.obj',
            title='protected.obj',
            uploaded_by=self.designer,
        )
        url = reverse('delete_design_folder_api', args=[folder.pk])

        for user in [self.designer, self.pm] + self.reviewers:
            with self.subTest(user=user.username):
                self.client.force_login(user)
                response = self.client.post(url)
                self.assertEqual(response.status_code, 403)
                self.assertTrue(PatternDesignFolder.objects.filter(pk=folder.pk).exists())
                self.assertTrue(PatternDesignImage.objects.filter(pk=image.pk).exists())

        self.client.force_login(self.superuser)
        with patch('management.views.default_storage.delete'):
            response = self.client.post(url)

        self.assertEqual(response.status_code, 200)
        self.assertFalse(PatternDesignFolder.objects.filter(pk=folder.pk).exists())
        self.assertFalse(PatternDesignImage.objects.filter(pk=image.pk).exists())

