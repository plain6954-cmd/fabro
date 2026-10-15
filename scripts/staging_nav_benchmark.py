"""Compare FABRO revisions on fresh, isolated PostgreSQL databases.

Run this script from the feature worktree; pass a detached baseline or feature
worktree with --checkout. It never flushes or drops a database. It refuses any
database with existing public tables and any non-loopback database URL.
"""

import argparse
import json
import os
import socket
import subprocess
import sys
import time
from datetime import date
from pathlib import Path
from urllib.parse import unquote, urlparse
from urllib.request import urlopen


SCRIPT_DIR = Path(__file__).resolve().parent
FEATURE_DIR = SCRIPT_DIR.parent
ROUTES = ('/', '/car-details/', '/complaints/')
VIEWPORT = {'width': 1440, 'height': 900}


def configure(checkout, assets_only):
    if not (checkout / '.git').is_file():
        raise RuntimeError('The checkout must be a separate Git worktree, not the main2 working directory.')
    if (checkout / '.env').exists() or (checkout / '.env.production').exists():
        raise RuntimeError('Remove environment files from this disposable worktree before staging tests.')
    supplied_url = os.environ.get('FABRO_NAV_STAGING_DATABASE_URL', '')
    if not supplied_url and not assets_only:
        raise RuntimeError('Set FABRO_NAV_STAGING_DATABASE_URL for a fresh local PostgreSQL DB.')
    if not supplied_url:
        # The assets-only mode uses a dummy URL; it never opens a DB connection.
        os.environ['FABRO_NAV_STAGING_DATABASE_URL'] = (
            'postgresql://stage:stage@127.0.0.1:5432/fabro_nav_stage_assets_only'
        )
    parsed = urlparse(os.environ['FABRO_NAV_STAGING_DATABASE_URL'])
    if (parsed.scheme not in {'postgres', 'postgresql'}
            or parsed.hostname not in {'127.0.0.1', 'localhost', '::1'}
            or not unquote(parsed.path.lstrip('/')).startswith('fabro_nav_stage_')
            or not parsed.username or not parsed.password):
        raise RuntimeError('Refusing a non-loopback or non-disposable PostgreSQL URL.')
    os.environ['DJANGO_SETTINGS_MODULE'] = 'staging_nav_settings'
    sys.path.insert(0, str(SCRIPT_DIR))
    sys.path.insert(0, str(checkout))


def ensure_fresh_database(url):
    import psycopg2

    with psycopg2.connect(url, connect_timeout=5, sslmode='prefer') as connection:
        with connection.cursor() as cursor:
            cursor.execute('SELECT current_database()')
            name = cursor.fetchone()[0]
            if not name.startswith('fabro_nav_stage_'):
                raise RuntimeError('Refusing a database outside the fabro_nav_stage_* namespace.')
            cursor.execute("""
                SELECT EXISTS (
                    SELECT 1 FROM pg_class AS object
                    JOIN pg_namespace AS schema ON schema.oid = object.relnamespace
                    WHERE schema.nspname NOT IN ('pg_catalog', 'information_schema')
                      AND schema.nspname NOT LIKE 'pg_toast%'
                      AND object.relkind IN ('r', 'p', 'v', 'm', 'S', 'f')
                )
            """)
            if cursor.fetchone()[0]:
                raise RuntimeError('Staging database has objects; provide a fresh empty database. No flush was run.')
            cursor.execute("""SELECT current_setting('server_version'),
                current_setting('shared_buffers'), current_setting('work_mem')""")
            version, shared_buffers, work_mem = cursor.fetchone()
    return {'name': name, 'version': version,
            'shared_buffers': shared_buffers, 'work_mem': work_mem}


