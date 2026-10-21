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
                    self.assertEqual((approval.cad_status, approval.ed_status, approval.md_status), ('pending',) * 3)
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

    def test_om_notification_destination_remains_restricted(self):
        self.upload(self.om, False)
        image = PatternDesignImage.objects.latest('pk')
        self.assertEqual(self.client.get(reverse('design_approval_detail', args=[image.pk])).status_code, 403)
        gallery = self.client.get(reverse('get_design_folders_api'), {'vehicle_id': self.vehicle.pk}).json()
        self.assertNotIn(image.pk, {entry['id'] for entry in gallery['design_files']})

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

