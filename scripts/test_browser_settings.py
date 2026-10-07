"""Standalone browser test settings with file-based SQLite and media directory."""
import os
from pathlib import Path
from tempfile import gettempdir

BASE_DIR = Path(__file__).resolve().parent.parent
SECRET_KEY = 'offline-synthetic-test-key-not-for-deployment'
DEBUG = True
ALLOWED_HOSTS = ['*']

INSTALLED_APPS = [
    'django.contrib.admin', 'django.contrib.auth', 'django.contrib.contenttypes',
    'django.contrib.sessions', 'django.contrib.messages', 'django.contrib.staticfiles',
    'rest_framework', 'rest_framework.authtoken', 'widget_tweaks',
    'management.apps.ManagementConfig',
]

DB_PATH = os.path.join(gettempdir(), 'fabro_e2e_dual_approval.sqlite3')
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': DB_PATH,
    }
}

MIGRATION_MODULES = {app: None for app in (
    'admin', 'auth', 'contenttypes', 'sessions', 'authtoken', 'management',
)}

CACHES = {'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}}

AUTHENTICATION_BACKENDS = [
    'management.auth_backends.EmailOrUsernameModelBackend',
    'django.contrib.auth.backends.ModelBackend',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.locale.LocaleMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'management.middleware.UserProfileLocaleMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'management.middleware.SecurityHeadersMiddleware',
]

ROOT_URLCONF = 'fabro_leather.urls'

TEMPLATES = [{
    'BACKEND': 'django.template.backends.django.DjangoTemplates',
    'DIRS': [],
    'APP_DIRS': False,
    'OPTIONS': {
        'loaders': [
            'django.template.loaders.filesystem.Loader',
            'django.template.loaders.app_directories.Loader',
        ],
        'context_processors': [
            'django.template.context_processors.request',
            'django.template.context_processors.i18n',
            'django.contrib.auth.context_processors.auth',
            'django.contrib.messages.context_processors.messages',
            'management.context_processors.workflow_access',
        ]
    },
}]

STORAGES = {
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
}

MEDIA_ROOT = os.path.join(gettempdir(), 'fabro_e2e_media')
STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
STATICFILES_DIRS = [BASE_DIR / 'static']
MEDIA_URL = '/media/'
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
PASSWORD_HASHERS = [
    'django.contrib.auth.hashers.PBKDF2PasswordHasher',
    'django.contrib.auth.hashers.PBKDF2SHA1PasswordHasher',
    'django.contrib.auth.hashers.MD5PasswordHasher',
]
USE_S3_STORAGE = USE_SUPABASE_STORAGE = ALLOW_PUBLIC_REGISTRATION = False
TRUST_PROXY_HEADERS = False
CONTENT_SECURITY_POLICY = "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob: https://flagcdn.com; media-src 'self' blob:"
DASHBOARD_CACHE_TTL = 30
BADGE_CACHE_TTL = 15
S3_SIGNED_UPLOAD_TTL_SECONDS = 900
LOGIN_MAX_ATTEMPTS = 8
LOGIN_RATE_WINDOW_SECONDS = 300
LOGIN_LOCKOUT_SECONDS = 900
LOGIN_URL = '/login/'
LOGIN_REDIRECT_URL = '/'
LOGOUT_REDIRECT_URL = '/logout-success/'
LANGUAGE_CODE = 'en'
LANGUAGES = [('en', 'English'), ('ar', 'Arabic'), ('hi', 'Hindi')]
LOCALE_PATHS = [BASE_DIR / 'locale']
LANGUAGE_COOKIE_NAME = 'fabro_language'
TIME_ZONE = 'UTC'
USE_TZ = USE_I18N = True
EMAIL_BACKEND = 'django.core.mail.backends.locmem.EmailBackend'

# Disable web push in test to avoid external network timeouts
VAPID_PUBLIC_KEY = ''
VAPID_PRIVATE_KEY = ''
VAPID_ADMIN_EMAIL = 'test@example.com'
