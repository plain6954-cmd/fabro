"""Standalone verification settings. Never import deployment settings or .env."""
from pathlib import Path
from tempfile import TemporaryDirectory

BASE_DIR = Path(__file__).resolve().parent.parent
_temporary_files = TemporaryDirectory(prefix='fabro-offline-')
SECRET_KEY = 'offline-synthetic-test-key-not-for-deployment'
DEBUG = False
ALLOWED_HOSTS = ['testserver', 'localhost', '127.0.0.1']
INSTALLED_APPS = [
    'django.contrib.admin', 'django.contrib.auth', 'django.contrib.contenttypes',
    'django.contrib.sessions', 'django.contrib.messages', 'django.contrib.staticfiles',
    'rest_framework', 'rest_framework.authtoken', 'widget_tweaks',
    'management.apps.ManagementConfig',
]
DATABASES = {'default': {
    'ENGINE': 'django.db.backends.sqlite3', 'NAME': ':memory:',
    'TEST': {'NAME': ':memory:'},
}}
# Build disposable model tables only; never execute project migrations.
MIGRATION_MODULES = {app: None for app in (
    'admin', 'auth', 'contenttypes', 'sessions', 'authtoken', 'management',
)}
CACHES = {'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}}
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
    'DIRS': [], 'APP_DIRS': False,
    'OPTIONS': {'loaders': [
        'django.template.loaders.filesystem.Loader',
        'django.template.loaders.app_directories.Loader',
    ], 'context_processors': [
        'django.template.context_processors.request',
        'django.template.context_processors.i18n',
        'django.contrib.auth.context_processors.auth',
        'django.contrib.messages.context_processors.messages',
        'management.context_processors.workflow_access',
    ]},
}]
STORAGES = {
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
}
MEDIA_ROOT = Path(_temporary_files.name) / 'media'
MEDIA_URL = '/media/'
STATIC_ROOT = Path(_temporary_files.name) / 'static'
STATIC_URL = '/static/'
STATICFILES_DIRS = [BASE_DIR / 'static']
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
PASSWORD_HASHERS = ['django.contrib.auth.hashers.MD5PasswordHasher']
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
]
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'rest_framework.authentication.TokenAuthentication',
        'rest_framework.authentication.SessionAuthentication',
    ],
    'DEFAULT_PERMISSION_CLASSES': ['rest_framework.permissions.IsAuthenticated'],
    'DEFAULT_PAGINATION_CLASS': 'management.pagination.FabroPageNumberPagination',
    'PAGE_SIZE': 25,
    'DEFAULT_THROTTLE_RATES': {'login': '20/min'},
}
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
