from django.conf import settings
from django.utils.cache import patch_vary_headers
from django.utils import translation


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
            language = getattr(profile, 'preferred_language', 'en') or 'en'
            if language not in self.supported_languages:
                language = 'en'
            translation.activate(language)
            request.LANGUAGE_CODE = language
        response = self.get_response(request)
        patch_vary_headers(response, ('Cookie',))
        return response
