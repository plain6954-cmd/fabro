from django.conf import settings
from django.utils.cache import patch_vary_headers


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
