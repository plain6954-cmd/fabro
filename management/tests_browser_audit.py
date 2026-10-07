"""Real Chrome checks against disposable Django test records and sessions."""

import io
import json
import os
from pathlib import Path
from urllib.parse import urlparse

os.environ['DJANGO_ALLOW_ASYNC_UNSAFE'] = 'true'

from django.contrib.auth import get_user_model
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import Client
from playwright.sync_api import sync_playwright
from PIL import Image

from management.models import (
    ApprovalRoles, Brand, Model, PatternDesignImage, SubModel, UserProfile,
    WorkflowRoles, YearRange,
)


PNG_BUFFER = io.BytesIO()
Image.new('RGB', (2, 2), color=(90, 120, 180)).save(PNG_BUFFER, format='PNG')
PNG = PNG_BUFFER.getvalue()
ARTIFACTS = Path('output/audit-2026-10-07')


class FabroChromeAuditTests(StaticLiveServerTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        ARTIFACTS.mkdir(parents=True, exist_ok=True)
        cls.playwright = sync_playwright().start()
        cls.browser = cls.playwright.chromium.launch(channel='chrome', headless=True)

    @classmethod
    def tearDownClass(cls):
        try:
            cls.browser.close()
            cls.playwright.stop()
        finally:
            super().tearDownClass()

    def setUp(self):
        self.contexts = []
        self.browser_errors = []
        self.timings = []
        self.users = {}
        roles = {
            'admin': (WorkflowRoles.ADMIN, '', True),
            'designer': (WorkflowRoles.FREELANCE_3D_DESIGNER, '', False),
            'other_designer': (WorkflowRoles.FREELANCE_3D_DESIGNER, '', False),
            'cad': (WorkflowRoles.APPROVER, ApprovalRoles.CAD, False),
            'ed': (WorkflowRoles.APPROVER, ApprovalRoles.ED, False),
            'pm': (WorkflowRoles.APPROVER, ApprovalRoles.PM, False),
            'om': (WorkflowRoles.APPROVER, ApprovalRoles.OM, False),
            'md': (WorkflowRoles.APPROVER, ApprovalRoles.MD, False),
            'country': (WorkflowRoles.COUNTRY_EXECUTIVE, '', False),
            'factory': (WorkflowRoles.FACTORY_EXECUTIVE, '', False),
            'registrar': (WorkflowRoles.FACTORY_COMPLAINT_REGISTRAR, '', False),
            'viewer': (WorkflowRoles.FACTORY_VIEWER, '', False),
        }
        User = get_user_model()
        for name, (role, approval_role, is_admin) in roles.items():
            user = User.objects.create_user(
                username=f'audit_{name}', password='AuditOnly!234',
                email=f'{name}@fabro.test', is_staff=is_admin,
                is_superuser=is_admin,
            )
            profile, _ = UserProfile.objects.get_or_create(user=user)
            profile.role, profile.approval_role = role, approval_role
            profile.save()
            self.users[name] = user
        brand = Brand.objects.create(name='TOYOTA')
        model = Model.objects.create(brand=brand, name='RAV4')
        submodel = SubModel.objects.create(model=model, name='BR2')
        self.vehicle = YearRange.objects.create(
            sub_model=submodel, year_start=2026, year_end=2026,
            layout_code='AUDIT-RAV4-BR2', serial_number='A0001',
        )

    def tearDown(self):
        for context in self.contexts:
            context.close()
        super().tearDown()

    def page_as(self, role, viewport=None, touch=False):
        viewport = viewport or {'width': 1366, 'height': 768}
        context = self.browser.new_context(viewport=viewport, reduced_motion='reduce',
                                           has_touch=touch, is_mobile=touch)
        context.add_init_script("""
            window.__fabroLongTasks = [];
            try { new PerformanceObserver(list => {
                for (const entry of list.getEntries()) window.__fabroLongTasks.push(entry.duration);
            }).observe({entryTypes: ['longtask']}); } catch (error) {}
        """)
        self.contexts.append(context)
        client = Client()
        client.force_login(self.users[role])
        context.add_cookies([{
            'name': 'sessionid', 'value': client.session.session_key,
            'domain': urlparse(self.live_server_url).hostname, 'path': '/',
        }])
        page = context.new_page()
        page.on('pageerror', lambda error: self.browser_errors.append({'role': role, 'url': page.url, 'error': str(error)}))
        page.on('response', lambda response: self.browser_errors.append({
            'role': role, 'url': response.url, 'status': response.status,
        }) if '/api/' in response.url and response.status >= 500 else None)
        return page

    def test_pattern_rows_and_designer_dual_approval(self):
        admin = self.page_as('admin')
        admin.goto(f'{self.live_server_url}/car-details/')
        row = admin.locator(f'#row-view-{self.vehicle.pk}')
        row.wait_for()
        row.locator('.pattern-row-select').check()
        self.assertNotIn('vehicle_id=', admin.url)
        row.locator('.col-brand').click()
        admin.wait_for_function(f"location.search.includes('vehicle_id={self.vehicle.pk}')")
        self.assertTrue(admin.locator('#tab-pane-design-options').is_visible())
        admin.screenshot(path=str(ARTIFACTS / 'pattern-master-desktop.png'))

        designer = self.page_as('designer')
        dialogs = []
        designer.on('dialog', lambda dialog: (dialogs.append(dialog.message), dialog.accept()))
        designer.goto(f'{self.live_server_url}/car-details/?vehicle_id={self.vehicle.pk}#design-options')
        designer.locator('#directVehicleImageFileInput').wait_for(state='attached')
        upload_path = ARTIFACTS / 'rav4-audit.png'
        upload_path.write_bytes(PNG)
        with designer.expect_response(lambda response: '/design-images/upload/' in response.url) as upload:
            designer.locator('#directVehicleImageFileInput').set_input_files(str(upload_path))
        self.assertEqual(upload.value.status, 200, upload.value.text())
        designer.locator('#directImagesMatrixGrid .design-matrix-card:not(.is-uploading)').wait_for()
        designer.wait_for_function("document.querySelector('#designDirectImagesCountBadge')?.textContent.trim() === '1'")
        self.assertEqual(designer.locator('#directUploadingSkeleton').count(), 0)
        self.assertFalse(any('session has expired' in message.lower() for message in dialogs))
        image = PatternDesignImage.objects.get(uploaded_by=self.users['designer'])
        self.assertEqual(image.approval_status, 'pending')
        self.assertEqual(image.latest_approval.cad_status, 'pending')
        self.assertEqual(image.latest_approval.ed_status, 'pending')
        designer.screenshot(path=str(ARTIFACTS / 'designer-uploaded.png'))
        # A retried upload of the same selected file returns the same row.
        with designer.expect_response(lambda response: '/design-images/upload/' in response.url) as retry:
            designer.locator('#directVehicleImageFileInput').set_input_files(str(upload_path))
        self.assertEqual(retry.value.status, 200)
        self.assertEqual(retry.value.json()['images'][0]['id'], image.pk)
        self.assertEqual(PatternDesignImage.objects.filter(vehicle=self.vehicle).count(), 1)
        designer.wait_for_function("!document.querySelector('#directUploadingSkeleton')")
        invalid_path = ARTIFACTS / 'invalid-design.txt'
        invalid_path.write_text('not a design image')
        with designer.expect_response(lambda response: '/design-images/upload/' in response.url) as invalid:
            designer.locator('#directVehicleImageFileInput').set_input_files(str(invalid_path))
        self.assertEqual(invalid.value.status, 400)
        designer.wait_for_function("!document.querySelector('#directUploadingSkeleton')")
        self.assertTrue(any('unsupported' in message.lower() for message in dialogs))
        self.assertFalse(any('session has expired' in message.lower() for message in dialogs))
        designer.reload()
        designer.wait_for_function("document.querySelector('#designDirectImagesCountBadge')?.textContent.trim() === '1'")
        self.assertTrue(designer.locator('#directImagesMatrixGrid .design-matrix-card').first.is_visible())

        # Separate Chrome sessions exercise the independent reviewer forms.
        cad = self.page_as('cad')
        ed = self.page_as('ed')
        ed.on('dialog', lambda dialog: dialog.accept())
        url = f'{self.live_server_url}/design-approvals/{image.pk}/'
        cad.goto(url)
        ed.goto(url)
        cad.locator('#cadCommentInput').fill('CAD geometry checked')
        cad.locator('#cadReviewForm button[value="approved"]').click()
        image.refresh_from_db()
        self.assertEqual(image.approval_status, 'pending')
        self.assertEqual(image.latest_approval.status, 'partially_approved')
        ed.locator('#edCommentInput').fill('ED material checked')
        ed.locator('#edReviewForm button[value="approved"]').click()
        image.refresh_from_db()
        self.assertEqual(image.approval_status, 'approved')
        designer.goto(url)
        self.assertIn('CAD geometry checked', designer.content())
        self.assertIn('ED material checked', designer.content())
        designer.screenshot(path=str(ARTIFACTS / 'dual-approval-complete.png'))

        revised_path = ARTIFACTS / 'rav4-revision.png'
        revised_path.write_bytes(PNG)
        designer.goto(f'{self.live_server_url}/car-details/?vehicle_id={self.vehicle.pk}#design-options')
        with designer.expect_response(lambda response: '/design-images/upload/' in response.url) as second_upload:
            designer.locator('#directVehicleImageFileInput').set_input_files(str(revised_path))
        self.assertEqual(second_upload.value.status, 200)
        second_id = second_upload.value.json()['images'][0]['id']
        second_url = f'{self.live_server_url}/design-approvals/{second_id}/'
        ed.goto(second_url)
        ed.locator('#edCommentInput').fill('ED asks for corrected seam')
        ed.locator('#edReviewForm button[value="rejected"]').click()
        second = PatternDesignImage.objects.get(pk=second_id)
        self.assertEqual(second.approval_status, 'rejected')
        cad.goto(second_url)
        cad.locator('#cadCommentInput').fill('CAD dimensions pass')
        cad.locator('#cadReviewForm button[value="approved"]').click()
        second.refresh_from_db()
        self.assertEqual(second.latest_approval.ed_status, 'rejected')
        self.assertEqual(second.latest_approval.cad_status, 'approved')
        designer.goto(second_url)
        self.assertIn('ED asks for corrected seam', designer.content())
        self.assertIn('CAD dimensions pass', designer.content())
        resubmit = designer.locator('form:has(input[name="action"][value="resubmit"])')
        resubmit.locator('input[type="file"]').set_input_files(str(upload_path))
        with designer.expect_navigation():
            resubmit.locator('button[type="submit"]').click()
        second.refresh_from_db()
        self.assertEqual(second.latest_approval.cycle, 2)
        self.assertEqual(second.latest_approval.cad_status, 'pending')
        self.assertEqual(second.latest_approval.ed_status, 'pending')
        ed.goto(second_url)
        ed.locator('#edCommentInput').fill('ED revised seam passes')
        ed.locator('#edReviewForm button[value="approved"]').click()
        second.refresh_from_db()
        self.assertEqual(second.approval_status, 'pending')
        cad.goto(second_url)
        cad.locator('#cadCommentInput').fill('CAD revised pattern passes')
        cad.locator('#cadReviewForm button[value="approved"]').click()
        second.refresh_from_db()
        self.assertEqual(second.approval_status, 'approved')
        designer.goto(second_url)
        self.assertIn('ED revised seam passes', designer.content())
        self.assertIn('CAD revised pattern passes', designer.content())
        designer.screenshot(path=str(ARTIFACTS / 'dual-approval-resubmitted.png'))

        other = self.page_as('other_designer')
        response = other.goto(second_url)
        self.assertEqual(response.status, 403)
        self.assertEqual(self.browser_errors, [])
        (ARTIFACTS / 'browser-interaction-errors.json').write_text(json.dumps(self.browser_errors, indent=2))

    def test_role_routes_and_responsive_chrome_viewports(self):
        sizes = [
            (320, 568), (360, 800), (390, 844), (568, 320),
            (768, 1024), (1024, 768), (1366, 768), (1920, 1080), (2560, 1080),
        ]
        for role in self.users:
            page = self.page_as(role)
            response = page.goto(f'{self.live_server_url}/car-details/')
            self.assertEqual(response.status, 200, role)
            self.assertTrue(page.locator(f'#row-view-{self.vehicle.pk}').count(), role)
            page.locator(f'#row-view-{self.vehicle.pk} .col-brand').click()
            page.wait_for_function(f"location.search.includes('vehicle_id={self.vehicle.pk}')")
            page.wait_for_load_state('networkidle')
            page.goto(f'{self.live_server_url}/car-details/')
            response = page.goto(f'{self.live_server_url}/design-approvals/')
            allowed = role in {'admin', 'designer', 'other_designer', 'cad', 'ed'}
            self.assertEqual(response.status, 200 if allowed else 403, role)
            response = page.goto(f'{self.live_server_url}/approvals/')
            complaint_allowed = role in {'admin', 'cad', 'ed', 'pm', 'om', 'md', 'country', 'factory'}
            if complaint_allowed:
                self.assertEqual(response.status, 200, (role, page.url))
                self.assertEqual(urlparse(page.url).path, '/approvals/', role)
            else:
                self.assertTrue(response.status == 403 or urlparse(page.url).path in {'/login/', '/'},
                                (role, response.status, page.url))
            page.context.close()

        for role, route in [
            ('admin', '/car-details/'), ('designer', '/car-details/'),
            ('cad', '/design-approvals/'), ('admin', '/admin_panel/'),
        ]:
            page = self.page_as(role)
            for width, height in sizes:
                page.set_viewport_size({'width': width, 'height': height})
                response = page.goto(f'{self.live_server_url}{route}')
                self.assertEqual(response.status, 200, (role, route, width, height))
                overflow = page.evaluate('document.documentElement.scrollWidth - innerWidth')
                self.assertLessEqual(overflow, 2, (role, route, width, height, overflow))
                timing = page.evaluate("""() => {
                    const n = performance.getEntriesByType('navigation')[0];
                    return {ttfb_ms: Math.round(n.responseStart - n.requestStart),
                        dom_ms: Math.round(n.domContentLoadedEventEnd - n.startTime),
                        load_ms: Math.round(n.loadEventEnd - n.startTime),
                        long_tasks: window.__fabroLongTasks || []};
                }""")
                self.timings.append({'role': role, 'route': route, 'width': width, 'height': height, **timing})
                if width == 320:
                    page.screenshot(path=str(ARTIFACTS / f'{role}-{route.strip("/").replace("/", "-")}-320.png'))
            # Effective CSS viewport for 1366x768 at 200%; headless Chrome
            # does not change page zoom from the keyboard shortcut.
            page.set_viewport_size({'width': 683, 'height': 384})
            page.goto(f'{self.live_server_url}{route}')
            overflow = page.evaluate('document.documentElement.scrollWidth - innerWidth')
            self.assertLessEqual(overflow, 2, (role, route, '200% effective viewport', overflow))
            page.context.close()
        (ARTIFACTS / 'chrome-timings.json').write_text(json.dumps(self.timings, indent=2))
        (ARTIFACTS / 'browser-responsive-errors.json').write_text(json.dumps(self.browser_errors, indent=2))
        self.assertEqual(self.browser_errors, [])

    def test_chrome_performance_recording(self):
        summaries = []
        for role, route in [
            ('admin', '/car-details/'),
            ('designer', f'/car-details/?vehicle_id={self.vehicle.pk}#design-options'),
            ('cad', '/design-approvals/'),
        ]:
            page = self.page_as(role)
            design_list_requests = []
            page.on('request', lambda request: design_list_requests.append(request.url)
                    if '/api/design-folders/?' in request.url else None)
            cdp = page.context.new_cdp_session(page)
            events = []
            cdp.on('Tracing.dataCollected', lambda payload: events.extend(payload.get('value', [])))
            cdp.send('Tracing.start', {
                'categories': 'devtools.timeline,blink.user_timing',
                'transferMode': 'ReportEvents',
            })
            response = page.goto(f'{self.live_server_url}{route}')
            self.assertEqual(response.status, 200)
            page.wait_for_load_state('networkidle')
            cdp.send('Tracing.end')
            page.wait_for_timeout(300)
            tasks = [event.get('dur', 0) / 1000 for event in events
                     if event.get('name') in {'RunTask', 'ThreadControllerImpl::RunTask'}
                     and event.get('dur', 0) >= 50_000]
            expensive = sorted((event for event in events if event.get('dur', 0) >= 50_000),
                               key=lambda event: event.get('dur', 0), reverse=True)[:8]
            observed_tasks = page.evaluate('window.__fabroLongTasks || []')
            frames = sorted(event.get('ts', 0) for event in events if event.get('name') == 'DrawFrame')
            frame_gaps = [(b - a) / 1000 for a, b in zip(frames, frames[1:])]
            summaries.append({
                'role': role, 'route': route,
                'long_task_count': len(tasks),
                'max_task_ms': round(max(tasks, default=0), 1),
                'observer_long_task_count': len(observed_tasks),
                'observer_max_task_ms': round(max(observed_tasks, default=0), 1),
                'top_trace_slices': [
                    {'name': event.get('name'), 'duration_ms': round(event['dur'] / 1000, 1)}
                    for event in expensive
                ],
                'frame_gap_over_50ms_count': sum(gap > 50 for gap in frame_gaps),
                'max_frame_gap_ms': round(max(frame_gaps, default=0), 1),
                'trace_event_count': len(events),
                'design_list_request_count': len(design_list_requests),
            })
        (ARTIFACTS / 'chrome-performance-recording.json').write_text(json.dumps(summaries, indent=2))
        self.assertEqual(self.browser_errors, [])

    def test_role_page_sweep_in_chrome(self):
        routes = [
            '/', '/car-details/', '/complaints/', '/add-complaint/',
            '/approvals/', '/design-approvals/', '/add-sku/',
            '/master-settings/', '/admin_panel/', '/profile/',
            '/notifications/', '/chat/',
        ]
        coverage = []
        for role in self.users:
            page = self.page_as(role)
            for route in routes:
                response = page.goto(f'{self.live_server_url}{route}')
                page.wait_for_load_state('domcontentloaded')
                coverage.append({
                    'role': role, 'route': route, 'status': response.status,
                    'final_path': urlparse(page.url).path,
                    'overflow_px': page.evaluate('document.documentElement.scrollWidth - innerWidth'),
                    'page_error_count': len(self.browser_errors),
                })
            page.context.close()
        (ARTIFACTS / 'role-page-coverage.json').write_text(json.dumps(coverage, indent=2))
        failures = [row for row in coverage if row['status'] >= 500]
        self.assertEqual(failures, [])
        self.assertEqual(self.browser_errors, [])

    def test_pattern_touch_scroll_and_nested_menu(self):
        page = self.page_as('designer', {'width': 390, 'height': 844}, touch=True)
        page.goto(f'{self.live_server_url}/car-details/')
        row = page.locator(f'#row-view-{self.vehicle.pk}')
        row.wait_for()
        card = row.locator('.pattern-mobile-card')
        card.scroll_into_view_if_needed()
        box = card.bounding_box()
        self.assertIsNotNone(box)
        x = box['x'] + min(80, box['width'] / 2)
        y = box['y'] + min(120, box['height'] / 2)
        cdp = page.context.new_cdp_session(page)
        cdp.send('Input.dispatchTouchEvent', {'type': 'touchStart', 'touchPoints': [{'x': x, 'y': y}]})
        cdp.send('Input.dispatchTouchEvent', {'type': 'touchMove', 'touchPoints': [{'x': x, 'y': y - 80}]})
        cdp.send('Input.dispatchTouchEvent', {'type': 'touchEnd', 'touchPoints': []})
        page.wait_for_timeout(100)
        self.assertNotIn('vehicle_id=', page.url)
        more = page.locator(f'#cardActionsBtn-{self.vehicle.pk}')
        more.scroll_into_view_if_needed()
        button_box = more.bounding_box()
        page.touchscreen.tap(button_box['x'] + button_box['width'] / 2,
                             button_box['y'] + button_box['height'] / 2)
        self.assertNotIn('vehicle_id=', page.url)
        self.assertTrue(page.locator(f'#cardActionsMenu-{self.vehicle.pk}').is_visible())
        page.locator(f'#cardActionsMenu-{self.vehicle.pk} .action-design').click()
        page.wait_for_function(f"location.search.includes('vehicle_id={self.vehicle.pk}')")
        self.assertTrue(page.locator('#tab-pane-design-options').is_visible())
