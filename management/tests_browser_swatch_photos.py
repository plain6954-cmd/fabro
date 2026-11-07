"""Real browser swatch-gallery checks using the isolated PostgreSQL test server."""
import base64
import io
import os
import socket
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Condition, Event
from unittest.mock import patch
from urllib.parse import urlparse

os.environ['DJANGO_ALLOW_ASYNC_UNSAFE'] = 'true'

from django.contrib.auth import get_user_model
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.core.servers.basehttp import ThreadedWSGIServer
from django.test import Client, override_settings
from django.test.testcases import LiveServerThread
from PIL import Image
from playwright.sync_api import expect, sync_playwright

from management.models import Brand, ColorMaster, Model, PickedColorPhoto, PickedColorSelection, SubModel, WorkflowRoles, YearRange


def photo(name, color):
    stream = io.BytesIO()
    Image.new('RGB', (24, 16), color).save(stream, 'PNG')
    return {'name':name, 'mimeType':'image/png', 'buffer':stream.getvalue()}


class DrainingSwatchServer(ThreadedWSGIServer):
    """Finish aborted browser requests before TransactionTestCase flushes PostgreSQL."""

    def __init__(self, *args, **kwargs):
        self.requests_finished = Condition()
        self.request_sockets = set()
        super().__init__(*args, **kwargs)

    def process_request(self, request, client_address):
        with self.requests_finished:
            self.request_sockets.add(request)
        super().process_request(request, client_address)

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            with self.requests_finished:
                self.request_sockets.discard(request)
                self.requests_finished.notify_all()

    def drain(self):
        # Chromium's API-request pool can leave keep-alive sockets idle after
        # context.close(). Wake their handlers without interrupting DB cleanup.
        with self.requests_finished:
            for request in tuple(self.request_sockets):
                try:
                    request.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
            return self.requests_finished.wait_for(lambda: not self.request_sockets, timeout=15)


class SwatchLiveServerThread(LiveServerThread):
    server_class = DrainingSwatchServer


