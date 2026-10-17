import json
from django.test import TestCase, Client
from django.contrib.auth.models import User
from django.urls import reverse
from management.models import MasterSetting, MaterialVariant, UserProfile

class MaterialVariantTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.admin_user = User.objects.create_superuser(
            username='mat_admin',
            email='admin@fabro.com',
            password='testpassword123'
        )
        self.non_admin_user = User.objects.create_user(
            username='mat_user',
            email='user@fabro.com',
            password='testpassword123'
        )
        UserProfile.objects.filter(user=self.admin_user).update(role='admin')
        UserProfile.objects.filter(user=self.non_admin_user).update(role='country_executive')

        # Create Material MasterSetting
        self.material = MasterSetting.objects.create(
            category='Material',
            name='Rexin'
        )
        # Create Channel MasterSetting (non-material)
        self.channel = MasterSetting.objects.create(
            category='Channel',
            name='Retail'
        )

    def test_model_creation_and_ordering(self):
        v1 = MaterialVariant.objects.create(material=self.material, name='Standard', display_order=1)
        v2 = MaterialVariant.objects.create(material=self.material, name='Premium', display_order=0)
        
        variants = list(self.material.variants.all())
        self.assertEqual(len(variants), 2)
        self.assertEqual(variants[0].name, 'Premium')
        self.assertEqual(variants[1].name, 'Standard')

    def test_get_material_variants_endpoint(self):
        self.client.login(username='mat_admin', password='testpassword123')
        MaterialVariant.objects.create(material=self.material, name='Matte', display_order=0)

        url = reverse('get_material_variants', args=[self.material.id])
        response = self.client.get(url, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data.get('success'))
        self.assertEqual(len(data.get('variants')), 1)
        self.assertEqual(data['variants'][0]['name'], 'Matte')

    def test_get_material_variants_non_material_404(self):
        self.client.login(username='mat_admin', password='testpassword123')
        url = reverse('get_material_variants', args=[self.channel.id])
        response = self.client.get(url, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(response.status_code, 404)

    def test_edit_material_variants_atomic(self):
        self.client.login(username='mat_admin', password='testpassword123')
        v1 = MaterialVariant.objects.create(material=self.material, name='OldVariant', display_order=0)

        payload = {
            'edit_setting': '1',
            'category': 'Material',
            'name': 'Rexin Updated',
            'variants_json': json.dumps([
                {'id': None, 'name': 'Premium', 'order': 0},
                {'id': v1.id, 'name': 'Standard', 'order': 1},
                {'id': None, 'name': 'Matte', 'order': 2},
            ])
        }

        url = reverse('edit_master_setting', args=[self.material.id])
        response = self.client.post(url, payload, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data.get('success'))
        self.assertEqual(data.get('name'), 'Rexin Updated')

        self.material.refresh_from_db()
        self.assertEqual(self.material.name, 'Rexin Updated')
        
        variants = list(self.material.variants.all().order_by('display_order'))
        self.assertEqual(len(variants), 3)
        self.assertEqual([v.name for v in variants], ['Premium', 'Standard', 'Matte'])
        self.assertEqual([v.display_order for v in variants], [0, 1, 2])
        # OldVariant ID should be preserved and renamed to Standard
        self.assertEqual(variants[1].id, v1.id)

    def test_edit_material_delete_variant(self):
        self.client.login(username='mat_admin', password='testpassword123')
        v1 = MaterialVariant.objects.create(material=self.material, name='VariantA', display_order=0)
        v2 = MaterialVariant.objects.create(material=self.material, name='VariantB', display_order=1)

        # Remove VariantB
        payload = {
            'edit_setting': '1',
            'category': 'Material',
            'name': 'Rexin',
            'variants_json': json.dumps([
                {'id': v1.id, 'name': 'VariantA', 'order': 0}
            ])
        }

        url = reverse('edit_master_setting', args=[self.material.id])
        response = self.client.post(url, payload, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(response.status_code, 200)

        variants = list(self.material.variants.all())
        self.assertEqual(len(variants), 1)
        self.assertEqual(variants[0].name, 'VariantA')
        self.assertFalse(MaterialVariant.objects.filter(id=v2.id).exists())

    def test_inline_delete_only_removes_requested_variant(self):
        self.client.force_login(self.admin_user)
        old_variant = MaterialVariant.objects.create(material=self.material, name='Old', display_order=0)
        other_variant = MaterialVariant.objects.create(material=self.material, name='Concurrent', display_order=1)
        response = self.client.post(
            reverse('edit_master_setting', args=[self.material.id]),
            {'delete_variant_id': old_variant.id},
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(MaterialVariant.objects.filter(pk=old_variant.pk).exists())
        self.assertTrue(MaterialVariant.objects.filter(pk=other_variant.pk).exists())
        self.assertEqual(
            [item['id'] for item in response.json()['variants']],
            [other_variant.pk],
        )

    def test_inline_delete_rejects_other_material_and_non_admin(self):
        other_material = MasterSetting.objects.create(category='Material', name='Leather')
        other_variant = MaterialVariant.objects.create(material=other_material, name='Grain')
        self.client.force_login(self.admin_user)
        response = self.client.post(
            reverse('edit_master_setting', args=[self.material.id]),
            {'delete_variant_id': other_variant.id},
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )
        self.assertEqual(response.status_code, 404)
        self.client.force_login(self.non_admin_user)
        response = self.client.post(
            reverse('edit_master_setting', args=[other_material.id]),
            {'delete_variant_id': other_variant.id},
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )
        self.assertEqual(response.status_code, 403)
        self.assertTrue(MaterialVariant.objects.filter(pk=other_variant.pk).exists())

    def test_edit_non_material_setting_unchanged(self):
        self.client.login(username='mat_admin', password='testpassword123')
        url = reverse('edit_master_setting', args=[self.channel.id])
        payload = {
            'edit_setting': '1',
            'category': 'Channel',
            'name': 'Wholesale'
        }
        response = self.client.post(url, payload)
        self.assertEqual(response.status_code, 302)
        self.channel.refresh_from_db()
        self.assertEqual(self.channel.name, 'Wholesale')
