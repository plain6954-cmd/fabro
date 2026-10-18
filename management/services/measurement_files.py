import logging
import os
import re
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from django.utils.text import get_valid_filename
from django.utils.translation import gettext_lazy as _

from management.models import PatternMeasurementFile, YearRange

logger = logging.getLogger(__name__)

MAX_MEASUREMENT_FILE_SIZE = 100 * 1024 * 1024  # 100 MB

SCANNED_EXTENSIONS = {
    '.dxf': 'dxf',
    '.pdf': 'pdf',
    '.jpg': 'image',
    '.jpeg': 'image',
    '.png': 'image',
    '.webp': 'image',
    '.heic': 'image',
    '.heif': 'image',
    '.dwg': 'cad',
    '.step': 'cad',
    '.stp': 'cad',
}

INTERIOR_EXTENSIONS = {
    '.jpg': 'image',
    '.jpeg': 'image',
    '.png': 'image',
    '.webp': 'image',
    '.heic': 'image',
    '.heif': 'image',
    '.mp4': 'video',
    '.mov': 'video',
    '.webm': 'video',
    '.avi': 'video',
    '.mkv': 'video',
}

REFERENCE_EXTENSIONS = {
    '.jpg': 'image',
    '.jpeg': 'image',
    '.png': 'image',
    '.webp': 'image',
    '.heic': 'image',
    '.heif': 'image',
}


def get_allowed_extensions_for_category(category):
    if category == PatternMeasurementFile.CATEGORY_SCANNED:
        return SCANNED_EXTENSIONS
    if category == PatternMeasurementFile.CATEGORY_INTERIOR:
        return INTERIOR_EXTENSIONS
    if category == PatternMeasurementFile.CATEGORY_REFERENCE:
        return REFERENCE_EXTENSIONS
    return {}


def validate_measurement_file(uploaded_file, category):
    if not uploaded_file:
        raise ValidationError(_("No file was provided."))

    size = uploaded_file.size
    if size <= 0:
        raise ValidationError(_("Uploaded file cannot be empty."))
    if size > MAX_MEASUREMENT_FILE_SIZE:
        raise ValidationError(_("File size exceeds maximum allowed limit of 100 MB."))

    original_name = uploaded_file.name or ''
    safe_name = get_valid_filename(os.path.basename(original_name))
    ext = os.path.splitext(safe_name)[1].lower()

    allowed_map = get_allowed_extensions_for_category(category)
    if ext not in allowed_map:
        raise ValidationError(
            _("Unsupported file format '%(ext)s' for this section.") % {'ext': ext}
        )

    file_type = allowed_map[ext]
    return safe_name, ext, size, file_type


def save_measurement_file(vehicle, category, uploaded_file, user=None, client_key=None):
    safe_name, ext, size, file_type = validate_measurement_file(uploaded_file, category)

    if client_key:
        existing = PatternMeasurementFile.objects.filter(client_upload_key=client_key).first()
        if existing:
            return existing, False

    with transaction.atomic():
        meas_file = PatternMeasurementFile.objects.create(
            vehicle=vehicle,
            category=category,
            file=uploaded_file,
            filename=safe_name,
            file_size=size,
            file_type=file_type,
            file_ext=ext.lstrip('.'),
            uploaded_by=user,
            client_upload_key=client_key or None,
        )
        return meas_file, True


def serialize_measurement_file(meas_file, request=None):
    from django.urls import reverse

    download_url = reverse('measurement_file_download', args=[meas_file.pk])
    preview_url = meas_file.file.url if meas_file.file else ''

    return {
        'id': meas_file.id,
        'filename': meas_file.filename,
        'file_size': meas_file.file_size,
        'file_type': meas_file.file_type,
        'file_ext': meas_file.file_ext,
        'url': preview_url,
        'download_url': download_url,
        'uploaded_at': timezone.localtime(meas_file.uploaded_at).strftime('%b %d, %Y %H:%M'),
        'uploaded_by': meas_file.uploaded_by.username if meas_file.uploaded_by else '',
    }
