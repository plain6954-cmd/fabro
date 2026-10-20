from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from management.models import (
    ApprovalRoles, Brand, MasterSetting, Model, PatternDesignFolder,
    PatternDesignImage, SubModel, WorkflowRoles, YearRange,
)


class DesignApprovalDetailsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.designer = User.objects.create_user('details_designer')
        cls.other = User.objects.create_user('details_other')
        for user in (cls.designer, cls.other):
            profile = user.workflow_profile
            profile.role = WorkflowRoles.FREELANCE_3D_DESIGNER
            profile.save()
        cls.cad = User.objects.create_user('details_cad')
        profile = cls.cad.workflow_profile
        profile.role, profile.approval_role = WorkflowRoles.APPROVER, ApprovalRoles.CAD
        profile.save()
        cls.factory = User.objects.create_user('details_factory')
        profile = cls.factory.workflow_profile
        profile.role = WorkflowRoles.FACTORY_EXECUTIVE
        profile.save()
        brand = Brand.objects.create(name='Details Brand')
        model = Model.objects.create(brand=brand, name='Details Model')
        sub = SubModel.objects.create(model=model, name='Touring')
        country = MasterSetting.objects.create(category='Country', name='Saudi Arabia')
        cls.vehicle = YearRange.objects.create(
            sub_model=sub, year_start=2024, year_end=2026,
            vehicle_country=country, layout_code='DETAILS-S237',
        )
        # Historical serials are displayed verbatim, never re-numbered on GET.
        YearRange.objects.filter(pk=cls.vehicle.pk).update(serial_number='S237')
        cls.vehicle.refresh_from_db()
        cls.folder = PatternDesignFolder.objects.create(vehicle=cls.vehicle, name='Design details')

    def image(self, **kwargs):
        data = dict(folder=self.folder, uploaded_by=self.designer,
                    image='pattern_designs/existing.png', title='Seat design.png', approval_status='pending')
        data.update(kwargs)
        return PatternDesignImage.objects.create(**data)

    def detail(self, image, user=None):
        self.client.force_login(user or self.designer)
        return self.client.get(reverse('design_approval_detail', args=[image.pk]))

    def test_folder_vehicle_full_name_and_existing_serial(self):
        image = self.image()
        response = self.detail(image)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['design_vehicle'], self.vehicle)
        self.assertContains(response, 'Details Brand Details Model 2024-2026 Touring')
        self.assertContains(response, '<strong>S237</strong>', html=True)
        self.vehicle.refresh_from_db()
        self.assertEqual(self.vehicle.serial_number, 'S237')

    def test_direct_vehicle_takes_precedence_and_preserves_india_prefix(self):
        india, _ = MasterSetting.objects.get_or_create(category='Country', name='India')
        direct = YearRange.objects.create(sub_model=self.vehicle.sub_model,
                                         measurement_country=india, serial_number='I42', year_start=2025)
        image = self.image(vehicle=direct)
        response = self.detail(image)
        self.assertEqual(response.context['design_vehicle'].pk, direct.pk)
        self.assertContains(response, direct.serial_number)
        self.assertEqual(response.context['design_vehicle_name'], 'Details Brand Details Model 2025 Touring')

    def test_missing_association_does_not_invent_vehicle_or_gallery(self):
        image = self.image(folder=None)
        self.image(folder=None)
        response = self.detail(image)
        self.assertIsNone(response.context['design_vehicle'])
        self.assertEqual(response.context['design_vehicle_name'], '')
        self.assertEqual([entry['id'] for entry in response.context['preview_images']], [image.pk])

    def test_gallery_excludes_other_designers_folders_references_and_nonimages(self):
        image = self.image(thumbnail='pattern_design_thumbnails/existing.webp')
        sibling = self.image(image='pattern_designs/another.jpg')
        self.image(uploaded_by=self.other, approval_status='approved')
        self.image(is_reference=True)
        self.image(image='pattern_designs/design.obj')
        self.image(folder=PatternDesignFolder.objects.create(vehicle=self.vehicle, name='Other folder'))
        response = self.detail(image, self.cad)
        entries = response.context['preview_images']
        self.assertEqual([entry['id'] for entry in entries], [image.pk, sibling.pk])
        self.assertEqual(entries[0]['url'], reverse('pattern_design_image_download', args=[image.pk]))
        self.assertIn('pattern_design_thumbnails/existing.webp', entries[0]['thumbnail'])
        self.assertEqual(set(entries[0]), {'id', 'title', 'url', 'thumbnail'})
        self.assertContains(response, 'id="designImageViewer"', count=1)

    def test_direct_gallery_is_scoped_to_pattern_and_uploader(self):
        image = self.image(folder=None, vehicle=self.vehicle)
        sibling = self.image(folder=None, vehicle=self.vehicle)
        self.image(folder=None, vehicle=self.vehicle, uploaded_by=self.other)
        self.image()
        entries = self.detail(image).context['preview_images']
        self.assertEqual([entry['id'] for entry in entries], [image.pk, sibling.pk])

    def test_details_and_fullsize_media_keep_existing_access_controls(self):
        image = self.image()
        detail_url = reverse('design_approval_detail', args=[image.pk])
        media_url = reverse('pattern_design_image_download', args=[image.pk])
        self.assertEqual(self.client.get(detail_url).status_code, 302)
        self.assertEqual(self.client.get(media_url).status_code, 302)
        self.assertEqual(self.detail(image, self.other).status_code, 403)
        self.assertEqual(self.client.get(media_url).status_code, 404)
        self.assertEqual(self.detail(image, self.factory).status_code, 403)
        self.assertEqual(self.client.get(media_url).status_code, 404)
        self.assertEqual(self.detail(image, self.designer).status_code, 200)
        self.assertEqual(self.client.get(media_url).status_code, 302)

    def test_review_defaults_and_optional_remarks_remain_intact(self):
        from management.services.design_approvals import submit_design_for_approval
        image = self.image()
        submit_design_for_approval(image, self.designer)
        response = self.detail(image, self.cad)
        self.assertContains(response, '<option value="minor" selected>Minor Change</option>', html=True)
        self.assertContains(response, 'id="cadReviewForm"')
        self.assertNotContains(response, 'Mandatory if declining')
        self.assertContains(response, 'Optional')
