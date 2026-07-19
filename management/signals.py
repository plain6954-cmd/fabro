from django.contrib.auth.signals import user_logged_in
from django.contrib.auth.models import User
from django.core.files.storage import default_storage
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver
from django.utils.timezone import now
from .models import ComplaintMedia, UserProfile
from .security import get_client_ip

@receiver(user_logged_in)
def capture_login_metadata(sender, request, user, **kwargs):
    # Store login time
    request.session['login_time'] = str(now())

    request.session['ip_address'] = get_client_ip(request)

    # Also store user_id explicitly if needed
    request.session['user_id'] = user.id


@receiver(post_save, sender=User)
def ensure_workflow_profile(sender, instance, created, **kwargs):
    UserProfile.objects.get_or_create(user=instance)


@receiver(post_delete, sender=ComplaintMedia)
def delete_complaint_media_file(sender, instance, **kwargs):
    storage_name = instance.storage_name
    if storage_name and not ComplaintMedia.objects.filter(file=instance.file).exists():
        default_storage.delete(storage_name)
