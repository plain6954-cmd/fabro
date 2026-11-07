"""Owned swatch uploads, immutable historical links and private delivery metadata."""
from datetime import timedelta
import hashlib
import json
import logging
from pathlib import PurePosixPath
import re
from uuid import uuid4

from django import forms
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.http import Http404
from django.urls import reverse
from django.utils import timezone
from django.utils.text import get_valid_filename

from management.models import ActivityLog, PickedColorPhoto, PickedColorSelection
from management.services.activity_permissions import granted, require
from management.services import picked_colors

logger = logging.getLogger(__name__)
MAX_SIZE = 10 * 1024 * 1024
TYPES = {'.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.png': 'image/png',
         '.webp': 'image/webp', '.heic': 'image/heic', '.heif': 'image/heif'}


def operation_key(user, row, raw):
    if not isinstance(raw, str) or not re.fullmatch(r'[A-Za-z0-9-]{1,64}', raw):
        raise ValidationError('A valid photo upload key is required.')
    return f'photo:{user.pk}:{row.pk}:{raw}'


def photo_data(photo, row, user, *, source=None):
    if source:
        url = reverse('color_selection_photo_file', args=[source.pk, photo.pk])
    else:
        url = reverse('picked_color_photo_file', args=[row.pk, photo.pk]) + f'?vehicle_id={row.vehicle_id}'
    return {'id': photo.pk, 'filename': photo.filename, 'file_size': photo.file_size,
        'content_type': photo.content_type, 'url': url,
        'uploaded_at': photo.uploaded_at.isoformat() if photo.uploaded_at else None,
        'uploaded_by': photo.uploader_name, 'legacy': photo.legacy_source_id is not None,
        'can_delete': bool(not source and picked_colors.permitted(user, row, 'edit'))}


def gallery(row, user):
    photos = [photo_data(photo, row, user) for photo in row.swatch_photos.all()
              if photo.image and photo.uploaded_at and not photo.removed_at]
    legacy = unimported_legacy(row)
    if legacy:
        photos.insert(0, {'id': f'legacy-{row.source_selection_id}', 'filename': PurePosixPath(legacy.name).name,
            'file_size': 0, 'content_type': '', 'url': reverse('picked_color_swatch', args=[row.pk]) + f'?vehicle_id={row.vehicle_id}',
            'uploaded_at': row.source_selection.created_at.isoformat(), 'uploaded_by': row.creator_name,
            'legacy': True, 'can_delete': False})
    return photos


def unimported_legacy(row):
    """Read-only fallback for older writers; removed known media stays removed."""
    file = row.source_selection.swatch_image if row.source_selection else None
    if file and not any(photo.image.name == file.name for photo in row.swatch_photos.all()):
        return file
    return None


def selection_gallery(selection, user):
    if not user or not all(granted(user, key) for key in ('picked_colors.view', 'color.view', 'color.history')):
        return []
    try:
        picked_colors.vehicle_for_user(user, selection.vehicle_id)
    except (PermissionDenied, Http404, ValidationError):
        return []
    return [photo_data(photo, None, user, source=selection) for photo in selection.swatch_photos.all()
            if photo.image and photo.uploaded_at]


def plans(data):
    raw = data.get('swatch_photos', '[]')
    try:
        values = json.loads(raw) if isinstance(raw, str) else raw
    except (ValueError, TypeError):
        raise ValidationError('Invalid swatch photo preparation data.')
    if not isinstance(values, list) or len(values) > 100:
        raise ValidationError('Prepare at most 100 photos in one save.')
    result, keys, hashes = [], set(), set()
    for item in values:
        if not isinstance(item, dict):
            raise ValidationError('Invalid swatch photo preparation data.')
        key, checksum, name, size = (item.get(field) for field in ('upload_key', 'sha256', 'filename', 'file_size'))
        if (not isinstance(key, str) or not re.fullmatch(r'[A-Za-z0-9-]{1,64}', key)
                or not isinstance(checksum, str) or not re.fullmatch('[a-f0-9]{64}', checksum)
                or not isinstance(name, str) or not name or len(name) > 255
                or type(size) is not int or not 0 < size <= MAX_SIZE
                or PurePosixPath(name.replace('\\', '/')).suffix.lower() not in TYPES or key in keys):
            raise ValidationError('Invalid photo metadata, format, or size (maximum 10 MB).')
        keys.add(key)
        if checksum not in hashes:
            result.append(dict(upload_key=key, sha256=checksum, filename=get_valid_filename(PurePosixPath(name.replace('\\', '/')).name), file_size=size))
            hashes.add(checksum)
    return result


