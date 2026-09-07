# Physical-server deployment and performance notes

All values in angle brackets are placeholders. Keep the environment file outside Git and readable only by the service account. Garage/S3 credentials, Django's secret key, database credentials, and Redis credentials must never be committed.

## Environment

Set `DATABASE_URL` (or the existing split DB variables), retain `sslmode=require`, and set `CONN_MAX_AGE` initially between 60 and 300 seconds. Django enables `CONN_HEALTH_CHECKS`. A Supabase pooler hostname commonly contains `pooler`, but verify the connection mode in the Supabase dashboard without printing the URL or credentials. Size Gunicorn workers and database connections together so their maximum is below the pooler's limit.

Set `CACHE_URL=redis://<REDIS_HOST>:<PORT>/<DB>` to enable shared caching. Optional tuning variables are `CACHE_KEY_PREFIX`, `CACHE_DEFAULT_TIMEOUT`, `BADGE_CACHE_TTL`, `DASHBOARD_CACHE_TTL`, `CATALOG_CACHE_TTL`, `PERFORMANCE_TIMING_ENABLED`, and `SLOW_REQUEST_THRESHOLD_MS`. Leave `CACHE_URL` empty for the local in-memory fallback; tests do not require Redis.

## Safe update checklist

1. Back up application state and confirm the release commit.
2. Create/update the virtual environment and run `pip install -r requirements.txt`.
3. Run `python manage.py check --deploy` with the production environment loaded.
4. Review migrations with `python manage.py showmigrations` and `python manage.py sqlmigrate management 0027`.
5. Run `python manage.py migrate` during the approved maintenance window.
6. Run `python manage.py collectstatic --noinput`.
7. Run the relevant Django tests against a non-production test database.
8. Validate Nginx with `nginx -t`, then perform a graceful Gunicorn reload and Nginx reload.
9. Check `/health/`, login, a role-scoped complaint list, uploads, and a signed download.

Never run tests against the production database. Never expose Garage directly as a public media directory; the browser uploads with signed URLs and Django authorizes signed downloads.

## Database latency and plans

Measure geographic latency from the physical application server with a credential-free TCP/TLS timing tool and compare direct and pooler endpoints configured in Supabase. Measure an application query with Django shell using aggregate timing only; do not log SQL parameters. Keep the app server and Supabase region close where operationally possible.

On production-like data, run `EXPLAIN (ANALYZE, BUFFERS, FORMAT TEXT)` only for a read-only `SELECT`, inside `BEGIN READ ONLY; ...; ROLLBACK;`. Remove or replace literal private values before sharing output. Compare plans before and after `0027_performance_indexes`; do not add `pg_trgm` until the extension is verified and representative `icontains` plans prove it is needed.
