"""Local-only synthetic media delivery for browser performance testing."""

from django.conf import settings
from django.urls import re_path
from django.views.static import serve

from fabro_leather.urls import urlpatterns as fabro_urls


urlpatterns = list(fabro_urls) + [
    re_path(r'^media/(?P<path>.*)$', serve,
            {'document_root': settings.MEDIA_ROOT}, name='synthetic_media'),
]
