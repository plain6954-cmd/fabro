"""Private voice attachments to existing review decisions; no separate review workflow."""
from array import array
import io
import logging
import time
import uuid
import wave

import av
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.base import ContentFile
from django.db import transaction
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext as _

from management.models import DesignReviewVoiceNote
from management.services.design_pdfs import design_file_storage

logger = logging.getLogger(__name__)
MAX_VOICE_BYTES = 5 * 1024 * 1024
MAX_VOICE_SECONDS = 60


def validate_voice_recording(upload):
    if not 0 < upload.size <= MAX_VOICE_BYTES:
        raise ValidationError(_('Voice notes must be non-empty and at most 5 MB.'))
    started = time.monotonic()
    pcm = bytearray()
    total_seconds = 0
    first_time = None
    last_time = 0
    try:
        upload.seek(0)
        raw = upload.read(MAX_VOICE_BYTES + 1)
        if len(raw) > MAX_VOICE_BYTES:
            raise ValidationError(_('Voice notes must be at most 5 MB.'))
        with av.open(io.BytesIO(raw), mode='r', options={
            'format_whitelist': 'matroska,webm,mov,mp4,m4a,3gp,3g2,mj2,ogg,wav',
            'protocol_whitelist': 'pipe', 'enable_drefs': '0',
        }) as source:
            if len(source.streams) != 1 or len(source.streams.audio) != 1:
                raise ValueError('A voice note must contain only one audio stream')
            stream = source.streams.audio[0]
            if stream.codec_context.name not in ('opus', 'aac', 'vorbis', 'pcm_s16le', 'pcm_s24le', 'pcm_s32le', 'pcm_f32le', 'pcm_u8'):
                raise ValueError('Unsupported recording codec')
            stream.codec_context.thread_count = 1
            resampler = av.AudioResampler(format='s16', layout='mono', rate=16000)
            for frame in source.decode(stream):
                if not 8000 <= frame.sample_rate <= 96000 or len(frame.layout.channels) > 2:
                    raise ValueError('Unsupported recording layout')
                seconds = frame.samples / frame.sample_rate
                total_seconds += seconds
                if frame.time is not None:
                    if first_time is None:
                        first_time = frame.time
                    last_time = max(last_time, frame.time - first_time + seconds)
                if max(total_seconds, last_time) > MAX_VOICE_SECONDS + 0.0001:
                    raise ValidationError(_('Voice notes must not exceed 60 seconds.'))
                if time.monotonic() - started > 8:
                    raise ValidationError(_('Recording could not be processed. Please try a shorter note.'))
                for converted in resampler.resample(frame):
                    pcm.extend(bytes(converted.planes[0])[:converted.samples * 2])
            for converted in resampler.resample(None):
                pcm.extend(bytes(converted.planes[0])[:converted.samples * 2])
        samples = array('h')
        samples.frombytes(pcm)
        duration_ms = round(len(samples) / 16)
        if not 0 < duration_ms <= 60000:
            raise ValidationError(_('Voice notes must last between a moment and 60 seconds.'))
        peaks = [max((abs(value) for value in samples[len(samples) * index // 32:len(samples) * (index + 1) // 32]), default=0) for index in range(32)]
        largest = max(peaks) or 1
        waveform = [max(8, round(90 * value / largest)) for value in peaks]
        # Small, seekable PCM WAV plays consistently across desktop, Android and iOS.
        output = io.BytesIO()
        with wave.open(output, 'wb') as target:
            target.setnchannels(1)
            target.setsampwidth(2)
            target.setframerate(16000)
            target.writeframes(pcm)
        return output.getvalue(), duration_ms, waveform
    except ValidationError:
        raise
    except Exception as exc:
        raise ValidationError(_('Unsupported or damaged voice recording.')) from exc
    finally:
        upload.seek(0)


def record_design_review_with_voice(image, user, decision, comment='', stage=None, change_type='', voice_note=None):
    from management.services.design_approvals import (
        get_latest_approval_request, record_design_review_decision, resolve_design_review_role,
    )
    from management.services.activity_permissions import require
    require(user, 'design_approval.voice')
    role = resolve_design_review_role(user, stage)
    if image.uploaded_by_id == user.id:
        raise PermissionDenied(_('Designer cannot approve their own design.'))
    latest = get_latest_approval_request(image)
    if not latest or getattr(latest, role.lower() + '_status') != 'pending':
        raise ValueError(_('This review decision has already been submitted or is unavailable.'))
    if (change_type or '').strip().lower() not in ('minor', 'major'):
        raise ValidationError(_('Please select either Minor Change or Major Change.'))
    content, duration_ms, waveform = validate_voice_recording(voice_note)
    name = 'private_design_voice_notes/' + uuid.uuid4().hex + '.wav'
    storage = design_file_storage(name)
    saved = name
    committed_note = None
    try:
        saved = storage.save(name, ContentFile(content))
        with transaction.atomic():
            approval, image = record_design_review_decision(image, user, decision, comment, stage=stage, change_type=change_type)
            committed_note = DesignReviewVoiceNote.objects.create(
                approval=approval, reviewer=user, reviewer_name=(user.get_full_name() or user.username)[:255],
                stage=role, file=saved, duration_ms=duration_ms, waveform=waveform,
            )
        return approval, image
    except Exception:
        # Never delete a committed attachment because a later on_commit callback failed.
        retained = committed_note and DesignReviewVoiceNote.objects.filter(pk=committed_note.pk).exists()
        if saved and not retained:
            delete_voice_file(saved)
        raise


def delete_voice_file(name):
    try:
        design_file_storage(name).delete(name)
    except Exception:
        logger.warning('Unable to delete private review recording.', exc_info=True)


def serialize_voice_note(note, approval=None):
    approval = approval or note.approval
    reviewed_at = getattr(approval, note.stage.lower() + '_decided_at') or note.created_at
    return {'id': note.pk, 'url': reverse('design_review_voice_audio', args=[note.pk]),
            'stage': note.stage, 'cycle': approval.cycle, 'reviewer': note.reviewer_name,
            'reviewed_at': timezone.localtime(reviewed_at).strftime('%b %d, %Y %I:%M %p'),
            'duration_ms': note.duration_ms, 'waveform': note.waveform}
