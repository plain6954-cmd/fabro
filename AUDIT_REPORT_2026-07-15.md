# FABRO Portal Functional and Security Audit

Date: 15 July 2026

## Scope

The audit covered authentication, all configured workflow roles, dashboard navigation,
complaint CRUD and workflow, approvals, notifications, vehicle and SKU management,
master settings, profile management, admin controls, REST endpoints, Supabase persistence,
responsive rendering, browser errors, dependency health, migrations, and deployment checks.

## Test Accounts Created

The following temporary accounts were created in Supabase:

| Username | Workflow role | Approval role | Country |
| --- | --- | --- | --- |
| `audit_country` | Country Executive | - | KSA |
| `audit_viewer` | Factory Viewer | - | - |
| `audit_factory` | Factory Executive | - | - |
| `audit_pm` | Approver | PM | - |
| `audit_om` | Approver | OM | - |
| `audit_cad` | Approver | CAD | - |
| `audit_ed` | Approver | ED | - |
| `audit_md` | Approver | MD | - |
| `audit_admin` | Admin | - | - |

These are audit-only accounts and must be removed or assigned strong unique passwords
before production deployment.

## Automated Results

- Django system check: passed.
- Dependency check: passed with no broken requirements.
- Supabase migration check: passed; no unapplied migrations.
- Model migration generation check: no ungenerated model changes.
- Backend suite: 38 of 38 tests passed.
- Playwright browser suite: 15 of 15 scenarios passed.
- Browser JavaScript runtime errors: none.
- Live Supabase write/read/rollback check: passed.
- Playwright command teardown: failed to exit after tests completed and timed out.

## Confirmed Working

- Valid login, invalid login, logout, protected-route redirects, session persistence, and login rate limiting.
- Dashboard cards and primary navigation.
- Complaint create, list, search, filter, view, edit, delete, CSV export, and media fallback behavior.
- Country Executive visibility restriction to the assigned country and exclusion of Line complaints.
- Factory assignment, mandatory factory review, parallel approval creation, and notifications.
- PM, OM, CAD, ED, and MD approver inbox access.
- Waiting for every required approver before resolving a rejected approval round.
- Medium-priority approval path and final CAD/container closure.
- Line complaint closure without a production container.
- Rework and resubmission into a fresh approval round.
- Vehicle create, edit, delete, dropdown endpoints, and CSV validation.
- SKU create, search, edit, delete, and CSV validation.
- Master setting create, edit, and delete for administrators.
- Profile update and password-change backend behavior.
- Dark/light theme switching and refresh persistence.
- REST authentication, profile, dashboard, complaint, approval, notification, vehicle, and SKU endpoints.
- Database writes now target Supabase PostgreSQL.

## Findings

### 1. Production security configuration is not ready

Severity: Critical before deployment

`manage.py check --deploy` reports six warnings: `DEBUG=True`, an inadequate secret key,
no HTTPS redirect, no HSTS, and non-secure session and CSRF cookies. Local development is
working, but these settings must not be used on the deployed site.

### 2. Session termination uses destructive GET requests
 
Severity: High

The admin panel terminates one or all sessions through normal links and the corresponding
views accept GET requests. A malicious link or embedded request could log users out without
CSRF protection. These actions must be POST-only forms with CSRF tokens.

Affected code: `management/views.py` session termination views and the session links in
`management/templates/management/admin_panel.html`.

### 3. Vehicle brand logos are broken

Severity: High

All five brands with logos store full Supabase public URLs in an `ImageField`. The vehicle
template calls `.url`, which prefixes `/media/` and produces paths such as
`/media/https:/...`. Four unique image requests returned HTTP 404 during every vehicle-page
scan. The stored data format and rendering logic need normalization.

### 4. Uploaded media is not currently durable in Supabase Storage

Severity: High before deployment

The active default storage is local filesystem storage and `USE_S3=False`. Uploaded complaint
media and new brand logos are therefore written under the local `media` directory. Those files
will not survive a stateless deployment or be shared across multiple server instances, even
though their database metadata is stored in Supabase.

### 5. The report step does not enforce the agreed mandatory fields

Severity: High workflow mismatch

`ComplaintForm` explicitly marks nearly every report field optional. A form containing only
the default status and priority validates successfully. This conflicts with the agreed rule
that every field in each workflow step must be mandatory. Required fields should be finalized
per complaint type, with only intentionally unavailable fields exempted.

### 6. SKU page has a severe N+1 query problem

Severity: High performance

The live SKU page took 40-46 seconds and executed 726 SQL queries for 720 SKUs. The queryset
does not preload each SKU's region, so rendering performs one additional query per row. This
page will become progressively slower as the catalog grows.

Measured source: `management/views.py` SKU queryset and `add_skus.html` region rendering.

