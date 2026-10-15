# FABRO fast navigation audit and implementation — 15 October 2026

## Scope and repository state

The feature worktree is `feature/fast-navigation-htmx`, created from committed
`main2` revision `a9679d9`. The original `main2` checkout had eight modified
source files and one untracked test module concerning complaint forms and the
designer approvals workspace. No generated files or credentials were in that
change list. Eight focused tests passed, but `git diff --check` found trailing
whitespace and the new designer workspace template calls
`openQuickDesignReviewModal`, `submitQuickDesignDecision`, and preview close
functions that are not defined in that template. That existing change set was
left untouched and was not approved for commit or push. The feature branch may
need rebasing if those changes are later fixed and approved for `main2`.

## Architecture before and after

FABRO already served authenticated Django templates with a persistent navbar
and vendored HTMX 2.0.8. The templates render complete documents for normal
requests; `HX-Request: true` produces a `data-fabro-page-head` template and
`#app-content` without the shared shell. The base router enhances eligible
links with `hx-get`, `hx-select`, `hx-target`, `hx-swap`, and `hx-push-url`.
Back/forward uses HTMX history snapshots. The `workflow_access` context
processor supplies role flags and per-user badge counts. Django views enforce
the same authentication and role checks for full and partial requests.

The feature branch keeps that architecture. It narrows partial navigation to
known routes that implement the content/head contract, checks the response
content type before swapping, and leaves admin, chat, downloads, mutation
endpoints, login/logout, and unknown routes on normal navigation. The shell,
theme/profile controls, badges, and `web_push.js` remain mounted. Navigation
starts a small fixed progress indicator at request start. CSS waits, stale
response rejection, history, and full-document fallback remain in place.

## Confirmed bottlenecks

- Pattern Master rendered 50 vehicles per page. Each vehicle produces a desktop
  row, mobile card, and editor markup. The admin response was 1,785,351 bytes
  and 8,460 element nodes. Complaints rendered 25 records with report and
  workflow details: 726,057 bytes and 7,181 nodes.
- HTMX parsed the destination to swap content, while the router also parsed the
  entire response to extract a small page-head template. The second parse was
  especially costly for Pattern Master.
- The existing loading overlay appeared only after the server response, leaving
  a long click-to-feedback gap.
- A Pattern Master document click listener, a profile resize listener, and an
  add-complaint `ResizeObserver` remained live after their pages were swapped.
- The standalone admin suite treated its own create-user password input as a
  login redirect, triggering an unnecessary full-document reload on section
  and pagination fetches.

Images and complaint thumbnails already use lazy loading. The design folder API
is loaded when its design pane is used. WhiteNoise already provides compressed,
versioned static assets in non-debug deployments. No user-specific HTML cache
or speculative prefetch was added because complaint, stock, and approval data
can change and roles differ.

## Changes

1. Pattern Master page size: 50 to 20; Complaints page size: 25 to 10. Existing
   pagination, filters, controls, and access checks remain in place.
2. Read-only Pattern Master visits skip the editor-only next-serial scan.
3. The router parses only the head template fragment, keeps the existing
   full-response fallback, displays immediate progress, and reports network
   failure without abandoning the current page.
4. Page-owned listeners and the observer are disposed on page swap.
5. Admin section fetches identify login by redirect or login-page marker.

### Files changed

- `management/templates/management/base.html`: route gating, response handling,
  head parsing, and navigation feedback.
- `management/views.py`: Pattern Master and complaint pagination, and the
  read-only serial-query skip.
- `management/templates/management/car_details.html`,
  `profile_settings.html`, and `add_complaint.html`: page-owned cleanup.
- `management/templates/management/admin_panel.html`: login redirect detection.
- `management/tests.py`, `management/tests_performance.py`,
  `tests/e2e/navigation.spec.ts`, and `tests/e2e/admin-navigation.spec.ts`:
  regression and behavior checks.
- This report: `docs/FAST_NAVIGATION_HTMX_2026-10-15.md`.

## Matched local performance results

Chrome headless, 1440×900, reduced motion, local Django and SQLite, synthetic
fixture of 250 vehicles, 200 complaints, and 50 SKUs. Ten fresh browser contexts
per cold route; ten warm Pattern Master and Complaints visits each, returning to
Dashboard between visits (20 warm Dashboard samples). One authorized admin
session was used. `usable` is URL and swap completion plus two animation frames.
Median / p95 use the nearest-rank p95. Browser samples are from the same script
and fixture on the clean baseline and feature branch, run sequentially on this
Windows host. They do not represent Scaleway/PostgreSQL latency.
"Cold" means a fresh browser context and asset cache; Django's process cache
could be warm after the first request. "Warm" means the persistent shell was
already loaded in one browser session.

