from django.contrib.auth import get_user_model
from django.test import TestCase, Client
from django.urls import reverse

from management.models import (
    Brand,
    Model,
    SubModel,
    YearRange,
    VehicleDriveLink,
    UserProfile,
    WorkflowRoles,
)

User = get_user_model()


class VehicleDriveLinksTests(TestCase):
    def setUp(self):
        self.client = Client()

        # Superuser
        self.superuser = User.objects.create_superuser(
            username='admin_test',
            password='admin_password123',
            email='admin@fabro.test',
        )

        # Normal User (e.g. Country Executive)
        self.normal_user = User.objects.create_user(
            username='staff_test',
            password='staff_password123',
            email='staff@fabro.test',
        )
        profile, _ = UserProfile.objects.get_or_create(user=self.normal_user)
        profile.role = WorkflowRoles.COUNTRY_EXECUTIVE
        profile.save()

        self.designer = User.objects.create_user(
            username='designer_drive_test', password='designer_password123',
            email='designer@fabro.test',
        )
        designer_profile, _ = UserProfile.objects.get_or_create(user=self.designer)
        designer_profile.role = WorkflowRoles.FREELANCE_3D_DESIGNER
        designer_profile.save()

        # Vehicle
        self.brand = Brand.objects.create(name='Toyota')
        self.model = Model.objects.create(brand=self.brand, name='Land Cruiser')
        self.sub_model = SubModel.objects.create(model=self.model, name='HT76')
        self.vehicle = YearRange.objects.create(
            sub_model=self.sub_model,
            year_start=1990,
            year_end=2021,
            serial_number='I9999',
            layout_code='LC-HT76-9021',
            google_drive_url='https://drive.google.com/drive/folders/initial123',
        )

    def test_get_drive_links_api(self):
        VehicleDriveLink.objects.create(
            vehicle=self.vehicle,
            url='https://drive.google.com/drive/folders/folderA',
            title='Front Pattern',
            created_by=self.superuser,
        )
        self.client.force_login(self.normal_user)
        url = reverse('vehicle_drive_links_api', args=[self.vehicle.id])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['status'], 'success')
        self.assertEqual(len(data['links']), 1)
        self.assertEqual(data['links'][0]['title'], 'Front Pattern')

    def test_superuser_can_add_drive_link(self):
        self.client.force_login(self.superuser)
        url = reverse('vehicle_drive_links_api', args=[self.vehicle.id])
        response = self.client.post(url, {
            'url': 'https://drive.google.com/drive/folders/folderB',
            'title': 'Rear Pattern',
        })
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['status'], 'success')
        self.assertEqual(data['link']['title'], 'Rear Pattern')
        self.assertTrue(VehicleDriveLink.objects.filter(vehicle=self.vehicle, title='Rear Pattern').exists())

    def test_designer_can_add_drive_link_from_visible_control(self):
        self.client.force_login(self.designer)
        page = self.client.get(reverse('car_details'))
        self.assertContains(page, 'id="googleDriveAddSection"')
        response = self.client.post(reverse('vehicle_drive_links_api', args=[self.vehicle.pk]), {
            'url': 'https://drive.google.com/drive/folders/designer-pattern',
            'title': 'Designer CAD folder',
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(VehicleDriveLink.objects.get(title='Designer CAD folder').created_by, self.designer)

    def test_non_drive_destination_is_rejected(self):
        self.client.force_login(self.superuser)
        response = self.client.post(reverse('vehicle_drive_links_api', args=[self.vehicle.pk]), {
            'url': 'https://example.com/not-drive', 'title': 'Wrong destination',
        })
        self.assertEqual(response.status_code, 400)

    def test_non_superuser_cannot_add_drive_link(self):
        self.client.force_login(self.normal_user)
        url = reverse('vehicle_drive_links_api', args=[self.vehicle.id])
        response = self.client.post(url, {
            'url': 'https://drive.google.com/drive/folders/folderC',
            'title': 'Hacker Pattern',
        })
        self.assertEqual(response.status_code, 403)
        self.assertFalse(VehicleDriveLink.objects.filter(title='Hacker Pattern').exists())

    def test_superuser_can_delete_drive_link(self):
        link = VehicleDriveLink.objects.create(
            vehicle=self.vehicle,
            url='https://drive.google.com/drive/folders/folderD',
            title='Delete Me',
            created_by=self.superuser,
        )
        self.client.force_login(self.superuser)
        url = reverse('delete_vehicle_drive_link_api', args=[link.id])
        response = self.client.post(url)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(VehicleDriveLink.objects.filter(id=link.id).exists())

    def test_non_superuser_cannot_delete_drive_link(self):
        link = VehicleDriveLink.objects.create(
            vehicle=self.vehicle,
            url='https://drive.google.com/drive/folders/folderE',
            title='Keep Me',
            created_by=self.superuser,
        )
        self.client.force_login(self.normal_user)
        url = reverse('delete_vehicle_drive_link_api', args=[link.id])
        response = self.client.post(url)
        self.assertEqual(response.status_code, 403)
        self.assertTrue(VehicleDriveLink.objects.filter(id=link.id).exists())

    def test_design_folders_api_includes_drive_links(self):
        VehicleDriveLink.objects.create(
            vehicle=self.vehicle,
            url='https://drive.google.com/drive/folders/folderF',
            title='CAD Files',
            created_by=self.superuser,
        )
        self.client.force_login(self.normal_user)
        url = reverse('get_design_folders_api') + f'?vehicle_id={self.vehicle.id}'
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn('vehicle', data)
        self.assertIn('drive_links', data['vehicle'])
        self.assertEqual(len(data['vehicle']['drive_links']), 1)
        self.assertEqual(data['vehicle']['drive_links'][0]['title'], 'CAD Files')

    def test_add_drive_link_empty_url_returns_400(self):
        self.client.force_login(self.superuser)
        url = reverse('vehicle_drive_links_api', args=[self.vehicle.id])
        response = self.client.post(url, {
            'url': '   ',
            'title': 'Empty',
        })
        self.assertEqual(response.status_code, 400)
        data = response.json()
        self.assertEqual(data['status'], 'error')

    def test_add_multiple_drive_links(self):
        self.client.force_login(self.superuser)
        url = reverse('vehicle_drive_links_api', args=[self.vehicle.id])
        for i in range(1, 4):
            self.client.post(url, {
                'url': f'https://drive.google.com/drive/folders/folder_{i}',
                'title': f'Link {i}',
            })
        self.assertEqual(self.vehicle.drive_links.count(), 3)
        get_res = self.client.get(url)
        data = get_res.json()
        self.assertEqual(len(data['links']), 3)
        # Newest first
        self.assertEqual(data['links'][0]['title'], 'Link 3')

    def test_car_details_page_renders_add_section_only_for_superuser(self):
        # When logged in as superuser:
        self.client.force_login(self.superuser)
        resp_admin = self.client.get(reverse('car_details'))
        self.assertEqual(resp_admin.status_code, 200)
        self.assertContains(resp_admin, 'id="googleDriveAddSection"')
        self.assertContains(resp_admin, 'id="vehicleGoogleDriveDropdownMenu"')

        # When logged in as normal user:
        self.client.force_login(self.normal_user)
        resp_normal = self.client.get(reverse('car_details'))
        self.assertEqual(resp_normal.status_code, 200)
        self.assertNotContains(resp_normal, 'id="googleDriveAddSection"')
        self.assertContains(resp_normal, 'id="vehicleGoogleDriveDropdownMenu"')
