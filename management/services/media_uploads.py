import logging
import os
import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from django.utils.text import get_valid_filename

from management.models import (
    ComplaintMedia,
    ComplaintMediaUpload,
    ComplaintMediaUploadBatch,
)

from .supabase_storage import (
    SupabaseStorageError,
    create_signed_upload_url,
    delete_objects,
    get_object_info,
)


MAX_COMPLAINT_MEDIA_FILES = 10
MAX_COMPLAINT_MEDIA_SIZE = 100 * 1024 * 1024
ALLOWED_COMPLAINT_MEDIA_TYPES = {
    '.jpg': {'image/jpeg'},
    '.jpeg': {'image/jpeg'},
    '.png': {'image/png'},
    '.webp': {'image/webp'},
    '.gif': {'image/gif'},
    '.mp4': {'video/mp4'},
    '.mov': {'video/quicktime'},
    '.webm': {'video/webm'},
    '.avi': {'video/x-msvideo', 'video/avi'},
    '.mkv': {'video/x-matroska'},
}
logger = logging.getLogger(__name__)


def normalize_content_type(value):
    return (value or '').split(';', 1)[0].strip().lower()


def validate_media_metadata(filename, size, content_type):
    safe_name = get_valid_filename(os.path.basename(filename or ''))
    extension = os.path.splitext(safe_name)[1].lower()
    normalized_type = normalize_content_type(content_type)
    if not safe_name or extension not in ALLOWED_COMPLAINT_MEDIA_TYPES:
        raise ValidationError('Unsupported media file extension.')
    try:
        size = int(size)
    except (TypeError, ValueError) as exc:
        raise ValidationError('Media file size is invalid.') from exc
    if size <= 0:
        raise ValidationError('Media files cannot be empty.')
    if size > MAX_COMPLAINT_MEDIA_SIZE:
        raise ValidationError('file size exceeds 100 MB.')
    if normalized_type not in ALLOWED_COMPLAINT_MEDIA_TYPES[extension]:
        raise ValidationError('The media MIME type does not match its file extension.')
    return safe_name, size, normalized_type, extension


def create_upload_batch(user, complaint=None):
    return ComplaintMediaUploadBatch.objects.create(user=user, complaint=complaint)


def get_owned_batch(user, batch_id, complaint=None, *, for_update=False):
    queryset = ComplaintMediaUploadBatch.objects
    if for_update:
        queryset = queryset.select_for_update()
    try:
        batch = queryset.get(id=batch_id, user=user)
    except (ComplaintMediaUploadBatch.DoesNotExist, ValueError, TypeError) as exc:
        raise ValidationError('The media upload session is invalid.') from exc
    if batch.expires_at <= timezone.now():
        raise ValidationError('The media upload session has expired. Refresh the page and retry.')
    if batch.complaint_id != (complaint.pk if complaint else None):
        raise ValidationError('The media upload session does not belong to this complaint.')
    return batch


def _validated_removal_ids(complaint, removal_ids):
    if not complaint:
        return []
    return list(
        complaint.media_files.filter(id__in=removal_ids or []).values_list('id', flat=True)
    )


def create_upload_ticket(user, batch, *, filename, size, content_type, removal_ids=None):
    safe_name, size, content_type, extension = validate_media_metadata(
        filename,
        size,
        content_type,
    )
    valid_removals = _validated_removal_ids(batch.complaint, removal_ids)
    existing_count = (
        batch.complaint.media_files.exclude(id__in=valid_removals).count()
        if batch.complaint_id
        else 0
    )
    pending_count = batch.uploads.filter(status=ComplaintMediaUpload.Status.PENDING).count()
    if existing_count + pending_count >= MAX_COMPLAINT_MEDIA_FILES:
        raise ValidationError(f'A complaint can contain at most {MAX_COMPLAINT_MEDIA_FILES} media files.')

    upload_id = uuid.uuid4()
    storage_path = (
        f'complaint_media/uploads/user_{user.pk}/{batch.id}/{upload_id}/'
        f'{uuid.uuid4().hex}{extension}'
    )
    upload = ComplaintMediaUpload.objects.create(
        id=upload_id,
        batch=batch,
        storage_path=storage_path,
        original_name=safe_name[:255],
        expected_size=size,
        expected_content_type=content_type,
    )
    try:
        signed_url = create_signed_upload_url(storage_path)
    except Exception:
        upload.delete()
        raise
    return upload, signed_url


