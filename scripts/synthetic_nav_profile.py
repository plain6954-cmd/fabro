"""Chrome and Django navigation profile on an isolated synthetic SQLite DB."""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse


SCRIPT_DIR = Path(__file__).resolve().parent
FEATURE_DIR = SCRIPT_DIR.parent


def configure(checkout):
    if Path.cwd().resolve() != checkout:
        raise RuntimeError('Run from the selected worktree.')
    sys.path.insert(0, str(SCRIPT_DIR))
    sys.path.insert(0, str(checkout))
    os.environ['DJANGO_SETTINGS_MODULE'] = 'synthetic_perf_settings'
    from synthetic_perf_settings import allowed_worktree
    if not allowed_worktree(checkout):
        raise RuntimeError('Unapproved worktree.')


def browser_login_smoke(base, passwords, users):
    from playwright.sync_api import sync_playwright

    expected_approvals = {'admin', 'cad', 'ed', 'pm', 'om', 'md',
                          'country_ksa', 'country_uae', 'factory'}
    expected_design = {'admin', 'designer', 'other_designer', 'cad', 'ed'}
    results = {}
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel='chrome', headless=True)
        try:
            for role, user in users.items():
                context = browser.new_context(viewport={'width': 1366, 'height': 768},
                                              reduced_motion='reduce')
                page = context.new_page()
                errors = []
                page.on('pageerror', lambda error: errors.append(str(error)))
                page.goto(base + '/login/')
                page.locator('input[name="username"]').fill(user.username)
                page.locator('input[name="password"]').fill(passwords[user.username])
                page.locator('#loginButton').click()
                page.wait_for_url(lambda url: urlparse(str(url)).path != '/login/', timeout=15000)
                checks = {}
                for path in ('/car-details/', '/approvals/', '/design-approvals/'):
                    response = page.goto(base + path, wait_until='domcontentloaded')
                    checks[path] = response.status
                if checks['/car-details/'] != 200:
                    raise RuntimeError(f'Pattern Master denied for {role}.')
                if checks['/approvals/'] != (200 if role in expected_approvals else 403):
                    raise RuntimeError(f'Unexpected complaint approvals access for {role}.')
                if checks['/design-approvals/'] != (200 if role in expected_design else 403):
                    raise RuntimeError(f'Unexpected design approvals access for {role}.')
                if errors:
                    raise RuntimeError(f'JavaScript errors for {role}: {errors[:2]}')
                results[role] = {'login': 'ok', 'routes': checks}
                context.close()
        finally:
            browser.close()
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--checkout', type=Path, required=True)
    parser.add_argument('--label', choices=('before', 'after'), required=True)
    args = parser.parse_args()
    checkout = args.checkout.resolve()
    configure(checkout)
    import django
    django.setup()
    from django.contrib.auth import get_user_model
    from django.db import connection
    from django.test import Client
    from synthetic_data import assert_isolated_database, COMPLAINTS, DESIGNS, PATTERNS, SKUS, PREFIX
    from staging_nav_benchmark import (browser_profile, collect_assets,
                                       launch_server, role_checks, server_profile)
    assert_isolated_database()
    credentials = json.loads((checkout / 'output' / 'navigation-synthetic-credentials.json')
                             .read_text(encoding='utf8'))['users']
    users = {role: get_user_model().objects.get(username=PREFIX + role)
             for role in ('admin', 'country_ksa', 'country_uae', 'factory', 'registrar',
                          'viewer', 'designer', 'other_designer', 'pm', 'om', 'cad', 'ed', 'md')}
    assets = collect_assets(checkout)
    result = {
        'label': args.label,
        'revision': subprocess.check_output(
            ['git', 'rev-parse', 'HEAD'], cwd=checkout, text=True).strip(),
        'fixture': {'patterns': PATTERNS, 'complaints': COMPLAINTS,
                    'skus': SKUS, 'designs': DESIGNS},
        'database_bytes': Path(connection.settings_dict['NAME']).stat().st_size,
        'media_bytes': sum(path.stat().st_size for path in
                           (checkout / 'output' / 'navigation-synthetic-media').rglob('*')
                           if path.is_file()),
        'assets': assets, 'roles': role_checks(users),
        'server': server_profile(users['admin']),
    }
    client = Client()
    client.force_login(users['admin'])
    base, process = launch_server(checkout)
    output = FEATURE_DIR / 'output' / f'synthetic-navigation-{args.label}.json'
    try:
        result['browser'] = browser_profile(base, client.session.session_key, assets)
        result['logins'] = browser_login_smoke(base, credentials, users)
    except Exception as error:
        result['error'] = str(error)
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


if __name__ == '__main__':
    main()
