# FABRO navigation staging and deployment readiness — 15 October 2026

## Decision

**Not yet ready to merge into `main2`.** Commit `c476e8c` passed the local
SQLite/Chrome checks in [the optimization audit](FAST_NAVIGATION_HTMX_2026-10-15.md),
but no isolated PostgreSQL service is available on this host. The user chose
"prepare the harness only." There is therefore no PostgreSQL median/p95
comparison or PostgreSQL browser/workflow result to claim. The original `main2`
working directory retains its unrelated uncommitted changes and was not edited.

## Isolated staging harness

`scripts/staging_nav_benchmark.py` accepts a separate, clean Git worktree and a
PostgreSQL URL only on loopback. It requires a database name beginning with
`fabro_nav_stage_`, rejects worktrees containing `.env` or `.env.production`,
and refuses a database containing any user tables, views, sequences or similar
objects. It does not flush or drop databases. Provide **two fresh, separate**
databases for baseline and feature runs, using a database account scoped only
to these disposable databases. Never supply a production URL or credentials.

`scripts/staging_nav_settings.py` runs `DEBUG=False` with the application's
WhiteNoise `CompressedManifestStaticFilesStorage`, PostgreSQL, the existing
middleware, and the same 250 vehicle / 200 complaint / 50 SKU synthetic fixture
for both revisions. Media and collected assets stay under each worktree's
ignored `output/` directory. S3, real VAPID keys, and shared Redis are disabled
to avoid external writes and delivery. The loopback HTTP server requires local
exceptions for HTTPS redirect, secure cookies, and HSTS; **those exceptions are
in the test settings module only**. This is production-equivalent for static
asset build and delivery, not a complete Scaleway replica.

The browser profiler runs 10 fresh-context cold navigations per route and 10
warm Pattern Master/Complaints cycles with Dashboard returns. It records TTFB,
DOMContentLoaded, LCP, usable time, SQL count/duration, script and long-task
time, DOM size, HTTP/JavaScript failures, document reloads, and back/forward.
It also checks that full and HTMX requests have matching status codes for 11
roles. `scripts/compare_staging_nav.py` prints median/p95 and rejects captures
with mismatched fixtures, reused databases, missing history, or browser errors.

### Run when isolated local PostgreSQL is available

Run the commands from the feature worktree. Inject URLs through a local secret
manager or inherited environment; do not type passwords into shell history or
commit them. The baseline worktree must still point at `a9679d9`, and the
feature worktree at the reviewed feature commit.

```powershell
$navPython = 'C:\Users\POWER-13\Documents\FABRO\Fabro-Leather-Portal\env\Scripts\python.exe'
& $navPython scripts/staging_nav_benchmark.py --checkout ..\fast-navigation-baseline --label before --assets-only
& $navPython scripts/staging_nav_benchmark.py --checkout . --label after --assets-only

# Set this environment variable from a secret manager to the fresh baseline DB.
$env:FABRO_NAV_STAGING_DATABASE_URL = $env:FABRO_NAV_STAGING_BEFORE_URL
& $navPython scripts/staging_nav_benchmark.py --checkout ..\fast-navigation-baseline --label before --preflight-only
& $navPython scripts/staging_nav_benchmark.py --checkout ..\fast-navigation-baseline --label before

# Use a second fresh DB with the same PostgreSQL version and settings.
$env:FABRO_NAV_STAGING_DATABASE_URL = $env:FABRO_NAV_STAGING_AFTER_URL
& $navPython scripts/staging_nav_benchmark.py --checkout . --label after --preflight-only
& $navPython scripts/staging_nav_benchmark.py --checkout . --label after

& $navPython scripts/compare_staging_nav.py output/staging-navigation-before.json output/staging-navigation-after.json
Remove-Item Env:FABRO_NAV_STAGING_DATABASE_URL
```

The two captures must use identical host, PostgreSQL configuration, Chrome
version, viewport, fixture, and run order without competing load. Record
PostgreSQL server version, connection latency, and host resources alongside
the result. Run the comparison more than once if local host load causes a wide
p95 spread. Report the raw files and median/p95; do not substitute the earlier
SQLite numbers for staging results.

### PostgreSQL feature preservation gate

After the matched benchmark, use a **third fresh local**
`fabro_nav_stage_validation` database with a restricted account. Run the
preflight before tests. Django creates and removes its own `test_...` database,
so the account needs local `CREATEDB` permission. Test Web Push delivery is
mocked; it never sends to external subscriptions. The browser audit uses
authorized synthetic users and local file uploads.

```powershell
$env:FABRO_NAV_STAGING_DATABASE_URL = $env:FABRO_NAV_STAGING_VALIDATION_URL
& $navPython scripts/staging_nav_benchmark.py --checkout . --label after --preflight-only
$env:PYTHONPATH = (Resolve-Path scripts).Path
$env:DJANGO_SETTINGS_MODULE = 'staging_nav_settings'
& $navPython manage.py test management.tests_browser_audit management.tests_web_push management.tests_design_approvals management.tests_performance --noinput
Remove-Item Env:FABRO_NAV_STAGING_DATABASE_URL
Remove-Item Env:DJANGO_SETTINGS_MODULE
Remove-Item Env:PYTHONPATH
```

This validation covers role routes, mobile/tablet/desktop layouts, history and
page lifecycle through the profiler, designer uploads, CAD/ED decisions,
complaint approval permissions, and mocked notification/Web Push behavior.
Run the complete `management` suite as the final PostgreSQL gate if the
focused suite passes. Existing Playwright tests use `globalSetup` that calls
`flush`; do not point that suite at any database containing wanted data.

## Work completed without PostgreSQL

- Verified `c476e8c` on `feature/fast-navigation-htmx` and base `a9679d9`.
- Inspected the full navigation audit and original `main2` status.
- Built collected assets for both baseline and feature with `DEBUG=False` and
  WhiteNoise's compressed manifest storage. The pinned HTMX asset, page
  lifecycle JS, and dashboard CSS resolved to hashed URLs and were served
  with HTTP 200, `gzip`, and `Cache-Control: max-age=315360000, public, immutable`.
- No PostgreSQL command-line tools, Docker command, or WSL installation was
  available. Service enumeration was restricted, and no isolated PostgreSQL
  endpoint was supplied. No staging or production database was contacted.

## Merge gate and remaining risks

Merge readiness requires: passing PostgreSQL browser/workflow/Web Push tests;
zero unexpected HTTP or JavaScript failures; equal role access for full and
partial responses; one request per supported navigation; correct back/forward;
and a measured median/p95 comparison without material regressions. Check the
result against `c476e8c` and resolve any staging-specific failure on the
feature branch before requesting a merge. In addition, the unrelated dirty
`main2` designer workspace changes need review and integration planning; they
were not included in this feature branch.

## Deployment and rollback after approval

1. Review both feature and pre-existing `main2` changes, then merge only after
   the PostgreSQL gate passes. No schema migration is added by this feature.
2. Build assets with the existing Docker/WhiteNoise pipeline and verify the
   hashed HTMX, lifecycle JS, and CSS URLs in staging over HTTPS. Run the
   complete Django and browser suites, including real-role smoke checks.
3. Deploy through the existing Scaleway process only after separate approval.
   Watch server timing, SQL counts, 4xx/5xx, browser errors, and Web Push.
4. If navigation regresses, revert the feature merge or redeploy the preceding
   `main2` revision, then rebuild static assets. Existing ordinary link
   navigation remains the fallback when HTMX is unavailable.

No merge, push, deployment, production data change, or infrastructure change
was performed.

NOTIFICATION IMPACT: None
