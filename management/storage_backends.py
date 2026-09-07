from django.core.files.storage import Storage

from .services.s3_storage import (
    create_signed_download_url,
    delete_objects,
    get_object_info,
    upload_content,
)


class S3Storage(Storage):
    """Django storage adapter backed by Garage/S3."""

    def _save(self, name, content):
        content.seek(0)
        upload_content(
            name,
            content.read(),
            getattr(content, "content_type", None),
        )
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
        return int(info.get("size") or 0)

    def url(self, name):
        return create_signed_download_url(name)
