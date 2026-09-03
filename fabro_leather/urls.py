from django.contrib import admin
from django.urls import path, include
from django.views.i18n import JavaScriptCatalog
from django.conf import settings
from django.conf.urls.static import static
from .health import health_check

urlpatterns = [
    path('health/', health_check, name='health_check'),
    path('jsi18n/', JavaScriptCatalog.as_view(), name='javascript-catalog'),
    path('admin/', admin.site.urls),
    path('', include('management.urls')),
]

# Serve local media and static files in development.
if settings.DEBUG:
    if not settings.USE_SUPABASE_STORAGE:
        urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    # Serve from the collected staticfiles folder
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
    # Also serve directly from STATICFILES_DIRS so new files don't need collectstatic
    for static_dir in settings.STATICFILES_DIRS:
        urlpatterns += static(settings.STATIC_URL, document_root=static_dir)
