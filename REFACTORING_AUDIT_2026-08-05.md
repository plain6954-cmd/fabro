# FABRO Leather Portal Refactoring Audit

Date: 2026-08-05

## Executive Summary

The portal is a single Django project with one large domain application, `management`, plus a Flutter client and Playwright browser tests. The system already has meaningful workflow services, role-aware query filtering, REST endpoints, upload validation, production-aware settings, and broad backend/browser coverage. It is not a candidate for a rewrite.

The main maintainability cost is concentration: `management/views.py`, `management/tests.py`, and several templates each exceed 1,000 lines, while presentation CSS and JavaScript remain embedded in templates. The safest path is incremental: first restore a clean baseline and remove behavior-neutral duplication, then split modules behind the existing URL/API contracts.

No database reset, migration rewrite, model-field rename, URL rename, API-shape change, or UI redesign is proposed.

## A. Current Architecture

### Runtime components

- `fabro_leather/`: project settings, root URLs, WSGI/ASGI entry points, and health check.
- `management/`: the only Django domain app. It owns authentication-facing pages, complaint workflow, catalog management, administration, REST APIs, templates, and audit records.
- `management/services/workflow.py`: the principal business-service boundary. It contains role checks, complaint visibility, factory assignment, approval rounds, notifications, execution, closure, and timeline/audit behavior.
- `management/views.py`: server-rendered dashboard, complaint, vehicle, SKU, master-data, profile, and user/session administration views. It also contains CSV and media helpers.
- `management/api_views.py` and `management/serializers.py`: DRF authentication, dashboard, complaint workflow, notifications, SKU, and vehicle APIs used by `mobile/`.
- `management/models.py`: vehicle catalog, SKU/master data, user workflow profiles, complaints, approvals, media, notifications, timeline, and activity/edit audit models.
- `management/templates/management/`: server-rendered UI. `base.html`, `complaint_list.html`, `index.html`, and `add_complaint.html` contain substantial inline CSS/JavaScript.
- `static/`: shared images, Font Awesome assets, and workflow CSS. Much page-specific styling remains inline.
- `mobile/`: Flutter client using the DRF API.
- `tests/e2e/`: Playwright tests with an isolated SQLite database and media root on port 8001.
- `management/tests.py`: Django integration, permission, workflow, form, API, upload, filtering, and dashboard tests.

### Data and integration flow

1. Browser requests enter function-based views, bind forms, then call workflow services for state transitions.
2. Mobile requests enter DRF views and serializers, then call the same workflow services for the core approval/execution lifecycle.
3. Django ORM is the data-access layer. Production PostgreSQL is hosted by Supabase through `DATABASE_URL`/`DB_*`; there is no duplicate Supabase data client in application code.
4. Media uses Django's configured storage backend: local storage in development or S3-compatible storage when `USE_S3` is enabled.
5. Notifications are persisted Django records. No separate realtime subscription implementation was found in the server code.

### Public compatibility boundaries

- URL names and paths in `management/urls.py`.
- DRF response fields produced by `management/serializers.py`.
- model fields and existing migrations `0001` through `0005`.
- template context keys, DOM behavior, dark/light mode, and responsive layouts.
- role and workflow constants in `management/models.py`.

## B. Main Problems Found

### Confirmed correctness issues

1. `visible_complaints_for_user()` uses `queryset = queryset or Complaint.objects.all()`. QuerySet truth testing executes a query; an empty supplied QuerySet is replaced by an unordered all-record QuerySet. This causes incorrect scope semantics and the observed pagination ordering warning.
2. The existing dashboard contract test expects complaint-type summary links for line, pattern, and production complaints, but those links are absent from the current template. Baseline result: 44 passed, 1 failed.
3. `Complaint` declares `country`, `person`, `case_sub_category`, `series`, and `material` twice in the class body. Python/Django silently keep only the second declaration. This is dead duplication and makes schema review error-prone, although removing the shadowed declarations should produce no migration.

