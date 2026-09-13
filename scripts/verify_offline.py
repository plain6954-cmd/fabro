"""Run regression checks without accessing configured databases or services."""
import os
from pathlib import Path
import socket
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ['DJANGO_SETTINGS_MODULE'] = 'offline_settings'

# Fail closed even if an unmocked integration slips into a test.
_connect = socket.socket.connect


def local_connect(sock, address):
    if not isinstance(address, tuple) or address[0] not in ('127.0.0.1', '::1', 'localhost'):
        raise RuntimeError('External connections are disabled during offline verification.')
    return _connect(sock, address)


socket.socket.connect = local_connect

import django
django.setup()

from django.test.runner import DiscoverRunner

if __name__ == '__main__':
    runner = DiscoverRunner(verbosity=1, interactive=False)
    failures = runner.run_tests(sys.argv[1:] or ['management'])
    sys.exit(bool(failures))