def reserve(row, user, prepared, *, initial=False):
    """Only creation may reserve initial add-only uploads; hashes bind the intent."""
    for item in prepared:
        if row.swatch_photos.filter(sha256=item['sha256'], removed_at=None).exists():
            continue
        photo = PickedColorPhoto.objects.create(selection=row, sha256=item['sha256'],
            filename=item['filename'], file_size=item['file_size'],
            upload_key=operation_key(user, row, item['upload_key']), uploaded_by=user,
            uploader_name=user.get_full_name() or user.username,
            initial_upload_expires_at=timezone.now() + timedelta(days=1) if initial else None)
        if row.source_selection_id:
            photo.approval_selections.add(row.source_selection)


def bind_history(row):
    if row.source_selection_id:
        photos = list(row.swatch_photos.filter(removed_at=None))
        if photos:
            row.source_selection.swatch_photos.add(*photos)


def import_legacy(row):
    source = row.source_selection
    if not source or not source.swatch_image:
        return
    if row.swatch_photos.filter(image=source.swatch_image.name).exists():
        return
    photo, _ = PickedColorPhoto.objects.get_or_create(legacy_source=source, defaults={
        'selection': row, 'image': source.swatch_image.name,
        'filename': PurePosixPath(source.swatch_image.name).name[:255],
        'upload_key': f'legacy:{source.pk}', 'uploaded_by_id': source.submitted_by_id,
        'uploader_name': row.creator_name, 'created_at': source.created_at, 'uploaded_at': source.created_at})
    photo.approval_selections.add(source)


def _locked(user, vehicle_id, row_id):
    actor = get_user_model().objects.select_for_update().get(pk=user.pk)
    vehicle = picked_colors.vehicle_for_user(actor, vehicle_id)
    require(actor, 'picked_colors.view')
    try:
        row = PickedColorSelection.objects.select_for_update(of=('self',)).select_related('source_selection').get(
            pk=row_id, vehicle=vehicle, deleted_at=None)
    except PickedColorSelection.DoesNotExist:
        raise Http404
    return actor, row


def _may_upload(user, row, photo):
    initial = bool(photo and not photo.removed_at and photo.initial_upload_expires_at
        and photo.initial_upload_expires_at > timezone.now()
        and row.created_by_id == user.pk == photo.uploaded_by_id and granted(user, 'picked_colors.add'))
    if not picked_colors.permitted(user, row, 'edit') and not initial:
        raise PermissionDenied('Adding photos to this color selection is not permitted.')


def _audit(row, user, action, photo):
    row.audit_events = [*row.audit_events, {'action': action, 'actor_id': user.pk,
        'actor_name': user.get_full_name() or user.username, 'at': timezone.now().isoformat(),
        'vehicle_id': row.vehicle_id, 'photo_id': photo.pk, 'upload_key': photo.upload_key,
        'source_selection_id': row.source_selection_id, 'filename': photo.filename,
        'sha256': photo.sha256, 'file_size': photo.file_size}]
    row.save(update_fields=['audit_events', 'updated_at'])
    ActivityLog.objects.create(user=user, action=action, object_type='Picked Color Photo',
        object_name=f'{photo.pk} / color {row.pk} / vehicle {row.vehicle_id}')


def validate_image(file):
    if not file or not 0 < file.size <= MAX_SIZE:
        raise ValidationError('Each matching swatch photo must be nonempty and at most 10 MB.')
    name = get_valid_filename(PurePosixPath(file.name.replace('\\', '/')).name)[:255]
    extension = PurePosixPath(name).suffix.lower()
    if extension not in TYPES:
        raise ValidationError('Unsupported photo format. Use JPG, PNG, WebP, HEIC or HEIF.')
    # Match the existing opaque HEIC/HEIF policy; no new decoder dependency.
    if extension not in ('.heic', '.heif'):
        forms.ImageField().clean(file)
    file.seek(0)
    checksum = hashlib.sha256()
    for chunk in file.chunks():
        checksum.update(chunk)
    file.seek(0)
    return name, extension, checksum.hexdigest()


def matching_legacy(row, checksum):
    """Hash an old, authorized swatch only when a new upload needs deduplication."""
    for photo in row.swatch_photos.filter(removed_at=None, sha256='').exclude(image=''):
        try:
            size = photo.image.size
            if size > MAX_SIZE:
                continue  # It cannot equal a permitted new upload.
            digest = hashlib.sha256()
            with photo.image.open('rb') as stream:
                for chunk in stream.chunks():
                    digest.update(chunk)
        except FileNotFoundError:
            continue
        actual = digest.hexdigest()
        if not row.swatch_photos.filter(sha256=actual, removed_at=None).exclude(pk=photo.pk).exists():
            photo.sha256, photo.file_size = actual, size
            photo.save(update_fields=['sha256', 'file_size'])
        if actual == checksum:
            return photo
    return None