def _object_size_and_type(info):
    metadata = info.get('metadata') or {}
    size = info.get('size') or metadata.get('size') or metadata.get('contentLength')
    content_type = (
        info.get('contentType')
        or info.get('content_type')
        or metadata.get('mimetype')
        or metadata.get('contentType')
    )
    try:
        size = int(size)
    except (TypeError, ValueError) as exc:
        raise ValidationError('Supabase did not return valid object size metadata.') from exc
    return size, normalize_content_type(content_type)


def verify_pending_uploads(user, batch, upload_ids, *, complaint=None, existing_count=0):
    unique_ids = list(dict.fromkeys(str(upload_id) for upload_id in upload_ids if upload_id))
    if existing_count + len(unique_ids) > MAX_COMPLAINT_MEDIA_FILES:
        raise ValidationError(f'Keep at most {MAX_COMPLAINT_MEDIA_FILES} media files on one complaint.')
    if not unique_ids:
        return []

    uploads = list(
        ComplaintMediaUpload.objects.select_for_update()
        .select_related('batch')
        .filter(id__in=unique_ids)
    )
    if len(uploads) != len(unique_ids):
        raise ValidationError('One or more media uploads are missing or invalid.')

    expected_prefix = f'complaint_media/uploads/user_{user.pk}/{batch.id}/'
    for upload in uploads:
        if upload.batch_id != batch.id or upload.batch.user_id != user.pk:
            raise ValidationError('A media upload does not belong to the signed-in user.')
        if upload.status != ComplaintMediaUpload.Status.PENDING:
            raise ValidationError('A media upload has already been used.')
        if upload.batch.expires_at <= timezone.now():
            raise ValidationError('A media upload has expired.')
        if upload.storage_path.startswith(expected_prefix) is False:
            raise ValidationError('A media upload has an invalid storage path.')
        if f'/{upload.id}/' not in upload.storage_path:
            raise ValidationError('A media upload path does not match its upload record.')
        if upload.batch.complaint_id != (complaint.pk if complaint else None):
            raise ValidationError('A media upload belongs to a different complaint.')

        try:
            info = get_object_info(upload.storage_path)
        except SupabaseStorageError as exc:
            raise ValidationError(f'{upload.original_name}: uploaded object was not found.') from exc
        actual_size, actual_type = _object_size_and_type(info)
        extension = os.path.splitext(upload.storage_path)[1].lower()
        if actual_size != upload.expected_size or actual_size > MAX_COMPLAINT_MEDIA_SIZE:
            raise ValidationError(f'{upload.original_name}: uploaded object size does not match.')
        if actual_type != upload.expected_content_type:
            raise ValidationError(f'{upload.original_name}: uploaded object MIME type does not match.')
        if actual_type not in ALLOWED_COMPLAINT_MEDIA_TYPES.get(extension, set()):
            raise ValidationError(f'{upload.original_name}: uploaded object type is unsupported.')
    return uploads


def attach_verified_uploads(complaint, uploads):
    for upload in uploads:
        ComplaintMedia.objects.create(complaint=complaint, file=upload.storage_path)
        upload.complaint = complaint
        upload.status = ComplaintMediaUpload.Status.ATTACHED
        upload.attached_at = timezone.now()
        upload.save(update_fields=['complaint', 'status', 'attached_at'])


def discard_uploads(user, upload_ids):
    uploads = list(
        ComplaintMediaUpload.objects.filter(
            id__in=upload_ids,
            batch__user=user,
            status=ComplaintMediaUpload.Status.PENDING,
        )
    )
    if not uploads:
        return 0
    paths = [upload.storage_path for upload in uploads]
    try:
        delete_objects(paths)
    except SupabaseStorageError:
        logger.warning('Unable to delete pending Supabase media uploads.', exc_info=True)
        return 0
    return ComplaintMediaUpload.objects.filter(id__in=[upload.id for upload in uploads]).update(
        status=ComplaintMediaUpload.Status.REJECTED
    )


def cleanup_expired_uploads(now=None):
    now = now or timezone.now()
    uploads = list(
        ComplaintMediaUpload.objects.filter(
            status=ComplaintMediaUpload.Status.PENDING,
            batch__expires_at__lte=now,
        )
    )
    if not uploads:
        return 0
    delete_objects([upload.storage_path for upload in uploads])
    with transaction.atomic():
        return ComplaintMediaUpload.objects.filter(id__in=[upload.id for upload in uploads]).update(
            status=ComplaintMediaUpload.Status.REJECTED
        )