### Large files and mixed responsibilities

- `management/views.py`: about 1,800 lines across seven unrelated page domains plus CSV, upload, and session helpers.
- `management/tests.py`: about 1,400 lines across many feature domains.
- `management/templates/management/complaint_list.html`: about 2,000 lines.
- `management/templates/management/base.html`: about 1,660 lines.
- `management/templates/management/index.html`: about 1,090 lines.
- `management/templates/management/add_complaint.html`: about 980 lines.
- `management/services/workflow.py`: about 900 lines; cohesive at the domain level but ready for approval and execution submodules after protection tests are strengthened.

### Duplication and dead-code candidates

- Duplicate model declarations listed above are confirmed dead.
- Web and API views repeat complaint lookup/404/permission-to-service exception translation.
- Catalog permission checks exist as both a local view wrapper and workflow helper.
- Template CSS, button/status markup, and page initialization logic repeat across large templates.
- Requirements include probable tooling/transitive packages (`argcomplete`, `click`, `colorama`, `pipx`, `platformdirs`, `userpath`) that have no application import. They must not be removed until deployment scripts and operator workflows are checked.
- `django-select2`, `django-widget-tweaks`, `python-decouple`, `pandas`, and `numpy` require a complete usage confirmation before removal. Their presence alone is not proof of dead code.

### Query and performance problems

- QuerySet truth testing in complaint visibility adds an avoidable query and changes empty-query behavior.
- `Complaint._build_next_complaint_id()` performs read-then-insert retries. It handles primary-key collisions, but high-concurrency numbering remains a database-contention risk and deserves dedicated concurrency testing before redesign.
- Some API detail querysets do not carry the `select_related`/`prefetch_related` plan used by list endpoints, so nested complaint serialization can cause N+1 queries.
- `ApprovalInboxAPIView` computes current-round status in Python per approval and calls `approval_progress`; this can become query-heavy with a large inbox.
- Dashboard aggregation is split across several queries. This is acceptable at current scale but should be measured before consolidation.

### Security and configuration

- Normal `manage.py check` passes.
- Local `check --deploy` reports six expected warnings because local development uses `DEBUG=True`, HTTP cookies, and the development key. Production branches in settings enable SSL redirect, secure cookies, and HSTS; a production-mode check still needs to be recorded with valid deployment environment values.
- Login rate limiting, CSP, permission policy, role-aware object visibility, upload limits, and POST-only administrative mutations are present.
- The custom `.env` parser is intentionally small but does not provide the parsing guarantees of a maintained environment loader. Since `python-decouple` is installed yet unused, configuration handling should eventually be consolidated rather than supporting both approaches.
- Exception handling around storage deletion and session termination is broad. Failures need specific exception classes and structured logging without exposing paths, session keys, or credentials.

### Frontend and template problems

- Large inline style/script blocks make review, caching, and reuse difficult.
- Repeated inline styles inhibit consistent responsive fixes.
- Existing browser coverage is desktop-only in Playwright configuration even though responsive tests may resize the viewport. Separate phone/tablet projects would give stronger isolation and reporting.
- Moving assets must preserve template load order and page-specific initialization; this is medium risk and should follow snapshot/browser protection.

### Testing gaps

- Baseline Django suite is not fully green: 45 tests, 1 dashboard-link failure.
- No dedicated query-count tests protect dashboard, complaint list/detail serialization, or approval inbox.
- No explicit test protects empty supplied QuerySets in `visible_complaints_for_user()`.
- No concurrency test protects complaint ID allocation.
- Supabase is exercised as PostgreSQL through Django, but there is no clearly isolated integration test for production connection configuration or storage failure boundaries.
- Ruff and mypy are not installed in the project environment. A global `pytest` executable exists, but the project is built around Django's test runner and Playwright.

## C. Proposed Target Structure

