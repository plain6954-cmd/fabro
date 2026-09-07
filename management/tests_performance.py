from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from .models import Brand, ChatMessage, Model, SKU, SubModel, YearRange


class PerformancePaginationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_superuser('perf-test-admin', 'perf@example.com', 'test-password')
        brand = Brand.objects.create(name='Performance Brand')
        model = Model.objects.create(brand=brand, name='Performance Model')
        submodel = SubModel.objects.create(model=model, name='Performance Submodel')
        YearRange.objects.bulk_create([
            YearRange(
                sub_model=submodel,
                serial_number=f'I{number:04d}',
                year_start=1900 + number,
                year_end=1900 + number,
                layout_code=f'PERF-{number:04d}',
            )
            for number in range(60)
        ])
        SKU.objects.bulk_create([
            SKU(code=f'PERF-SKU-{number:04d}', description='Performance test')
            for number in range(60)
        ])

    def setUp(self):
        self.client.force_login(self.user)

    def test_pattern_master_limits_initial_vehicle_page(self):
        response = self.client.get(reverse('car_details'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context['car_data']), 50)
        self.assertEqual(response.context['page_obj'].paginator.count, 60)
        self.assertNotIn('design_folders', response.context)

    def test_pattern_vehicle_api_is_authenticated_and_paginated(self):
        self.client.logout()
        anonymous = self.client.get(reverse('pattern_vehicle_list_api'))
        self.assertEqual(anonymous.status_code, 302)
        self.client.force_login(self.user)
        response = self.client.get(reverse('pattern_vehicle_list_api'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()['results']), 50)
        self.assertEqual(response.json()['count'], 60)

    def test_rest_catalogues_use_bounded_pagination(self):
        vehicle_response = self.client.get(reverse('api_vehicles_list_create'))
        sku_response = self.client.get(reverse('api_skus_list_create'))
        self.assertEqual(len(vehicle_response.json()['results']), 25)
        self.assertEqual(vehicle_response.json()['count'], 60)
        self.assertEqual(len(sku_response.json()['results']), 25)
        self.assertEqual(sku_response.json()['count'], 60)


class IncrementalChatTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user('chat-owner', password='test-password')
        cls.other = User.objects.create_user('chat-peer', password='test-password')
        ChatMessage.objects.bulk_create([
            ChatMessage(sender=cls.other, recipient=cls.user, message=f'Message {number}')
            for number in range(60)
        ])

    def setUp(self):
        self.client.force_login(self.user)

    def test_initial_chat_and_older_cursor_are_bounded(self):
        initial = self.client.get(reverse('chat_messages_api', args=[self.other.pk]))
        self.assertEqual(len(initial.json()['messages']), 50)
        self.assertTrue(initial.json()['has_more'])
        oldest_id = initial.json()['messages'][0]['id']
        older = self.client.get(reverse('chat_messages_api', args=[self.other.pk]), {'before_id': oldest_id})
        self.assertEqual(len(older.json()['messages']), 10)

    def test_after_cursor_returns_only_new_messages(self):
        latest = ChatMessage.objects.order_by('-pk').first()
        created = ChatMessage.objects.create(sender=self.other, recipient=self.user, message='Newest')
        response = self.client.get(
            reverse('chat_messages_api', args=[self.other.pk]), {'after_id': latest.pk}
        )
        self.assertEqual([item['id'] for item in response.json()['messages']], [created.pk])
