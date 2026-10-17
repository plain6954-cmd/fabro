"""Print non-sensitive effective database settings without connecting to the database."""

from django.conf import settings
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Show safe database connection diagnostics without opening a connection.'
    requires_system_checks = []

    def handle(self, *args, **options):
        database = settings.DATABASES['default']
        backend = database['ENGINE'].rsplit('.', 1)[-1]
        self.stdout.write(f'Backend: {backend}')
        self.stdout.write(f'Connection mode: {settings.DATABASE_CONNECTION_MODE}')
        if backend == 'postgresql':
            self.stdout.write(f'Port: {database["PORT"]}')
            self.stdout.write(f'CONN_MAX_AGE: {database["CONN_MAX_AGE"]}')
            self.stdout.write(f'CONN_HEALTH_CHECKS: {database["CONN_HEALTH_CHECKS"]}')
            self.stdout.write(
                f'DISABLE_SERVER_SIDE_CURSORS: {database["DISABLE_SERVER_SIDE_CURSORS"]}'
            )
            self.stdout.write(f'SSL mode: {database["OPTIONS"]["sslmode"]}')
            if settings.DATABASE_CONNECTION_MODE == 'unspecified':
                self.stdout.write('Set DB_CONNECTION_MODE to confirm direct, session, or transaction mode.')
