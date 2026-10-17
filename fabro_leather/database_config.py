"""Validate PostgreSQL connection settings without opening a connection."""

from django.core.exceptions import ImproperlyConfigured


def database_port(value):
    try:
        port = int(value)
    except (TypeError, ValueError):
        raise ImproperlyConfigured('PostgreSQL port must be an integer from 1 to 65535.') from None
    if not 1 <= port <= 65535:
        raise ImproperlyConfigured('PostgreSQL port must be an integer from 1 to 65535.')
    return port


def connection_mode(configured_mode, host, port):
    """Recognize only known Supabase endpoints; otherwise keep the mode explicit."""
    configured_mode = (configured_mode or '').strip().lower()
    if configured_mode and configured_mode not in {'transaction', 'session', 'direct'}:
        raise ImproperlyConfigured('DB_CONNECTION_MODE must be transaction, session, or direct.')

    host = (host or '').lower().rstrip('.')
    shared_pooler = host.endswith('.pooler.supabase.com')
    supabase_database = host.startswith('db.') and host.endswith('.supabase.co')
    recognized_mode = None
    if shared_pooler:
        recognized_mode = {6543: 'transaction', 5432: 'session'}.get(port)
    elif supabase_database:
        recognized_mode = {6543: 'transaction', 5432: 'direct'}.get(port)
    if (shared_pooler or supabase_database) and not recognized_mode:
        raise ImproperlyConfigured('Known Supabase database endpoints require port 5432 or 6543.')

    if configured_mode and recognized_mode and configured_mode != recognized_mode:
        raise ImproperlyConfigured('DB_CONNECTION_MODE conflicts with the Supabase endpoint and port.')
    if configured_mode == 'transaction' and port != 6543:
        raise ImproperlyConfigured('Transaction mode requires an explicit PostgreSQL port 6543.')
    return configured_mode or recognized_mode or 'unspecified'


def connection_max_age(configured_age, mode, port):
    """A zero default is safe for transaction pooling and all other modes."""
    if configured_age is None:
        age = 0
    elif configured_age.strip().lower() == 'none':
        age = None
    else:
        try:
            age = int(configured_age)
        except (TypeError, ValueError):
            raise ImproperlyConfigured('CONN_MAX_AGE must be a nonnegative integer or None.') from None
        if age < 0:
            raise ImproperlyConfigured('CONN_MAX_AGE must be a nonnegative integer or None.')

    if mode == 'transaction' and age != 0:
        raise ImproperlyConfigured('Transaction mode requires CONN_MAX_AGE=0.')
    return age