### 7. Admin panel is query-heavy

Severity: Medium to High performance

The admin panel took 6-7.5 seconds and executed 102 SQL queries. Permission labels in the
group form and active-session/user rendering cause repeated related-object work. Permissions,
content types, and other related data should be loaded in bounded queries.

### 8. Role-aware navigation is incomplete

Severity: Medium

Every authenticated user receives the same top navigation. Country Executives, Factory
Viewers, Factory Executives, and Approvers can open the Add Vehicle and Add SKU forms even
though submission is rejected unless they are Django staff. The Master link is also visible
to non-admin users and redirects them away after clicking. Actions should be hidden or shown
read-only according to role.

The backend mutation checks are present; this is primarily an authorization UX mismatch.

### 9. Every profile is labelled Administrator

Severity: Medium

The header and profile dropdown contain hard-coded `Administrator` and `System Administrator`
text. Country Executives, Factory Viewers, Factory Executives, and Approvers therefore see the
wrong identity/role description.

### 10. Complaint creation is not restricted to intended reporter roles

Severity: Medium workflow policy gap

The creation service applies special country restrictions but otherwise permits any
authenticated role to create a complaint. Factory Viewers and Approvers can reach and submit
the report form. The permitted reporters for Pattern, Production, and Line complaints need an
explicit role policy.

### 11. Admin edit buttons do not edit the selected row

Severity: Medium

The Existing Users and Existing Groups tables send Edit to the generic Django admin list.
Custom edit modals and JavaScript functions exist but no row button calls them. Consequently,
the visible edit action does not open the selected user/group in the custom panel.

### 12. Approver uniqueness is not enforced at database level

Severity: Medium workflow reliability

The custom forms prevent two active users from sharing PM/OM/CAD/ED/MD, and the workflow
service detects duplicates. Django admin can still create a duplicate because `UserProfile`
has no database constraint. A duplicate makes approval-round creation fail at runtime.

### 13. Responsive horizontal overflow remains

Severity: Medium UI

Measured overflow:

| Page | Tablet | Mobile |
| --- | ---: | ---: |
| Vehicle list | 166 px | 592 px |
| Admin panel | 8 px | 325 px |
| Most other pages | 7-18 px | 10-18 px |

The vehicle table still requires substantial page-level horizontal movement on smaller screens.
The admin panel also extends well beyond the mobile viewport.

### 14. Browser suite does not terminate cleanly

Severity: Medium test infrastructure

All 15 Playwright tests completed successfully, but the command remained alive until the
four-minute timeout. The likely cause is global teardown flushing the SQLite database while
the Playwright-managed Django server is still running. This prevents reliable one-command CI.

### 15. Responsive tests are too shallow

Severity: Low to Medium test coverage

The current responsive test confirms that pages are non-empty and the navbar is visible, but
does not assert overflow, clipped controls, form usability, or card/button alignment. This is
why the vehicle and admin overflow passed the automated suite.

### 16. Browser workflow coverage is incomplete for alternate branches

Severity: Low to Medium test coverage

Backend tests cover rejection, rework, Line closure, and priority matrices. Browser automation
currently covers only the medium-priority successful approval/closure path. Full UI tests are
still needed for Low, Top, rejection-after-all-reviews, rework/resubmission, and Line closure.

### 17. REST API feature parity is incomplete

Severity: Medium for the Flutter phase

The REST API covers authentication, profile, dashboard, complaints, workflow, notifications,
vehicles, and SKUs. It does not expose Master Settings CRUD or admin user/group management,
so the Flutter client cannot yet reproduce every current website feature.

## Role Access Observed

| Role | Complaint list | Add complaint | Approval inbox | Master | Custom admin | Django admin |
| --- | --- | --- | --- | --- | --- | --- |
| Country Executive | Yes, country-scoped | Yes | Forbidden | Redirected | Redirected | Login redirect |
| Factory Viewer | Yes, all | Yes | Forbidden | Redirected | Redirected | Login redirect |
| Factory Executive | Yes, all | Yes | Forbidden | Redirected | Redirected | Login redirect |
| PM/OM/CAD/ED/MD | Yes, all | Yes | Yes | Redirected | Redirected | Login redirect |
| Admin | Yes, all | Yes | Forbidden unless also configured as approver | Yes | Yes | Yes |

## Recommended Repair Order

1. Production security settings and POST-only session termination.
2. Supabase media storage and existing broken logo normalization.
3. Mandatory complaint fields and explicit role-based creation policy.
4. SKU and admin query optimization.
5. Role-aware navigation and correct profile role labels.
6. Admin row edit actions and approver uniqueness constraint.
7. Responsive overflow fixes.
8. Playwright teardown and expanded role/workflow/responsive tests.
9. Remaining REST API parity for Flutter.
