from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from management.models import (
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

        for user in (self.designer, self.pm):
            with self.subTest(user=user.username):
                self.assertEqual(self.upload(user, True).status_code, 403)

    def test_design_upload_is_designer_only(self):
        response = self.upload(self.designer, False)
        self.assertEqual(response.status_code, 200)
        image = PatternDesignImage.objects.latest('pk')
        self.assertFalse(image.is_reference)
        self.assertTrue(PatternDesignApproval.objects.filter(design_image=image).exists())

        for user in [self.superuser, self.pm] + self.reviewers:
            with self.subTest(user=user.username):
                self.assertEqual(self.upload(user, False).status_code, 403)

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

        for user in [self.designer, self.pm] + self.reviewers:
            with self.subTest(user=user.username):
                self.client.force_login(user)
                self.assertEqual(self.client.post(url).status_code, 403)
                self.assertTrue(PatternDesignImage.objects.filter(pk=image.pk).exists())

        permission = Permission.objects.get(
            content_type__app_label='management',
            codename='delete_patterndesignimage',
        )
        manager = get_user_model().objects.create_user(username='ref_asset_manager')
        manager.user_permissions.add(permission)
        self.client.force_login(manager)
        with patch('management.views.default_storage.delete'):
            self.assertEqual(self.client.post(url).status_code, 200)
        self.assertFalse(PatternDesignImage.objects.filter(pk=image.pk).exists())

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