def upload(user, vehicle_id, row_id, raw_key, file):
    storage = PickedColorPhoto._meta.get_field('image').storage
    # Commit the private object reservation before writing storage. If storage
    # cleanup or a later database commit is interrupted, the object still has an
    # owning record and a known recovery key; incomplete records are never served.
    with transaction.atomic():
        actor, row = _locked(user, vehicle_id, row_id)
        key = operation_key(actor, row, raw_key)
        photo = row.swatch_photos.filter(upload_key=key).first()
        _may_upload(actor, row, photo)
        if photo and photo.removed_at:
            raise ValidationError('This upload was cancelled or removed. Select it again to start a new upload.')
        name, extension, checksum = validate_image(file)
        if photo and photo.sha256 and photo.sha256 != checksum:
            raise ValidationError('The upload key belongs to a different photo.')
        if photo and photo.image:
            return row, photo, False
        duplicate = row.swatch_photos.filter(sha256=checksum, removed_at=None).exclude(pk=photo.pk if photo else None).first()
        if duplicate and duplicate.image:
            return row, duplicate, False
        legacy = matching_legacy(row, checksum)
        if legacy:
            return row, legacy, False
        if duplicate:
            photo = duplicate
        if photo is None:
            photo = PickedColorPhoto(selection=row, upload_key=key, uploaded_by=actor,
                uploader_name=actor.get_full_name() or actor.username)
        photo.sha256, photo.filename, photo.file_size = checksum, name, file.size
        if not photo.pending_storage_key:
            photo.pending_storage_key = f'picked_color_photos/{uuid4().hex}{extension}'
        photo.save()
        if row.source_selection_id:
            photo.approval_selections.add(row.source_selection)
        photo_id = photo.pk

    error = None
    with transaction.atomic():
        actor, row = _locked(user, vehicle_id, row_id)
        photo = row.swatch_photos.get(pk=photo_id)
        _may_upload(actor, row, photo)
        if photo.removed_at:
            raise ValidationError('This upload was cancelled.')
        if photo.image:
            return row, photo, False
        written_name = photo.pending_storage_key
        try:
            with transaction.atomic():
                # This key belongs only to this unfinished upload, never to a
                # completed/shared image. Retry safely clears a staged write.
                storage.delete(written_name)
                file.seek(0)
                written_name = storage.save(written_name, file)
                photo.image, photo.pending_storage_key = written_name, ''
                photo.uploaded_by, photo.uploader_name = actor, actor.get_full_name() or actor.username
                photo.filename, photo.content_type, photo.file_size = name, TYPES[extension], file.size
                photo.uploaded_at = timezone.now()
                photo.save()
                if row.source_selection_id:
                    photo.approval_selections.add(row.source_selection)
                _audit(row, actor, 'photo_added', photo)
        except Exception as caught:
            error = caught
            # Keep the color lock through cleanup so another retry cannot write
            # the same object between rollback and deletion.
            pending = ''
            try:
                storage.delete(written_name)
            except Exception:
                pending = written_name
                logger.exception('Staged swatch object retained for retry: %s', written_name)
            PickedColorPhoto.objects.filter(pk=photo_id, uploaded_at=None).update(pending_storage_key=pending)
    if error:
        raise error
    return row, photo, True


@transaction.atomic
def remove(user, vehicle_id, row_id, *, photo_id=None, raw_key=None):
    actor, row = _locked(user, vehicle_id, row_id)
    if photo_id is not None:
        if not picked_colors.permitted(actor, row, 'edit'):
            raise PermissionDenied('Removing this photo is not permitted.')
        photo = row.swatch_photos.filter(pk=photo_id).first()
        if photo is None:
            raise Http404
    else:
        key = operation_key(actor, row, raw_key)
        photo = row.swatch_photos.filter(upload_key=key).first()
        _may_upload(actor, row, photo)
        if photo and photo.image and not picked_colors.permitted(actor, row, 'edit'):
            raise PermissionDenied('Removing a saved photo requires color editing permission.')
        if photo is None:
            photo = PickedColorPhoto.objects.create(selection=row, upload_key=key, uploaded_by=actor)
    if not photo.removed_at:
        photo.removed_at = timezone.now()
        photo.save(update_fields=['removed_at'])
        _audit(row, actor, 'photo_removed' if photo.image else 'photo_cancelled', photo)
    return row