```text
management/
  constants.py
  models/
    __init__.py
    catalog.py
    complaints.py
    workflow.py
    audit.py
  views/
    __init__.py
    dashboard.py
    complaints.py
    vehicles.py
    skus.py
    masters.py
    users.py
  api/
    __init__.py
    auth.py
    complaints.py
    workflow.py
    catalog.py
    notifications.py
    serializers.py
  services/
    complaints.py
    workflow.py
    approvals.py
    notifications.py
    media.py
    imports.py
  selectors/
    complaints.py
    catalog.py
    approvals.py
  templates/management/partials/
  static/management/css/
  static/management/js/
  tests/
    test_auth.py
    test_permissions.py
    test_complaints.py
    test_workflow.py
    test_catalog.py
    test_api.py
```

This is a destination, not a single patch. Compatibility re-exports from `management.views`, `management.models`, and serializer modules should remain while modules are moved. Splitting models is lower priority because it creates import/migration-state risk without immediate runtime benefit.

## D. Refactoring Priority

| Priority | Change |
| --- | --- |
| Critical | Restore the green baseline; correct QuerySet truth testing and dashboard filter links. |
| High | Add query-count and visibility tests; optimize nested API detail queries; split complaint/catalog/admin views behind unchanged URL names. |
| High | Extract upload, CSV import/export, and complaint filtering into focused services/selectors. |
| High | Replace broad storage/session exception handling with specific handling and safe structured logging. |
| Medium | Split workflow approval and execution logic after service-level tests cover every transition. |
| Medium | Move page CSS/JavaScript into feature assets and introduce reusable partials without visual changes. |
| Medium | Consolidate environment loading and document Supabase PostgreSQL/storage deployment settings. |
| Medium | Audit and remove only confirmed unused direct dependencies. |
| Low | Split model declarations into modules after all higher-value boundaries are stable. |
| Low | Add typing incrementally to service and selector boundaries; do not type-churn templates/views. |

## E. Risk and Verification Matrix

| Task | Benefit | Files affected | Risk | Required testing | Migration |
| --- | --- | --- | --- | --- | --- |
| Fix QuerySet defaulting/order | Correct scope, avoids query, stable pagination | `services/workflow.py`, tests | Low | visibility + full Django suite | No |
| Restore dashboard type links | Restores tested navigation/filter contract | `index.html` | Low | dashboard/filter + browser smoke | No |
| Remove shadowed model fields | Removes misleading dead declarations | `models.py` | Low | migration check + model/full suite | No expected migration |
| Extract complaint selectors | Central filtering/query plan | views, API, new selectors, tests | Medium | permissions, filters, query counts, API | No |
| Split server-rendered views | Smaller ownership boundaries | views package, URLs/imports | Medium | full Django + Playwright | No |
| Split workflow service | Isolated approval/execution rules | services, tests | High | every workflow transition and rollback | No |
| Optimize nested API queries | Lower request query counts | API views/selectors | Medium | API contract + query-count tests | No |
| Extract media/import services | Shared validation and safer errors | views, forms, services | Medium | uploads, storage failure, CSV validation | No |
| Frontend asset extraction | Cacheability and maintainability | templates/static | Medium | visual/responsive Playwright, console | No |
| Settings consolidation | Predictable deployment configuration | settings, env example, docs | Medium | dev/e2e/production checks | No |
| Add indexes after measurement | Faster production filters | models/migration | Medium | explain/query benchmarks + migration rehearsal | Yes |
| Dependency cleanup | Smaller, clearer environment | requirements/docs | Medium | clean install + complete test suite | No DB migration |

## F. Estimated Code Reduction

- Confirmed shadowed model declarations: about 35 lines.
- Repeated web/API lookup and exception translation: about 40-80 lines after a clear shared boundary exists.
- CSV/media validation and handling: about 60-120 net lines through reuse, while gaining tests and logging.
- Repeated template styles/scripts/partials: about 300-600 template lines moved or consolidated; many lines move to static assets rather than disappear.
- Requirements cleanup: potentially 5-10 direct entries, pending deployment/runtime confirmation.
- View splitting will not necessarily reduce total lines initially. Its value is smaller modules, explicit dependencies, and focused tests.

