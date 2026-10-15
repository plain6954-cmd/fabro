"""Disposable SQLite navigation fixture settings for isolated Git worktrees."""

import os
import secrets
from pathlib import Path


def allowed_worktree(path):
    return (path.name in {'fast-navigation-htmx', 'fast-navigation-baseline'}
            and path.parent.name == 'output'
            and (path / '.git').is_file()
            and not (path / '.env').exists()
            and not (path / '.env.production').exists())


# The runner puts the chosen checkout first on sys.path. Its settings module
# must never import a production .env or inherit a remote DATABASE_URL.
checkout = Path.cwd().resolve()
if not allowed_worktree(checkout):
    raise RuntimeError('Synthetic settings require an approved, .env-free FABRO worktree.')

key_path = checkout / 'output' / 'navigation-synthetic-signing-key.txt'
key_path.parent.mkdir(parents=True, exist_ok=True)
if key_path.exists() and not key_path.resolve().is_relative_to((checkout / 'output').resolve()):
    raise RuntimeError('Local signing key path escapes the disposable worktree.')
if not key_path.exists():
    descriptor = os.open(key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, 'w', encoding='utf8') as output:
        output.write(secrets.token_urlsafe(64))
    os.chmod(key_path, 0o600)
signing_key = key_path.read_text(encoding='utf8').strip()
if len(signing_key) < 50:
    raise RuntimeError('Invalid local synthetic signing key.')

os.environ['DATABASE_URL'] = ''
os.environ['USE_POSTGRES'] = 'False'
os.environ['E2E_TESTING'] = 'False'
os.environ['VERCEL'] = ''
os.environ['DEBUG'] = 'False'
os.environ['DJANGO_SECRET_KEY'] = signing_key
os.environ['USE_S3_STORAGE'] = 'False'
os.environ['CACHE_URL'] = ''
os.environ['ALLOWED_HOSTS'] = '127.0.0.1,localhost,testserver'
os.environ['WEBPUSH_VAPID_PUBLIC_KEY'] = ''
os.environ['WEBPUSH_VAPID_PRIVATE_KEY'] = ''
os.environ['PERFORMANCE_TIMING_ENABLED'] = 'True'
os.environ['SQL_QUERY_COUNT_ENABLED'] = 'True'

from fabro_leather.settings import *  # noqa: E402,F401,F403

DATABASES = {'default': {
    'ENGINE': 'django.db.backends.sqlite3',
    'NAME': BASE_DIR / 'output' / 'navigation-synthetic.sqlite3',
}}
STATIC_ROOT = BASE_DIR / 'output' / 'navigation-synthetic-static'
MEDIA_ROOT = BASE_DIR / 'output' / 'navigation-synthetic-media'
ROOT_URLCONF = 'synthetic_perf_urls'
SECURE_SSL_REDIRECT = False
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False
SECURE_HSTS_SECONDS = 0
SECURE_HSTS_INCLUDE_SUBDOMAINS = False
SECURE_HSTS_PRELOAD = False
SYNTHETIC_NAV_DB = True

assert not DEBUG
assert DATABASES['default']['ENGINE'] == 'django.db.backends.sqlite3'
assert Path(DATABASES['default']['NAME']).resolve().is_relative_to(BASE_DIR / 'output')
assert STORAGES['staticfiles']['BACKEND'] == 'whitenoise.storage.CompressedManifestStaticFilesStorage'
