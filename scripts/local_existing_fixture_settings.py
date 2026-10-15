"""Opt-in synthetic fixture settings for this worktree's existing SQLite database."""

from pathlib import Path

from scripts.synthetic_perf_settings import *  # noqa: E402,F401,F403


if BASE_DIR.resolve().name != 'fast-navigation-htmx':
    raise RuntimeError('The existing-database fixture is restricted to the feature worktree.')

DATABASES = {'default': {
    'ENGINE': 'django.db.backends.sqlite3',
    'NAME': BASE_DIR / 'db.sqlite3',
}}
MEDIA_ROOT = BASE_DIR / 'output' / 'navigation-local-media'
ROOT_URLCONF = 'scripts.synthetic_perf_urls'
SYNTHETIC_NAV_TARGET = 'existing-local-db'

assert Path(DATABASES['default']['NAME']).resolve() == (BASE_DIR / 'db.sqlite3').resolve()
assert Path(MEDIA_ROOT).resolve().is_relative_to((BASE_DIR / 'output').resolve())