| Warm destination | Before usable ms | After usable ms | Before HTML | After HTML | Before nodes | After nodes |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Dashboard | 488 / 812 | 213 / 275 | 84,756 B | 84,756 B | 715 | 716 |
| Pattern Master | 1,005 / 2,135 | 331 / 465 | 1,785,351 B | 926,186 B | 8,460 | 3,901 |
| Complaints | 676 / 1,216 | 236 / 551 | 726,057 B | 340,647 B | 7,181 | 3,402 |

| Cold destination | Before TTFB ms | After TTFB ms | Before DCL ms | After DCL ms | Before LCP ms | After LCP ms |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Dashboard | 76 / 833 | 56 / 301 | 529 / 2,854 | 349 / 1,838 | 468 / 904 | 368 / 468 |
| Pattern Master | 275 / 389 | 142 / 193 | 920 / 1,079 | 541 / 634 | 580 / 804 | 480 / 576 |
| Complaints | 205 / 361 | 127 / 148 | 659 / 1,176 | 474 / 510 | 528 / 812 | 438 / 460 |

Cold navigation HTML response duration was 2–4 ms median on loopback.

| Warm destination | TTFB before/after median ms | HTML response duration before/after median ms |
| --- | ---: | ---: |
| Dashboard | 43 / 35 | 1.2 / 0.8 |
| Pattern Master | 247 / 96 | 2.8 / 2.0 |
| Complaints | 190 / 76 | 2.2 / 1.1 |

The benefit mainly comes from reduced server rendering and browser script/DOM
work, not transfer time on loopback.

| Destination | Before server ms | After server ms | SQL queries before/after | SQL execution ms before/after | Warm script ms before/after | Warm long-task ms before/after |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Dashboard | 17.5 / 733 | 13.4 / 404 | 8 / 8 median | 2.5 / 1.1 median | 275 / 101 median | 363 / 129 median |
| Pattern Master | 114.5 / 176 | 44.7 / 100 | 7 / 7 median | 2.7 / 1.4 median | 250 / 86 median | 404 / 103 median |
| Complaints | 93.8 / 237 | 48.0 / 84 | 13 / 13 median | 10.2 / 6.0 median | 188 / 67 median | 319 / 95 median |

Server cells show median / p95; SQL execution cells show median only. SQL
durations used a high-resolution Django `execute_wrapper`, since SQLite's
standard query log rounded short queries to zero. Query counts were unchanged
for admin: these fixes reduce rendered volume. Warm navigation issued one HX
destination request per visit and only the initial document request. Both
builds had zero browser page errors and failed requests in the benchmark.

## Security and lifecycle

No workflow logic, model schema, recipients, push service, CSRF behavior,
permission gates, or CSP directive changed. The HTMX asset is pinned and local.
The existing CSP still permits inline scripts for the legacy Django templates;
this change did not add `unsafe-inline` or `unsafe-eval`. The router does not
evaluate scripts extracted from responses; page scripts in trusted templates
continue through the existing HTMX lifecycle. HTML responses vary on
`HX-Request`, and authenticated locale middleware varies on Cookie. Existing
badge and dashboard summary caches retain their user/role scoping and TTLs.

`fabroCreatePageScope` owns page listeners, fetches, and cleanup. The new
cleanup coverage prevents the identified document/resize/observer accumulation.
Repeated Chrome cycles showed no duplicate destination requests. CDP heap
samples varied across routes and were not force-collected, so they do not prove
a precise memory trend.

## Validation

- `manage.py check`: passed.
- Playwright Chrome: 41/41 passed, plus the final focused click-feedback test
  (1/1), including repeated shell navigation,
  back/forward, direct URL/refresh, stale and failed responses, CSS loading,
  Pattern Master selection/search/edit/design pagination, complaint forms and
  filters, admin history, and the full factory/approver workflow.
- Real-Chrome audit: 5/5 passed across 12 roles and nine widths from 320 to
  2560 px, including 360, 390, 768, 1024, and 1920. The 1440 px viewport was
  used for the matched benchmark. It also exercised designer image upload,
  CAD/ED decisions, touch controls, route permissions, and console/network
  diagnostics.
- Complete Django suite: 322/322 passed (`manage.py test management --failfast`).

## Remaining work and deployment

Pattern Master still contains a large inline page script and stylesheet.
Dashboard server p95 is variable due cache misses and local host load. A
staging run using Scaleway-like PostgreSQL latency and the deployed static
pipeline is needed before predicting production gains. Prefetching sensitive
HTML was deliberately deferred. The pre-existing dirty `main2` designer
workspace changes need their missing callbacks and a separate full regression
pass before they can be considered for a base-branch commit.

For a deployment after approval: first merge the reviewed feature branch into
`main2`, run `manage.py check`, the Django and Playwright suites in staging,
then deploy via the established Scaleway procedure. No migrations or data
changes are required. Rollback is a Git revert of the feature commit (or
redeploy the previous `main2` revision); normal full-document navigation
continues to work if HTMX fails to load.

NOTIFICATION IMPACT: None
