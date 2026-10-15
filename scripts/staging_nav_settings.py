"""Isolated navigation benchmark settings; never use for deployment."""

import os
from urllib.parse import unquote, urlparse


database_url = os.environ.get('FABRO_NAV_STAGING_DATABASE_URL', '')
parsed = urlparse(database_url)
database_name = unquote(parsed.path.lstrip('/'))
if (
    parsed.scheme not in {'postgres', 'postgresql'}
    or parsed.hostname not in {'127.0.0.1', 'localhost', '::1'}
    or not database_name.startswith('fabro_nav_stage_')
    or not parsed.username
    or not parsed.password
):
    raise RuntimeError(
        'Use a loopback PostgreSQL URL for a disposable database named '
        'fabro_nav_stage_*. Production and remote databases are forbidden.'
    )

# Set these before importing the real settings, which reads environment values.
os.environ['DATABASE_URL'] = database_url
os.environ['E2E_TESTING'] = 'False'  # E2E_TESTING forces SQLite in FABRO.
os.environ['DEBUG'] = 'False'
os.environ['DJANGO_SECRET_KEY'] = 'fabro-staging-navigation-disposable-local-key-2026-only-0001'
os.environ['USE_S3_STORAGE'] = 'False'
os.environ['CACHE_URL'] = ''
os.environ['ALLOWED_HOSTS'] = '127.0.0.1,localhost,testserver'
os.environ['PERFORMANCE_TIMING_ENABLED'] = 'True'
os.environ['SQL_QUERY_COUNT_ENABLED'] = 'True'
os.environ['WEBPUSH_VAPID_PUBLIC_KEY'] = ''
os.environ['WEBPUSH_VAPID_PRIVATE_KEY'] = ''

from fabro_leather.settings import *  # noqa: E402,F401,F403

# WhiteNoise and CompressedManifestStaticFilesStorage remain production-like.
# Output and uploads stay inside the ignored worktree output directory.
STATIC_ROOT = BASE_DIR / 'output' / 'staging-nav-staticfiles'
MEDIA_ROOT = BASE_DIR / 'output' / 'staging-nav-media'

# The benchmark runs on HTTP loopback without a TLS proxy. This exception is
# limited to this settings module and does not alter production security.
SECURE_SSL_REDIRECT = False
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False
SECURE_HSTS_SECONDS = 0
SECURE_HSTS_INCLUDE_SUBDOMAINS = False
SECURE_HSTS_PRELOAD = False
DATABASES['default']['OPTIONS']['sslmode'] = 'prefer'

assert not DEBUG
assert DATABASES['default']['ENGINE'] == 'django.db.backends.postgresql'
assert STORAGES['staticfiles']['BACKEND'] == 'whitenoise.storage.CompressedManifestStaticFilesStorage'
assert not USE_S3_STORAGE
