from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth.models import User
from management.models import (
    Brand, Model, SubModel, YearRange, MasterSetting,
    get_country_letter, format_pattern_serial, get_next_pattern_serial,
    Complaint, PatternDesignFolder, PatternDesignImage, VehicleDriveLink
)
from management.forms import CarDetailsForm


class PatternMasterImportTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_superuser(
            username='admin_test',
            email='admin@fabro.com',
            password='testpassword123'
        )
        self.client.force_login(self.user)

        # Create or get MasterSettings
        self.gcc, _ = MasterSetting.objects.get_or_create(category='Country', name='GCC')
        self.ksa, _ = MasterSetting.objects.get_or_create(category='Country', name='KSA')
        self.india, _ = MasterSetting.objects.get_or_create(category='Country', name='India')

        # Create test vehicles
        self.brand = Brand.objects.create(name='TOYOTA')
        self.model = Model.objects.create(brand=self.brand, name='CAMRY')
        self.variant = SubModel.objects.create(model=self.model, name='N1')

    def test_country_letter_prefix_mapping(self):
        """Verify that GCC evaluates to prefix 'S' per authorized rule."""
        self.assertEqual(get_country_letter(self.gcc), 'S')
        self.assertEqual(get_country_letter(self.ksa), 'S')
        self.assertEqual(get_country_letter(self.india), 'I')
        self.assertEqual(get_country_letter(None), 'S')

    def test_pattern_serial_formatting(self):
        """Verify serial number zero-padding and prefix generation."""
        self.assertEqual(format_pattern_serial(1, self.gcc), 'S0001')
        self.assertEqual(format_pattern_serial('221', self.gcc), 'S0221')
        self.assertEqual(format_pattern_serial('005', self.gcc), 'S0005')

    def test_prefix_determined_by_measurement_country(self):
        """Verify that pattern serial prefix is determined according to Measurement Country."""
        # Measurement country India -> prefix 'I' even if vehicle country is GCC
        yr_india = YearRange(
            sub_model=self.variant,
            serial_number='auto',
            year_start=2020,
            year_end=2025,
            br='BR1',
            vehicle_country=self.gcc,
            measurement_country=self.india,
            drive='LHD'
        )
        yr_india.save()
        self.assertTrue(yr_india.serial_number.startswith('I'))

        # Measurement country KSA -> prefix 'S' even if vehicle country is India
        yr_ksa = YearRange(
            sub_model=self.variant,
            serial_number='auto',
            year_start=2020,
            year_end=2025,
            br='BR1',
            vehicle_country=self.india,
            measurement_country=self.ksa,
            drive='LHD'
        )
        yr_ksa.save()
        self.assertTrue(yr_ksa.serial_number.startswith('S'))

    def test_next_pattern_serial(self):
        """Verify that get_next_pattern_serial produces consecutive S numbers."""
        YearRange.objects.create(
            sub_model=self.variant,
            serial_number='S0001',
            year_start=2020,
            year_end=2025,
            br='BR1',
            vehicle_country=self.gcc,
            measurement_country=self.ksa,
            drive='LHD'
        )
        next_s = get_next_pattern_serial(self.gcc)
        self.assertEqual(next_s, 'S0002')

    def test_car_details_form_labels(self):
        """Verify that CarDetailsForm presents Sub Model and Variant without BR label."""
        form = CarDetailsForm()
        self.assertEqual(str(form.fields['br'].label), 'Sub Model')
        self.assertEqual(str(form.fields['sub_model_name'].label), 'Variant')
        self.assertNotIn('BR', str(form.fields['br'].label))
        self.assertNotIn('Sub-Model Name', str(form.fields['sub_model_name'].label))

    def test_add_pattern_flow_preservation(self):
        """Verify manual Add Pattern creates record with correct country, prefix, and fields."""
        response = self.client.post(reverse('car_details'), {
            'brand_name': 'HONDA',
            'model_name': 'ACCORD',
            'sub_model_name': 'N2',  # Variant
            'br': 'BR2',             # Sub Model
            'year_start': 2021,
            'year_end': 2025,
            'number_of_seats': 5,
            'number_of_doors': 4,
            'x_code': 'X9999',
            'fitting_confirmation': 'Confirmed',
            'vehicle_country': self.gcc.id,
            'measurement_country': self.ksa.id,
            'drive': 'LHD',
        })
        self.assertEqual(response.status_code, 302)
        yr = YearRange.objects.filter(x_code='X9999').first()
        self.assertIsNotNone(yr)
        self.assertTrue(yr.serial_number.startswith('S'))
        self.assertEqual(yr.br, 'BR2')
        self.assertEqual(yr.sub_model.name, 'N2')
        self.assertEqual(yr.vehicle_country, self.gcc)
        self.assertEqual(yr.measurement_country, self.ksa)
        self.assertEqual(yr.drive, 'LHD')

    def test_edit_pattern_saves_and_preserves_dropdowns(self):
        """Verify editing a pattern preserves dropdown preselection and updates correctly."""
        yr = YearRange.objects.create(
            sub_model=self.variant,
            serial_number='S0100',
            year_start=2018,
            year_end=2022,
            br='BR1',
            number_of_seats=5,
            number_of_doors=4,
            x_code='X1000',
            fitting_confirmation='Pending',
            vehicle_country=self.gcc,
            measurement_country=self.ksa,
            drive='LHD'
        )

        # GET Edit Pattern page
        get_res = self.client.get(reverse('edit_car_detail', args=[yr.id]))
        self.assertEqual(get_res.status_code, 200)
        self.assertContains(get_res, 'Sub Model')
        self.assertContains(get_res, 'Variant')
        self.assertContains(get_res, 'selected>Pending</option>')

        # POST Edit Pattern changes
        post_res = self.client.post(reverse('edit_car_detail', args=[yr.id]), {
            'serial_number': 'S0100',
            'brand_name': 'TOYOTA',
            'model_name': 'CAMRY',
            'sub_model_name': 'N3',
            'br': 'BR3',
            'year_start': 2019,
            'year_end': 2023,
            'number_of_seats': 5,
            'number_of_doors': 4,
            'x_code': 'X1001',
            'fitting_confirmation': 'Confirmed',
            'vehicle_country': self.gcc.id,
            'measurement_country': self.ksa.id,
            'drive': 'LHD',
        })
        self.assertEqual(post_res.status_code, 302)
        yr.refresh_from_db()
        self.assertEqual(yr.br, 'BR3')
        self.assertEqual(yr.sub_model.name, 'N3')
        self.assertEqual(yr.year_start, 2019)
        self.assertEqual(yr.year_end, 2023)
        self.assertEqual(yr.fitting_confirmation, 'Confirmed')

    def test_search_and_filter_support(self):
        """Verify searching by variant and sub_model/br returns correct results."""
        yr = YearRange.objects.create(
            sub_model=self.variant,
            serial_number='S0050',
            year_start=2020,
            year_end=2024,
            br='BR_TEST',
            vehicle_country=self.gcc,
            measurement_country=self.ksa,
            drive='LHD'
        )
        res_br = self.client.get(reverse('car_details'), {'search': 'BR_TEST', 'search_by': 'br'})
        self.assertEqual(res_br.status_code, 200)
        self.assertContains(res_br, 'S0050')

        res_var = self.client.get(reverse('car_details'), {'search': 'N1', 'search_by': 'variant'})
        self.assertEqual(res_var.status_code, 200)
        self.assertContains(res_var, 'S0050')
