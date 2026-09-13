# Code audit and optimization — September 13, 2026

The audit inventoried the 216 existing tracked files and covered Django views,
forms, serializers, workflow services, templates, browser scripts/styles, Flutter
sources, tests, and operational tooling. Automated syntax checks passed for all
95 inspected Python/template files, excluding deployment settings. Binary assets
were inventoried rather than treated as source code. Credentials, environment
files, stored media, databases, model definitions, and migrations were not edited.

## Implemented fixes

- **Navigation:** Page scripts now use isolated scopes, release global event
  listeners on navigation, and cancel page-owned requests. Repeated visits no
  longer collide on top-level JavaScript declarations. Pattern Master registers
  its stylesheet for partial navigation; Back/Forward restores page assets.
  Shared icon styles remain loaded across page transitions.
- **Responsiveness:** The admin workspace now contains its desktop tables and
  adapts its navigation, cards, filters, and forms to small screens. Touch controls
  have larger targets, keyboard focus is visible, dynamic viewport heights are
  respected, and reduced-motion preferences apply consistently.
- **Forms and media:** A second submission cannot bypass an upload already in
  progress. Validation cancellation prevents upload requests. Loading indicators
  respect cancelled/AJAX submissions and recover after browser history restores.
  Thumbnail removal remains synchronized with the selected files.
- **Chat:** Opening the mobile directory no longer marks an unopened conversation
  read. Hidden conversations do not poll; overlapping message/user refreshes are
  guarded. Replies stay with their original conversation when the user switches
  chats during sending. Incoming messages preserve the reader's scroll position.
  Complaint context now uses the existing country/role visibility rules.
- **Catalog:** The next-serial endpoint uses the existing sequence calculation
  instead of always returning `0001`. Country-prefixed serial searches no longer
  inadvertently match unrelated display ranks.
- **Backend performance:** Removed a duplicate dashboard settings count. Badge
  cache hits no longer continually renew stale counts. Complaint detail loads
  related reviewers/history in fixed queries and reuses the validated instance
  during updates. Large HTML views use Django's built-in gzip response decorator.
- **Flutter lists:** Vehicles, SKUs, and Complaints ignore stale or disposed-screen
  responses, prevent overlapping page loads, preserve current results during
  pagination, and expose loading/retry/load-more controls. Filtering a short list
  no longer makes the next page unreachable.
- **Maintenance:** Repaired an incomplete legacy user-list template. Importer
  tests now isolate their report/rollback files in temporary directories and mock
  the dry-run crawler. Updated assertions that depended on old HTML formatting.

## Measured results

Measurements use synthetic fixtures, not production traffic.

| Measurement | Before | After |
|---|---:|---:|
| Pattern Master HTML, 50 displayed vehicles | 1,626,869 bytes uncompressed | 77,831 bytes gzip |
| Complaint serialization, 12 approvals + 12 timeline events | 29 queries | 5 queries including permission lookup |
| Admin page horizontal overflow at 360px | 615px | 0px |

The representative HTML response was **95.2% smaller over the wire**. Django's
gzip output includes randomized padding, so byte counts vary slightly per request.

## Verification

- **178 Django tests passed**, including existing complaint/workflow/RBAC coverage
  and new regression checks for caching, chat visibility, partial-page assets,
  fixed query counts, and compression.
- **50 browser page/viewport checks passed:** ten main pages at 360, 390, 768,
  834, and 1366 pixels. All returned HTTP 200 with no page-width overflow.
- **Six interaction checks passed:** Back/Forward restoration, Pattern Master
  cards/filters, approval filter dismissal, repeated form navigation/attachment
  removal, admin tab switching, and mobile chat opening/back navigation.
- **Three JavaScript unit tests passed** for listener cleanup and upload guards.
- Browser checks reported **zero JavaScript page errors**. Mobile screenshots
  were visually inspected; the verification browser blocks external assets.
- Dart analyzer: **No issues found** across the Flutter project.
- Source syntax checks and `git diff --check` passed.

## Safe reproduction

The standalone settings in `scripts/offline_settings.py` do not import deployment
settings or `.env`. They use SQLite **in memory**, local memory caches, temporary
file storage, synthetic accounts, and no project migrations. The runner blocks
outbound socket connections except loopback. No configured database/storage
service is contacted. The normal E2E setup/teardown, which migrates/flushes a test
database file, was not executed.

```powershell
.\env\Scripts\python.exe scripts/verify_offline.py
.\env\Scripts\python.exe scripts/audit_sources.py
.\env\Scripts\python.exe scripts/measure_offline.py
node --test tests/unit/frontend-runtime.test.cjs
```

For browser checks, start the disposable fixture server in one terminal, then run
the browser script in another:

```powershell
.\env\Scripts\python.exe scripts/offline_preview.py
node scripts/verify_browser.mjs
```

Stop the fixture server after verification. Generated reports/screenshots are in
the ignored `scratch/offline-audit/` directory. The verification servers started
during this audit were stopped.

## Scope limits

These results do not establish production latency or an absolute performance
ceiling. No live PostgreSQL, storage, deployment, load test, or Flutter emulator
was used. Pattern Master still renders both desktop and mobile representations;
compression reduces transfer size but does not eliminate that DOM cost. Its
column-filter choices remain scoped to the rendered page, while text search is
server-side. The changes preserve that behavior.
