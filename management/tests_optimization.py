"""Regressions for read-only performance and mobile interaction support."""
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import RequestFactory, TestCase
from django.urls import reverse
from django.utils import timezone

from .context_processors import workflow_access
from .models import ChatMessage, Complaint, ComplaintApproval, ComplaintTimeline, MasterSetting, UserProfile, WorkflowRoles


class OptimizationRegressionTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.admin = User.objects.create_superuser('optimization-admin', password='test-only')
        self.peer = User.objects.create_user('optimization-peer', password='test-only')
        self.client.force_login(self.admin)
        cache.clear()

    def test_badge_cache_hits_do_not_renew_stale_values(self):
        request = RequestFactory().get('/')
        request.user = self.admin
        workflow_access(request)
        with patch('management.context_processors.cache.set') as cache_set:
            workflow_access(request)
        cache_set.assert_not_called()

    def test_chat_directory_does_not_mark_unopened_messages_read(self):
        message = ChatMessage.objects.create(sender=self.peer, recipient=self.admin, message='Synthetic unread')
        response = self.client.get(reverse('chat_view'))
        self.assertEqual(response.status_code, 200)
        message.refresh_from_db()
        self.assertFalse(message.is_read)
        response = self.client.get(reverse('chat_messages_api', args=[self.peer.pk]))
        self.assertEqual(response.status_code, 200)
        message.refresh_from_db()
        self.assertTrue(message.is_read)

    def test_chat_context_respects_country_visibility(self):
        india = MasterSetting.objects.get(category='Country', name='India')
        other_country = MasterSetting.objects.create(category='Country', name='Offline Country')
        UserProfile.objects.filter(user=self.peer).update(role=WorkflowRoles.COUNTRY_EXECUTIVE, country=other_country)
        complaint = Complaint.objects.create(date=timezone.localdate(), country=india, created_by=self.admin)
        self.client.force_login(self.peer)
        response = self.client.get(reverse('chat_view'), {'complaint': complaint.complaint_id})
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.context['selected_complaint'])
        self.assertEqual(response.context['default_message'], '')

    def test_pattern_stylesheet_is_available_to_partial_navigation(self):
        response = self.client.get(reverse('car_details'), HTTP_HX_REQUEST='true')
        from html.parser import HTMLParser

        class AssetParser(HTMLParser):
            found = False

            def handle_starttag(self, tag, attrs):
                attrs = dict(attrs)
                if tag == 'link' and 'pattern-master.css' in attrs.get('href', ''):
                    self.found = 'data-fabro-page-asset' in attrs

        parser = AssetParser()
        parser.feed(response.content.decode())
        self.assertTrue(parser.found)

    def test_detail_serialization_has_constant_query_count_as_history_grows(self):
        from .api_views import ComplaintRetrieveUpdateDestroyAPIView
        from .serializers import ComplaintSerializer
        complaint = Complaint.objects.create(date=timezone.localdate(), created_by=self.admin)
        for number in range(12):
            ComplaintApproval.objects.create(
                complaint=complaint, approval_round=number + 1, approver_role='PM', approver_user=self.peer,
            )
            ComplaintTimeline.objects.create(
                complaint=complaint, action_type='test', title='Synthetic history', user=self.peer,
            )
        view = ComplaintRetrieveUpdateDestroyAPIView()
        view.request = RequestFactory().get('/')
        view.request.user = self.admin
        # One permission/profile lookup plus four fixed relation queries.
        with self.assertNumQueries(5):
            data = ComplaintSerializer(view.get_queryset().get(pk=complaint.pk)).data
        self.assertEqual(len(data['approvals']), 12)
        self.assertEqual(len(data['timeline_events']), 12)

    def test_large_catalogue_response_compresses_without_losing_cache_variants(self):
        import gzip
        response = self.client.get(reverse('car_details'), HTTP_ACCEPT_ENCODING='gzip', HTTP_HX_REQUEST='true')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Encoding'], 'gzip')
        decoded = gzip.decompress(response.content)
        self.assertIn(b'id="mobileFiltersBtn"', decoded)
        self.assertLess(len(response.content), len(decoded) // 2)
        self.assertIn('Accept-Encoding', response['Vary'])
        self.assertIn('HX-Request', response['Vary'])
