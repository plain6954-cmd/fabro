from django.conf import settings
from django.utils.cache import patch_vary_headers
from django.utils import translation
from django.db import connection
import logging
import time

logger = logging.getLogger('fabro.performance')


class SecurityHeadersMiddleware:
    """Add browser security boundaries that are not provided by Django 5.2."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if settings.CONTENT_SECURITY_POLICY:
            response.setdefault('Content-Security-Policy', settings.CONTENT_SECURITY_POLICY)
        response.setdefault(
            'Permissions-Policy',
            'camera=(self), microphone=(self), geolocation=(), payment=(), usb=()',
        )
        response.setdefault('Cross-Origin-Opener-Policy', 'same-origin')
        if response.get('Content-Type', '').startswith('text/html'):
            patch_vary_headers(response, ('HX-Request',))
        return response


class UserProfileLocaleMiddleware:
    """Activate the authenticated user's persisted portal language."""

    supported_languages = {'en', 'ar', 'hi'}

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, 'user', None)
        if user and user.is_authenticated:
            profile = getattr(user, 'workflow_profile', None)

            # Reuse the profile already fetched here throughout this request.
            # workflow.get_user_profile() checks this attribute first, avoiding
            # a second database round trip for the same UserProfile.
            if profile is not None:
                user._workflow_profile = profile

            language = getattr(profile, 'preferred_language', 'en') or 'en'
            if language not in self.supported_languages:
                language = 'en'
            translation.activate(language)
            request.LANGUAGE_CODE = language
        response = self.get_response(request)
        patch_vary_headers(response, ('Cookie',))
        return response


class PerformanceTimingMiddleware:
    """Optional, privacy-safe request timing for diagnostics."""

    def __init__(self, get_response):
        self.get_response = get_response
        self.enabled = getattr(settings, 'PERFORMANCE_TIMING_ENABLED', False)
        self.slow_ms = getattr(settings, 'SLOW_REQUEST_THRESHOLD_MS', 750)
        self.count_queries = getattr(settings, 'SQL_QUERY_COUNT_ENABLED', False)

    def __call__(self, request):
        started = time.perf_counter()
        query_count = 0
        if self.count_queries:
            def count_query(execute, sql, params, many, context):
                nonlocal query_count
                query_count += 1
                return execute(sql, params, many, context)
            with connection.execute_wrapper(count_query):
                response = self.get_response(request)
        else:
            response = self.get_response(request)
        duration_ms = (time.perf_counter() - started) * 1000
        if self.enabled:
            response['Server-Timing'] = f'app;dur={duration_ms:.1f}'
            if self.count_queries:
                response['Server-Timing'] += f', db;desc="queries";dur={query_count}'
        if self.count_queries:
            logger.info(
                'Request SQL count method=%s path=%s status=%s queries=%s',
                request.method, request.path, response.status_code, query_count,
            )
        if duration_ms >= self.slow_ms:
            logger.warning(
                'Slow request method=%s path=%s status=%s duration_ms=%.1f',
                request.method, request.path, response.status_code, duration_ms,
            )
        return response