def collect_assets(checkout):
    from django.conf import settings
    from django.core.management import call_command
    from django.contrib.staticfiles.storage import staticfiles_storage
    from django.test import Client

    call_command('collectstatic', interactive=False, verbosity=0)
    manifest = settings.STATIC_ROOT / 'staticfiles.json'
    if not manifest.is_file():
        raise RuntimeError('WhiteNoise manifest was not produced.')
    checked = {}
    client = Client()
    for asset in ('vendor/htmx/htmx.min.js', 'js/fabro-page.js',
                  'management/css/dashboard.css'):
        url = staticfiles_storage.url(asset)
        local = settings.STATIC_ROOT / urlparse(url).path.removeprefix(settings.STATIC_URL)
        if not local.is_file():
            raise RuntimeError(f'Missing collected asset: {asset}')
        response = client.get(url, HTTP_ACCEPT_ENCODING='gzip')
        if response.status_code != 200:
            raise RuntimeError(f'WhiteNoise could not serve: {asset}')
        if 'immutable' not in response.get('Cache-Control', ''):
            raise RuntimeError(f'Collected asset lacks immutable caching: {asset}')
        checked[asset] = {'url': url, 'cache_control': response['Cache-Control'],
                          'content_encoding': response.get('Content-Encoding', '')}
    return {'root': str(settings.STATIC_ROOT.relative_to(checkout)),
            'manifest': str(manifest.relative_to(checkout)), 'assets': checked}


def seed_fixture():
    from django.contrib.auth import get_user_model
    from django.core.cache import cache
    from management.models import (ApprovalRoles, Brand, Complaint, ComplaintTypes,
        MasterSetting, Model, SKU, SubModel, UserProfile, WorkflowRoles,
        WorkflowStatuses, YearRange)

    country = MasterSetting.objects.create(category='Country', name='KSA')
    india = MasterSetting.objects.create(category='Country', name='India')
    roles = {
        'admin': (WorkflowRoles.ADMIN, '', True),
        'designer': (WorkflowRoles.FREELANCE_3D_DESIGNER, '', False),
        'cad': (WorkflowRoles.APPROVER, ApprovalRoles.CAD, False),
        'ed': (WorkflowRoles.APPROVER, ApprovalRoles.ED, False),
        'pm': (WorkflowRoles.APPROVER, ApprovalRoles.PM, False),
        'om': (WorkflowRoles.APPROVER, ApprovalRoles.OM, False),
        'md': (WorkflowRoles.APPROVER, ApprovalRoles.MD, False),
        'factory': (WorkflowRoles.FACTORY_EXECUTIVE, '', False),
        'registrar': (WorkflowRoles.FACTORY_COMPLAINT_REGISTRAR, '', False),
        'country': (WorkflowRoles.COUNTRY_EXECUTIVE, '', False),
        'viewer': (WorkflowRoles.FACTORY_VIEWER, '', False),
    }
    users = {}
    for name, (role, approval_role, is_admin) in roles.items():
        user = get_user_model().objects.create_user(
            username=f'nav_stage_{name}', password='DisposableNavigationOnly!234',
            email=f'{name}@fabro.test', is_staff=is_admin, is_superuser=is_admin,
        )
        profile, _ = UserProfile.objects.get_or_create(user=user)
        profile.role, profile.approval_role = role, approval_role
        if name == 'country':
            profile.country = country
        profile.save()
        users[name] = user
    brand = Brand.objects.create(name='STAGING NAV BRAND')
    model = Model.objects.create(brand=brand, name='STAGING NAV MODEL')
    submodel = SubModel.objects.create(model=model, name='STAGING NAV SUB')
    YearRange.objects.bulk_create([
        YearRange(sub_model=submodel, serial_number=f'I{i:04d}', year_start=2020,
                  year_end=2025, number_of_seats=5, number_of_doors=4,
                  layout_code=f'NAV-STAGE-{i:04d}', vehicle_country=india)
        for i in range(1, 251)
    ])
    SKU.objects.bulk_create([
        SKU(code=f'NAV-STAGE-SKU-{i:04d}', description='Benchmark SKU')
        for i in range(1, 51)
    ])
    Complaint.objects.bulk_create([
        Complaint(complaint_id=f'PAT-2610{i:04d}', complaint_type=ComplaintTypes.PATTERN,
                  workflow_status=WorkflowStatuses.SUBMITTED, created_by=users['admin'],
                  country=country if i % 2 else india, date=date(2026, 10, 1),
                  brand=brand, model=model, sub_model=submodel, priority='Medium',
                  status='Open', complaint_description='Synthetic staging complaint')
        for i in range(1, 201)
    ])
    cache.clear()
    return users


