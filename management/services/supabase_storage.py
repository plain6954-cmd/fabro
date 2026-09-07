"""Backward-compatibility shim for s3_storage.

Deprecated: Import directly from management.services.s3_storage instead.
"""
import warnings

from .s3_storage import (
    S3StorageError,
    create_signed_download_url,
    create_signed_upload_url,
    delete_objects,
    get_object_info,
    upload_content,
)

warnings.warn(
    'management.services.supabase_storage is deprecated; use management.services.s3_storage instead.',
    DeprecationWarning,
    stacklevel=2,
)

SupabaseStorageError = S3StorageError

__all__ = [
    'S3StorageError',
    'SupabaseStorageError',
    'create_signed_download_url',
    'create_signed_upload_url',
    'delete_objects',
    'get_object_info',
    'upload_content',
]
