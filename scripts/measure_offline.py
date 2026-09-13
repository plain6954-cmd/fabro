"""Measure representative HTML compression and serializer queries on fixtures."""
import json
import gzip
import verify_offline
from django.db import connection
from django.test import Client, RequestFactory
from django.test.runner import DiscoverRunner
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from management.tests_performance import PerformancePaginationTests
from management.models import Complaint, ComplaintApproval, ComplaintTimeline
from management.api_views import ComplaintRetrieveUpdateDestroyAPIView
from management.serializers import ComplaintSerializer

runner = DiscoverRunner(verbosity=0, interactive=False)
database_config = runner.setup_databases()
try:
    PerformancePaginationTests.setUpTestData()
    user = PerformancePaginationTests.user
    client = Client()
    client.force_login(user)
    response = client.get('/car-details/', HTTP_ACCEPT_ENCODING='gzip')
    expanded = gzip.decompress(response.content)
    complaint = Complaint.objects.create(date=timezone.localdate(), created_by=user)
    for number in range(12):
        ComplaintApproval.objects.create(complaint=complaint, approval_round=number + 1, approver_role='PM', approver_user=user)
        ComplaintTimeline.objects.create(complaint=complaint, action_type='test', title='Synthetic event', user=user)
    with CaptureQueriesContext(connection) as original_queries:
        ComplaintSerializer(Complaint.objects.get(pk=complaint.pk)).data
    view = ComplaintRetrieveUpdateDestroyAPIView()
    view.request = RequestFactory().get('/')
    view.request.user = user
    with CaptureQueriesContext(connection) as optimized_queries:
        ComplaintSerializer(view.get_queryset().get(pk=complaint.pk)).data
    print(json.dumps({
        'fixture': '60 vehicles, 50 shown; complaint with 12 approvals and 12 timeline events',
        'html_bytes': len(expanded), 'gzip_bytes': len(response.content),
        'reduction_percent': round(100 * (1 - len(response.content) / len(expanded)), 1),
        'original_serializer_queries': len(original_queries),
        'optimized_queries_including_permissions': len(optimized_queries),
    }, indent=2))
finally:
    runner.teardown_databases(database_config)