def role_checks(users):
    from django.test import Client

    results = {}
    for role, user in users.items():
        client = Client()
        client.force_login(user)
        results[role] = {}
        for route in ('/', '/car-details/', '/complaints/', '/approvals/',
                      '/design-approvals/'):
            full = client.get(route)
            partial = client.get(route, HTTP_HX_REQUEST='true')
            if full.status_code != partial.status_code:
                raise RuntimeError(f'Full/partial permission mismatch: {role} {route}')
            results[role][route] = full.status_code
    if results['viewer']['/approvals/'] != 403:
        raise RuntimeError('Factory viewer accessed approvals.')
    if results['designer']['/car-details/'] != 200:
        raise RuntimeError('Designer lost Pattern Master access.')
    return results


def server_profile(user):
    from django.core.cache import cache
    from django.db import connection
    from django.test import Client
    from django.test.utils import CaptureQueriesContext

    client = Client()
    client.force_login(user)
    results = {}
    for route in ROUTES:
        samples = []
        for run in range(10):
            if run == 0:
                cache.clear()
            sql_ms = 0.0
            def measure_sql(execute, sql, params, many, context):
                nonlocal sql_ms
                started = time.perf_counter()
                try:
                    return execute(sql, params, many, context)
                finally:
                    sql_ms += (time.perf_counter() - started) * 1000
            started = time.perf_counter()
            with connection.execute_wrapper(measure_sql):
                with CaptureQueriesContext(connection) as queries:
                    response = client.get(route, HTTP_HX_REQUEST='true')
            samples.append({'duration_ms': round((time.perf_counter()-started)*1000, 1),
                            'sql_count': len(queries), 'sql_duration_ms': round(sql_ms, 2),
                            'status': response.status_code, 'html_bytes': len(response.content)})
        results[route] = samples
    return results