A realistic safe net reduction is 5-10% of handwritten Python and 10-20% of repeated template markup/styles over several phases. Correctness, query behavior, and ownership boundaries are the primary measures.

## Baseline Evidence

- `python manage.py check`: passed, 0 issues.
- `python manage.py check --deploy` under local development environment: 6 expected development-setting warnings.
- `python manage.py makemigrations --check --dry-run`: passed, no changes detected.
- `python manage.py showmigrations management`: migrations `0001` through `0005` applied.
- `python -m pip check`: passed, no broken requirements.
- `python manage.py test management` with isolated E2E SQLite settings: 45 tests, 44 passed, 1 failed.
- Failure: dashboard complaint-type summary links are absent.
- Warning: complaint pagination received an unordered QuerySet when the supplied visible QuerySet was empty.

## Incremental Plan

1. Phase 1: fix the two baseline regressions, add regression coverage, remove shadowed declarations, and prove no migration drift.
2. Phase 2: establish query-count tests and extract complaint selectors/filtering.
3. Phase 3: split views by domain with compatibility imports and unchanged URL names.
4. Phase 4: split workflow approval/execution services under transition tests.
5. Phase 5: extract template assets/partials and run responsive browser comparisons.
6. Phase 6: audit dependencies/settings, rehearse production checks, and document deployment.

## Phase 1 Completion Report

1. **Files analysed:** project settings/URLs, management models/forms/views/API/serializers/admin/security/middleware/signals/context processor/workflow service, major templates, requirements, Flutter dependency manifest, Django tests, Playwright configuration/helpers/specs, migrations, and the prior audit.
2. **Files modified:** `management/models.py`, `management/services/workflow.py`, `management/views.py`, `management/templates/management/index.html`, `management/templates/management/complaint_list.html`, `management/tests.py`, `playwright.config.ts`, four E2E specs, and `tests/helpers/navigation.ts`.
3. **Files created:** this audit report.
4. **Files deleted:** none.
5. **Dead code removed:** five shadowed duplicate `Complaint` field declarations (about 35 source lines); runtime schema unchanged.
6. **Duplicated code consolidated:** complaint E2E search interaction now uses one shared helper.
7. **Functions/classes extracted:** `searchComplaints()` test helper; no production abstraction added before a stable baseline.
8. **Database changes:** none; no production records were written or reset.
9. **Migration status:** migrations `0001`-`0005` are applied; `makemigrations --check --dry-run` reports no changes; `migrate --check` passes.
10. **Tests executed:** focused Django regressions, full Django management suite, focused Playwright reruns, and the full Playwright suite.
11. **Test results:** Django 47/47 passed; Playwright 15/15 passed.
12. **Django checks:** normal check passed with 0 issues; production-mode `check --deploy` passed with 0 issues when supplied valid production-style environment values; `pip check` passed.
13. **Remaining risks:** oversized view/template/workflow files, unmeasured API/detail query counts, complaint-ID concurrency, broad storage/session exceptions, probable but unconfirmed unused dependencies, and no dedicated phone/tablet Playwright projects.
14. **Recommended next phase:** add query-count/permission contract tests, then extract complaint filtering and optimized query construction into a selector module without changing URL, context, or API contracts.

### Phase 1 improvements

- Empty caller-supplied QuerySets now remain empty and retain ordering instead of being replaced through truth testing.
- Complaint pagination no longer receives an accidentally unordered fallback QuerySet.
- Dashboard complaint-type counts again link to real line, pattern, and production filters.
- Description search is available in the custom search-field menu.
- Blank filter values remain blank instead of becoming `None` and causing foreign-key parsing errors.
- Playwright can use an explicitly managed external test server on Windows, exits cleanly, and its selectors now follow the current UI.
