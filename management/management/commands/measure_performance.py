import json
import time

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import connection
from django.test import Client
from django.test.utils import CaptureQueriesContext, setup_test_environment


class Command(BaseCommand):
    help = 'Measure response time, SQL count, response bytes, and visible records for key routes.'

    def add_arguments(self, parser):
        parser.add_argument('--username', required=True)

    def handle(self, *args, **options):
        user = get_user_model().objects.filter(username=options['username']).first()
        if not user:
            raise CommandError('The measurement user does not exist.')
        setup_test_environment()
        client = Client()
        client.force_login(user)
        routes = [
            '/', '/car-details/', '/complaints/', '/add-complaint/', '/approvals/',
            '/admin_panel/', '/add-sku/', '/master-settings/', '/chat/',
            '/notifications/', '/profile/', '/api/complaints/', '/api/vehicles/',
            '/api/skus/', '/api/notifications/',
        ]
        rows = []
        for path in routes:
            started = time.perf_counter()
            with CaptureQueriesContext(connection) as queries:
                response = client.get(path)
            context = getattr(response, 'context', None)
            visible = None
            if context:
                for key in ('complaints', 'car_data', 'approval_items', 'users_data', 'notifications'):
                    value = context.get(key)
                    if value is not None:
                        try:
                            visible = len(value)
                        except TypeError:
                            pass
                        break
            rows.append({
                'path': path,
                'status': response.status_code,
                'milliseconds': round((time.perf_counter() - started) * 1000, 2),
                'queries': len(queries),
                'bytes': len(response.content),
                'visible_records': visible,
            })
        self.stdout.write('PERF_JSON=' + json.dumps(rows, separators=(',', ':')))
