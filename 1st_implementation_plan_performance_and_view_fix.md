# Implementation Plan 1: Fix Scrambled Initial View & Maximize Page Rendering Performance

## 1. Problem Diagnosis & Root Cause Analysis

### 1.1 Why the View Appears Scrambled & Bugged (As Shown in Screenshot)
From analyzing the portal architecture and comparing the screenshot with the DOM:
1. **Missing `data-fabro-page-asset` Attribute on `<link>` Tags:**
   - In [index.html](file:///c:/Users/POWER-13/Documents/FABRO/Fabro-Leather-Portal/management/templates/management/index.html#L13-L14):
     ```html
     <link href="{% static 'vendor/fontawesome/css/all.min.css' %}" rel="stylesheet">
     <link rel="stylesheet" href="{% static 'management/css/dashboard.css' %}?v=20260907-perf1">
     ```
   - In [base.html](file:///c:/Users/POWER-13/Documents/FABRO/Fabro-Leather-Portal/management/templates/management/base.html#L2061-L2064), the HTMX app-shell router swaps views using:
     ```javascript
     document.head.querySelectorAll('[data-fabro-page-asset]').forEach((asset) => asset.remove());
     headTemplate.content.querySelectorAll('[data-fabro-page-asset]').forEach((asset) => {
         document.head.appendChild(asset.cloneNode(true));
     });
     ```
   - Because `dashboard.css` and `all.min.css` **do not have `data-fabro-page-asset`**, they are **never injected into `<head>`** during shell navigation, while previously loaded page assets are removed.
2. **Resulting Visual Breakdown:**
   - Without `dashboard.css`:
     - `.dashboard-layout` loses its two-column CSS grid (`minmax(0, 2.08fr) minmax(350px, 0.92fr)`), so `.dashboard-split-column` takes 100% width.
     - `.stats-sidebar-section` drops directly to the bottom below both complaint tables.
     - `.stat-card-compact.complaint-summary` is an unstyled HTML `<a>` tag, causing `Total Complaints`, `Open`, `Closed`, and `On Hold` to render as **raw browser-default purple/blue underlined hyperlinks** (identical to the screenshot).
     - Icons render as raw unstyled unicode glyphs instead of FontAwesome vectors.

---

## 2. Page Lag & Call Bottleneck Analysis

When rendering pages, the following calls, queries, and functions create severe latency:

1. **Database N+1 Queries on Dashboard (`views.py:index`):**
   - `recent_complaints` only selects `('brand', 'model', 'sub_model', 'year', 'person', 'sku')`.
   - The template [index.html](file:///c:/Users/POWER-13/Documents/FABRO/Fabro-Leather-Portal/management/templates/management/index.html#L99-L289) accesses:
     - `complaint.channel.name`
     - `complaint.assigned_factory_executive.get_full_name`
     - `complaint.material.name`
     - `complaint.series.name`
   - **Impact:** Each complaint row triggers **4 additional database queries** over the network to Supabase PostgreSQL. For 15 complaints, this generates up to **60 redundant round trips** (~1.5s - 3s latency).

2. **Parser-Blocking Dynamic Script (`/jsi18n/`):**
   - In [base.html](file:///c:/Users/POWER-13/Documents/FABRO/Fabro-Leather-Portal/management/templates/management/base.html#L4):
     `<script src="{% url 'javascript-catalog' %}"></script>` is loaded synchronously at the top of the body.
   - The browser pauses all HTML parsing while Django compiles and returns translation catalogs dynamically, blocking page paint.

3. **Massive 83 KB Uncached Inline CSS in `base.html`:**
   - Lines 11–1792 of [base.html](file:///c:/Users/POWER-13/Documents/FABRO/Fabro-Leather-Portal/management/templates/management/base.html) contain 1,748 lines of raw CSS inside an inline `<style>` tag.
   - This prevents browser HTTP caching (`304 Not Modified` / `Cache-Control`). Every page request must re-download and re-parse 83 KB of identical CSS.

4. **Redundant User Profile & Badge Queries on Every Request:**
   - `get_user_profile(user)` is executed multiple times in `UserProfileLocaleMiddleware`, `context_processors.py`, and individual views instead of reusing `request._user_profile`.

5. **Heavy DOM Iteration in `enhanceLinks`:**
   - On every page swap, `enhanceLinks` queries every `a[href]` in the DOM and mutates attributes, which can be avoided using document-level event delegation.

---

## 3. Proposed Changes (Minimal Calls & Zero Lag)

### Core Optimization Strategy
- **Eliminate N+1 Queries:** Add missing relations to `select_related` in `index` and relevant views.
- **Tag Page Assets:** Add `data-fabro-page-asset` to `<link>` tags in `index.html` and `complaint_list.html` so CSS is never dropped.
- **Cache & Defer Translation Catalog:** Add HTTP caching headers to `/jsi18n/` and load script asynchronously or with `defer`.
- **Extract Inline CSS to Cached Static Bundle:** Move the 1,748 lines of CSS from `base.html` into `fabro-global.css` (or `base.css`), allowing WhiteNoise to compress and serve it with long-term caching (`max-age=31536000`).
- **Request-Level Profile Caching:** Cache `profile` directly on `request._user_profile` to cut duplicate DB calls in context processors.

---

### Component-by-Component Plan

#### [MODIFY] [index.html](file:///c:/Users/POWER-13/Documents/FABRO/Fabro-Leather-Portal/management/templates/management/index.html)
- Add `data-fabro-page-asset` to:
  ```html
  <link href="{% static 'vendor/fontawesome/css/all.min.css' %}" rel="stylesheet" data-fabro-page-asset>
  <link rel="stylesheet" href="{% static 'management/css/dashboard.css' %}?v=20260907-perf2" data-fabro-page-asset>
  ```
- Ensures styles are properly injected into `<head>` during HTMX navigation and on initial page render.

#### [MODIFY] [complaint_list.html](file:///c:/Users/POWER-13/Documents/FABRO/Fabro-Leather-Portal/management/templates/management/complaint_list.html)
- Add `data-fabro-page-asset` to FontAwesome and `complaints.css` `<link>` elements to avoid unstyled rendering when navigating to complaints.

#### [MODIFY] [management/views.py](file:///c:/Users/POWER-13/Documents/FABRO/Fabro-Leather-Portal/management/views.py)
- In `index(request)`:
  - Update `recent_complaints` query:
    ```python
    visible_complaints.select_related(
        'brand', 'model', 'sub_model', 'year', 'person', 'sku',
        'channel', 'assigned_factory_executive', 'material', 'series'
    )
    ```
  - This eliminates 60+ N+1 queries per dashboard load, reducing server response time from seconds to milliseconds.

#### [MODIFY] [management/context_processors.py](file:///c:/Users/POWER-13/Documents/FABRO/Fabro-Leather-Portal/management/context_processors.py)
- Reuse `getattr(request, '_user_profile', None)` if already resolved in middleware, avoiding redundant SQL queries for the user profile.

#### [MODIFY] [fabro_leather/urls.py](file:///c:/Users/POWER-13/Documents/FABRO/Fabro-Leather-Portal/fabro_leather/urls.py)
- Wrap `JavaScriptCatalog` with `cache_page(86400)`:
  ```python
  from django.views.decorators.cache import cache_page
  path('jsi18n/', cache_page(86400)(JavaScriptCatalog.as_view()), name='javascript-catalog'),
  ```
- Prevents re-compiling translations on every request and allows browsers to cache the script.

#### [MODIFY] [base.html](file:///c:/Users/POWER-13/Documents/FABRO/Fabro-Leather-Portal/management/templates/management/base.html)
- Add `defer` to the `/jsi18n/` script tag so it does not block the browser HTML parser.
- Move the massive 1,748-line `<style>` block into [fabro-global.css](file:///c:/Users/POWER-13/Documents/FABRO/Fabro-Leather-Portal/static/css/fabro-global.css) so WhiteNoise serves it with gzip/brotli compression and long-lived client caching.
- Optimize `enhanceLinks` to avoid heavy eager DOM operations.

---

## 4. Verification Plan

### Automated Verification
- Run existing Django test suite:
  ```powershell
  python manage.py test management
  ```
- Verify query counts on dashboard route using `PerformanceTimingMiddleware`:
  ```powershell
  python manage.py test management.tests.PerformanceTests
  ```

### Manual Verification
- Open Dashboard directly in browser (`/`): Verify two-column grid displays cleanly without FOUC or unstyled links.
- Navigate from Dashboard to Complaints and back: Verify HTMX preserves and applies all stylesheets without scrambled layouts.
- Inspect Chrome DevTools Network Tab:
  - Verify zero N+1 queries.
  - Verify static CSS and `/jsi18n/` are served from browser cache (`200 (disk cache)` or `304 Not Modified`).
  - Total payload reduced by ~80KB per request.
