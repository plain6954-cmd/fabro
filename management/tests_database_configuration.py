"""Database settings tests that never open a PostgreSQL connection."""

import json
import os
import subprocess
import sys

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.test import SimpleTestCase

from fabro_leather.database_config import connection_max_age, connection_mode, database_port


class DatabaseConfigurationTests(SimpleTestCase):
    def settings_process(self, **overrides):
        environment = os.environ.copy()
        environment.update({
            'DJANGO_SETTINGS_MODULE': 'fabro_leather.settings',
            'DEBUG': 'True',
            'DJANGO_SECRET_KEY': 'local-database-configuration-test-key',
            'USE_S3_STORAGE': 'False',
            'CACHE_URL': '',
            'E2E_TESTING': 'False',
            'USE_POSTGRES': 'False',
            'DATABASE_URL': '',
            'DB_CONNECTION_MODE': '',
            'CONN_MAX_AGE': '0',
            'DB_NAME': 'split_database',
            'DB_USER': 'split_user',
            'DB_PASSWORD': 'split-test-password',
            'DB_HOST': 'localhost',
            'DB_PORT': '5432',
        })
        environment.update(overrides)
        script = (
            'import json; from django.conf import settings; '
            'db=settings.DATABASES["default"]; '
            'print(json.dumps({"engine":db["ENGINE"], '
            '"name":str(db["NAME"]), "port":db.get("PORT"), '
            '"mode":settings.DATABASE_CONNECTION_MODE, '
            '"age":db.get("CONN_MAX_AGE"), '
            '"health":db.get("CONN_HEALTH_CHECKS"), '
            '"cursors":db.get("DISABLE_SERVER_SIDE_CURSORS"), '
            '"ssl":db.get("OPTIONS", {}).get("sslmode")}))'
        )
        return subprocess.run(
            [sys.executable, '-c', script],
            cwd=settings.BASE_DIR,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )

    def assert_config(self, expected, **environment):
        process = self.settings_process(**environment)
        self.assertEqual(process.returncode, 0, process.stderr)
        config = json.loads(process.stdout)
        for key, value in expected.items():
            self.assertEqual(config[key], value, key)
        return config

    def test_transaction_pooler_config_and_safe_defaults(self):
        self.assertEqual(connection_max_age(None, 'transaction', 6543), 0)
        config = self.assert_config(
            {'mode': 'transaction', 'port': 6543, 'age': 0,
             'health': True, 'cursors': True, 'ssl': 'require'},
            DATABASE_URL='postgresql://fake:fake@aws-0-eu-west-3.pooler.supabase.com:6543/postgres',
        )
        self.assertEqual(config['engine'], 'django.db.backends.postgresql')

    def test_explicit_transaction_mode_on_isolated_host(self):
        self.assert_config(
            {'mode': 'transaction', 'age': 0, 'port': 6543},
            DATABASE_URL='postgresql://fake:fake@localhost:6543/disposable',
            DB_CONNECTION_MODE='transaction',
        )

    def test_transaction_mode_rejects_persistent_connections_and_wrong_port(self):
        for environment in (
            {'DATABASE_URL': 'postgresql://fake:fake@localhost:6543/disposable',
             'DB_CONNECTION_MODE': 'transaction', 'CONN_MAX_AGE': '60'},
            {'DATABASE_URL': 'postgresql://fake:fake@localhost/disposable',
             'DB_CONNECTION_MODE': 'transaction'},
            {'DATABASE_URL': 'postgresql://fake:fake@aws-0-eu-west-3.pooler.supabase.com:6543/postgres',
             'CONN_MAX_AGE': '60'},
        ):
            with self.subTest(environment=environment):
                self.assertNotEqual(self.settings_process(**environment).returncode, 0)

    def test_ambiguous_6543_does_not_silently_select_a_mode(self):
        self.assert_config(
            {'mode': 'unspecified', 'port': 6543, 'age': 0},
            DATABASE_URL='postgresql://fake:fake@custom.example:6543/disposable',
        )
        self.assert_config(
            {'mode': 'unspecified', 'port': 6543, 'age': 60},
            DATABASE_URL='postgresql://fake:fake@custom.example:6543/disposable',
            CONN_MAX_AGE='60',
        )

    def test_known_supabase_endpoint_rejects_unknown_port(self):
        process = self.settings_process(
            DATABASE_URL='postgresql://fake:fake@aws-0-eu-west-3.pooler.supabase.com:5433/postgres',
        )
        self.assertNotEqual(process.returncode, 0)
        self.assertIn('Known Supabase database endpoints', process.stderr)

    def test_direct_and_session_modes_preserve_explicit_lifetimes(self):
        for mode, host in (
            ('direct', 'db.test.supabase.co'),
            ('session', 'aws-0-eu-west-3.pooler.supabase.com'),
        ):
            with self.subTest(mode=mode):
                self.assert_config(
                    {'mode': mode, 'port': 5432, 'age': 120},
                    DATABASE_URL=f'postgresql://fake:fake@{host}:5432/postgres',
                    CONN_MAX_AGE='120',
                )
        self.assertIsNone(connection_max_age('None', 'direct', 5432))
        with self.assertRaises(ImproperlyConfigured):
            connection_max_age('None', 'transaction', 6543)

    def test_explicit_mode_must_match_known_supabase_endpoint(self):
        process = self.settings_process(
            DATABASE_URL='postgresql://fake:fake@aws-0-eu-west-3.pooler.supabase.com:6543/postgres',
            DB_CONNECTION_MODE='session',
        )
        self.assertNotEqual(process.returncode, 0)
        self.assertIn('conflicts', process.stderr)

    def test_database_url_takes_precedence_over_split_variables(self):
        self.assert_config(
            {'name': 'url_database', 'port': 6543, 'mode': 'transaction'},
            DATABASE_URL='postgresql://url_user:url_password@aws-0-eu-west-3.pooler.supabase.com:6543/url_database',
            DB_NAME='split_database', DB_PORT='5432',
        )
        self.assert_config(
            {'name': 'split_database', 'port': 5432, 'mode': 'direct'},
            USE_POSTGRES='True', DB_CONNECTION_MODE='direct',
        )

    def test_sqlite_and_e2e_sqlite_override(self):
        self.assert_config({'mode': 'sqlite', 'port': None, 'age': None})
        self.assert_config(
            {'mode': 'sqlite', 'port': None, 'age': None},
            E2E_TESTING='True',
            DATABASE_URL='postgresql://fake:fake@localhost:6543/disposable',
            DB_CONNECTION_MODE='transaction',
        )

    def test_invalid_values_and_errors_never_expose_secrets(self):
        secret = 'never-print-this-test-secret'
        for environment in (
            {'DATABASE_URL': f'postgresql://fake:fake@localhost:6543/disposable',
             'CONN_MAX_AGE': secret},
            {'DATABASE_URL': f'postgresql://fake:fake@localhost:{secret}/disposable'},
            {'USE_POSTGRES': 'True', 'DB_PORT': secret},
        ):
            with self.subTest(environment=environment):
                process = self.settings_process(**environment)
                self.assertNotEqual(process.returncode, 0)
                self.assertNotIn(secret, process.stderr)
        with self.assertRaises(ImproperlyConfigured):
            connection_max_age('-1', 'direct', 5432)
        with self.assertRaises(ImproperlyConfigured):
            database_port('0')
        with self.assertRaises(ImproperlyConfigured):
            connection_mode('invalid', 'localhost', 5432)

    def test_diagnostic_command_prints_only_safe_fields(self):
        environment = os.environ.copy()
        environment.update({
            'DEBUG': 'True', 'DJANGO_SECRET_KEY': 'local-diagnostic-test-key',
            'USE_S3_STORAGE': 'False', 'CACHE_URL': '', 'E2E_TESTING': 'False',
            'DATABASE_URL': 'postgresql://secret_user:secret_password@localhost:6543/private_name',
            'DB_CONNECTION_MODE': 'transaction', 'CONN_MAX_AGE': '0',
        })
        process = subprocess.run(
            [sys.executable, 'manage.py', 'show_database_config'],
            cwd=settings.BASE_DIR, env=environment, capture_output=True, text=True, check=False,
        )
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertIn('Connection mode: transaction', process.stdout)
        self.assertIn('DISABLE_SERVER_SIDE_CURSORS: True', process.stdout)
        for secret in ('secret_user', 'secret_password', 'private_name', 'localhost'):
            self.assertNotIn(secret, process.stdout + process.stderr)
