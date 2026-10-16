from django.contrib.auth.models import User
from django.test import TestCase, Client
from django.urls import reverse
from management.models import ColorMaster, UserProfile, WorkflowRoles


class ColorMasterTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.admin_user = User.objects.create_user(
            username='admin_user',
            is_staff=True,
            is_superuser=True
        )
        UserProfile.objects.filter(user=self.admin_user).update(
            role=WorkflowRoles.ADMIN
        )
        self.viewer_user = User.objects.create_user(
            username='viewer_user',
            is_staff=False
        )
        UserProfile.objects.filter(user=self.viewer_user).update(
            role=WorkflowRoles.FACTORY_VIEWER
        )

        self.color1 = ColorMaster.objects.create(
            color_code='01',
            name='F.BEIGE',
            hex_code='#AF955C',
            pantone_code='4007 U',
            rgb_code='175, 149, 92',
            cmyk_code='32, 38, 78, 5',
            color_category='Beige & Tan',
            material_series='Beige & Tan',
            status='Active'
        )
        self.color2 = ColorMaster.objects.create(
            color_code='02',
            name='I.GREY',
            hex_code='#9E9D93',
            pantone_code='414 U',
            rgb_code='158, 157, 147',
            cmyk_code='37, 30, 36, 1',
            color_category='Grey & Neutral',
            material_series='Grey & Neutral',
            status='Sampling'
        )

    def test_car_details_view_contains_color_master_context(self):
        self.client.force_login(self.admin_user)
        response = self.client.get(reverse('car_details'))
        self.assertEqual(response.status_code, 200)
        self.assertIn('colors', response.context)
        self.assertIn('total_colors_count', response.context)
        self.assertIn('total_patterns_count', response.context)
        self.assertIn('active_subwindow', response.context)
        self.assertEqual(response.context['active_subwindow'], 'patterns')
        self.assertContains(response, 'subtaskbarPatternCount')
        self.assertContains(response, 'subtaskbarColorCount')
        self.assertContains(response, 'Color Master')
        self.assertContains(response, 'F.BEIGE')
        self.assertContains(response, '#AF955C')
        self.assertContains(response, 'color-tile__serial')
        self.assertContains(response, '#01')
        self.assertContains(response, 'I.GREY')
        self.assertContains(response, '#9E9D93')
        self.assertContains(response, '#02')

    def test_car_details_subwindow_param(self):
        self.client.force_login(self.admin_user)
        response = self.client.get(reverse('car_details') + '?subwindow=colors')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['active_subwindow'], 'colors')

    def test_car_details_color_search_filter(self):
        self.client.force_login(self.admin_user)
        # Search by Pantone code
        response = self.client.get(reverse('car_details') + '?color_search=4007')
        self.assertEqual(response.status_code, 200)
        colors = response.context['colors']
        self.assertTrue(any(c.name == 'F.BEIGE' for c in colors))
        self.assertFalse(any(c.name == 'I.GREY' for c in colors))

    def test_create_color_api(self):
        self.client.force_login(self.admin_user)
        response = self.client.post(reverse('create_color_api'), {
            'name': 'RED',
            'color_code': '06',
            'hex_code': '#E03C31',
            'pantone_code': '2347 U',
            'color_category': 'Red & Maroon',
            'status': 'Active'
        })
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['status'], 'success')
        self.assertTrue(ColorMaster.objects.filter(color_code='06', name='RED').exists())

    def test_update_color_api(self):
        self.client.force_login(self.admin_user)
        response = self.client.post(reverse('update_color_api', args=[self.color1.id]), {
            'name': 'F.BEIGE PRIME',
            'hex_code': '#B0965D',
            'pantone_code': '4007 U',
            'color_category': 'Beige & Tan',
            'status': 'Active'
        })
        self.assertEqual(response.status_code, 200)
        self.color1.refresh_from_db()
        self.assertEqual(self.color1.name, 'F.BEIGE PRIME')
        self.assertEqual(self.color1.hex_code, '#B0965D')

    def test_delete_color_api(self):
        self.client.force_login(self.admin_user)
        response = self.client.post(reverse('delete_color_api', args=[self.color2.id]))
        self.assertEqual(response.status_code, 200)
        self.assertFalse(ColorMaster.objects.filter(id=self.color2.id).exists())

    def test_permission_denied_for_regular_viewer(self):
        self.client.force_login(self.viewer_user)
        response = self.client.post(reverse('create_color_api'), {
            'name': 'Unauthorized Color',
            'hex_code': '#123456'
        })
        self.assertEqual(response.status_code, 403)

    def test_rejects_invalid_css_color_and_status(self):
        self.client.force_login(self.admin_user)
        response = self.client.post(reverse('create_color_api'), {
            'name': 'Injected', 'color_code': 'X1',
            'hex_code': '#123456;display:none', 'status': 'Active',
        })
        self.assertEqual(response.status_code, 400)
        self.assertFalse(ColorMaster.objects.filter(color_code='X1').exists())
        response = self.client.post(reverse('update_color_api', args=[self.color1.id]), {
            'hex_code': '#123456', 'status': 'invalid',
        })
        self.assertEqual(response.status_code, 400)
        self.color1.refresh_from_db()
        self.assertEqual(self.color1.hex_code, '#AF955C')

    def test_car_details_view_contains_toggle_and_list_table(self):
        self.client.force_login(self.admin_user)
        response = self.client.get(reverse('car_details') + '?subwindow=colors')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'colorViewToggle')
        self.assertContains(response, 'toggle-container')
        self.assertContains(response, 'colorListTable')
        self.assertContains(response, 'colorListTableWrapper')
        self.assertContains(response, 'color-table-row')
        self.assertContains(response, 'color-row__swatch')

    def test_master_colors_api(self):
        self.client.force_login(self.admin_user)
        # 1. Active colors by default
        response = self.client.get(reverse('master_colors_api'))
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['status'], 'success')
        self.assertGreaterEqual(data['count'], 1)
        names = [c['name'] for c in data['colors']]
        self.assertIn('F.BEIGE', names)

        # 2. Search filter q
        response = self.client.get(reverse('master_colors_api') + '?q=BEIGE')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(all('BEIGE' in c['name'] or 'BEIGE' in c['hex_code'] for c in data['colors']))

        # 3. Include archived / status test
        self.color2.status = 'Discontinued'
        self.color2.save()
        # Default should not include Discontinued
        response = self.client.get(reverse('master_colors_api'))
        data = response.json()
        self.assertNotIn('I.GREY', [c['name'] for c in data['colors']])
        # include_id should include it even if archived
        response = self.client.get(reverse('master_colors_api') + f'?include_id={self.color2.id}')
        data = response.json()
        self.assertIn('I.GREY', [c['name'] for c in data['colors']])

    def test_color_service_and_form_field(self):
        from management.services.color_service import (
            get_active_master_colors,
            get_master_colors_for_selection,
            get_master_color_choices,
        )
        from management.forms import MasterColorChoiceField

        active_qs = get_active_master_colors()
        self.assertIn(self.color1, active_qs)

        choices = get_master_color_choices()
        self.assertTrue(any(c[0] == self.color1.id for c in choices))

        field = MasterColorChoiceField()
        self.assertIn(self.color1, field.queryset)

    def test_car_details_search_component_markup(self):
        self.client.force_login(self.admin_user)
        response = self.client.get(reverse('car_details') + '?subwindow=colors')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="color-search-form"')
        self.assertContains(response, 'id="color-search-picker"')
        self.assertContains(response, 'id="colorSearchInput"')
        self.assertContains(response, 'id="color-search-by"')
        self.assertContains(response, 'id="color-search-field-label"')
        self.assertContains(response, 'id="color-search-options"')
        self.assertContains(response, 'data-search-by="serial_number"')
        self.assertContains(response, 'data-search-by="name"')
        self.assertContains(response, 'data-search-by="color_code"')
        self.assertContains(response, 'data-search-by="hex_code"')
        self.assertContains(response, 'data-search-by="rgb_code"')
        self.assertContains(response, 'data-search-by="material_series"')
        self.assertContains(response, 'data-search-by="status"')
        self.assertContains(response, 'data-search-by="compatible_models"')
        self.assertContains(response, 'data-search-by="all"')
        self.assertContains(response, 'id="colorSearchSubmitBtn"')
        self.assertContains(response, 'id="clearColorSearchBtn"')

    def test_car_details_color_search_by_fields(self):
        self.client.force_login(self.admin_user)

        # 1. Serial Number
        resp = self.client.get(reverse('car_details') + '?subwindow=colors&color_search=01&color_search_by=serial_number')
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(any(c.color_code == '01' for c in resp.context['colors']))
        self.assertFalse(any(c.color_code == '02' for c in resp.context['colors']))

        # 2. Name
        resp = self.client.get(reverse('car_details') + '?subwindow=colors&color_search=BEIGE&color_search_by=name')
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(any(c.name == 'F.BEIGE' for c in resp.context['colors']))
        self.assertFalse(any(c.name == 'I.GREY' for c in resp.context['colors']))

        # 3. HEX code (with and without #)
        resp = self.client.get(reverse('car_details') + '?subwindow=colors&color_search=AF955C&color_search_by=hex_code')
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(any(c.name == 'F.BEIGE' for c in resp.context['colors']))
        self.assertFalse(any(c.name == 'I.GREY' for c in resp.context['colors']))

        # 4. RGB code
        resp = self.client.get(reverse('car_details') + '?subwindow=colors&color_search=158&color_search_by=rgb_code')
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(any(c.name == 'I.GREY' for c in resp.context['colors']))
        self.assertFalse(any(c.name == 'F.BEIGE' for c in resp.context['colors']))

        # 5. Material Series
        resp = self.client.get(reverse('car_details') + '?subwindow=colors&color_search=Grey&color_search_by=material_series')
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(any(c.name == 'I.GREY' for c in resp.context['colors']))
        self.assertFalse(any(c.name == 'F.BEIGE' for c in resp.context['colors']))

        # 6. Status
        resp = self.client.get(reverse('car_details') + '?subwindow=colors&color_search=Sampling&color_search_by=status')
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(any(c.name == 'I.GREY' for c in resp.context['colors']))
        self.assertFalse(any(c.name == 'F.BEIGE' for c in resp.context['colors']))

        # 7. All Fields
        resp = self.client.get(reverse('car_details') + '?subwindow=colors&color_search=414&color_search_by=all')
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(any(c.name == 'I.GREY' for c in resp.context['colors']))
        self.assertFalse(any(c.name == 'F.BEIGE' for c in resp.context['colors']))

    def test_color_rich_data_attributes(self):
        self.client.force_login(self.admin_user)
        response = self.client.get(reverse('car_details') + '?subwindow=colors')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-serial="#01"')
        self.assertContains(response, 'data-rgb="175, 149, 92"')
        self.assertContains(response, 'data-derived-rgb=')


