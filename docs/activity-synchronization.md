# Live activity permission synchronization

## Findings at bf2d079

Backend authorization was already evaluated per request. Login, navigation and
page refresh obtained current grants; focus and HTMX settlement could refresh the
browser snapshot. An otherwise idle, open page did not check for access changes.
In-app/Web Push notifications did not invalidate the permission manager. Some
denied controls were omitted entirely from templates, and file actions retained
the authorized state from the previous gallery response.

## Transport and consistency

The repository deployment example uses synchronous Gunicorn workers. No shared
SSE/WebSocket transport is configured, so persistent connections would require a
deployment change and consume workers. This implementation uses existing Django
HTTP delivery without Redis, Channels, Celery, new dependencies or migrations.

Visible pages check the authenticated `/account/activity-access/` endpoint every
2 seconds. Normal expected worst-case delay is 2 seconds plus request/render
latency; this is polling, not instantaneous delivery. Failed checks back off to
4/8/16/30 seconds, and online/focus/foreground events immediately revalidate.
Background pages pause until foregrounded. Timed-out requests abort after 8
seconds, checks do not overlap, and navigation disposes timers and observers.
Back-forward cache restoration resumes checking.

A SHA-256 content-addressed change token covers user identity, effective grants
and business visibility scope. This is an equivalent reliable change token, not
a monotonically increasing database counter. It detects individual overrides,
role-default configuration, existing Django group/direct rights and account
changes without relying on one particular save path. Unchanged checks omit the
permission map; the registry and labels are never downloaded by the poller.

The token is computed from database-visible state, so another session cannot
observe an uncommitted/rolled-back permission save. It is not an authorization
token. All actual actions still pass existing request, object and workflow
authorization. There is no cross-request permission cache.

Where available, same-origin Web Locks coalesce simultaneous tab checks and
BroadcastChannel shares only account-scoped invalidations, not permission data.
Followers fetch their own authenticated snapshot when stale. Other browsers and
devices independently poll the same database-backed endpoint. Unsupported
browsers use the same correct per-tab polling fallback. Cross-tab coordination is
a best-effort optimization, not a security dependency.

## Interface integration

- One shared manager handles declarative activity/all/any visibility, disabled
  states, stale clicks/submissions, mutation updates and comparison shadow roots.
- Business-eligible controls remain renderable when an activity is denied, so a
  later grant can reveal them without replacing the page or unsaved inputs.
- Pattern Master/reference/designer galleries reuse their existing authenticated
  loaders to obtain current own/all, visibility and protected-file eligibility.
  Delete availability is never inferred from a generic grant. Gallery revisions
  also include the effective access token. Pending gallery hydration retries on
  successful revalidation; old asynchronous loads are guarded.
- Measurements refresh authorized file/action state and discard stale responses.
- Comparison refreshes its authorized manifest while preserving independent
  file selections and view state when the selected files remain accessible.
  Unsaved approval drafts stay mounted; clean workspaces can be reauthorized.
- Business-eligible CAD/ED/MD form shells retain drafts while their existing
  decision/comment/voice actions update. No stage authority is added. Standalone
  review history is refreshed separately from the form, and denied history is
  hidden/cleared. Revoked voice/history access stops affected playback/recording.
- Complaint creation/edit/delete/export and vehicle controls update declaratively
  without bypassing record/workflow restrictions. The chat composer now has the
  missing shared send gate.
- ERP section gates, authorized session fragments and Control Tower refreshes
  follow the same invalidation. Fragment hydration preserves review forms and
  drafts and rejects out-of-date responses.
- Whole-section revocation displays a blocking access-changed state; restoration
  removes it without navigation. Session/account loss shows a sign-in state.
  No automatic document reload is used.

Ordinary activity grants/revocations do not require refresh or navigation. A
change to the actual role, reviewer identity, staff/superuser authority or country
scope blocks the old business interface and retains its drafts. Authorized
navigation is necessary to rebuild that different server-rendered interface;
the manager does not guess newly assigned role/object access from old markup.
Already delivered content cannot be removed from browser memory, and externally
issued signed storage URLs remain subject to their existing expiry.

## Verification

Deterministic Django tests cover private/compact tokens, immediate revoked-action
403s, role/group defaults, rollback, page/section queries, query bounds, existing
ownership/workflow guards and notification behavior. Frontend tests cover live
gates, version checks, scheduling, concurrency, cleanup and recovery.

Playwright uses real Admin Save and independent signed-in browser contexts. It
covers own-reference grant/revoke, actual eligible deletion, foreign/protected
files, multiple contexts/tabs, designer actions, measurements, vehicle controls,
an authorized complaint operator, chat, offline/foreground recovery, rapid saves,
whole-section denial/restoration, deactivation, CAD drafts/stage boundaries and
failed saves. Existing comparison/image/PDF/voice, complaint workflow, ERP and
responsive User Control Panel regressions are retained.

Server verification: 256 targeted Django regressions plus 27 existing Web Push
tests passed; 58 affected permission/review tests were rerun successfully after
the final form-shell adjustment. All 30 frontend unit tests passed. Schema drift
check reported no changes. Browser results and rerun evidence are included in
the local verification report; isolated live fixtures are removed after the
spec so they cannot change existing Control Tower counter expectations.

50 distinct targeted Playwright scenarios passed across the broad run and
focused reruns. Failed assertions were rerun after correcting the hidden form
shell, isolated fixture counters/activity cleanup, obsolete asset-version
expectation and a history test that initially selected an already completed
review stage. Final targeted history, draft, submission and voice checks passed.

Measured cross-device propagation in final focused verification: grant 1873 ms,
revoke 1673 ms for both independent contexts. The broad run measured 2016/1366 ms.
These are observed local test results, not production latency guarantees. Tests
use isolated SQLite/browser fixtures, not production PostgreSQL or live Baro.

## Notification impact

NOTIFICATION IMPACT: None. Existing access-change in-app/Web Push recipients,
messages, `/profile/` destination and after-commit trigger remain unchanged.
Machine invalidations are distinguished by `type: activity_access` and do not
create notification records or push deliveries. The existing push-failure
logging fallback now has its missing logger; no parallel notification system
was added. No Baro deployment is performed.
