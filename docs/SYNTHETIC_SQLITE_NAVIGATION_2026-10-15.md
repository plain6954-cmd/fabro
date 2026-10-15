# FABRO synthetic SQLite navigation validation — 15 October 2026

## Decision

The **local synthetic SQLite gate passed** for the feature worktree. The
optimization is **not yet ready to merge into `main2` for production**: the
separate PostgreSQL staging gate in
[`STAGING_NAVIGATION_READINESS_2026-10-15.md`](STAGING_NAVIGATION_READINESS_2026-10-15.md)
has not run. This work did not merge, push, deploy, access production data, or
modify the original `main2` checkout. The feature revision measured here was
`845278c` (parent `c476e8c`); baseline was detached `a9679d9`.

## Isolation and setup

- `scripts/synthetic_perf_settings.py` accepts only the two separate Git
  worktrees named `fast-navigation-htmx` and `fast-navigation-baseline` under
  `output`, rejects local `.env` files, clears remote database/S3/cache/push
  settings, and pins SQLite to each worktree's own ignored
  `output/navigation-synthetic.sqlite3`. The seeder checks the live Django
  connection, media root, storage mode, checkout path, and a synthetic-only
  settings marker before writing. A call against the ordinary `.e2e.sqlite3`
  settings was refused as intended. It also refuses unrelated users, vehicle,
  SKU, complaint, design, or master-setting records in a database copied into
  the expected file path.
- Existing feature-worktree `.e2e.sqlite3` and `db.sqlite3` were backed up
  **before** fixture work via SQLite's online backup API to ignored files in
  `output/sqlite-preseed-backups/`. Both backups passed `integrity_check`.
  Those original databases were not used for the synthetic fixture.
- Migrations through `management.0041` were applied only to the two new
  synthetic SQLite files. No pending migrations remained. `PRAGMA
  integrity_check` passed after fixture generation and session resets.
- The two fixture databases were reset to zero benchmark login sessions and
  compacted before each paired capture. Both started at **1,658,880 bytes**
  (405 pages) with identical counts in every table. The generated media
  fixture had **460 files, 1,755,690 bytes**, with identical SHA-256 content
  fingerprints across worktrees. A prior browser test left extra unreferenced
  synthetic test uploads under the feature media root; the comparison checks
  only the 460 generated fixture files.
- Credentials are independent random passwords per account, stored in each
  worktree's ignored `output/navigation-synthetic-credentials.json`. Passwords
  and the Django signing key are generated locally, never committed or printed.
  The signing key is kept in an ignored file in each worktree. The seeder
  refuses to silently regenerate
  credentials if existing fixture users remain but the credential file is
  missing. All media are generated placeholders; no customer records or
  production media were copied.

## Fixture volumes and coverage

| Entity | Count |
| --- | ---: |
| Users (admin, two country executives, factory executive, registrar, viewer, two designers, PM/OM/CAD/ED/MD) | 13 |
| Brands / models / variants | 6 / 24 / 48 |
| Pattern Master vehicle records | 300 |
| SKU catalogue records | 150 |
| Complaints | 400 |
| Design folders / images / approval cycles | 180 / 180 / 216 |
| Complaint approval tickets | 1,687 |
| Complaint attachments | 100 |

Complaints span all 13 current workflow status values and all four complaint
types. Design cycles include pending, partial, approved, declined, and revised
submissions. Country and reviewer identities use existing role/profile fields.
The seed command uses stable synthetic keys and can run repeatedly without
duplicating fixture rows; both worktrees retained the counts above after
repeat runs. SQLite foreign-key checks passed.

**Inventory gap:** The checked Django models and migrations contain `SKU` as a
catalogue entity but no Stock or Inventory model, quantity field, or stock
table. The 150 SKUs exercise catalogue/navigation load; they cannot represent
stock balance operations without inventing new schema or business behavior.

## Browser and server measurement

Chrome 155.0.8059.79, headless, 1440 × 900, reduced motion, local loopback
Django, `DEBUG=False`, WhiteNoise compressed manifest storage. Hashed HTMX,
page lifecycle JS, and dashboard CSS were served with HTTP 200, gzip, and
immutable caching. Each pair used 10 fresh-context cold visits per route and
10 warm visits each to Pattern Master and Complaints, returning through
Dashboard after each visit (20 warm Dashboard samples). The two pairs began
from identical compacted fixture files and were run sequentially. Warm usable
time is click to route/swap completion plus two animation frames. p95 uses the
nearest-rank sample. Browser cache is cold per fresh context; the server
process and OS file cache may be warm after the first request.

### Combined two-pair result

| Route | Cold DCL before → after, median / p95 ms | Warm usable before → after, median / p95 ms | Server before → after, median / p95 ms |
| --- | --- | --- | --- |
| Dashboard | 332 / 418 → 352 / 536 | 451 / 948 → 316 / 482 | 24 / 71 → 28 / 78 |
| Pattern Master | 801 / 1,089 → 642 / 838 | 955 / 1,772 → 440 / 676 | 132 / 205 → 70 / 149 |
| Complaints | 741 / 1,321 → 562 / 833 | 736 / 1,487 → 461 / 616 | 137 / 172 → 128 / 152 |

