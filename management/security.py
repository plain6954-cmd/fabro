import hashlib

from django.conf import settings
from django.contrib.auth.views import LoginView
from django.core.cache import cache


def get_client_ip(request):
    """Return a proxy-aware client IP only when proxy headers are explicitly trusted."""
    if settings.TRUST_PROXY_HEADERS:
        forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR', '')
        if forwarded_for:
            return forwarded_for.split(',', 1)[0].strip()
    return request.META.get('REMOTE_ADDR', '') or 'unknown'


class RateLimitedLoginView(LoginView):
    """Protect the session login form from repeated credential guessing."""

    def _cache_keys(self):
        username = (self.request.POST.get('username') or '').strip().casefold()[:150]
        identity = f'{get_client_ip(self.request)}|{username}'.encode('utf-8')
        digest = hashlib.sha256(identity).hexdigest()
        return f'fabro:login-attempts:{digest}', f'fabro:login-lock:{digest}'

    def post(self, request, *args, **kwargs):
        attempts_key, lock_key = self._cache_keys()
        self._attempts_key = attempts_key
        self._lock_key = lock_key
        if cache.get(lock_key):
            form = self.get_form()
            form.add_error(None, 'Invalid username or password.')
            return self.render_to_response(self.get_context_data(form=form), status=429)
        return super().post(request, *args, **kwargs)

    def form_invalid(self, form):
        attempts_key = getattr(self, '_attempts_key', None)
        lock_key = getattr(self, '_lock_key', None)
        if attempts_key and lock_key:
            if cache.add(attempts_key, 1, timeout=settings.LOGIN_RATE_WINDOW_SECONDS):
                attempts = 1
            else:
                try:
                    attempts = cache.incr(attempts_key)
                except ValueError:
                    cache.set(attempts_key, 1, timeout=settings.LOGIN_RATE_WINDOW_SECONDS)
                    attempts = 1
            if attempts >= settings.LOGIN_MAX_ATTEMPTS:
                cache.set(lock_key, True, timeout=settings.LOGIN_LOCKOUT_SECONDS)
        return super().form_invalid(form)

    def form_valid(self, form):
        attempts_key = getattr(self, '_attempts_key', None)
        lock_key = getattr(self, '_lock_key', None)
        if attempts_key:
            cache.delete(attempts_key)
        if lock_key:
            cache.delete(lock_key)
        return super().form_valid(form)
