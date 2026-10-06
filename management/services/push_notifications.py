import json
import logging
from django.conf import settings
from django.db import transaction
from django.utils import timezone

logger = logging.getLogger(__name__)


def is_web_push_configured():
    """Check if VAPID keys and subject are configured in settings."""
    private_key = getattr(settings, 'WEBPUSH_VAPID_PRIVATE_KEY', '').strip()
    public_key = getattr(settings, 'WEBPUSH_VAPID_PUBLIC_KEY', '').strip()
    subject = getattr(settings, 'WEBPUSH_VAPID_SUBJECT', '').strip()
    return bool(private_key and public_key and subject)


def get_vapid_claims():
    """Return VAPID claims dictionary for pywebpush."""
    subject = getattr(settings, 'WEBPUSH_VAPID_SUBJECT', '').strip() or 'mailto:admin@fabroleather.com'
    return {'sub': subject}


def build_push_payload(title, body, url=None, tag=None, data=None):
    """Build a sanitized JSON payload for the push notification."""
    # Ensure safe same-origin URL fallback
    safe_url = url if url and str(url).startswith('/') else '/'

    payload_data = {'url': safe_url}
    if data and isinstance(data, dict):
        payload_data.update(data)
        # Never allow overriding url with an external destination
        if not str(payload_data.get('url', '')).startswith('/'):
            payload_data['url'] = '/'

    payload = {
        'title': str(title)[:120],
        'body': str(body or '')[:250],
        'icon': '/static/favicon.ico',
        'badge': '/static/favicon.ico',
        'tag': str(tag or 'fabro-notification')[:50],
        'data': payload_data,
    }
    return json.dumps(payload)


def send_push_to_subscription(subscription, payload_str):
    """
    Send Web Push notification to a single PushSubscription.
    Updates failure count or deactivates expired subscriptions safely.
    Returns True on success, False on failure.
    """
    if not is_web_push_configured():
        logger.debug("Web Push is not configured. Skipping delivery.")
        return False

    if not subscription.is_active:
        return False

    private_key = getattr(settings, 'WEBPUSH_VAPID_PRIVATE_KEY', '').strip()
    claims = get_vapid_claims()

    subscription_info = {
        'endpoint': subscription.endpoint,
        'keys': {
            'p256dh': subscription.p256dh,
            'auth': subscription.auth,
        },
    }

    try:
        from pywebpush import WebPushException, webpush

        webpush(
            subscription_info=subscription_info,
            data=payload_str,
            vapid_private_key=private_key,
            vapid_claims=claims,
            ttl=86400,
        )

        subscription.last_success_at = timezone.now()
        subscription.failure_count = 0
        subscription.save(update_fields=['last_success_at', 'failure_count', 'updated_at'])
        return True

    except Exception as exc:
        status_code = None
        # Safely inspect pywebpush response status if available
        resp = getattr(exc, 'response', None)
        if resp is not None:
            status_code = getattr(resp, 'status_code', None)

        if status_code in (404, 410):
            # Subscription is permanently gone or unsubscribed at browser push service
            logger.info("Deactivating expired push subscription id=%s status=%s", subscription.id, status_code)
            subscription.is_active = False
            subscription.failure_count += 1
            subscription.save(update_fields=['is_active', 'failure_count', 'updated_at'])
        else:
            subscription.failure_count += 1
            if subscription.failure_count >= 10:
                logger.warning("Deactivating push subscription id=%s after repeated failures", subscription.id)
                subscription.is_active = False
                subscription.save(update_fields=['is_active', 'failure_count', 'updated_at'])
            else:
                subscription.save(update_fields=['failure_count', 'updated_at'])

            logger.warning(
                "Push delivery error for subscription id=%s (status=%s): %s",
                subscription.id,
                status_code,
                exc.__class__.__name__,
            )
        return False


def send_push_to_user(user, title, body, url=None, tag=None, data=None):
    """
    Send Web Push notification to all active devices of a single authenticated user.
    Returns a summary dict: {'sent': int, 'failed': int, 'total': int}.
    """
    if not user or not user.is_authenticated:
        return {'sent': 0, 'failed': 0, 'total': 0}

    from management.models import PushSubscription

    active_subs = list(
        PushSubscription.objects.filter(user=user, is_active=True)
    )
    if not active_subs:
        return {'sent': 0, 'failed': 0, 'total': 0}

    payload_str = build_push_payload(title=title, body=body, url=url, tag=tag, data=data)
    sent_count = 0
    failed_count = 0

    for sub in active_subs:
        try:
            if send_push_to_subscription(sub, payload_str):
                sent_count += 1
            else:
                failed_count += 1
        except Exception as exc:
            failed_count += 1
            logger.error("Unexpected error delivering push to sub id=%s: %s", sub.id, exc)

    return {'sent': sent_count, 'failed': failed_count, 'total': len(active_subs)}


def send_push_to_users(users, title, body, url=None, tag=None, data=None):
    """Send Web Push notification to multiple users."""
    total_sent = 0
    total_failed = 0
    total_subs = 0

    for user in users:
        result = send_push_to_user(user, title, body, url=url, tag=tag, data=data)
        total_sent += result['sent']
        total_failed += result['failed']
        total_subs += result['total']

    return {'sent': total_sent, 'failed': total_failed, 'total': total_subs}


def send_push_on_commit(user, title, body, url=None, tag=None, data=None):
    """
    Send Web Push only after the surrounding database transaction commits successfully.
    If no transaction is active, executes immediately.
    """
    def _deliver():
        try:
            send_push_to_user(user, title, body, url=url, tag=tag, data=data)
        except Exception as exc:
            logger.error("Error delivering deferred push to user %s: %s", getattr(user, 'id', None), exc)

    transaction.on_commit(_deliver)
