from django.contrib.auth import get_user_model
from django.test import TestCase, Client
from django.urls import reverse

from management.models import (
    ActivityLog,
    ApprovalRoles,
    Brand,
    Model,
    SubModel,
    YearRange,
    VehicleDriveLink,
    Notification,
    PatternDesignImage,
    PatternEditLog,
    UserProfile,
    WorkflowRoles,
)
from management.services.workflow import can_user_manage_design_assets

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


class CADDriveLinkPermissionTests(TestCase):
    """Drive entry stores URLs, not file bytes; cover both existing write APIs."""

    @classmethod
    def setUpTestData(cls):
        cls.users = {}
        roles = [
            ('superuser', WorkflowRoles.COUNTRY_EXECUTIVE, '', {'is_superuser': True}),
            ('staff', WorkflowRoles.COUNTRY_EXECUTIVE, '', {'is_staff': True}),
            ('admin', WorkflowRoles.ADMIN, '', {}),
            ('designer', WorkflowRoles.FREELANCE_3D_DESIGNER, '', {}),
            ('country', WorkflowRoles.COUNTRY_EXECUTIVE, '', {}),
            ('factory', WorkflowRoles.FACTORY_EXECUTIVE, '', {}),
            ('viewer', WorkflowRoles.FACTORY_VIEWER, '', {}),
            ('registrar', WorkflowRoles.FACTORY_COMPLAINT_REGISTRAR, '', {}),
            # An unrelated role retaining an old CAD value must not gain access.
            ('stale_cad', WorkflowRoles.FACTORY_VIEWER, ApprovalRoles.CAD, {}),
        ] + [
            (role.lower(), WorkflowRoles.APPROVER, role, {})
            for role, _ in ApprovalRoles.CHOICES
        ]
        for name, role, approval_role, flags in roles:
            user = User.objects.create_user(username='drive_' + name, **flags)
            profile = user.workflow_profile
            profile.role = role
            profile.approval_role = approval_role
            profile.save()
            cls.users[name] = user
        brand = Brand.objects.create(name='Drive permission brand')
        model = Model.objects.create(brand=brand, name='Drive permission model')
        submodel = SubModel.objects.create(model=model, name='Drive permission submodel')
        cls.vehicle = YearRange.objects.create(
            sub_model=submodel, year_start=2025, year_end=2026, layout_code='CAD-DRIVE',
        )

    def endpoints(self):
        return (
            (reverse('vehicle_drive_links_api', args=[self.vehicle.pk]), 'url'),
            (reverse('update_vehicle_google_drive_api', args=[self.vehicle.pk]), 'google_drive_url'),
        )

    def test_cad_and_existing_authorized_roles_can_save_through_each_endpoint(self):
        for name in ('cad', 'superuser', 'staff', 'admin', 'designer', 'md'):
            user = self.users[name]
            self.client.force_login(user)
            page = self.client.get(reverse('car_details'))
            self.assertContains(page, 'id="googleDriveAddSection"', count=1)
            self.assertContains(page, 'id="saveGoogleDriveBtn"', count=1)
            for index, (url, field) in enumerate(self.endpoints()):
                with self.subTest(role=name, endpoint=url):
                    destination = f'https://drive.google.com/drive/folders/{name}-{index}'
                    response = self.client.post(url, {field: destination, 'title': 'CAD folder'})
                    self.assertEqual(response.status_code, 200)
                    self.assertEqual(response.json()['status'], 'success')
                    link = VehicleDriveLink.objects.get(vehicle=self.vehicle, url=destination)
                    self.assertEqual(link.created_by, user)
                    self.assertIn(link.pk, [item['id'] for item in response.json()['links']])

    def test_unauthorized_roles_cannot_save_through_either_endpoint(self):
        for name in ('country', 'factory', 'viewer', 'registrar', 'stale_cad', 'pm', 'om', 'ed'):
            self.client.force_login(self.users[name])
            page = self.client.get(reverse('car_details'))
            self.assertNotContains(page, 'id="googleDriveAddSection"')
            self.assertNotContains(page, 'id="saveGoogleDriveBtn"')
            for url, field in self.endpoints():
                with self.subTest(role=name, endpoint=url):
                    response = self.client.post(url, {
                        field: 'https://drive.google.com/drive/folders/forbidden',
                    })
                    self.assertEqual(response.status_code, 403)
        self.assertFalse(VehicleDriveLink.objects.exists())
        self.vehicle.refresh_from_db()
        self.assertEqual(self.vehicle.google_drive_url, '')

    def test_cad_can_access_page_and_supporting_read_endpoints(self):
        self.client.force_login(self.users['cad'])
        self.assertEqual(self.client.get(reverse('car_details')).status_code, 200)
        self.assertEqual(self.client.get(self.endpoints()[0][0]).status_code, 200)
        gallery = self.client.get(reverse('get_design_folders_api'), {'vehicle_id': self.vehicle.pk})
        self.assertEqual(gallery.status_code, 200)
        self.assertEqual(gallery.json()['vehicle']['drive_links'], [])

    def test_existing_read_access_is_preserved_for_non_writers(self):
        self.client.force_login(self.users['viewer'])
        self.assertEqual(self.client.get(self.endpoints()[0][0]).status_code, 200)

    def test_anonymous_requests_require_login(self):
        urls = [reverse('car_details'), self.endpoints()[0][0], reverse('get_design_folders_api')]
        for url in urls:
            with self.subTest(url=url, method='GET'):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 302)
                self.assertIn('/login/?next=', response.url)
        for url, field in self.endpoints():
            with self.subTest(url=url, method='POST'):
                response = self.client.post(url, {field: 'https://drive.google.com/drive/folders/test'})
                self.assertEqual(response.status_code, 302)
                self.assertIn('/login/?next=', response.url)
        self.assertFalse(VehicleDriveLink.objects.exists())

    def test_csrf_is_required_and_valid_token_allows_each_write(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.users['cad'])
        client.get(reverse('car_details'))
        token = client.cookies['csrftoken'].value
        for index, (url, field) in enumerate(self.endpoints()):
            with self.subTest(endpoint=url):
                data = {field: f'https://drive.google.com/drive/folders/csrf-{index}'}
                self.assertEqual(client.post(url, data).status_code, 403)
                self.assertEqual(client.post(url, data, HTTP_X_CSRFTOKEN='bad').status_code, 403)
                self.assertFalse(VehicleDriveLink.objects.filter(url=data[field]).exists())
                self.assertEqual(client.post(url, data, HTTP_X_CSRFTOKEN=token).status_code, 200)

    def test_invalid_urls_and_oversized_urls_remain_rejected_by_each_endpoint(self):
        self.client.force_login(self.users['cad'])
        invalid_urls = (
            'https://example.com/folder', 'http://drive.google.com/folder',
            'javascript:alert(1)', 'https://drive.google.com.evil.test/folder',
            'https://drive.google.com/drive/folders/' + 'a' * 500,
        )
        for url, field in self.endpoints():
            for value in invalid_urls:
                with self.subTest(endpoint=url, value=value[:65]):
                    response = self.client.post(url, {field: value})
                    self.assertEqual(response.status_code, 400)
                    self.assertEqual(response.json()['status'], 'error')
        self.assertFalse(VehicleDriveLink.objects.exists())

    def test_link_entry_rejects_missing_payload_and_oversized_title(self):
        self.client.force_login(self.users['cad'])
        url, field = self.endpoints()[0]
        for data in ({}, {field: '   '}, {
            field: 'https://drive.google.com/drive/folders/valid', 'title': 'a' * 256,
        }):
            with self.subTest(data=data):
                self.assertEqual(self.client.post(url, data).status_code, 400)
        self.assertEqual(self.client.post(url, '{}', content_type='application/json').status_code, 400)
        self.assertFalse(VehicleDriveLink.objects.exists())

    def test_url_normalization_and_legacy_clear_behavior_are_preserved(self):
        self.client.force_login(self.users['cad'])
        for index, (url, field) in enumerate(self.endpoints()):
            destination = f'drive.google.com/drive/folders/normalized-{index}'
            response = self.client.post(url, {field: '  ' + destination + '  '})
            self.assertEqual(response.status_code, 200)
            self.assertTrue(VehicleDriveLink.objects.filter(url='https://' + destination).exists())
        url, field = self.endpoints()[1]
        self.assertEqual(self.client.post(url, {field: ''}).status_code, 200)
        self.vehicle.refresh_from_db()
        self.assertEqual(self.vehicle.google_drive_url, '')
        self.assertEqual(VehicleDriveLink.objects.count(), 2)

    def test_existing_persistence_and_attribution_without_file_or_workflow_side_effects(self):
        self.client.force_login(self.users['cad'])
        models = (ActivityLog, PatternEditLog, PatternDesignImage, Notification)
        before = [model.objects.count() for model in models]
        destination = 'https://drive.google.com/drive/folders/attributed'
        url, field = self.endpoints()[0]
        self.assertEqual(self.client.post(url, {field: destination}).status_code, 200)
        link = VehicleDriveLink.objects.get(url=destination)
        self.assertEqual(link.created_by, self.users['cad'])
        self.assertEqual(link.title, 'Google Drive Folder')
        self.vehicle.refresh_from_db()
        self.assertEqual(self.vehicle.google_drive_url, destination)
        url, field = self.endpoints()[1]
        for _ in range(2):
            self.assertEqual(self.client.post(url, {field: destination}).status_code, 200)
        self.assertEqual(VehicleDriveLink.objects.filter(url=destination).count(), 1)
        self.assertEqual([model.objects.count() for model in models], before)

    def test_cad_does_not_gain_design_options_catalog_or_drive_delete_permissions(self):
        cad = self.users['cad']
        self.assertFalse(can_user_manage_design_assets(cad))
        self.client.force_login(cad)
        page = self.client.get(reverse('car_details'))
        self.assertFalse(page.context['can_manage_design_assets'])
        self.assertFalse(page.context['can_manage_catalog'])
        response = self.client.post(reverse('create_design_folder_api'), {
            'vehicle_id': self.vehicle.pk, 'name': 'Unrelated Design Options',
        })
        self.assertEqual(response.status_code, 403)
        link = VehicleDriveLink.objects.create(vehicle=self.vehicle, url='https://drive.google.com/folder')
        self.assertEqual(self.client.post(
            reverse('delete_vehicle_drive_link_api', args=[link.pk]),
        ).status_code, 403)
        self.assertTrue(VehicleDriveLink.objects.filter(pk=link.pk).exists())