class MatchingSwatchBrowserTests(StaticLiveServerTestCase):
    server_thread_class = SwatchLiveServerThread

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
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
        self.media = TemporaryDirectory(prefix='swatch-browser-')
        self.addCleanup(self.media.cleanup)
        config = override_settings(MEDIA_ROOT=self.media.name, USE_S3_STORAGE=False, USE_SUPABASE_STORAGE=False,
            STORAGES={'default':{'BACKEND':'django.core.files.storage.FileSystemStorage'},
                      'staticfiles':{'BACKEND':'django.contrib.staticfiles.storage.StaticFilesStorage'}})
        config.enable()
        self.addCleanup(config.disable)
        self.owner = get_user_model().objects.create_user('swatch-browser-owner')
        self.owner.workflow_profile.role = WorkflowRoles.FREELANCE_3D_DESIGNER
        self.owner.workflow_profile.save()
        brand = Brand.objects.create(name='Swatch Browser Brand')
        model = Model.objects.create(brand=brand, name='Swatch Browser Model')
        sub = SubModel.objects.create(model=model, name='Swatch Browser Sub')
        self.vehicle = YearRange.objects.create(sub_model=sub, layout_code='SWATCH-BROWSER')
        self.red = ColorMaster.objects.create(name='Browser Red', color_code='SW-R', hex_code='#FF0000')
        self.blue = ColorMaster.objects.create(name='Browser Blue', color_code='SW-B', hex_code='#0000FF')
        self.context = self.browser.new_context(viewport={'width':1366,'height':768}, reduced_motion='reduce', has_touch=True)
        self.addCleanup(self.context.close)
        client = Client()
        client.force_login(self.owner)
        self.context.add_cookies([{'name':'sessionid','value':client.session.session_key,
                                  'domain':urlparse(self.live_server_url).hostname,'path':'/'}])
        self.page = self.context.new_page()
        self.page.on('dialog', lambda dialog: dialog.accept())
        self.errors, self.server_errors = [], []
        self.page.on('pageerror', lambda error: self.errors.append(str(error)))
        self.page.on('response', lambda response: self.server_errors.append(response.url) if response.status == 500 else None)
        self.page.goto(f'{self.live_server_url}/car-details/?vehicle_id={self.vehicle.pk}#measurements')
        self.gallery = self.page.locator('#matchingSwatchGallery')
        expect(self.gallery).to_be_visible()
        expect(self.gallery.locator('[data-swatch-add]')).to_be_enabled()
        self.page.locator('#selectExistingSingleColor').select_option(str(self.red.pk))

    def tearDown(self):
        self.context.close()
        server = self.server_thread.httpd
        self.assertTrue(server.drain(), 'Live browser requests must finish before the test database is flushed')
        super().tearDown()

    def add(self, files):
        with self.page.expect_file_chooser() as chooser:
            self.gallery.locator('[data-swatch-add]').click()
        chooser.value.set_files(files)

    def settled(self, count):
        expect(self.gallery.locator('.swatch-photo-tile')).to_have_count(count)
        expect(self.gallery.locator('.is-pending')).to_have_count(0, timeout=15000)
        expect(self.gallery.locator('.is-failed')).to_have_count(0)

    def test_desktop_save_append_edit_refresh_and_independent_remove(self):
        red, blue, green = photo('red.png','red'), photo('blue.png','blue'), photo('green.png','green')
        self.add([red, blue])
        expect(self.gallery.locator('.swatch-photo-tile')).to_have_count(2)
        self.assertEqual(PickedColorSelection.objects.count(), 0)
        self.assertEqual(PickedColorPhoto.objects.count(), 0)
        expect(self.gallery.locator('.swatch-photo-open img').first).to_have_js_property('naturalWidth', 24)
        baseline = self.page.evaluate('[document.body.style.overflow,document.documentElement.style.overflow]')
        self.gallery.locator('.swatch-photo-open').first.click()
        viewer = self.page.locator('#matchingSwatchViewer')
        expect(viewer).to_be_visible()
        self.assertEqual(viewer.locator('[data-swatch-media] img').evaluate('(img)=>getComputedStyle(img).objectFit'), 'contain')
        self.page.keyboard.press('ArrowRight')
        expect(viewer.locator('[data-swatch-caption]')).to_contain_text('2 / 2')
        self.page.keyboard.press('Escape')
        expect(viewer).not_to_be_visible()
        self.assertEqual(self.page.evaluate('[document.body.style.overflow,document.documentElement.style.overflow]'), baseline)
        self.page.locator('#btnSaveColorSelection').click()
        self.settled(2)
        row = PickedColorSelection.objects.get()
        source_id = row.source_selection_id
        self.assertEqual(row.swatch_photos.filter(uploaded_at__isnull=False).count(), 2)
        self.assertEqual(len(list(Path(self.media.name).rglob('*.png'))), 2)
        self.page.reload()
        tile = self.page.locator(f'[data-picked-id="{row.pk}"]')
        expect(tile.locator('.picked-color-photo-strip button')).to_have_count(2)
        tile.locator('[data-picked-action="edit"]').click()
        self.settled(2)
        self.add([green])
        self.settled(3)
        self.page.locator('#selectExistingSingleColor').select_option(str(self.blue.pk))
        self.page.locator('#pickedColorRemarks').fill('Keep all matching photos on color edit')
        self.page.locator('#btnSaveColorSelection').click()
        expect(self.page.locator('#pickedEditNotice')).to_contain_text('saved')
        expect(self.page.locator('#btnSaveColorSelection')).to_be_enabled()
        self.settled(3)
        row.refresh_from_db()
        self.assertNotEqual(row.source_selection_id, source_id)
        self.assertEqual(PickedColorSelection.objects.count(), 1)
        second = row.swatch_photos.get(filename='blue.png')
        self.gallery.get_by_role('button', name='Remove blue.png', exact=True).click()
        self.settled(2)
        second.refresh_from_db()
        self.assertIsNotNone(second.removed_at)
        self.assertTrue(second.image.storage.exists(second.image.name))
        history = self.context.request.get(f'{self.live_server_url}/color-selections/{source_id}/photos/{second.pk}/file/')
        self.assertEqual(history.status, 200)
        self.assertEqual(history.body(), blue['buffer'])
        expect(self.gallery.locator('[data-swatch-add]')).to_be_enabled()
        self.gallery.screenshot(path='output/swatch-gallery-desktop.png')
        self.assertEqual((self.errors, self.server_errors), ([], []))

    def test_mobile_drop_keyboard_invalid_files_and_heic_fallback(self):
        self.page.set_viewport_size({'width':390,'height':844})
        plus_button = self.gallery.locator('[data-swatch-add]')
        plus_button.scroll_into_view_if_needed()
        expect(plus_button).to_be_enabled()
        plus_button.focus()
        expect(plus_button).to_be_focused()
        with self.page.expect_file_chooser() as chooser:
            plus_button.press('Enter')
        chooser.value.set_files([photo('keyboard.png','red')])
        payload = photo('dropped.png','blue')
        transfer = self.page.evaluate_handle('''data=>{const dt=new DataTransfer();dt.items.add(new File([Uint8Array.from(atob(data.bytes),c=>c.charCodeAt(0))],data.name,{type:'image/png'}));return dt;}''',
            {'name':payload['name'], 'bytes':base64.b64encode(payload['buffer']).decode()})
        self.gallery.dispatch_event('dragenter', {'dataTransfer':transfer})
        expect(self.gallery).to_have_class('matching-swatch-gallery is-dragging')
        self.gallery.dispatch_event('drop', {'dataTransfer':transfer})
        expect(self.gallery.locator('.swatch-photo-tile')).to_have_count(2)
        self.assertNotIn('is-dragging', self.gallery.get_attribute('class'))
        self.add([{'name':'invalid.txt','mimeType':'text/plain','buffer':b'not a photo'}])
        expect(self.gallery.locator('.is-failed')).to_have_count(1)
        self.page.locator('#btnSaveColorSelection').click()
        expect(self.page.locator('#pickedEditNotice')).to_contain_text('Remove invalid photos')
        self.assertFalse(PickedColorSelection.objects.exists())
        self.gallery.get_by_role('button', name='Remove invalid.txt', exact=True).click()
        self.add([{'name':'phone.heic','mimeType':'image/heic','buffer':b'opaque HEIC test fixture'}])
        self.page.locator('#btnSaveColorSelection').click()
        self.settled(3)
        heic = PickedColorPhoto.objects.get(filename='phone.heic')
        self.assertEqual(heic.file_size, len(b'opaque HEIC test fixture'))
        boxes = self.gallery.locator('.swatch-photo-tile').evaluate_all('(tiles)=>tiles.map(el=>({w:el.getBoundingClientRect().width,h:el.getBoundingClientRect().height}))')
        self.assertTrue(all(abs(box['w']-box['h']) < 1 for box in boxes))
        self.assertLessEqual(self.page.evaluate('document.documentElement.scrollWidth-innerWidth'), 1)
        plus = self.gallery.locator('[data-swatch-add]').bounding_box()
        self.assertEqual((round(plus['width']),round(plus['height'])), (40,40))
        self.assertLess(self.gallery.bounding_box()['height'], 330)
        self.gallery.locator('.swatch-photo-open').first.tap()
        viewer = self.page.locator('#matchingSwatchViewer')
        expect(viewer).to_be_visible()
        box = viewer.bounding_box()
        self.assertGreaterEqual(box['x'], 0)
        self.assertLessEqual(box['x'] + box['width'], 391)
        viewer.locator('[data-swatch-next]').tap()
        expect(viewer.locator('[data-swatch-caption]')).to_contain_text('2 / 3')
        viewer.locator('[data-swatch-close]').tap()
        expect(viewer).not_to_be_visible()
        self.gallery.screenshot(path='output/swatch-gallery-mobile.png')
        self.assertEqual((self.errors, self.server_errors), ([], []))

    def test_actual_processing_failure_retry_and_inflight_cancellation(self):
        self.add([photo('retry.png','red')])
        storage = PickedColorPhoto._meta.get_field('image').storage
        original = storage.save
        started, release = Event(), Event()
        def delayed_failure(name, content, **kwargs):
            started.set()
            if not release.wait(15):
                raise TimeoutError('Test storage gate did not open')
            raise OSError('Controlled test storage interruption')
        with patch.object(storage, 'save', side_effect=delayed_failure):
            self.page.locator('#btnSaveColorSelection').click()
            self.assertTrue(started.wait(5))
            try:
                expect(self.gallery.locator('[data-progress-label]')).to_contain_text('Processing')
                expect(self.gallery.locator('[role=progressbar]')).to_have_attribute('aria-valuenow','100')
                expect(self.gallery.locator('.is-pending')).to_have_count(1)
                self.assertFalse(PickedColorPhoto.objects.filter(uploaded_at__isnull=False).exists())
            finally:
                release.set()
            expect(self.gallery.locator('.swatch-photo-retry')).to_be_enabled()
        self.gallery.locator('.swatch-photo-retry').click()
        self.settled(1)
        self.assertEqual(PickedColorSelection.objects.count(), 1)
        self.assertEqual(PickedColorPhoto.objects.filter(uploaded_at__isnull=False).count(), 1)
        started, release = Event(), Event()
        def delayed_success(name, content, **kwargs):
            started.set()
            if not release.wait(15):
                raise TimeoutError('Test cancellation gate did not open')
            return original(name, content, **kwargs)
        with patch.object(storage, 'save', side_effect=delayed_success):
            self.add([photo('cancel.png','blue')])
            self.assertTrue(started.wait(5))
            try:
                self.gallery.get_by_role('button', name='Remove cancel.png', exact=True).click()
            finally:
                release.set()
            self.settled(1)
        cancelled = PickedColorPhoto.objects.get(filename='cancel.png')
        self.assertIsNotNone(cancelled.removed_at)
        self.assertTrue(cancelled.approval_selections.exists())
        self.assertTrue(cancelled.image.storage.exists(cancelled.image.name))
        self.assertEqual((self.errors, self.server_errors), ([], []))
