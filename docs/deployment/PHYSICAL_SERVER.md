# Physical-server deployment and performance notes

All values in angle brackets are placeholders. Keep the environment file outside Git and readable only by the service account. Garage/S3 credentials, Django's secret key, database credentials, and Redis credentials must never be committed.

## Environment

Use the Supabase **Transaction Pooler** for the current FABRO deployment. Copy its connection string from the Supabase dashboard into `DATABASE_URL`; it must specify port `6543`. Keep the existing username and credentials. Set `DB_CONNECTION_MODE=transaction` and `CONN_MAX_AGE=0` in the service environment. Django always sets `CONN_HEALTH_CHECKS=True`, `DISABLE_SERVER_SIDE_CURSORS=True`, and PostgreSQL `sslmode=require`. The current Gunicorn configuration has four workers with two threads each; monitor active connections and transaction latency as usage grows. Do not increase concurrency merely to hide pooler errors.

`DB_CONNECTION_MODE` is optional for backward compatibility. When absent, FABRO recognizes a Supabase shared or dedicated pooler from its known endpoint **and** port; unknown hosts are reported as `unspecified`. PostgreSQL defaults to `CONN_MAX_AGE=0`. An explicit `transaction` mode requires port `6543` and age `0`; a conflicting known Supabase endpoint or unsupported port is rejected before serving requests. Unknown hosts on port `6543` retain explicitly configured lifetimes because they may be legitimate non-Supabase connections; the diagnostic reports `unspecified` until their mode is declared. Direct or session connections can still use a deliberately configured positive age. SQLite and isolated E2E SQLite do not use these PostgreSQL settings. `DATABASE_URL` takes precedence over the split `DB_*` variables.

Example with placeholders only:

```text
DATABASE_URL=postgresql://<USER>:<PASSWORD>@<SUPABASE_TRANSACTION_POOLER_HOST>:6543/<DATABASE>
DB_CONNECTION_MODE=transaction
CONN_MAX_AGE=0
```

Run `python manage.py show_database_config` with the intended service environment to print only the backend, mode, port, age, cursor and health settings, and SSL mode. This command does not connect to the database and never prints the host, database name, user, password, or full URL. Run `python manage.py check --deploy` separately. Verify on Scaleway that the effective URL really uses the selected Supabase Transaction Pooler endpoint and port `6543`, its credentials remain unchanged, `CONN_MAX_AGE=0`, and no process or environment override conflicts with `DB_CONNECTION_MODE`. This local repository cannot establish the effective live environment from source alone.

Set `CACHE_URL=redis://<REDIS_HOST>:<PORT>/<DB>` to enable shared caching. Optional tuning variables are `CACHE_KEY_PREFIX`, `CACHE_DEFAULT_TIMEOUT`, `BADGE_CACHE_TTL`, `DASHBOARD_CACHE_TTL`, `CATALOG_CACHE_TTL`, `PERFORMANCE_TIMING_ENABLED`, `SQL_QUERY_COUNT_ENABLED`, and `SLOW_REQUEST_THRESHOLD_MS`. Leave `CACHE_URL` empty for the local in-memory fallback; tests do not require Redis. Keep SQL query-count logging disabled in production unless diagnosing a bounded incident; it records counts only, never query parameters.

## Safe update checklist

1. Back up application state and confirm the release commit.
2. Create/update the virtual environment and run `pip install -r requirements.txt`.
3. Run `python manage.py check --deploy` with the production environment loaded.
4. Review migration files without opening a production connection. Use a direct PostgreSQL connection for `pg_dump`, backups, and migration operations as recommended by Supabase; prepare any maintenance connection separately from the request-serving transaction pooler. Confirm the direct endpoint is reachable and approved before use.
5. Run migrations only during an approved maintenance window against the intended database after a verified backup. This database configuration change itself needs no migration.
6. Run `python manage.py collectstatic --noinput`.
7. Run the relevant Django tests against a non-production test database.
8. Validate Nginx with `nginx -t`, then perform a graceful Gunicorn reload and Nginx reload.
9. Check `/health/`, login, a role-scoped complaint list, uploads, and a signed download.

Never run tests against the production database. Never expose Garage directly as a public media directory; the browser uploads with signed URLs and Django authorizes signed downloads.

If a new release fails configuration validation, first compare the effective non-secret diagnostics with the approved deployment values. Correct a mistaken mode, port, or `CONN_MAX_AGE` in the service environment and restart through the normal deployment procedure. If code rollback is required, restore the previously verified application image/commit and its environment file; no database schema or data rollback is required for this settings-only change. Do not switch back to the exhausted Session Pooler as an automatic rollback.

## Database latency and plans

Measure geographic latency from the physical application server with a credential-free TCP/TLS timing tool and compare direct and pooler endpoints configured in Supabase. Measure an application query with Django shell using aggregate timing only; do not log SQL parameters. Keep the app server and Supabase region close where operationally possible.

On production-like data, run `EXPLAIN (ANALYZE, BUFFERS, FORMAT TEXT)` only for a read-only `SELECT`, inside `BEGIN READ ONLY; ...; ROLLBACK;`. Remove or replace literal private values before sharing output. Compare plans before and after `0027_performance_indexes`; do not add `pg_trgm` until the extension is verified and representative `icontains` plans prove it is needed.

Database connection references: [Supabase connection modes and endpoint ports](https://supabase.com/docs/guides/database/connecting-to-postgres) and [Django 5.2 transaction pooling and server-side cursors](https://docs.djangoproject.com/en/5.2/ref/databases/#transaction-pooling-and-server-side-cursors).
