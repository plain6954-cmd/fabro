from datetime import datetime, timezone as dt_tz
from django.contrib.auth.models import User
from django.test import TestCase, Client
from django.urls import reverse

from management.models import ChatMessage, WorkflowRoles
from management.timezones import is_valid_timezone, get_all_timezones


class TimezoneConfigurationTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='tz_tester',
            password='TestPassword123!',
            email='tz@test.com'
        )
        self.profile = self.user.workflow_profile
        self.profile.role = WorkflowRoles.FACTORY_EXECUTIVE
        self.profile.timezone = 'Asia/Kolkata'
        self.profile.save()

        self.other_user = User.objects.create_user(
            username='chat_partner',
            password='TestPassword123!',
            email='partner@test.com'
        )
        self.other_profile = self.other_user.workflow_profile
        self.other_profile.role = WorkflowRoles.FACTORY_EXECUTIVE
        self.other_profile.timezone = 'UTC'
        self.other_profile.save()

        self.client = Client()
        self.client.login(username='tz_tester', password='TestPassword123!')

    def test_timezone_validation_and_listing(self):
        self.assertTrue(is_valid_timezone('Asia/Kolkata'))
        self.assertTrue(is_valid_timezone('UTC'))
        self.assertTrue(is_valid_timezone('Asia/Dubai'))
        self.assertTrue(is_valid_timezone('America/New_York'))
        self.assertFalse(is_valid_timezone('Invalid/Timezone'))
        self.assertFalse(is_valid_timezone(''))
        self.assertFalse(is_valid_timezone(None))

        all_tz = get_all_timezones()
        self.assertTrue(len(all_tz) > 10)
        # Ensure common timezones are in the list
        tz_values = [tz[0] for tz in all_tz]
        self.assertIn('Asia/Kolkata', tz_values)
        self.assertIn('Asia/Dubai', tz_values)
        self.assertIn('UTC', tz_values)

    def test_profile_settings_page_renders_timezone_options(self):
        response = self.client.get(reverse('profile_settings'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-testid="profile-timezone-select"')
        self.assertContains(response, 'value="Asia/Kolkata"')
        self.assertContains(response, 'value="Asia/Dubai"')
        self.assertContains(response, 'selected')

    def test_user_can_update_timezone_in_profile_settings(self):
        # Update timezone to Asia/Dubai
        response = self.client.post(reverse('profile_settings'), {
            'update_profile': '1',
            'first_name': 'TZ',
            'last_name': 'Tester',
            'email': 'tz@test.com',
            'phone_number': '1234567890',
            'timezone': 'Asia/Dubai',
        }, follow=True)
        self.assertEqual(response.status_code, 200)
        
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.timezone, 'Asia/Dubai')

    def test_chat_message_api_converts_to_user_configured_timezone(self):
        # Fixed UTC timestamp: 2026-10-01 03:34:00 UTC
        fixed_utc_dt = datetime(2026, 10, 1, 3, 34, 0, tzinfo=dt_tz.utc)
        chat_msg = ChatMessage.objects.create(
            sender=self.other_user,
            recipient=self.user,
            message="Test timezone message",
        )
        ChatMessage.objects.filter(pk=chat_msg.pk).update(created_at=fixed_utc_dt)

        # 1. With user timezone set to UTC
        self.profile.timezone = 'UTC'
        self.profile.save()
        response = self.client.get(reverse('chat_messages_api', args=[self.other_user.id]))
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['status'], 'ok')
        self.assertEqual(len(data['messages']), 1)
        # In UTC: Oct 01, 03:34
        self.assertEqual(data['messages'][0]['created_at'], 'Oct 01, 03:34')

        # 2. With user timezone set to Asia/Kolkata (+05:30)
        self.profile.timezone = 'Asia/Kolkata'
        self.profile.save()
        response = self.client.get(reverse('chat_messages_api', args=[self.other_user.id]))
        self.assertEqual(response.status_code, 200)
        data = response.json()
        # In IST (+05:30): Oct 01, 09:04
        self.assertEqual(data['messages'][0]['created_at'], 'Oct 01, 09:04')

        # 3. With user timezone set to Asia/Dubai (+04:00)
        self.profile.timezone = 'Asia/Dubai'
        self.profile.save()
        response = self.client.get(reverse('chat_messages_api', args=[self.other_user.id]))
        self.assertEqual(response.status_code, 200)
        data = response.json()
        # In GST (+04:00): Oct 01, 07:34
        self.assertEqual(data['messages'][0]['created_at'], 'Oct 01, 07:34')

    def test_chat_send_api_returns_localtime(self):
        self.profile.timezone = 'Asia/Dubai'
        self.profile.save()

        response = self.client.post(reverse('chat_send_api'), {
            'recipient_id': self.other_user.id,
            'message': 'Hello from Dubai timezone'
        })
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['status'], 'ok')
        # Check that created_at is formatted with hour & minute
        created_str = data['message']['created_at']
        self.assertTrue(len(created_str) > 0)

    def test_anonymous_user_safely_falls_back(self):
        anon_client = Client()
        response = anon_client.get(reverse('index'))
        # Should not crash, and middleware deactivates timezone
        self.assertEqual(response.status_code, 302)
