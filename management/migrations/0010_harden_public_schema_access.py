from django.db import migrations


def harden_public_schema_access(apps, schema_editor):
    """Keep Django-owned tables inaccessible through Supabase's public API roles."""
    connection = schema_editor.connection
    if connection.vendor != 'postgresql':
        return

    quote_name = schema_editor.quote_name
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT rolname FROM pg_roles WHERE rolname IN ('anon', 'authenticated')"
        )
        api_roles = [row[0] for row in cursor.fetchall()]

        cursor.execute(
            """
            SELECT c.relname
            FROM pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p')
            """
        )
        table_names = [row[0] for row in cursor.fetchall()]
        for table_name in table_names:
            qualified_table = f'{quote_name("public")}.{quote_name(table_name)}'
            cursor.execute(f'ALTER TABLE {qualified_table} ENABLE ROW LEVEL SECURITY')
            for role in api_roles:
                cursor.execute(
                    f'REVOKE ALL PRIVILEGES ON TABLE {qualified_table} FROM {quote_name(role)}'
                )

        cursor.execute(
            """
            SELECT c.relname
            FROM pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = 'public' AND c.relkind = 'S'
            """
        )
        sequence_names = [row[0] for row in cursor.fetchall()]
        for sequence_name in sequence_names:
            qualified_sequence = f'{quote_name("public")}.{quote_name(sequence_name)}'
            for role in api_roles:
                cursor.execute(
                    f'REVOKE ALL PRIVILEGES ON SEQUENCE {qualified_sequence} FROM {quote_name(role)}'
                )

        for role in api_roles:
            cursor.execute(
                'ALTER DEFAULT PRIVILEGES IN SCHEMA public '
                f'REVOKE ALL PRIVILEGES ON TABLES FROM {quote_name(role)}'
            )
            cursor.execute(
                'ALTER DEFAULT PRIVILEGES IN SCHEMA public '
                f'REVOKE ALL PRIVILEGES ON SEQUENCES FROM {quote_name(role)}'
            )


class Migration(migrations.Migration):

    dependencies = [
        ('admin', '0003_logentry_add_action_flag_choices'),
        ('auth', '0012_alter_user_first_name_max_length'),
        ('authtoken', '0004_alter_tokenproxy_options'),
        ('contenttypes', '0002_remove_content_type_name'),
        ('sessions', '0001_initial'),
        ('management', '0009_userprofile_phone_number'),
    ]

    operations = [
        migrations.RunPython(
            harden_public_schema_access,
            reverse_code=migrations.RunPython.noop,
        ),
    ]
