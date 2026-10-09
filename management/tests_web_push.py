"""
Automated unit and integration tests for Web Push Notifications in Fabro Leather Portal.
All external push network calls are strictly mocked.
"""
import json
import base64
from io import StringIO
from unittest.mock import MagicMock, patch
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from management.models import (
    ApprovalRoles,
    Complaint,
    Notification,
    PushSubscription,
    UserProfile,
    WorkflowRoles,
    WorkflowStatuses,
)
from management.services.push_notifications import (
    build_push_payload,
    get_vapid_configuration_status,
    is_web_push_configured,
    send_push_to_subscription,
    send_push_to_user,
    send_push_to_users,
)
from management.services.workflow import (
    assign_factory_executive,
    notify_factory_assignment,
    notify_user,
)

User = get_user_model()

_test_private = ec.generate_private_key(ec.SECP256R1())
TEST_VAPID_PRIVATE_KEY = base64.urlsafe_b64encode(
    _test_private.private_numbers().private_value.to_bytes(32, 'big')
).decode().rstrip('=')
TEST_VAPID_PUBLIC_KEY = base64.urlsafe_b64encode(
    _test_private.public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint,
    )
).decode().rstrip('=')


@override_settings(
    WEBPUSH_VAPID_PUBLIC_KEY=TEST_VAPID_PUBLIC_KEY,
    WEBPUSH_VAPID_PRIVATE_KEY=TEST_VAPID_PRIVATE_KEY,
    WEBPUSH_VAPID_SUBJECT='mailto:admin@example.com',
)
class WebPushNotificationTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.password = "SecurePass123!"

        # User A
        self.user_a = User.objects.create_user(
            username="user_a",
            email="usera@example.com",
            password=self.password,
        )
        self.user_a.workflow_profile.role = WorkflowRoles.FACTORY_EXECUTIVE
        self.user_a.workflow_profile.save()

        # User B
        self.user_b = User.objects.create_user(
            username="user_b",
            email="userb@example.com",
            password=self.password,
        )
        self.user_b.workflow_profile.role = WorkflowRoles.FACTORY_EXECUTIVE
        self.user_b.workflow_profile.save()

        # Factory Executive 2 (for reassignment)
        self.exec_2 = User.objects.create_user(
            username="exec_two",
            email="exectwo@example.com",
            password=self.password,
        )
        self.exec_2.workflow_profile.role = WorkflowRoles.FACTORY_EXECUTIVE
        self.exec_2.workflow_profile.save()

        # Sample subscription payload
        self.sample_sub_data = {
            "endpoint": "https://fcm.googleapis.com/fcm/send/sample-token-123",
            "keys": {
                "p256dh": "BNcRdreALRFXTkOOUHK1EtK2wtaz5Ry4YfYCA_0QT9ScVU7M2N0Un8864EbG",
                "auth": "tBHItJI5svbpez7KI4CCXg",
            },
        }

    # 1. Unauthenticated subscribe is rejected
    def test_unauthenticated_subscribe_rejected(self):
        url = reverse("push_subscribe")
        response = self.client.post(
            url,
            data=json.dumps(self.sample_sub_data),
            content_type="application/json",
        )
        # Should redirect to login
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login/", response.url)

    # 2. Authenticated subscription automatically belongs to request.user
    def test_authenticated_subscription_belongs_to_request_user(self):
        self.client.login(username="user_a", password=self.password)
        url = reverse("push_subscribe")
        response = self.client.post(
            url,
            data=json.dumps(self.sample_sub_data),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data.get("success"))

        sub = PushSubscription.objects.get(endpoint=self.sample_sub_data["endpoint"])
        self.assertEqual(sub.user, self.user_a)
        self.assertTrue(sub.is_active)

    # 3. Frontend cannot select another user
    def test_frontend_cannot_select_another_user(self):
        self.client.login(username="user_a", password=self.password)
        tampered_data = dict(self.sample_sub_data)
        tampered_data["user_id"] = self.user_b.id
        tampered_data["user"] = self.user_b.username

        url = reverse("push_subscribe")
        response = self.client.post(
            url,
            data=json.dumps(tampered_data),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)

        sub = PushSubscription.objects.get(endpoint=self.sample_sub_data["endpoint"])
        # Must still belong to user_a, ignoring tampered user_id
        self.assertEqual(sub.user, self.user_a)
        self.assertNotEqual(sub.user, self.user_b)

    # 4. Duplicate subscription registration is idempotent
    def test_duplicate_subscription_registration_is_idempotent(self):
        self.client.login(username="user_a", password=self.password)
        url = reverse("push_subscribe")

        # First call
        self.client.post(url, data=json.dumps(self.sample_sub_data), content_type="application/json")
        # Second call with same endpoint
        response = self.client.post(url, data=json.dumps(self.sample_sub_data), content_type="application/json")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            PushSubscription.objects.filter(endpoint=self.sample_sub_data["endpoint"]).count(),
            1,
        )

    # 5. Shared computer: User A subscription re-registered by User B is reassigned
    def test_shared_browser_reassigns_to_current_user(self):
        # User A registers laptop browser
        self.client.login(username="user_a", password=self.password)
        self.client.post(reverse("push_subscribe"), data=json.dumps(self.sample_sub_data), content_type="application/json")
        self.client.logout()

        # User B logs into the same browser and registers
        self.client.login(username="user_b", password=self.password)
        response = self.client.post(reverse("push_subscribe"), data=json.dumps(self.sample_sub_data), content_type="application/json")
        self.assertEqual(response.status_code, 200)

        sub = PushSubscription.objects.get(endpoint=self.sample_sub_data["endpoint"])
        self.assertEqual(sub.user, self.user_b)
        # User A has no active subscriptions on this endpoint
        self.assertFalse(PushSubscription.objects.filter(user=self.user_a, endpoint=self.sample_sub_data["endpoint"]).exists())

    # 6. Unsubscribe only affects current user's subscription
    def test_unsubscribe_only_affects_current_users_subscription(self):
        sub_a = PushSubscription.objects.create(
            user=self.user_a,
            endpoint="https://example.com/sub-a",
            p256dh="key_a",
            auth="auth_a",
            is_active=True,
        )
        sub_b = PushSubscription.objects.create(
            user=self.user_b,
            endpoint="https://example.com/sub-b",
            p256dh="key_b",
            auth="auth_b",
            is_active=True,
        )

        self.client.login(username="user_a", password=self.password)
        # User A attempts to unsubscribe User B's endpoint
        self.client.post(
            reverse("push_unsubscribe"),
            data=json.dumps({"endpoint": sub_b.endpoint}),
            content_type="application/json",
        )

        sub_b.refresh_from_db()
        sub_a.refresh_from_db()
        # sub_b must remain active!
        self.assertTrue(sub_b.is_active)
        self.assertTrue(sub_a.is_active)

        # User A unsubscribes own endpoint
        self.client.post(
            reverse("push_unsubscribe"),
            data=json.dumps({"endpoint": sub_a.endpoint}),
            content_type="application/json",
        )
        sub_a.refresh_from_db()
        self.assertFalse(sub_a.is_active)

    # 7. Malformed subscription payload is rejected
    def test_malformed_subscription_payload_rejected(self):
        self.client.login(username="user_a", password=self.password)
        url = reverse("push_subscribe")

        # Missing keys
        resp1 = self.client.post(url, data=json.dumps({"endpoint": "https://example.com/test"}), content_type="application/json")
        self.assertEqual(resp1.status_code, 400)

        # Invalid protocol (not https or localhost)
        resp2 = self.client.post(
            url,
            data=json.dumps({"endpoint": "ftp://bad.url", "keys": {"p256dh": "k", "auth": "a"}}),
            content_type="application/json",
        )
        self.assertEqual(resp2.status_code, 400)

        # Bad json
        resp3 = self.client.post(url, data="bad-json", content_type="application/json")
        self.assertEqual(resp3.status_code, 400)

    # 8. Expired subscription handled safely (404/410 deactivates subscription)
    @patch("pywebpush.webpush")
    def test_expired_subscription_deactivates(self, mock_webpush):
        class MockWebPushException(Exception):
            def __init__(self):
                self.response = MagicMock()
                self.response.status_code = 410

        mock_webpush.side_effect = MockWebPushException()

        sub = PushSubscription.objects.create(
            user=self.user_a,
            endpoint="https://example.com/expired-sub",
            p256dh="key",
            auth="auth",
            is_active=True,
        )

        with self.settings(
            WEBPUSH_VAPID_PUBLIC_KEY=TEST_VAPID_PUBLIC_KEY,
            WEBPUSH_VAPID_PRIVATE_KEY=TEST_VAPID_PRIVATE_KEY,
            WEBPUSH_VAPID_SUBJECT="mailto:admin@example.com",
        ):
            success = send_push_to_subscription(sub, '{"title": "test"}')
            self.assertFalse(success)

            sub.refresh_from_db()
            self.assertFalse(sub.is_active)
            self.assertEqual(sub.failure_count, 1)

    # 9. Temporary push failure does not destroy valid subscription immediately
    @patch("pywebpush.webpush")
    def test_temporary_failure_increments_count_without_immediate_deactivation(self, mock_webpush):
        class MockServerException(Exception):
            def __init__(self):
                self.response = MagicMock()
                self.response.status_code = 503

        mock_webpush.side_effect = MockServerException()

        sub = PushSubscription.objects.create(
            user=self.user_a,
            endpoint="https://example.com/temp-fail-sub",
            p256dh="key",
            auth="auth",
            is_active=True,
            failure_count=2,
        )

        with self.settings(
            WEBPUSH_VAPID_PUBLIC_KEY=TEST_VAPID_PUBLIC_KEY,
            WEBPUSH_VAPID_PRIVATE_KEY=TEST_VAPID_PRIVATE_KEY,
            WEBPUSH_VAPID_SUBJECT="mailto:admin@example.com",
        ):
            success = send_push_to_subscription(sub, '{"title": "test"}')
            self.assertFalse(success)

            sub.refresh_from_db()
            self.assertTrue(sub.is_active)
            self.assertEqual(sub.failure_count, 3)

    # 10. Push delivery failure does not break complaint operation
    @patch("management.services.push_notifications.send_push_to_user")
    def test_push_failure_does_not_break_complaint_operation(self, mock_send_push):
        mock_send_push.side_effect = RuntimeError("Push network timed out")

        complaint = Complaint(
            complaint_id="PAT-26100001",
            complaint_type="pattern",
            created_by=self.user_a,
            assigned_factory_executive=self.user_a,
            workflow_status=WorkflowStatuses.ASSIGNED_TO_FACTORY,
            date=timezone.now().date(),
        )
        complaint.save()

        # notify_factory_assignment must succeed even if push fails
        try:
            with self.captureOnCommitCallbacks(execute=True):
                notify_factory_assignment(complaint, self.user_a)
        except Exception as exc:
            self.fail(f"notify_factory_assignment raised an unexpected exception: {exc}")

        # In-app notification was still created!
        self.assertTrue(self.user_a.workflow_notifications.filter(complaint=complaint).exists())

    # 11. Correct assignee receives assignment notification
    @patch("management.services.push_notifications.send_push_to_user")
    def test_correct_assignee_receives_assignment_notification(self, mock_send_push):
        complaint = Complaint(
            complaint_id="PRO-26100002",
            complaint_type="production",
            created_by=self.user_a,
            assigned_factory_executive=self.user_b,
            workflow_status=WorkflowStatuses.ASSIGNED_TO_FACTORY,
            date=timezone.now().date(),
        )
        complaint.save()

        with self.captureOnCommitCallbacks(execute=True):
            notify_factory_assignment(complaint, self.user_b)

        # send_push_to_user should be called with user_b
        mock_send_push.assert_called()
        call_user = mock_send_push.call_args[0][0]
        self.assertEqual(call_user, self.user_b)

    # 12. Unrelated user receives no assignment notification
    @patch("management.services.push_notifications.send_push_to_user")
    def test_unrelated_user_receives_no_notification(self, mock_send_push):
        complaint = Complaint(
            complaint_id="QUA-26100003",
            complaint_type="quality",
            created_by=self.user_a,
            assigned_factory_executive=self.user_a,
            workflow_status=WorkflowStatuses.ASSIGNED_TO_FACTORY,
            date=timezone.now().date(),
        )
        complaint.save()

        with self.captureOnCommitCallbacks(execute=True):
            notify_factory_assignment(complaint, self.user_a)

        called_users = [call[0][0] for call in mock_send_push.call_args_list]
        self.assertIn(self.user_a, called_users)
        self.assertNotIn(self.user_b, called_users)

    # 13. Inactive subscription receives no send attempt
    @patch("management.services.push_notifications.send_push_to_subscription")
    def test_inactive_subscription_receives_no_send_attempt(self, mock_send_sub):
        PushSubscription.objects.create(
            user=self.user_a,
            endpoint="https://example.com/inactive",
            p256dh="key",
            auth="auth",
            is_active=False,
        )

        with self.settings(
            WEBPUSH_VAPID_PUBLIC_KEY=TEST_VAPID_PUBLIC_KEY,
            WEBPUSH_VAPID_PRIVATE_KEY=TEST_VAPID_PRIVATE_KEY,
            WEBPUSH_VAPID_SUBJECT="mailto:admin@example.com",
        ):
            result = send_push_to_user(self.user_a, "Title", "Body")
            self.assertEqual(result["sent"], 0)
            mock_send_sub.assert_not_called()

    # 14. Missing VAPID configuration fails gracefully
    def test_missing_vapid_configuration_fails_gracefully(self):
        sub = PushSubscription.objects.create(
            user=self.user_a,
            endpoint="https://example.com/test",
            p256dh="key",
            auth="auth",
            is_active=True,
        )

        with self.settings(
            WEBPUSH_VAPID_PUBLIC_KEY="",
            WEBPUSH_VAPID_PRIVATE_KEY="",
            WEBPUSH_VAPID_SUBJECT="",
        ):
            self.assertFalse(is_web_push_configured())
            success = send_push_to_subscription(sub, '{"title": "test"}')
            self.assertFalse(success)
            # Subscription must not be marked inactive due to missing server config
            sub.refresh_from_db()
            self.assertTrue(sub.is_active)

    # 15. Unsafe external notification destination is rejected / falls back safely
    def test_unsafe_external_notification_destination_falls_back(self):
        payload_str = build_push_payload(
            title="Update",
            body="Test message",
            url="https://external-phishing.com/steal-data",
        )
        payload = json.loads(payload_str)
        self.assertEqual(payload["data"]["url"], "/")

        # Same origin path is preserved
        safe_payload_str = build_push_payload(
            title="Update",
            body="Test message",
            url="/complaint/factory-review/FAC-1001/",
        )
        safe_payload = json.loads(safe_payload_str)
        self.assertEqual(safe_payload["data"]["url"], "/complaint/factory-review/FAC-1001/")

    # 16. Multiple valid devices for same user are all supported
    @patch("management.services.push_notifications.send_push_to_subscription")
    def test_multiple_devices_for_same_user_supported(self, mock_send_sub):
        mock_send_sub.return_value = True

        PushSubscription.objects.create(
            user=self.user_a,
            endpoint="https://example.com/laptop",
            p256dh="k1",
            auth="a1",
            is_active=True,
        )
        PushSubscription.objects.create(
            user=self.user_a,
            endpoint="https://example.com/android-phone",
            p256dh="k2",
            auth="a2",
            is_active=True,
        )
        PushSubscription.objects.create(
            user=self.user_a,
            endpoint="https://example.com/desktop-edge",
            p256dh="k3",
            auth="a3",
            is_active=True,
        )

        with self.settings(
            WEBPUSH_VAPID_PUBLIC_KEY=TEST_VAPID_PUBLIC_KEY,
            WEBPUSH_VAPID_PRIVATE_KEY=TEST_VAPID_PRIVATE_KEY,
            WEBPUSH_VAPID_SUBJECT="mailto:admin@example.com",
        ):
            result = send_push_to_user(self.user_a, "Multi-device test", "Checking delivery")
            self.assertEqual(result["sent"], 3)
            self.assertEqual(result["total"], 3)
            self.assertEqual(mock_send_sub.call_count, 3)

    # 17. Reassignment selects new assignee correctly
    @patch("management.services.push_notifications.send_push_to_user")
    def test_reassignment_notifies_new_assignee(self, mock_send_push):
        complaint = Complaint(
            complaint_id="FAC-26100004",
            complaint_type="line",
            created_by=self.user_a,
            assigned_factory_executive=self.user_a,
            workflow_status=WorkflowStatuses.ASSIGNED_TO_FACTORY,
            date=timezone.now().date(),
        )
        complaint.save()

        # Reassign to exec_2
        complaint.assigned_factory_executive = self.exec_2
        complaint.save(update_fields=["assigned_factory_executive"])
        with self.captureOnCommitCallbacks(execute=True):
            notify_factory_assignment(complaint, self.exec_2)

        calls = [c[0][0] for c in mock_send_push.call_args_list]
        self.assertIn(self.exec_2, calls)

    # 18. Service Worker served with correct headers
    def test_service_worker_served_with_correct_headers(self):
        response = self.client.get("/sw.js")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/javascript; charset=utf-8")
        self.assertEqual(response["Service-Worker-Allowed"], "/")
        self.assertIn("notificationclick", response.content.decode("utf-8"))

    # 19. Push status endpoint
    def test_push_status_endpoint(self):
        self.client.login(username="user_a", password=self.password)
        with self.settings(WEBPUSH_VAPID_PUBLIC_KEY=TEST_VAPID_PUBLIC_KEY):
            response = self.client.get(reverse("push_status"))
            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertTrue(data.get("configured"))
            self.assertEqual(data.get("vapid_public_key"), TEST_VAPID_PUBLIC_KEY)
            self.assertNotIn(TEST_VAPID_PRIVATE_KEY, response.content.decode())
            self.assertFalse(data.get("is_subscribed"))

            # After subscribing
            PushSubscription.objects.create(
                user=self.user_a,
                endpoint="https://example.com/status-sub",
                p256dh="k",
                auth="a",
                is_active=True,
            )
            response2 = self.client.get(reverse("push_status"))
            data2 = response2.json()
            self.assertTrue(data2.get("is_subscribed"))

    def test_status_hides_public_key_when_pair_missing_or_mismatched(self):
        self.client.force_login(self.user_a)
        other_private = ec.generate_private_key(ec.SECP256R1())
        mismatch = base64.urlsafe_b64encode(
            other_private.private_numbers().private_value.to_bytes(32, 'big')
        ).decode().rstrip('=')
        for private_key in ('', 'not-a-private-key', mismatch):
            with self.subTest(private_key_present=bool(private_key)):
                with self.settings(WEBPUSH_VAPID_PRIVATE_KEY=private_key):
                    data = self.client.get(reverse('push_status')).json()
                    self.assertFalse(data['configured'])
                    self.assertEqual(data['vapid_public_key'], '')
                    self.assertNotIn('private_key', data)
                    response = self.client.post(
                        reverse('push_subscribe'), json.dumps(self.sample_sub_data),
                        content_type='application/json',
                    )
                    self.assertEqual(response.status_code, 503)
        self.assertFalse(PushSubscription.objects.exists())

    def test_read_only_vapid_diagnostics_never_print_keys(self):
        status = get_vapid_configuration_status()
        self.assertTrue(status['public_key_valid'])
        self.assertTrue(status['private_key_valid'])
        self.assertTrue(status['keys_match'])
        self.assertTrue(status['configured'])
        self.assertIn('subject_environment_present', status)
        output = StringIO()
        call_command('check_web_push', stdout=output)
        self.assertIn('configured: True', output.getvalue())
        self.assertNotIn(TEST_VAPID_PRIVATE_KEY, output.getvalue())
        self.assertNotIn(TEST_VAPID_PUBLIC_KEY, output.getvalue())
        with self.settings(WEBPUSH_VAPID_PRIVATE_KEY=''):
            status = get_vapid_configuration_status()
            self.assertFalse(status['private_key_exists'])
            self.assertFalse(status['keys_match'])
            self.assertFalse(status['configured'])

    def test_push_status_requires_authentication(self):
        response = self.client.get(reverse('push_status'))
        self.assertEqual(response.status_code, 302)
        self.assertNotIn(TEST_VAPID_PUBLIC_KEY, response.content.decode())

    def test_logout_deactivates_only_current_browser_subscription(self):
        self.client.force_login(self.user_a)
        response = self.client.post(
            reverse('push_subscribe'), json.dumps(self.sample_sub_data),
            content_type='application/json',
        )
        self.assertIn('fabro_push_subscription', response.cookies)
        other = PushSubscription.objects.create(
            user=self.user_a, endpoint='https://example.com/other-device',
            p256dh='key', auth='auth', is_active=True,
        )
        self.client.post(reverse('logout'))
        self.assertFalse(PushSubscription.objects.get(endpoint=self.sample_sub_data['endpoint']).is_active)
        other.refresh_from_db()
        self.assertTrue(other.is_active)

    def test_shared_browser_status_is_scoped_to_signed_in_user(self):
        self.client.force_login(self.user_a)
        self.client.post(
            reverse('push_subscribe'), json.dumps(self.sample_sub_data),
            content_type='application/json',
        )
        self.client.force_login(self.user_b)
        response = self.client.get(
            reverse('push_status'), {'endpoint': self.sample_sub_data['endpoint']},
        )
        self.assertFalse(response.json()['is_subscribed'])
        self.client.post(
            reverse('push_subscribe'), json.dumps(self.sample_sub_data),
            content_type='application/json',
        )
        self.assertEqual(PushSubscription.objects.get(endpoint=self.sample_sub_data['endpoint']).user, self.user_b)

    @patch('management.services.push_notifications.send_push_to_user')
    def test_workflow_push_omits_sensitive_in_app_message(self, mock_send):
        with self.captureOnCommitCallbacks(execute=True):
            notify_user(self.user_a, 'Review required', 'Private reviewer comment: confidential')
        self.assertEqual(Notification.objects.filter(recipient=self.user_a).count(), 1)
        self.assertIn('confidential', Notification.objects.get(recipient=self.user_a).message)
        self.assertEqual(mock_send.call_args.args[0], self.user_a)
        self.assertNotIn('confidential', mock_send.call_args.args[2])

    def test_protocol_relative_push_destination_is_rejected(self):
        payload = json.loads(build_push_payload('Update', 'Open Fabro', url='//example.com/steal'))
        self.assertEqual(payload['data']['url'], '/')
        payload = json.loads(build_push_payload('Update', 'Open Fabro', data={'url': '/\\example.com/steal'}))
        self.assertEqual(payload['data']['url'], '/')

    def test_malformed_subscription_types_are_rejected(self):
        self.client.force_login(self.user_a)
        for payload in ([], {'endpoint': 123, 'keys': {}}, {'endpoint': 'https://example.com', 'keys': []}):
            with self.subTest(payload=payload):
                response = self.client.post(
                    reverse('push_subscribe'), json.dumps(payload), content_type='application/json',
                )
                self.assertEqual(response.status_code, 400)
