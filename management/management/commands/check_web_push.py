"""Read-only VAPID diagnostics that never display key material."""
from django.core.management.base import BaseCommand

from management.services.push_notifications import get_vapid_configuration_status


class Command(BaseCommand):
    help = 'Report safe Web Push VAPID presence and compatibility checks.'

    def handle(self, *args, **options):
        for name, value in get_vapid_configuration_status().items():
            self.stdout.write(f'{name}: {value}')
