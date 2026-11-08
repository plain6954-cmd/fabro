"""Real Chrome version/status/stamp checks with local PostgreSQL and local media."""
from datetime import timedelta
import hashlib
import io
import json
from tempfile import TemporaryDirectory
from unittest.mock import patch
from urllib.parse import urlparse

from django.contrib.auth.models import User
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.core.files.base import ContentFile
from django.test import Client, override_settings
from django.urls import reverse
from django.utils import timezone
from PIL import Image
from playwright.sync_api import expect, sync_playwright

from management import tests_browser_swatch_photos as browser_support
from management.models import (Brand, Model, SubModel, YearRange, WorkflowRoles,
    PatternDesignImage, PatternDesignApproval)
from management.services.design_approvals import record_design_review_decision, submit_design_for_approval


class DesignStatusBrowserTests(StaticLiveServerTestCase):
    server_thread_class=browser_support.SwatchLiveServerThread

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.playwright=sync_playwright().start()
        cls.browser=cls.playwright.chromium.launch(channel='chrome',headless=True)

    @classmethod
    def tearDownClass(cls):
        try:cls.browser.close();cls.playwright.stop()
        finally:super().tearDownClass()

    def setUp(self):
        self.media=TemporaryDirectory(prefix='status-browser-');self.addCleanup(self.media.cleanup)
        config=override_settings(MEDIA_ROOT=self.media.name,USE_S3_STORAGE=False,USE_SUPABASE_STORAGE=False,
            STORAGES={'default':{'BACKEND':'django.core.files.storage.FileSystemStorage'},
                      'staticfiles':{'BACKEND':'django.contrib.staticfiles.storage.StaticFilesStorage'}})
        config.enable();self.addCleanup(config.disable)
        push=patch('management.services.push_notifications.send_push_to_user');push.start();self.addCleanup(push.stop)
        self.designer=self.account('status-browser-designer',WorkflowRoles.FREELANCE_3D_DESIGNER)
        self.users={role:self.account('status-browser-'+role.lower(),WorkflowRoles.APPROVER,role) for role in ('CAD','ED','MD','OM')}
        self.brand=Brand.objects.create(name='HONDA & Partner')
        self.model=Model.objects.create(brand=self.brand,name='ACCORD')
        self.variant=SubModel.objects.create(model=self.model,name='N1')
        self.vehicle=self.pattern(br='Hybrid',year_start=2013,year_end=2017)
        now=timezone.now()
        self.approved=self.design(self.vehicle,'Version1.png','green',now-timedelta(days=2))
        for role in ('CAD','ED','MD'):self.decide(self.approved,role)
        self.rejected=self.design(self.vehicle,'Version2.png','red',now-timedelta(days=1))
        self.decide(self.rejected,'CAD','rejected')
        self.pending=self.design(self.vehicle,'Version3.png','blue',now)
        self.references=[self.design(self.vehicle,f'Reference{index}.png','white',now+timedelta(days=3+index),reference=True) for index in range(2)]
        self.context=None;self.errors=[];self.http_errors=[];self.console_errors=[]
        self.login(self.users['CAD'])

    def tearDown(self):
        if self.context:self.context.close()
        self.assertTrue(self.server_thread.httpd.drain())
        self.assertEqual((self.errors,self.http_errors,self.console_errors),([],[],[]))
        super().tearDown()

    def account(self,name,role,stage=''):
        user=User.objects.create_user(name)
        profile=user.workflow_profile;profile.role=role;profile.approval_role=stage;profile.save()
        return user

    def pattern(self,**values):
        return YearRange.objects.create(sub_model=self.variant,**values)

    def raw(self,color='blue'):
        data=io.BytesIO();Image.new('RGB',(80,50),color).save(data,'PNG');return data.getvalue()

    def design(self,vehicle,name,color='blue',when=None,reference=False):
        image=PatternDesignImage(vehicle=vehicle,title=name,is_reference=reference,uploaded_by=self.users['CAD'] if reference else self.designer,
            approval_status='approved' if reference else 'pending')
        image.image.save(name,ContentFile(self.raw(color)))
        if not reference:submit_design_for_approval(image,self.designer)
        if when:PatternDesignImage.objects.filter(pk=image.pk).update(uploaded_at=when)
        image.refresh_from_db();return image

    def decide(self,image,role,decision='approved'):
        record_design_review_decision(image,self.users[role],decision,'Actual browser '+role,change_type='minor')

    def login(self,user):
        if self.context:
            self.context.close();self.assertTrue(self.server_thread.httpd.drain())
        self.context=self.browser.new_context(viewport={'width':1440,'height':900},has_touch=True,reduced_motion='reduce')
        client=Client();client.force_login(user)
        self.context.add_cookies([{'name':'sessionid','value':client.session.session_key,'domain':urlparse(self.live_server_url).hostname,'path':'/'}])
        self.page=self.context.new_page()
        self.page.on('pageerror',lambda error:self.errors.append(str(error)))
        self.page.on('console',lambda message:self.console_errors.append(message.text) if message.type=='error' and not message.text.startswith('Failed to load resource:') else None)
        self.page.on('response',lambda response:self.http_errors.append((response.status,response.url)) if response.url.startswith(self.live_server_url) and response.status>=400 and not (response.status==503 and '/design-images/upload/' in response.url) else None)
        self.page.on('dialog',lambda dialog:dialog.accept())

    def workspace(self):
        self.page.goto(f'{self.live_server_url}/car-details/?vehicle_id={self.vehicle.pk}#3d-design')
        expect(self.page.locator(f'#design3DFilesGallery [data-file-id="{self.pending.pk}"]')).to_be_visible()

    def status(self):
        self.page.goto(f'{self.live_server_url}/car-details/?subwindow=3d-status')
        expect(self.page.locator('#tab-pane-3d-status')).to_be_visible()

    def open(self,image=None):
        self.page.evaluate('(id)=>window.openDesignComparison(id)',(image or self.approved).pk)
        expect(self.page.locator('#designComparisonViewer')).to_be_visible()

    def selected(self,title):
        expect(self.page.locator('[data-comparison-panel="upload"] [data-panel-file]')).to_have_text(title)
        expect(self.page.locator('[data-comparison-carousel="upload"] button[aria-pressed="true"]')).to_have_attribute('aria-label',title)
        expect(self.page.locator('[data-comparison-panel="upload"] [data-panel-image]')).to_be_visible()

    def choose(self,title):
        self.page.locator('[data-comparison-carousel="upload"]').get_by_role('button',name=title,exact=True).click()
        self.selected(title)

    def assert_only_workspace(self, active):
        for name in ('pattern-list','color-master','3d-status','design-options'):
            pane=self.page.locator('#tab-pane-'+name)
            if name==active:expect(pane).to_be_visible()
            else:
                expect(pane).not_to_be_visible()
                self.assertEqual(pane.evaluate('(el)=>el.getClientRects().length'),0)

    def test_subwindows_are_exclusive_after_scroll_refresh_rapid_switch_and_history(self):
        for width,height in ((1440,900),(390,844)):
            self.page.set_viewport_size({'width':width,'height':height})
            for subwindow,pane in (('patterns','pattern-list'),('colors','color-master'),('3d-status','3d-status')):
                self.page.goto(f'{self.live_server_url}/car-details/?subwindow={subwindow}')
                self.assert_only_workspace(pane)
                self.page.evaluate('window.scrollTo(0,document.documentElement.scrollHeight)')
                self.assert_only_workspace(pane)
                self.page.reload();self.assert_only_workspace(pane)
            self.page.evaluate("() => {for(let n=0;n<6;n++){switchSubwindow('colors');switchSubwindow('patterns');switchSubwindow('3d-status');}}")
            self.assert_only_workspace('3d-status')
            self.page.go_back();self.assert_only_workspace('pattern-list')
            self.page.go_forward();self.assert_only_workspace('3d-status')
        # An in-flight status refresh must not reveal its now-inactive workspace.
        fragment=self.page.request.get(f'{self.live_server_url}/car-details/?subwindow=3d-status&status_fragment=1').text()
        held=[];route='**/car-details/?*status_fragment=1*'
        self.page.route(route,lambda request:held.append(request))
        with self.page.expect_request(lambda request:'status_fragment=1' in request.url):
            self.page.evaluate("document.activeElement?.blur();document.dispatchEvent(new CustomEvent('fabro:design-review-saved'))")
        self.page.locator('#subtaskbarBtnColors').click()
        self.assertTrue(held)
        try:
            for request in held:request.fulfill(status=200,content_type='text/html',body=fragment)
        finally:
            self.page.unroute(route)
        self.page.evaluate('() => new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))')
        self.assert_only_workspace('color-master')

    def test_design_entry_origin_and_back_forward_preserve_the_correct_workspace(self):
        other=self.pattern(br='Other pattern');other_upload=self.design(other,'Other pattern.png')
        self.page.goto(f'{self.live_server_url}/car-details/?subwindow=3d-status&status_search={other.serial_number}&status_sort=uploaded&status_direction=desc')
        self.page.locator(f'[data-status-pattern="{other.pk}"] .status-view-icon-btn').click()
        self.assert_only_workspace('design-options')
        expect(self.page.locator('#pattern3DDesignWorkspace')).to_be_visible()
        expect(self.page.locator('#patternMeasurementsWorkspace')).not_to_be_visible()
        expect(self.page.locator('#sidebarNavMeasurementsBtn')).not_to_be_visible()
        expect(self.page.locator(f'#design3DFilesGallery [data-file-id="{other_upload.pk}"]')).to_be_visible()
        expect(self.page.locator('#btnUpload3DDesigns')).to_be_visible()
        expect(self.page.locator('#btnOpenTopApprovalWorkflow')).to_be_visible()
        expect(self.page.locator(f'[data-file-id="{other_upload.pk}"] .tile-delete-btn')).not_to_be_visible()
        self.page.reload();self.assert_only_workspace('design-options')
        expect(self.page.locator('#patternMeasurementsWorkspace')).not_to_be_visible()
        self.page.locator('.pattern-back-btn').click();self.assert_only_workspace('3d-status')
        self.assertEqual(self.page.evaluate("new URLSearchParams(location.search).get('status_search')"),other.serial_number)
        self.assertEqual(self.page.evaluate("new URLSearchParams(location.search).get('status_sort')"),'uploaded')
        self.page.go_back();self.assert_only_workspace('design-options')
        expect(self.page.locator('#sidebarNavMeasurementsBtn')).not_to_be_visible()
        self.page.go_forward();self.assert_only_workspace('3d-status')
        self.page.locator('#subtaskbarBtnPatterns').click()
        self.page.locator(f'#row-view-{self.vehicle.pk} .pattern-row-select').check()
        self.page.locator('#patternActionsToggleBtn').click()
        self.page.locator('#actionBtnDesign').click()
        self.assert_only_workspace('design-options')
        expect(self.page.locator('#patternMeasurementsWorkspace')).to_be_visible()
        expect(self.page.locator('#sidebarNavMeasurementsBtn')).to_be_visible()
        self.page.locator('#sidebarNav3DDesignBtn').click()
        expect(self.page.locator('#pattern3DDesignWorkspace')).to_be_visible()
        expect(self.page.locator(f'#design3DFilesGallery [data-file-id="{self.pending.pk}"]')).to_be_visible()
        self.page.locator('#sidebarNavMeasurementsBtn').click()
        expect(self.page.locator('#patternMeasurementsWorkspace')).to_be_visible()
        self.page.locator('.pattern-back-btn').click();self.assert_only_workspace('pattern-list')
        self.page.go_back();self.assert_only_workspace('design-options')
        expect(self.page.locator('#sidebarNavMeasurementsBtn')).to_be_visible()
        self.page.go_forward();self.assert_only_workspace('pattern-list')
        self.page.goto(f'{self.live_server_url}/car-details/?vehicle_id={self.vehicle.pk}&tab=design-options')
        self.assert_only_workspace('design-options')
        self.page.locator('#subtaskbarBtnPatterns').click()
        self.page.reload();self.assert_only_workspace('pattern-list')
        self.assertIsNone(self.page.evaluate("new URLSearchParams(location.search).get('tab')"))
        profile=self.users['CAD'].workflow_profile
        profile.activity_permissions={'design.delete_uploaded':'allow'};profile.save(update_fields=['activity_permissions'])
        self.login(self.users['CAD'])
        self.page.goto(f'{self.live_server_url}/car-details/?subwindow=3d-status&vehicle_id={other.pk}&design_only=1#3d-design')
        expect(self.page.locator(f'#design3DFilesGallery [data-file-id="{other_upload.pk}"] .tile-delete-btn')).to_be_visible()

    def test_three_versions_manual_reference_zoom_refresh_and_stale_responses(self):
        self.workspace();self.open()
        self.selected('Version3.png')
        selected=self.page.locator('[data-comparison-carousel="upload"] button[aria-pressed="true"]')
        expect(selected).to_have_css('border-top-width','2px')
        stamp=self.page.locator('[data-comparison-stamp]');expect(stamp).not_to_be_visible()
        self.choose('Version2.png');expect(stamp).to_have_text('REJECTED');expect(stamp).to_have_attribute('data-outcome','rejected')
        self.choose('Version1.png');expect(stamp).to_have_text('APPROVED');expect(stamp).to_have_attribute('data-outcome','approved')
        self.page.locator('[data-comparison-carousel="reference"]').get_by_role('button',name='Reference1.png',exact=True).click()
        self.page.locator('[data-comparison-panel="upload"] [data-panel-action="in"]').click()
        self.page.evaluate('(id)=>window.load3DDesignWorkspace(id)',self.vehicle.pk)
        self.selected('Version1.png')
        expect(self.page.locator('[data-comparison-panel="upload"] [data-panel-zoom]')).to_have_text('125%')
        expect(self.page.locator('[data-comparison-panel="reference"] [data-panel-file]')).to_have_text('Reference1.png')
        held=[]
        route='**/api/design-images/*/comparison/'
        self.page.route(route,lambda request:held.append(request))
        self.page.evaluate('(id)=>window.load3DDesignWorkspace(id)',self.vehicle.pk)
        self.page.wait_for_timeout(100)
        self.assertTrue(held)
        self.choose('Version2.png');self.choose('Version3.png')
        for pending in held:pending.continue_()
        self.page.unroute(route)
        self.selected('Version3.png');expect(stamp).not_to_be_visible()
        self.page.locator('[data-comparison-action="split"]').click()
        self.assertEqual(self.page.locator('#designComparisonViewer').get_attribute('data-panel-focus'),'')
        for image in (self.approved,self.rejected,self.pending):
            with image.image.open('rb') as stream:self.assertEqual(hashlib.sha256(stream.read()).hexdigest(),hashlib.sha256(self.raw({'Version1.png':'green','Version2.png':'red','Version3.png':'blue'}[image.title])).hexdigest())

    def test_successful_new_upload_selects_new_file_failed_upload_keeps_it(self):
        self.workspace()
        held=[];route=f'**/api/vehicles/{self.vehicle.pk}/design-images/upload/'
        self.page.route(route,lambda request:held.append(request))
        self.page.locator('#design3DUploadInput').set_input_files({'name':'Version4.png','mimeType':'image/png','buffer':self.raw('yellow')})
        expect(self.page.locator('.tile-upload-percent')).to_be_visible()
        self.assertTrue(held)
        self.open();self.selected('Version3.png')
        held[0].continue_();self.page.unroute(route)
        self.selected('Version4.png')
        expect(self.page.locator('[data-comparison-information]')).to_contain_text(self.users['CAD'].username)
        expect(self.page.locator('[data-comparison-stamp]')).not_to_be_visible()
        expect(self.page.locator('#btnUpload3DDesigns')).to_be_enabled()
        self.page.route(route,lambda request:request.fulfill(status=503,content_type='application/json',body=json.dumps({'status':'error','message':'Controlled failed upload'})))
        self.page.locator('#design3DUploadInput').set_input_files({'name':'MustNotSelect.png','mimeType':'image/png','buffer':self.raw('black')})
        expect(self.page.locator('.tile-upload-retry')).to_be_visible()
        self.selected('Version4.png')
        self.assertFalse(PatternDesignImage.objects.filter(title='MustNotSelect.png').exists())

    def test_headings_stamps_and_layout_at_desktop_tablet_mobile(self):
        self.workspace()
        expect(self.page.locator('#designVehicleNameDisplay')).to_contain_text('Hybrid')
        expect(self.page.locator('#designVehicleNameDisplay')).to_contain_text('N1')
        self.open()
        expect(self.page.locator('[data-comparison-identity]')).to_have_text(self.vehicle.serial_number+' — HONDA & Partner ACCORD Hybrid N1 (2013–2017)')
        self.choose('Version1.png')
        for width,height in ((1440,900),(768,1024),(390,844)):
            self.page.set_viewport_size({'width':width,'height':height})
            if width<650:self.page.locator('button[data-mobile-side="upload"]').click()
            stamp=self.page.locator('[data-comparison-stamp]');expect(stamp).to_be_visible()
            self.assertTrue(stamp.evaluate('(el)=>{const a=el.getBoundingClientRect(),b=el.closest("header").getBoundingClientRect();return a.top>=b.top&&a.bottom<=b.bottom+6;}'))
            self.assertLessEqual(self.page.locator('#designComparisonViewer').evaluate('(el)=>el.scrollWidth-el.clientWidth'),1)
            self.assertLessEqual(self.page.locator('#designComparisonViewer').evaluate('(el)=>el.scrollHeight-el.clientHeight'),1)
            expect(self.page.locator('[data-comparison-action="close"]')).to_be_visible()
            if width in (1440,390):self.page.screenshot(path=f'output/3d-comparison-{width}.png')
        self.page.locator('[data-comparison-action="close"]').click()
        self.vehicle.br='';self.vehicle.save(update_fields=['br']);self.variant.name='-';self.variant.save(update_fields=['name'])
        self.workspace();self.open()
        identity=self.page.locator('[data-comparison-identity]').inner_text()
        self.assertNotIn('None',identity);self.assertNotIn('null',identity);self.assertNotIn('Hybrid',identity);self.assertNotIn('N1',identity)
        self.page.locator('[data-comparison-action="close"]').click()
        self.variant.name='Touring & Special '+('LongName '*8);self.variant.save(update_fields=['name'])
        self.workspace();self.open()
        expect(self.page.locator('[data-comparison-identity]')).to_contain_text('Touring & Special')
        self.assertLessEqual(self.page.locator('#designComparisonViewer').evaluate('(el)=>el.scrollWidth-el.clientWidth'),1)

    def test_upload_confirmed_during_initial_manifest_loading_is_not_lost(self):
        self.workspace()
        held=[];route='**/api/design-images/*/comparison/'
        def delay_initial(route_obj):
            held.append(route_obj)
        self.page.route(route,delay_initial)
        self.page.evaluate('(id)=>{void window.openDesignComparison(id);}',self.pending.pk)
        expect(self.page.locator('[data-comparison-notice]')).to_contain_text('Loading comparison')
        self.page.wait_for_timeout(200)
        self.assertTrue(held)
        self.page.locator('#design3DUploadInput').set_input_files({'name':'DuringOpen.png','mimeType':'image/png','buffer':self.raw('yellow')})
        expect(self.page.locator('#design3DFilesGallery')).to_contain_text('DuringOpen.png')
        expect(self.page.locator('#btnUpload3DDesigns')).to_be_enabled()
        for route_obj in held:route_obj.fulfill(response=route_obj.fetch())
        self.page.unroute(route)
        self.selected('DuringOpen.png')
        expect(self.page.locator('[data-comparison-stamp]')).not_to_be_visible()

    def test_status_roles_columns_search_sort_pagination_and_readonly_om(self):
        now=timezone.now();partial={}
        for index,stage in enumerate(('CAD','ED','MD')):
            image=self.design(self.pattern(),stage+'.png',when=now+timedelta(minutes=index+1))
            self.decide(image,stage);partial[stage]=image
        complete=self.design(self.pattern(),'AllApproved.png')
        for role in ('CAD','ED','MD'):self.decide(complete,role)
        for role,first in [('CAD',partial['MD']),('ED',partial['MD']),('MD',partial['ED']),('OM',partial['MD'])]:
            self.login(self.users[role]);self.status()
            expect(self.page.locator('#subtaskbarBtn3DStatus')).to_have_attribute('aria-selected','true')
            expect(self.page.locator('.design-status-table thead th')).to_have_count(13)
            expect(self.page.locator('select[name="status_page_size"]')).to_have_count(0)
            expect(self.page.locator('.status-rows-label')).to_have_count(0)
            rows=self.page.locator('.design-status-table tbody tr[data-status-upload]')
            expect(rows.first).to_have_attribute('data-status-upload',str(first.pk))
            expect(rows.last).to_have_attribute('data-status-upload',str(complete.pk))
            current=self.page.locator(f'[data-status-pattern="{self.vehicle.pk}"]')
            expect(current).to_have_attribute('data-status-upload',str(self.pending.pk))
            expect(current).to_contain_text('Version3.png');expect(current).to_contain_text('CAD: Pending')
            expect(current).to_contain_text('ED: Pending');expect(current).to_contain_text('MD: Pending')
            expect(current.locator('td.col-uploads')).to_have_text('3')
            expect(self.page.locator('.design-status-table thead th.th-pattern')).to_have_css('text-align','center')
            expect(current.locator('td.col-pattern')).to_have_css('text-align','center')
            expect(self.page.locator('.design-status-table thead th.th-uploads')).to_have_css('text-align','center')
            expect(current.locator('td.col-uploads')).to_have_css('text-align','center')
            if role=='OM':
                self.open();expect(self.page.locator('[data-approval-file] .review-decision-form')).to_have_count(0)
                self.page.locator('[data-comparison-action="close"]').click()
                direct=Client();direct.force_login(self.users['OM'])
                denied=direct.post(reverse('design_approval_detail',args=[self.pending.pk]),{'action':'review','stage':'cad','decision':'approved','change_type':'minor'})
                self.assertEqual(denied.status_code,403)
        self.page.locator('[data-status-sort="pattern"]').click()
        expect(self.page.locator('[data-status-sort="pattern"]').locator('..')).to_have_attribute('aria-sort','ascending')
        self.page.locator('[name="status_search"]').fill(self.vehicle.serial_number)
        self.page.locator('.design-status-search').get_by_role('button',name='Search',exact=True).click()
        expect(self.page.locator('.design-status-table tbody tr[data-status-upload]')).to_have_count(1)
        expect(self.page.locator('[data-status-upload]')).to_have_attribute('data-status-upload',str(self.pending.pk))
        self.page.locator('#subtaskbarBtnPatterns').click()
        for title in ('X-Code','Vehicle Country','Measurement Country','Drive'):
            expect(self.page.locator('#tab-pane-pattern-list th').filter(has_text=title).first).to_be_visible()
        self.page.screenshot(path='output/pattern-master-1440.png')
        self.page.locator('#subtaskbarBtnColors').click()
        expect(self.page.locator('#tab-pane-color-master')).to_be_visible()
        self.page.screenshot(path='output/color-master-1440.png')
        for index in range(28):
            PatternDesignImage.objects.create(vehicle=self.pattern(),uploaded_by=self.designer,image=self.pending.image.name,title=f'Page-33-{index}',approval_status='pending')
        self.status()
        expect(self.page.locator('.design-status-table tbody tr[data-status-upload]')).to_have_count(33)
        expect(self.page.locator('.design-status-pagination').get_by_role('link',name='Next',exact=True)).to_have_count(0)
        for index in range(54):
            PatternDesignImage.objects.create(vehicle=self.pattern(),uploaded_by=self.designer,image=self.pending.image.name,title=f'Page-80-{index}',approval_status='pending')
        self.status()
        expect(self.page.locator('.design-status-table tbody tr[data-status-upload]')).to_have_count(80)
        scroll_state=self.page.locator('.design-status-scroll').evaluate('el=>({scrollHeight:el.scrollHeight,clientHeight:el.clientHeight})')
        self.assertGreater(scroll_state['scrollHeight'],scroll_state['clientHeight'])
        first_page=set(self.page.locator('[data-status-upload]').evaluate_all('(rows)=>rows.map(row=>row.dataset.statusUpload)'))
        with self.page.expect_response(lambda response:'/car-details/' in response.url and 'status_page=2' in response.url and response.request.method=='GET') as page_response:
            self.page.locator('.design-status-pagination').get_by_role('link',name='Next',exact=True).click()
        self.assertEqual(page_response.value.status,200)
        expect(self.page.locator('[data-status-upload]')).to_have_count(7)
        next_page=set(self.page.locator('[data-status-upload]').evaluate_all('(rows)=>rows.map(row=>row.dataset.statusUpload)'))
        self.assertFalse(first_page & next_page)
        self.status()
        for width,height in ((1440,900),(768,1024),(390,844)):
            self.page.set_viewport_size({'width':width,'height':height})
            self.assertLessEqual(self.page.evaluate('document.documentElement.scrollWidth-innerWidth'),1)
            expect(self.page.locator('#subtaskbarBtn3DStatus')).to_be_visible()
            if width==390:
                bounds=self.page.locator('#subtaskbarBtn3DStatus').bounding_box()
                self.assertGreaterEqual(bounds['x'],0);self.assertLessEqual(bounds['x']+bounds['width'],390)
            if width in (1440,390):self.page.screenshot(path=f'output/3d-status-{width}.png')

    def test_existing_review_actions_refresh_stamp_and_status_without_cross_version_leak(self):
        self.status();self.open(self.pending)
        for role in ('CAD','ED','MD'):
            if role!='CAD':self.login(self.users[role]);self.status();self.open(self.pending)
            form=self.page.locator('[data-approval-file] .review-decision-form')
            expect(form).to_have_count(1)
            form.locator('textarea').fill('Browser '+role+' approval')
            form.locator('button[name="decision"][value="approved"]').click()
            expect(self.page.locator('[data-approval-file] .workspace-feedback.success')).to_be_visible()
            if role!='MD':expect(self.page.locator('[data-comparison-stamp]')).not_to_be_visible()
            else:expect(self.page.locator('[data-comparison-stamp]')).to_have_text('APPROVED')
            self.page.locator('[data-comparison-action="close"]').click()
            expect(self.page.locator(f'[data-status-upload="{self.pending.pk}"]')).to_contain_text(role+': Approved')
        self.pending.refresh_from_db();self.assertEqual(self.pending.approval_status,'approved')
        self.assertEqual(PatternDesignApproval.objects.filter(design_image=self.pending,cycle=1).count(),1)
        self.open(self.pending);self.choose('Version2.png')
        expect(self.page.locator('[data-comparison-stamp]')).to_have_text('REJECTED')
        form=self.page.locator('[data-approval-file] .review-decision-form')
        form.locator('textarea').fill('MD rejection of the older version only')
        form.locator('button[name="decision"][value="rejected"]').click()
        expect(self.page.locator('[data-approval-file]:not([hidden]) .workspace-feedback.success')).to_be_visible()
        self.page.locator('[data-comparison-action="close"]').click()
        expect(self.page.locator(f'[data-status-upload="{self.pending.pk}"]')).to_contain_text('Overall: Approved')
        self.assertEqual(self.rejected.latest_approval.md_status,'rejected')

    def test_delete_button_visibility_modal_cancel_and_confirm_soft_delete(self):
        # 1. By default, CAD user lacks 'design.delete_uploaded' -> delete button is not visible
        self.workspace()
        card = self.page.locator(f'#design3DFilesGallery [data-file-id="{self.pending.pk}"]')
        expect(card).to_be_visible()
        expect(card.locator('.tile-delete-btn')).not_to_be_visible()

        # 2. Grant 'design.delete_uploaded' to CAD user
        profile = self.users['CAD'].workflow_profile
        profile.activity_permissions = {'design.delete_uploaded': 'allow'}
        profile.save()
        self.users['CAD'].__dict__.pop('_activity_grants', None)
        self.login(self.users['CAD'])
        self.workspace()

        card = self.page.locator(f'#design3DFilesGallery [data-file-id="{self.pending.pk}"]')
        delete_btn = card.locator('.tile-delete-btn')
        expect(delete_btn).to_be_visible()
        try:
            self.page.screenshot(path="C:/Users/POWER-13/.gemini/antigravity/brain/a3834655-7097-45f2-9706-06b7662d4700/delete-button-card-1440.png")
        except Exception:
            pass

        # 3. Click delete button -> opens modal with pending file (no review history warning)
        delete_btn.click()
        modal = self.page.locator('#delete3DDesignModal')
        expect(modal).to_be_visible()
        expect(self.page.locator('#deleteModalFilename')).to_have_text('Version3.png')
        expect(self.page.locator('#deleteModalHistoryWarning')).not_to_be_visible()

        # 4. Cancel action -> modal closes, card preserved
        self.page.locator('#btnCancelDelete3DDesign').click()
        expect(modal).not_to_be_visible()
        expect(card).to_be_visible()
        self.pending.refresh_from_db()
        self.assertFalse(self.pending.is_deleted)

        # 5. Open modal for a file WITH review history (Version2.png is rejected)
        card_v2 = self.page.locator(f'#design3DFilesGallery [data-file-id="{self.rejected.pk}"]')
        expect(card_v2).to_be_visible()
        card_v2.locator('.tile-delete-btn').click()
        expect(modal).to_be_visible()
        expect(self.page.locator('#deleteModalFilename')).to_have_text('Version2.png')
        expect(self.page.locator('#deleteModalHistoryWarning')).to_be_visible()
        try:
            self.page.screenshot(path="C:/Users/POWER-13/.gemini/antigravity/brain/a3834655-7097-45f2-9706-06b7662d4700/delete-modal-warning-1440.png")
        except Exception:
            pass

        # 6. Confirm Delete -> modal closes, card removed, record soft-deleted
        self.page.locator('#btnConfirmDelete3DDesign').click()
        expect(modal).not_to_be_visible()
        expect(card_v2).not_to_be_visible()
        self.rejected.refresh_from_db()
        self.assertTrue(self.rejected.is_deleted)
        self.assertEqual(self.rejected.deleted_by, self.users['CAD'])
        self.assertIsNotNone(self.rejected.deleted_at)
        # Approval/rejection record remains preserved in database
        self.assertEqual(PatternDesignApproval.objects.filter(design_image=self.rejected).count(), 1)