def launch_server(checkout):
    sock = socket.socket()
    sock.bind(('127.0.0.1', 0))
    port = sock.getsockname()[1]
    sock.close()
    base = f'http://127.0.0.1:{port}'
    env = os.environ.copy()
    env['PYTHONPATH'] = os.pathsep.join((str(SCRIPT_DIR), env.get('PYTHONPATH', '')))
    process = subprocess.Popen(
        [sys.executable, 'manage.py', 'runserver', f'127.0.0.1:{port}',
         '--noreload', '--nostatic'], cwd=checkout, env=env,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    for _ in range(120):
        try:
            with urlopen(base + '/health/', timeout=1) as response:
                if response.status == 200:
                    return base, process
        except Exception:
            time.sleep(.1)
    process.terminate()
    raise RuntimeError('Loopback staging server failed to start.')


def browser_profile(base, cookie, assets):
    from playwright.sync_api import sync_playwright

    results = {'cold': {}, 'warm': {route: [] for route in ROUTES},
               'page_errors': [], 'request_failures': [], 'http_failures': []}
    observers = '''window.__navProfile={longTasks:[],lcp:0};
      try {new PerformanceObserver(list=>{for(const e of list.getEntries())
        window.__navProfile.longTasks.push({start:e.startTime,duration:e.duration});
      }).observe({entryTypes:['longtask']})} catch(e){}
      try {new PerformanceObserver(list=>{for(const e of list.getEntries())
        window.__navProfile.lcp=e.startTime;
      }).observe({type:'largest-contentful-paint',buffered:true})} catch(e){}'''
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel='chrome', headless=True)
        results['chrome_version'] = browser.version
        try:
            for route in ROUTES:
                samples = []
                for _ in range(10):
                    context = browser.new_context(viewport=VIEWPORT, reduced_motion='reduce')
                    context.add_init_script(observers)
                    context.add_cookies([{'name': 'sessionid', 'value': cookie,
                                          'domain': '127.0.0.1', 'path': '/'}])
                    page = context.new_page()
                    page.on('pageerror', lambda error: results['page_errors'].append(str(error)))
                    response = page.goto(base + route, wait_until='domcontentloaded')
                    page.evaluate('() => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))')
                    timing = page.evaluate('''() => {
                      const n = performance.getEntriesByType('navigation')[0];
                      return {ttfb_ms:n.responseStart-n.requestStart,
                        html_duration_ms:n.responseEnd-n.responseStart,
                        dcl_ms:n.domContentLoadedEventEnd-n.startTime,
                        lcp_ms:window.__navProfile.lcp || null,
                        long_task_ms:window.__navProfile.longTasks.reduce((v,e)=>v+e.duration,0)}; }''')
                    timing.update({'status': response.status, 'dom_nodes': page.locator('*').count(),
                                   'html_bytes': len(response.body())})
                    samples.append(timing)
                    context.close()
                results['cold'][route] = samples

            context = browser.new_context(viewport=VIEWPORT, reduced_motion='reduce')
            context.add_init_script(observers)
            context.add_cookies([{'name': 'sessionid', 'value': cookie,
                                  'domain': '127.0.0.1', 'path': '/'}])
            page = context.new_page()
            page.on('pageerror', lambda error: results['page_errors'].append(str(error)))
            page.on('requestfailed', lambda request: results['request_failures'].append(request.url))
            page.on('response', lambda response: results['http_failures'].append(
                {'url': response.url, 'status': response.status})
                if response.status >= 400 and response.url.startswith(base) else None)
            page.goto(base + '/', wait_until='domcontentloaded')
            cdp = context.new_cdp_session(page)
            cdp.send('Performance.enable')
            asset_response = page.request.get(
                base + assets['assets']['vendor/htmx/htmx.min.js']['url'])
            if asset_response.status != 200:
                raise RuntimeError('Collected HTMX asset was not served by WhiteNoise.')
            document_requests = 1
            def on_request(request):
                nonlocal document_requests
                if request.is_navigation_request():
                    document_requests += 1
            page.on('request', on_request)

            def navigate(route):
                responses = []
                def record_response(response):
                    if (urlparse(response.url).path == route
                            and response.request.headers.get('hx-request') == 'true'):
                        responses.append(response)
                page.on('response', record_response)
                before = {item['name']: item['value'] for item in cdp.send('Performance.getMetrics')['metrics']}
                mark = page.evaluate('performance.now()')
                started = time.perf_counter()
                page.locator(f'a[href="{route}"][hx-get]').first.evaluate('(a) => a.click()')
                page.wait_for_function('''route => location.pathname === route &&
                  !document.body.hasAttribute('aria-busy')''', arg=route, timeout=20000)
                page.evaluate('() => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))')
                after = {item['name']: item['value'] for item in cdp.send('Performance.getMetrics')['metrics']}
                resource = page.evaluate('''route => performance.getEntriesByType('resource')
                  .filter(e => new URL(e.name).pathname === route)
                  .map(e => ({ttfb_ms:e.responseStart-e.requestStart,
                    html_duration_ms:e.responseEnd-e.responseStart})).slice(-1)[0] || null''', route)
                long_tasks = page.evaluate('''mark => window.__navProfile.longTasks
                  .filter(e => e.start >= mark).reduce((v,e) => v+e.duration,0)''', mark)
                page.remove_listener('response', record_response)
                if len(responses) != 1 or responses[0].status != 200:
                    raise RuntimeError(f'Expected one successful HTMX response for {route}.')
                return {'usable_ms': round((time.perf_counter()-started)*1000, 1),
                        'dom_nodes': page.locator('*').count(),
                        'document_requests': document_requests,
                        'html_bytes': len(responses[0].body()),
                        'ttfb_ms': resource['ttfb_ms'] if resource else None,
                        'html_duration_ms': resource['html_duration_ms'] if resource else None,
                        'long_task_ms': round(long_tasks, 1),
                        'script_ms': round((after.get('ScriptDuration', 0)
                                            - before.get('ScriptDuration', 0))*1000, 1)}

            for _ in range(10):
                for route in ('/car-details/', '/complaints/'):
                    results['warm'][route].append(navigate(route))
                    results['warm']['/'].append(navigate('/'))
            if document_requests != 1:
                raise RuntimeError(f'Unexpected full-document reloads: {document_requests}')
            page.go_back()
            page.wait_for_function("location.pathname === '/complaints/'")
            page.go_back()
            page.wait_for_function("location.pathname === '/car-details/'")
            first_row = page.locator('tr[id^="row-view-"]').first
            first_row.locator('.pattern-row-select').check()
            page.locator('#patternActionsToggleBtn').click()
            if 'is-open' not in (page.locator('#patternActionsDrawer').get_attribute('class') or ''):
                raise RuntimeError('Pattern Master drawer failed after history restoration.')
            page.go_forward()
            page.wait_for_function("location.pathname === '/complaints/'")
            page.go_forward()
            page.wait_for_function("location.pathname === '/'")
            if document_requests != 1:
                raise RuntimeError('Browser history caused a full document reload.')
            results['history_ok'] = True
            context.close()
        finally:
            browser.close()
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--checkout', type=Path, required=True)
    parser.add_argument('--label', choices=('before', 'after'), required=True)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--assets-only', action='store_true')
    mode.add_argument('--preflight-only', action='store_true')
    args = parser.parse_args()
    checkout = args.checkout.resolve()
    configure(checkout, args.assets_only)
    if not args.assets_only:
        status = subprocess.check_output(['git', 'status', '--porcelain'], cwd=checkout, text=True)
        if status.strip():
            raise RuntimeError('Benchmark checkout must be committed and clean.')
        db_profile = ensure_fresh_database(os.environ['FABRO_NAV_STAGING_DATABASE_URL'])
    else:
        db_profile = None
    if args.preflight_only:
        print(json.dumps({'preflight_ok': True, 'database': db_profile,
                          'checkout': str(checkout)}, indent=2))
        return
    import django
    django.setup()
    assets = collect_assets(checkout)
    if args.assets_only:
        print(json.dumps({'assets_only': True, 'checkout': str(checkout), 'assets': assets}, indent=2))
        return

    from django.contrib.auth import get_user_model
    from django.core.management import call_command
    from django.test import Client
    call_command('migrate', interactive=False, verbosity=0)
    users = seed_fixture()
    result = {'label': args.label,
              'revision': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=checkout, text=True).strip(),
              'database_name': db_profile['name'], 'database_profile': db_profile,
              'fixture': {'patterns': 250, 'complaints': 200, 'skus': 50},
              'assets': assets, 'roles': role_checks(users), 'server': server_profile(users['admin'])}
    client = Client()
    client.force_login(get_user_model().objects.get(pk=users['admin'].pk))
    base, process = launch_server(checkout)
    output = FEATURE_DIR / 'output' / f'staging-navigation-{args.label}.json'
    output.parent.mkdir(exist_ok=True)
    try:
        result['browser'] = browser_profile(base, client.session.session_key, assets)
    except Exception as exc:
        result['browser_error'] = str(exc)
        output.write_text(json.dumps(result, indent=2), encoding='utf8')
        raise
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
    output.write_text(json.dumps(result, indent=2), encoding='utf8')
    print(output)
    browser = result['browser']
    if (browser['page_errors'] or browser['request_failures']
            or browser['http_failures']):
        raise RuntimeError('Browser errors or HTTP failures occurred; inspect the saved capture.')


if __name__ == '__main__':
    main()
