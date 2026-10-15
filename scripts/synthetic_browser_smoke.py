"""Read-only Chrome smoke of filters and controls on the populated fixture."""

import json
import os
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright


CHECKOUT = Path.cwd().resolve()
SCRIPTS = Path(__file__).resolve().parent
if CHECKOUT != SCRIPTS.parent:
    raise RuntimeError('Run from the feature worktree.')
sys.path[:0] = [str(SCRIPTS), str(CHECKOUT)]
os.environ['DJANGO_SETTINGS_MODULE'] = 'synthetic_perf_settings'

import django
django.setup()

from django.contrib.auth import get_user_model
from django.test import Client
from management.models import PatternDesignImage
from staging_nav_benchmark import launch_server
from synthetic_data import assert_isolated_database


def main():
    assert_isolated_database()
    admin = get_user_model().objects.get(username='navsyn_admin')
    client = Client()
    client.force_login(admin)
    image = PatternDesignImage.objects.get(client_upload_key='navsyn-design-0001')
    base, server = launch_server(CHECKOUT)
    results = {}
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(channel='chrome', headless=True)
            context = browser.new_context(viewport={'width': 1440, 'height': 900},
                                          reduced_motion='reduce')
            context.add_cookies([{'name': 'sessionid', 'value': client.session.session_key,
                                  'domain': '127.0.0.1', 'path': '/'}])
            page = context.new_page()
            errors = []
            failures = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.on('requestfailed', lambda request: failures.append(request.url))
            page.on('response', lambda response: failures.append(
                f'{response.status} {response.url}') if response.status >= 400
                and response.url.startswith(base) else None)

            response = page.goto(base + '/car-details/?search=NAVSYN-00001&search_by=layout_code')
            assert response.status == 200
            assert page.locator('tr[id^="row-view-"]').count() == 1
            assert page.locator('#vehicle-search-input').input_value() == 'NAVSYN-00001'
            page.locator('tr[id^="row-view-"] .pattern-row-select').check()
            page.locator('#patternActionsToggleBtn').click()
            assert 'is-open' in (page.locator('#patternActionsDrawer').get_attribute('class') or '')
            results['pattern_search_and_selection'] = 'passed'

            response = page.goto(base + '/complaints/?search=PAT-26100001&search_by=complaint_id')
            assert response.status == 200
            assert page.locator('tr.complaint-info-row').count() == 1
            assert 'PAT-26100001' in page.locator('tr.complaint-info-row').first.inner_text()
            page.locator('tr.complaint-info-row .action-btn.view').click()
            assert page.locator('#modal-PAT-26100001').is_visible()
            results['complaint_search_and_modal'] = 'passed'

            response = page.goto(base + '/complaints/?status=Closed')
            assert response.status == 200
            rows = page.locator('tr.complaint-info-row')
            assert rows.count() == 10
            assert page.locator('tr.complaint-info-row .status-badge.status-closed').count() == 10
            results['complaint_status_filter'] = 'passed'

            page.set_viewport_size({'width': 390, 'height': 844})
            page.goto(base + '/complaints/')
            page.locator('#filter-toggle').click()
            assert page.locator('#mobileFiltersSheet').is_visible()
            results['mobile_filter_drawer'] = 'passed'

            page.set_viewport_size({'width': 1440, 'height': 900})
            response = page.goto(base + '/approvals/')
            assert response.status == 200
            assert page.locator('#app-content').is_visible()
            results['approvals_workspace'] = 'passed'

            response = page.goto(base + f'/car-details/?vehicle_id={image.vehicle_id}#design-options')
            assert response.status == 200
            assert page.locator('#tab-pane-design-options').count() == 1
            results['design_options'] = 'passed'

            media_response = page.request.get(
                base + '/media/pattern_designs/synthetic/design-0001.jpg')
            assert media_response.status == 200
            assert 'image/jpeg' in media_response.headers.get('content-type', '')
            results['placeholder_media'] = 'passed'

            assert not errors, errors
            assert not failures, failures
            results['page_errors'] = errors
            results['request_failures'] = failures
            context.close()
            browser.close()
    finally:
        server.terminate()
        server.wait(timeout=5)
    print(json.dumps(results, indent=2))


if __name__ == '__main__':
    main()
