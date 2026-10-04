"""Tests for Region Spec, Measured in, and Drive dropdown APIs and table rendering."""
import json
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

from .models import (
    Brand,
    MasterSetting,
    Model,
    SubModel,
    UserProfile,
    WorkflowRoles,
    YearRange,
)


class CountryAndDriveDropdownTests(TestCase):
    def setUp(self):
        cache.clear()
        User = get_user_model()
        self.admin = User.objects.create_superuser('country-admin', password='test-password-123')
        profile = getattr(self.admin, 'workflow_profile', None) or UserProfile.objects.get(user=self.admin)
        profile.role = WorkflowRoles.ADMIN
        profile.save()

        self.regular_user = User.objects.create_user('regular-viewer', password='test-password-123')
        viewer_profile = getattr(self.regular_user, 'workflow_profile', None) or UserProfile.objects.get(user=self.regular_user)
        viewer_profile.role = WorkflowRoles.FACTORY_VIEWER
        viewer_profile.save()

        self.brand = Brand.objects.create(name='Audi')
        self.model = Model.objects.create(brand=self.brand, name='A6')
        self.sub_model = SubModel.objects.create(model=self.model, name='Sedan')
        self.year_range = YearRange.objects.create(
            sub_model=self.sub_model,
            year_start=2020,
            year_end=2024,
            fitting_confirmation='Confirmed',
            drive='LHD',
            number_of_seats=5,
            number_of_doors=4,
        )

        self.client.force_login(self.admin)

    def tearDown(self):
        cache.clear()

    # --------------------------------------------------------------------------
    # 1. Region Spec (Vehicle Country) tests
    # --------------------------------------------------------------------------
    def test_update_vehicle_country_success(self):
        url = reverse('update_vehicle_country_api', args=[self.year_range.id])
        response = self.client.post(
            url,
            data=json.dumps({'vehicle_country': 'GCC'}),
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['success'])
        self.assertEqual(data['vehicle_country'], 'GCC')

        self.year_range.refresh_from_db()
        self.assertIsNotNone(self.year_range.vehicle_country)
        self.assertEqual(self.year_range.vehicle_country.name, 'GCC')

    def test_update_vehicle_country_clear(self):
        # First set it
        setting, _ = MasterSetting.objects.get_or_create(category='Country', name='USA')
        self.year_range.vehicle_country = setting
        self.year_range.save()

        url = reverse('update_vehicle_country_api', args=[self.year_range.id])
        response = self.client.post(
            url,
            data=json.dumps({'vehicle_country': ''}),
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['success'])
        self.assertEqual(data['vehicle_country'], '')

        self.year_range.refresh_from_db()
        self.assertIsNone(self.year_range.vehicle_country)

    def test_update_vehicle_country_invalid_choice_rejected(self):
        url = reverse('update_vehicle_country_api', args=[self.year_range.id])
        response = self.client.post(
            url,
            data=json.dumps({'vehicle_country': 'Atlantis'}),
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 400)
        data = response.json()
        self.assertFalse(data['success'])
        self.assertIn('Invalid Vehicle Country', data['error'])

    # --------------------------------------------------------------------------
    # 2. Measured In (Measurement Country) tests
    # --------------------------------------------------------------------------
    def test_update_measurement_country_success(self):
        url = reverse('update_measurement_country_api', args=[self.year_range.id])
        response = self.client.post(
            url,
            data=json.dumps({'measurement_country': 'KSA'}),
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['success'])
        self.assertEqual(data['measurement_country'], 'KSA')

        self.year_range.refresh_from_db()
        self.assertIsNotNone(self.year_range.measurement_country)
        self.assertEqual(self.year_range.measurement_country.name, 'KSA')

    def test_update_measurement_country_normalizes_north_armerica(self):
        url = reverse('update_measurement_country_api', args=[self.year_range.id])
        response = self.client.post(
            url,
            data=json.dumps({'measurement_country': 'North Armerica'}),
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['success'])
        self.assertEqual(data['measurement_country'], 'North America')

        self.year_range.refresh_from_db()
        self.assertEqual(self.year_range.measurement_country.name, 'North America')

    def test_update_measurement_country_invalid_choice_rejected(self):
        url = reverse('update_measurement_country_api', args=[self.year_range.id])
        response = self.client.post(
            url,
            data=json.dumps({'measurement_country': 'Narnia'}),
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 400)
        data = response.json()
        self.assertFalse(data['success'])
        self.assertIn('Invalid Measurement Country', data['error'])

    # --------------------------------------------------------------------------
    # 3. Drive (New Field) tests
    # --------------------------------------------------------------------------
    def test_update_drive_success(self):
        url = reverse('update_drive_api', args=[self.year_range.id])
        response = self.client.post(
            url,
            data=json.dumps({'drive': 'RHD'}),
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['success'])
        self.assertEqual(data['drive'], 'RHD')

        self.year_range.refresh_from_db()
        self.assertEqual(self.year_range.drive, 'RHD')

    def test_update_drive_clear(self):
        url = reverse('update_drive_api', args=[self.year_range.id])
        response = self.client.post(
            url,
            data=json.dumps({'drive': ''}),
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['success'])
        self.assertEqual(data['drive'], '')

        self.year_range.refresh_from_db()
        self.assertEqual(self.year_range.drive, '')

    def test_update_drive_invalid_rejected(self):
        url = reverse('update_drive_api', args=[self.year_range.id])
        response = self.client.post(
            url,
            data=json.dumps({'drive': 'CENTER'}),
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 400)
        data = response.json()
        self.assertFalse(data['success'])
        self.assertIn('Invalid Drive', data['error'])

    # --------------------------------------------------------------------------
    # 4. Permission tests
    # --------------------------------------------------------------------------
    def test_viewer_denied_updates(self):
        self.client.force_login(self.regular_user)
        for endpoint, payload in [
            (reverse('update_vehicle_country_api', args=[self.year_range.id]), {'vehicle_country': 'GCC'}),
            (reverse('update_measurement_country_api', args=[self.year_range.id]), {'measurement_country': 'KSA'}),
            (reverse('update_drive_api', args=[self.year_range.id]), {'drive': 'RHD'}),
        ]:
            response = self.client.post(endpoint, data=json.dumps(payload), content_type='application/json')
            self.assertEqual(response.status_code, 403)

    # --------------------------------------------------------------------------
    # 5. Table rendering & car details view
    # --------------------------------------------------------------------------
    def test_car_details_page_renders_new_columns_and_buttons(self):
        response = self.client.get(reverse('car_details'))
        self.assertEqual(response.status_code, 200)
        content = response.content.decode('utf-8')

        self.assertIn('Vehicle Country', content)
        self.assertIn('Measurement Country', content)
        self.assertIn('Drive', content)
        self.assertIn('region-dropdown-btn', content)
        self.assertIn('measured-dropdown-btn', content)
        self.assertIn('drive-dropdown-btn', content)
        self.assertIn('regionSpecMenu', content)
        self.assertIn('measuredInMenu', content)
        self.assertIn('driveMenu', content)
