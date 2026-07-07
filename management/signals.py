from django.contrib.auth.signals import user_logged_in
from django.dispatch import receiver
from django.utils.timezone import now

@receiver(user_logged_in)
def capture_login_metadata(sender, request, user, **kwargs):
    # Store login time
    request.session['login_time'] = str(now())

    # Store IP address
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    ip = x_forwarded_for.split(',')[0] if x_forwarded_for else request.META.get('REMOTE_ADDR')
    request.session['ip_address'] = ip

    # Also store user_id explicitly if needed
    request.session['user_id'] = user.id