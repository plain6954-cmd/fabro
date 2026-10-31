"""Content validation and private storage for design PDFs, using existing records."""
import math
from pathlib import Path

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.files.storage import FileSystemStorage, default_storage
from django.utils.translation import gettext as _
from pypdf import PdfReader


PDF_PREFIX = 'private_design_pdfs/'


def design_file_storage(name):
    if name.startswith((PDF_PREFIX, 'private_design_voice_notes/')) and not settings.USE_S3_STORAGE:
        # Keep private design attachments outside publicly served MEDIA_ROOT.
        media_root = Path(settings.MEDIA_ROOT)
        return FileSystemStorage(location=media_root.with_name(media_root.name + '-private-designs'))
    return default_storage


def validate_design_pdf(upload):
    try:
        upload.seek(0)
        if not upload.read(8).startswith(b'%PDF-'):
            raise ValueError('PDF signature missing')
        upload.seek(0)
        reader = PdfReader(upload, strict=True)
        if reader.is_encrypted:
            raise ValidationError(_('Password-protected PDFs are not supported.'))
        if not len(reader.pages):
            raise ValueError('PDF has no pages')
        for page in reader.pages:
            box = page.mediabox
            if not all(math.isfinite(float(value)) for value in box) or box.width <= 0 or box.height <= 0:
                raise ValueError('Invalid PDF page dimensions')
    except ValidationError:
        raise
    except Exception as exc:
        raise ValidationError(_('Invalid or damaged PDF file.')) from exc
    finally:
        upload.seek(0)


def save_design_pdf(field, upload, filename):
    name = PDF_PREFIX + filename
    field.name = design_file_storage(name).save(name, upload)
    field._committed = True
