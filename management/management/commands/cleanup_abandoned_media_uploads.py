from django.core.management.base import BaseCommand, CommandError

from management.services.media_uploads import cleanup_expired_uploads
from management.services.supabase_storage import SupabaseStorageError


class Command(BaseCommand):
    help = 'Delete expired, unattached complaint media uploads from Supabase Storage.'

    def handle(self, *args, **options):
        try:
            deleted = cleanup_expired_uploads()
        except SupabaseStorageError as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(self.style.SUCCESS(f'Cleaned {deleted} abandoned media upload(s).'))
