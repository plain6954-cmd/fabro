import logging

from django.conf import settings

from django.contrib.auth.signals import user_logged_in
from django.contrib.auth.models import User
from django.core.files.storage import default_storage
from django.db import transaction
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver
from django.utils.timezone import now
from .models import (
    Brand, ChatMessage, Complaint, ComplaintApproval, ComplaintMedia,
    MasterSetting, Notification, SKU, UserProfile, YearRange,
)
from .services.cache_versions import bump_cache_version
from .security import get_client_ip


logger = logging.getLogger(__name__)


@receiver(post_save, sender=Complaint)
@receiver(post_delete, sender=Complaint)
@receiver(post_save, sender=ComplaintApproval)
@receiver(post_delete, sender=ComplaintApproval)
@receiver(post_save, sender=Notification)
@receiver(post_delete, sender=Notification)
@receiver(post_save, sender=ChatMessage)
@receiver(post_delete, sender=ChatMessage)
@receiver(post_save, sender=Brand)
@receiver(post_delete, sender=Brand)
@receiver(post_save, sender=YearRange)
@receiver(post_delete, sender=YearRange)
@receiver(post_save, sender=SKU)
@receiver(post_delete, sender=SKU)
@receiver(post_save, sender=MasterSetting)
@receiver(post_delete, sender=MasterSetting)
def invalidate_performance_caches(sender, **kwargs):
    bump_cache_version()

@receiver(user_logged_in)
def capture_login_metadata(sender, request, user, **kwargs):
    # Store login time
    request.session['login_time'] = str(now())

    request.session['ip_address'] = get_client_ip(request)

    # Also store user_id explicitly if needed
    request.session['user_id'] = user.id
    profile, _ = UserProfile.objects.get_or_create(user=user)
    language = profile.preferred_language or 'en'
    request.session[settings.LANGUAGE_COOKIE_NAME] = language
    request.session['_language'] = language


@receiver(post_save, sender=User)
def ensure_workflow_profile(sender, instance, created, **kwargs):
    UserProfile.objects.get_or_create(user=instance)


@receiver(post_delete, sender=ComplaintMedia)
def delete_complaint_media_file(sender, instance, **kwargs):
    storage_name = instance.storage_name
    if storage_name and not ComplaintMedia.objects.filter(file=instance.file).exists():
        transaction.on_commit(lambda name=storage_name: _delete_storage_name(name))


def _delete_storage_name(storage_name):
    try:
        default_storage.delete(storage_name)
    except (OSError, PermissionError):
        # Windows can temporarily lock a video that was open in the browser.
        # Media cleanup must never roll back or interrupt complaint deletion.
        logger.warning(
            'Unable to remove complaint media file %s because it is currently locked.',
            storage_name,
            exc_info=True,
        )
    except Exception:
        logger.warning(
            'Unable to remove complaint media file %s from storage.',
            storage_name,
            exc_info=True,
        )
