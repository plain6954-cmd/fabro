from django.core.files.storage import Storage

from .services.supabase_storage import (
    create_signed_download_url,
    delete_objects,
    get_object_info,
    upload_content,
)


class SupabaseStorage(Storage):
    """Django storage adapter for small non-complaint files.

    Complaint attachments use signed browser uploads and never call ``_save`` in
    production. This adapter keeps ImageField-backed logos/profile photos durable
    without retaining the previous S3-compatible backend.
    """

    def _save(self, name, content):
        content.seek(0)
        upload_content(name, content.read(), getattr(content, 'content_type', None))
        return name

    def delete(self, name):
        delete_objects([name])

    def exists(self, name):
        try:
            get_object_info(name)
        except Exception:
            return False
        return True

    def size(self, name):
        info = get_object_info(name)
        return int(info.get('size') or info.get('metadata', {}).get('size') or 0)

    def url(self, name):
        return create_signed_download_url(name)