The combined warm set has 40 Dashboard samples and 20 samples for each other
route on each revision. Cold and server sets have 20 per route/revision.
Pattern Master and Complaints show reduced server rendering and browser script
work. SQL query counts were unchanged at medians of 7 for Pattern Master and
16 for Complaints in the first pair; the optimization primarily reduces
rendered volume and client work. Dashboard warm navigation improved, while
Dashboard cold DCL and server medians were slightly higher in the combined
set. No claim of uniform improvement is made.

The host showed substantial run-to-run variation. In pair 1, Complaints warm
p95 was **749 ms before / 870 ms after** because one feature sample had
408 ms TTFB; medians were 511 / 419 ms. In pair 2, warm p95 was
**1,577 / 616 ms** and medians were 1,184 / 490 ms. The combined table is
useful for direction, but this local host is not a controlled load generator
and cannot predict Scaleway/PostgreSQL p95. Raw captures and both pair
comparisons remain in the ignored `output/synthetic-navigation-*.json` files.

## Functional and security validation

- All 13 generated accounts logged in through real Chrome. Full and HTMX
  responses had matching authorization outcomes across Dashboard, Pattern
  Master, Complaints, Approvals, and Design Approvals. Factory Viewer was
  denied Approvals; designer access stayed within its existing scope.
- Both revisions completed the corrected six-step Back/Forward sequence after
  repeated navigation, with one HTMX destination response per click, no
  additional document loads, and working Pattern Master row selection/drawer
  after history restoration. An earlier history assertion failed because the
  harness omitted an intervening Dashboard history entry; no application
  history fix was required.
- The populated feature fixture passed a separate read-only Chrome smoke:
  Pattern search/selection, complaint search and detail modal, Closed status
  filter, 390 px mobile filter drawer, Approvals workspace, Design Options,
  and generated JPEG delivery. It recorded zero page errors and failed/4xx/5xx
  requests.
- **60/60 Django tests passed** with Chrome E2E static serving, including
  designer image upload/retry, independent CAD/ED decisions, role routes,
  viewports 320–2560 px (including 360, 390, 768, 1024, 1920), and mocked
  Web Push failure and recipient cases. A trial run of this older
  `StaticLiveServerTestCase` suite under manifest/`DEBUG=False` had five
  setup-related failures because its static handler did not load
  `fabro-page.js`; the production-like loopback runserver profile loaded the
  hashed asset correctly and had no console failures. These are distinct
  static-serving test modes, not a production asset fix.
- Synthetic settings disable external Web Push delivery. The existing mocked
  tests verify the push path; no real subscription or notification was sent.

## Reproduce safely

Run these from the **feature worktree** with the existing local virtual
environment. The baseline worktree must remain detached at `a9679d9`.
Generated databases, credentials, media, static files, and captures are all
ignored by Git.

```powershell
$navPython = 'C:\Users\POWER-13\Documents\FABRO\Fabro-Leather-Portal\env\Scripts\python.exe'
$env:PYTHONPATH = (Resolve-Path scripts).Path
$env:DJANGO_SETTINGS_MODULE = 'synthetic_perf_settings'
& $navPython manage.py migrate --noinput
& $navPython manage.py seed_navigation_synthetic
& $navPython scripts/verify_synthetic_pair.py
& $navPython scripts/reset_synthetic_sessions.py
& $navPython scripts/synthetic_nav_profile.py --checkout . --label after
& $navPython scripts/compare_synthetic_nav.py
& $navPython scripts/synthetic_browser_smoke.py
Remove-Item Env:DJANGO_SETTINGS_MODULE
Remove-Item Env:PYTHONPATH
```

For a fresh baseline fixture, run the same `migrate` with `PYTHONPATH` set to
the feature `scripts` directory and `DJANGO_SETTINGS_MODULE` set to
`synthetic_perf_settings`, then run the feature's
`scripts/run_synthetic_seed.py --checkout .` from the baseline worktree.
Never point these commands at an existing customer, production, or original
`main2` database. The seeder's isolation guard is mandatory, not a substitute
for checking the current directory before running commands. The reset script
deletes **only** `django_session` rows in the two named synthetic databases.

## Remaining gates and rollback

The local result supports the feature's navigation improvement. Production
merge readiness still requires an isolated PostgreSQL staging database with
production-like settings and the validation in the existing staging report.
No Scaleway setting, credential, database, or infrastructure was changed.
If a future approved merge regresses navigation, revert that merge or deploy
the preceding `main2` revision, rebuild static assets, and validate normal
link navigation and browser history. No new schema migration is added by this
synthetic fixture harness.

NOTIFICATION IMPACT: None
