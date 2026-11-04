from django.conf import settings
from django.utils.cache import patch_vary_headers
from django.utils import translation, timezone
import zoneinfo
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

            user_tz = getattr(profile, 'timezone', None) or 'Asia/Kolkata'
            try:
                timezone.activate(zoneinfo.ZoneInfo(user_tz))
            except Exception:
                try:
                    timezone.activate(user_tz)
                except Exception:
                    timezone.activate(zoneinfo.ZoneInfo('Asia/Kolkata'))
        else:
            timezone.deactivate()
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


class ActivityPermissionMiddleware:
    """Feature gates after authentication; DRF gates run after token authentication."""
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_view(self, request, view_func, view_args, view_kwargs):
        from django.core.exceptions import PermissionDenied
        from django.http import JsonResponse
        from management.services.activity_routes import enforce_request
        # DRF wraps APIView in a CSRF-exempt view and authenticates inside dispatch.
        if hasattr(view_func, 'cls'):
            return None
        if getattr(view_func, '__module__', '') == 'django.views.static' and request.path.startswith(settings.MEDIA_URL):
            from management.models import PatternDesignImage, PatternMeasurementFile
            from django.db.models import Q
            from management.services.activity_permissions import scoped
            filename = view_kwargs.get('path', '')
            image = PatternDesignImage.objects.filter(Q(image=filename) | Q(thumbnail=filename)).first()
            measurement = None if image else PatternMeasurementFile.objects.filter(file=filename).first()
            if image or measurement:
                if not request.user.is_authenticated:
                    return JsonResponse({'message': 'Authentication required.'}, status=403)
                resource = 'reference' if image and image.is_reference else 'design' if image else 'measurement'
                item = image or measurement
                if not scoped(request.user, resource, 'view', item.uploaded_by_id):
                    raise PermissionDenied('Private file access denied.')
                if image:
                    from management.views import _visible_design_images_qs
                    if not _visible_design_images_qs(request.user, PatternDesignImage.objects.filter(pk=image.pk)).exists():
                        raise PermissionDenied('Private file access denied.')

            from management.models import ComplaintMedia, PatternColorSelection
            from management.services.activity_permissions import granted
            from management.services.workflow import visible_complaints_for_user
            filename = view_kwargs.get('path', '')
            if filename.startswith('private_design_voice_notes/'):
                raise PermissionDenied('Use the authenticated review voice endpoint.')
            if filename.startswith('color_swatches/'):
                if not request.user.is_authenticated or not granted(request.user, 'color.view') or not PatternColorSelection.objects.filter(swatch_image=filename).exists():
                    raise PermissionDenied('Private color access denied.')
            elif filename.startswith('complaint_media/'):
                media = ComplaintMedia.objects.filter(file=filename).first()
                if not request.user.is_authenticated or not granted(request.user, 'complaint.media_view') or not media or not visible_complaints_for_user(request.user).filter(pk=media.complaint_id).exists():
                    raise PermissionDenied('Private complaint media access denied.')
            elif filename.startswith(('pattern_designs/', 'pattern_design_thumbnails/', 'private_design_pdfs/', 'measurement_files/')) and not (image or measurement):
                raise PermissionDenied('Unregistered private file access denied.')
        if request.resolver_match.url_name in ('get_models', 'get_sub_models', 'get_year_ranges', 'get_available_years', 'get_filtered_skus', 'get_complaint_type_options') and not request.user.is_authenticated:
            return JsonResponse({'status': 'error', 'message': 'Authentication required.'}, status=403)
        if request.user.is_authenticated:
            try:
                enforce_request(request)
            except PermissionDenied as exc:
                if request.path.startswith('/api/') or 'application/json' in request.headers.get('Accept', ''):
                    return JsonResponse({'status': 'error', 'success': False, 'message': str(exc)}, status=403)
                raise
        return None
