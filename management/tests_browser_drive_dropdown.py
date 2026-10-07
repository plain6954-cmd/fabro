import os
os.environ["DJANGO_ALLOW_ASYNC_UNSAFE"] = "true"
import time
from tempfile import gettempdir
from django.contrib.auth import get_user_model
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from playwright.sync_api import sync_playwright

from management.models import (
    Brand,
    Model,
    SubModel,
    YearRange,
    VehicleDriveLink,
    UserProfile,
    WorkflowRoles,
)

User = get_user_model()
ARTIFACTS_DIR = os.path.join(gettempdir(), "fabro-drive-dropdown-tests")
os.makedirs(ARTIFACTS_DIR, exist_ok=True)


class DriveDropdownLiveBrowserTests(StaticLiveServerTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.playwright = sync_playwright().start()
        cls.browser = cls.playwright.chromium.launch(headless=True)

    @classmethod
    def tearDownClass(cls):
        try:
            cls.browser.close()
            cls.playwright.stop()
        finally:
            super().tearDownClass()

    def setUp(self):
        super().setUp()
        self.context = self.browser.new_context(viewport={'width': 1440, 'height': 900})
        self.page = self.context.new_page()

        # Create Superuser
        self.superuser = User.objects.create_superuser(
            username='admin_browser',
            password='Password123!',
            email='admin_browser@fabro.test',
        )

        # Create Normal User
        self.normal_user = User.objects.create_user(
            username='staff_browser',
            password='Password123!',
            email='staff_browser@fabro.test',
        )
        profile, _ = UserProfile.objects.get_or_create(user=self.normal_user)
        profile.role = WorkflowRoles.COUNTRY_EXECUTIVE
        profile.save()

        # Create Vehicle
        self.brand = Brand.objects.create(name='Toyota')
        self.model = Model.objects.create(brand=self.brand, name='Land Cruiser')
        self.sub_model = SubModel.objects.create(model=self.model, name='HT76')
        self.vehicle = YearRange.objects.create(
            sub_model=self.sub_model,
            year_start=1990,
            year_end=2021,
            serial_number='I1001',
            layout_code='LC-HT76-LIVE-01',
            google_drive_url='',
        )

    def tearDown(self):
        self.context.close()
        super().tearDown()

    def _wait_for_badge(self, page, expected_count, timeout=6.0):
        start = time.time()
        badge = page.locator("#vehicleDriveLinksCountBadge")
        while time.time() - start < timeout:
            try:
                if badge.is_visible() and badge.inner_text().strip() == str(expected_count):
                    return
            except Exception:
                pass
            time.sleep(0.1)
        self.assertEqual(badge.inner_text().strip(), str(expected_count))

    def test_drive_dropdown_all_features_e2e(self):
        page = self.page
        page.on("dialog", lambda dialog: dialog.accept())

        from urllib.parse import urlparse
        from django.test import Client
        parsed = urlparse(self.live_server_url)

        # -------------------------------------------------------------
        # STEP 1: Superuser Login & Navigate
        # -------------------------------------------------------------
        c = Client()
        c.force_login(self.superuser)
        self.context.add_cookies([{
            'name': 'sessionid',
            'value': c.session.session_key,
            'domain': parsed.hostname,
            'path': '/',
        }])

        car_url = f"{self.live_server_url}/car-details/?vehicle_id={self.vehicle.id}#design-options"
        page.goto(car_url)
        page.wait_for_selector("#vehicleGoogleDriveBtn")

        # Initial badge count should be 0 or hidden
        badge = page.locator("#vehicleDriveLinksCountBadge")

        # -------------------------------------------------------------
        # STEP 2: Open Dropdown and verify initial empty state
        # -------------------------------------------------------------
        page.click("#vehicleGoogleDriveBtn")
        dropdown = page.locator("#vehicleGoogleDriveDropdownMenu")
        self.assertTrue(dropdown.is_visible())

        # Empty state visible initially
        empty_msg = page.locator("#vehicleDriveLinksEmpty")
        self.assertTrue(empty_msg.is_visible())
        self.assertIn("No Drive links added yet", empty_msg.inner_text())

        # Superuser add section visible
        add_section = page.locator("#googleDriveAddSection")
        self.assertTrue(add_section.is_visible())

        screenshot_01 = os.path.join(ARTIFACTS_DIR, "browser_feat_01_empty_superuser_dropdown.png")
        page.screenshot(path=screenshot_01)

        # -------------------------------------------------------------
        # STEP 3: Add Link 1 (with custom title)
        # -------------------------------------------------------------
        page.fill("#vehicleDriveLinkTitleInput", "Official CAD Master Models")
        page.fill("#vehicleDriveLinkUrlInput", "https://drive.google.com/drive/folders/cad-official-master")
        page.click("#vehicleDriveLinkAddBtn")

        page.wait_for_selector(".vehicle-drive-link-row", timeout=5000)
        self.assertEqual(badge.inner_text().strip(), "1")
        self.assertTrue(badge.is_visible())
        self.assertFalse(empty_msg.is_visible())

        # -------------------------------------------------------------
        # STEP 4: Add Link 2 (without custom title - test default title fallback)
        # -------------------------------------------------------------
        page.fill("#vehicleDriveLinkTitleInput", "")
        page.fill("#vehicleDriveLinkUrlInput", "https://drive.google.com/file/d/seat-pattern-upholstery-specs/view")
        page.click("#vehicleDriveLinkAddBtn")

        # Wait until badge updates to 2
        self._wait_for_badge(page, 2)

        # -------------------------------------------------------------
        # STEP 5: Add more links (3, 4, 5) to test scrollable container
        # -------------------------------------------------------------
        links_data = [
            ("Door Panel References", "https://drive.google.com/drive/folders/door-panels-03"),
            ("Console & Armrest Templates", "https://drive.google.com/drive/folders/armrest-04"),
            ("3D Scan Archive", "https://drive.google.com/drive/folders/3d-scans-archive-05"),
        ]
        for title, url in links_data:
            page.fill("#vehicleDriveLinkTitleInput", title)
            page.fill("#vehicleDriveLinkUrlInput", url)
            page.click("#vehicleDriveLinkAddBtn")
            time.sleep(0.3)

        self._wait_for_badge(page, 5)

        # Verify scrollable container has overflow scroll / styling
        scroll_container = page.locator("#vehicleDriveLinksScrollContainer")
        self.assertTrue(scroll_container.is_visible())
        # Check that there are 5 link rows
        link_rows = page.locator(".vehicle-drive-link-row")
        self.assertEqual(link_rows.count(), 5)

        # Verify link target and rel attributes
        first_link_a = page.locator(".vehicle-drive-link-row a").first
        self.assertEqual(first_link_a.get_attribute("target"), "_blank")
        self.assertIn("noopener", first_link_a.get_attribute("rel"))

        screenshot_02 = os.path.join(ARTIFACTS_DIR, "browser_feat_02_multiple_links_scrollable.png")
        page.screenshot(path=screenshot_02)

        # -------------------------------------------------------------
        # STEP 6: Close Dropdown using ESCAPE key
        # -------------------------------------------------------------
        page.keyboard.press("Escape")
        time.sleep(0.3)
        self.assertFalse(dropdown.is_visible())

        screenshot_03 = os.path.join(ARTIFACTS_DIR, "browser_feat_03_dropdown_closed_via_escape.png")
        page.screenshot(path=screenshot_03)

        # Reopen by clicking button
        page.click("#vehicleGoogleDriveBtn")
        self.assertTrue(dropdown.is_visible())

        # Close by clicking outside (on design section title)
        page.locator(".design-section-title").first.click()
        time.sleep(0.3)
        self.assertFalse(dropdown.is_visible())

        # Reopen for delete test
        page.click("#vehicleGoogleDriveBtn")
        self.assertTrue(dropdown.is_visible())

        # -------------------------------------------------------------
        # STEP 7: Delete a link and verify badge & database update
        # -------------------------------------------------------------
        del_btns = page.locator(".drive-link-del-btn")
        self.assertEqual(del_btns.count(), 5)
        # Click the first delete button
        del_btns.first.click()
        time.sleep(0.5)

        self._wait_for_badge(page, 4)
        self.assertEqual(VehicleDriveLink.objects.filter(vehicle=self.vehicle).count(), 4)

        screenshot_04 = os.path.join(ARTIFACTS_DIR, "browser_feat_04_link_deleted_badge_updated.png")
        page.screenshot(path=screenshot_04)

        # -------------------------------------------------------------
        # STEP 8: Non-Superuser Permission Check (Clean Isolated Context)
        # -------------------------------------------------------------
        staff_context = self.browser.new_context(viewport={'width': 1440, 'height': 900})
        staff_page = staff_context.new_page()
        try:
            c_staff = Client()
            c_staff.force_login(self.normal_user)
            staff_context.add_cookies([{
                'name': 'sessionid',
                'value': c_staff.session.session_key,
                'domain': parsed.hostname,
                'path': '/',
            }])

            staff_page.goto(car_url)
            staff_page.wait_for_selector("#vehicleGoogleDriveBtn")

            # Wait for API to load drive links and update badge to 4
            self._wait_for_badge(staff_page, 4)

            # Open dropdown as non-superuser
            staff_dropdown = staff_page.locator("#vehicleGoogleDriveDropdownMenu")
            staff_page.click("#vehicleGoogleDriveBtn")
            self.assertTrue(staff_dropdown.is_visible())

            # Verify add section is NOT rendered or visible
            staff_add_section = staff_page.locator("#googleDriveAddSection")
            self.assertFalse(staff_add_section.is_visible())

            # Verify links are still visible to non-superuser
            staff_link_rows = staff_page.locator(".vehicle-drive-link-row")
            self.assertEqual(staff_link_rows.count(), 4)

            # Verify delete buttons are NOT rendered or visible for non-superuser
            staff_del_btns = staff_page.locator(".drive-link-del-btn")
            self.assertEqual(staff_del_btns.count(), 0)

            screenshot_05 = os.path.join(ARTIFACTS_DIR, "browser_feat_05_non_superuser_view.png")
            staff_page.screenshot(path=screenshot_05)
        finally:
            staff_context.close()
