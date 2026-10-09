"""Disposable browser-test settings; never point at the deployment database."""
import os
from .offline_settings import *  # noqa: F403

DEBUG = True
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': os.environ['FABRO_PUSH_TEST_DB'],
    }
}
WEBPUSH_VAPID_PUBLIC_KEY = os.environ.get('WEBPUSH_VAPID_PUBLIC_KEY', '')
WEBPUSH_VAPID_PRIVATE_KEY = os.environ.get('WEBPUSH_VAPID_PRIVATE_KEY', '')
WEBPUSH_VAPID_SUBJECT = 'mailto:browser-test@example.invalid'
