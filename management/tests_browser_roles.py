"""Real Chrome, synthetic local data, existing ERP controls and live access channel."""
from tempfile import TemporaryDirectory
from unittest.mock import patch
from urllib.parse import urlparse
from django.apps import apps
from django.contrib.auth import get_user_model
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import Client, override_settings
from django.urls import reverse
from playwright.sync_api import expect, sync_playwright
from management import tests_browser_swatch_photos as support
from management.models import (ActivityRole, UserProfile, WorkflowRoles, Brand, Model,
    SubModel, YearRange, PatternMeasurementFile)
from management.services.roles import save_role
from management.tests_roles import seed

User=get_user_model()


class RolesBrowserTests(StaticLiveServerTestCase):
    server_thread_class=support.SwatchLiveServerThread

    @classmethod
    def setUpClass(cls):
        super().setUpClass();cls.playwright=sync_playwright().start()
        cls.browser=cls.playwright.chromium.launch(channel='chrome',headless=True)

    @classmethod
    def tearDownClass(cls):
        try:cls.browser.close();cls.playwright.stop()
        finally:super().tearDownClass()

    def setUp(self):
        self.media=TemporaryDirectory(prefix='roles-browser-');self.addCleanup(self.media.cleanup)
        override=override_settings(MEDIA_ROOT=self.media.name,USE_S3_STORAGE=False,USE_SUPABASE_STORAGE=False,
            STORAGES={'default':{'BACKEND':'django.core.files.storage.FileSystemStorage'},'staticfiles':{'BACKEND':'django.contrib.staticfiles.storage.StaticFilesStorage'}})
        override.enable();self.addCleanup(override.disable)
        push=patch('management.services.push_notifications.send_push_to_user');push.start();self.addCleanup(push.stop)
        self.admin=User.objects.create_superuser('roles-browser-admin','admin@example.com','StrongTest!369')
        p=self.admin.workflow_profile;p.role=WorkflowRoles.ADMIN;p.save()
        self.viewer=User.objects.create_user('roles-browser-viewer','viewer@example.com','StrongTest!369')
        seed(apps,None);self.admin=User.objects.get(pk=self.admin.pk)
        self.errors=[];self.server_errors=[];self.contexts=[]
        self.context,self.page=self.login(self.admin)
        self.page.goto(self.live_server_url+reverse('admin_panel')+'?section=roles')
        expect(self.page.locator('#roleName')).to_have_value('Admin')
        expect(self.page.locator('#rolesWorkspace')).to_have_attribute('aria-busy','false')

    def login(self,user):
        context=self.browser.new_context(viewport={'width':1776,'height':886},reduced_motion='reduce')
        self.contexts.append(context);client=Client();client.force_login(user)
        context.add_cookies([{'name':'sessionid','value':client.session.session_key,'domain':urlparse(self.live_server_url).hostname,'path':'/'}])
        page=context.new_page();page.on('pageerror',lambda error:self.errors.append(str(error)))
        page.on('console',lambda message:self.errors.append(message.text) if message.type=='error' and not message.text.startswith('Failed to load resource:') else None)
        page.on('response',lambda response:self.server_errors.append((response.status,response.url)) if response.url.startswith(self.live_server_url) and response.status>=500 else None)
        return context,page

    def tearDown(self):
        for context in self.contexts:context.close()
        self.assertTrue(self.server_thread.httpd.drain())
        self.assertEqual(self.errors,[]);self.assertEqual(self.server_errors,[])
        super().tearDown()

    def action(self,name):return self.page.locator(f'[data-role-action="{name}"]')
    def window(self,key):return self.page.locator(f'[data-role-window="{key}"]')
    def permission(self,key):return self.page.locator(f'[data-role-permission="{key}"]')

    def save(self):
        self.action('save').click()
        expect(self.page.locator('#erpRoleToastHost')).to_contain_text('Saved Successfully')
        expect(self.page.locator('#rolesWorkspace')).to_have_attribute('aria-busy','false')

    def test_crud_hierarchy_confirmed_save_error_cancel_and_existing_user_assignment(self):
        expect(self.page.locator('#side-roles')).to_have_class('erp-sidebar-btn active')
        expect(self.page.locator('.erp-topbar-nav [onclick="switchErpTab(\'roles\')"]')).to_have_class('erp-nav-tab active')
        expect(self.page.locator('#tab-roles [data-filter-type]')).to_have_count(0)
        expect(self.page.locator('.erp-role-fields input')).to_have_count(2)
        self.action('new').click();expect(self.page.locator('#roleName')).to_have_value('')
        self.assertEqual(self.page.locator('.erp-role-tree input:checked').count(),0)
        expect(self.page.locator('[data-role-node="patterns.master"] summary')).to_be_visible()
        expect(self.window('patterns.master')).to_be_disabled()
        self.page.locator('#roleName').fill('  ');self.action('save').click()
        self.assertFalse(self.page.locator('#roleName').evaluate('(el)=>el.checkValidity()'))
        self.window('dashboard').check();expect(self.permission('dashboard.view')).not_to_be_checked()
        self.permission('dashboard.view').check();self.window('dashboard').uncheck()
        expect(self.permission('dashboard.view')).to_be_checked();expect(self.permission('dashboard.view')).to_be_disabled()
        expect(self.page.locator('[data-role-node="dashboard"] summary small')).to_contain_text('stored')
        self.window('dashboard').check();expect(self.permission('dashboard.view')).to_be_enabled()
        stored=self.page.locator('.erp-role-tree input:checked').count()
        self.action('collapse').click();self.action('expand').click()
        self.page.locator('[data-role-search]').fill('dashboard');self.page.locator('[data-role-search]').fill('')
        self.assertEqual(self.page.locator('.erp-role-tree input:checked').count(),stored)
        self.page.locator('#roleName').fill('Browser Operations')
        held=[];route='**/admin-panel/roles/save/'
        self.page.route(route,lambda request:held.append(request))
        self.action('save').click();expect(self.action('save')).to_be_disabled()
        expect(self.page.locator('#erpRoleToastHost')).not_to_be_visible()
        self.page.locator('[data-role-form]').evaluate('(form)=>form.requestSubmit()')
        self.assertEqual(len(held),1);held[0].continue_();self.page.unroute(route)
        expect(self.page.locator('#erpRoleToastHost')).to_contain_text('Role "Browser Operations" has been created.')
        role=ActivityRole.objects.get(name='Browser Operations');self.assertEqual(role.short_name,'')
        self.assertEqual(ActivityRole.objects.filter(name=role.name).count(),1)
        self.page.locator('#roleShortName').fill('OPS');self.save()
        self.page.locator('#roleName').fill('Admin');self.action('save').click()
        expect(self.page.locator('[data-role-feedback]')).to_contain_text('already exists')
        expect(self.page.locator('#roleName')).to_have_value('Admin');expect(self.page.locator('#erpRoleToastHost')).not_to_be_visible()
        self.page.once('dialog',lambda dialog:dialog.dismiss());self.action('cancel').click()
        expect(self.page.locator('#roleName')).to_have_value('Admin')
        self.page.once('dialog',lambda dialog:dialog.accept());self.action('cancel').click()
        expect(self.page.locator('#roleName')).to_have_value(role.name)
        self.action('duplicate').click();expect(self.page.locator('#roleName')).to_have_value('Browser Operations Copy')
        expect(self.permission('dashboard.view')).to_be_checked();self.save()
        copied=ActivityRole.objects.get(name='Browser Operations Copy');self.assertEqual(copied.members.count(),0)
        self.page.once('dialog',lambda dialog:dialog.dismiss());self.action('delete').click()
        self.assertTrue(ActivityRole.objects.filter(pk=copied.pk).exists())
        self.page.once('dialog',lambda dialog:dialog.accept());self.action('delete').click()
        expect(self.page.locator(f'[data-role-id="{copied.pk}"]')).to_have_count(0)
        self.page.locator(f'[data-role-id="{role.pk}"]').click()
        expect(self.page.locator('#roleName')).to_have_value(role.name)
        self.page.locator('#side-users').click()
        self.page.locator(f'.erp-user-card[data-user-id="{self.viewer.pk}"]').click()
        self.page.locator('#editRole').select_option(f'activity:{role.pk}')
        self.page.locator('#saveEditUserButton').click()
        expect(self.page.locator('#editUserFeedback')).to_contain_text('User saved successfully.')
        dashboard=self.page.locator('[data-permission="dashboard.view"]')
        expect(dashboard).to_be_checked();dashboard.uncheck()
        self.page.locator('#saveEditUserButton').click()
        expect(self.page.locator('#editUserFeedback')).to_contain_text('User saved successfully.')
        self.page.locator('#editUserModal .erp-modal-close').click()
        self.page.locator(f'.erp-user-card[data-user-id="{self.viewer.pk}"]').click()
        expect(self.page.locator('[data-permission="dashboard.view"]')).not_to_be_checked()
        self.page.locator('#editUserModal .erp-modal-close').click()
        self.page.locator('#side-roles').click()
        expect(self.page.locator(f'[data-role-id="{role.pk}"] .erp-role-card-count')).to_have_text('1 user')
        self.page.locator(f'[data-role-id="{role.pk}"]').click();expect(self.action('delete')).to_be_disabled()
        p=UserProfile.objects.get(user=self.viewer)
        self.assertEqual((p.activity_role_id,p.role),(role.pk,WorkflowRoles.FACTORY_VIEWER))
        self.assertEqual(p.activity_permissions,{'dashboard.view':'deny'})

    def test_live_role_revocation_and_individual_override_without_relogin(self):
        role=save_role(self.admin,{'name':'Live Role','permissions':{'pattern.view':True,'pattern.list':True,'chat.view':True},
            'windows':{'patterns':True,'patterns.master':True,'chat':True}})
        UserProfile.objects.filter(user=self.viewer).update(activity_role_id=role.pk,activity_permissions={'chat.view':'allow'})
        viewer_context,viewer_page=self.login(self.viewer)
        viewer_page.goto(self.live_server_url+'/car-details/')
        nav=viewer_page.locator('.nav-link[data-activity="chat.view"]');expect(nav).to_be_visible()
        cookies=viewer_context.cookies()
        self.page.reload();self.page.locator(f'[data-role-id="{role.pk}"]').click()
        expect(self.page.locator('#roleName')).to_have_value(role.name)
        self.window('chat').uncheck();expect(self.permission('chat.view')).to_be_checked();self.save()
        expect(nav).not_to_be_visible(timeout=10000)
        self.assertEqual(viewer_page.request.get(self.live_server_url+reverse('chat_users_api')).status,403)
        self.window('chat').check();self.save();expect(nav).to_be_visible(timeout=10000)
        self.assertEqual(viewer_page.request.get(self.live_server_url+reverse('chat_users_api')).status,200)
        self.assertEqual([item['value'] for item in viewer_context.cookies() if item['name']=='sessionid'],[item['value'] for item in cookies if item['name']=='sessionid'])
        UserProfile.objects.filter(user=self.viewer).update(activity_permissions={'chat.view':'deny'})
        expect(nav).not_to_be_visible(timeout=10000)
        self.assertEqual(viewer_page.request.get(self.live_server_url+reverse('chat_users_api')).status,403)

    def test_permission_revocation_preserves_unsaved_role_and_failed_save_has_no_toast(self):
        self.action('new').click();self.page.locator('#roleName').fill('Unsubmitted Draft')
        self.window('dashboard').check();self.permission('dashboard.view').check()
        UserProfile.objects.filter(user=self.admin).update(activity_permissions={'roles.permissions':'deny'})
        expect(self.permission('dashboard.view')).to_be_disabled(timeout=10000)
        expect(self.permission('dashboard.view')).to_be_checked()
        self.action('save').click()
        expect(self.page.locator('[data-role-feedback]')).to_have_attribute('data-error','true')
        expect(self.page.locator('#erpRoleToastHost')).not_to_be_visible()
        expect(self.page.locator('#roleName')).to_have_value('Unsubmitted Draft')
        self.assertFalse(ActivityRole.objects.filter(name='Unsubmitted Draft').exists())
        self.page.once('dialog',lambda dialog:dialog.dismiss());self.page.locator('#side-users').click()
        expect(self.page.locator('#tab-roles')).to_have_class('erp-tab-pane active')
        self.page.once('dialog',lambda dialog:dialog.accept());self.action('cancel').click()

    def test_measurements_only_role_loads_without_folder_or_design_access(self):
        brand=Brand.objects.create(name='Restricted role vehicle')
        model=Model.objects.create(brand=brand,name='Isolated measurements')
        sub=SubModel.objects.create(model=model,name='Test')
        vehicle=YearRange.objects.create(sub_model=sub,layout_code='ROLE-MEASUREMENT')
        PatternMeasurementFile.objects.create(vehicle=vehicle,category='scanned_pattern',
            filename='Authorized measurement.pdf',file='synthetic.pdf',uploaded_by=self.viewer)
        role=save_role(self.admin,{'name':'Measurements only',
            'permissions':{'pattern.view':True,'measurement.view_own':True},
            'windows':{'patterns':True,'patterns.measurements':True}})
        UserProfile.objects.filter(user=self.viewer).update(activity_role_id=role.pk)
        _,page=self.login(self.viewer)
        page.goto(f'{self.live_server_url}/car-details/?vehicle_id={vehicle.pk}#measurements')
        expect(page.locator('#scannedFilesList')).to_contain_text('Authorized measurement.pdf')
        self.assertEqual(page.request.get(self.live_server_url+'/api/design-folders/?vehicle_id='+str(vehicle.pk)).status,403)
        self.assertEqual(page.request.get(self.live_server_url+'/car-details/').status,403)

    def test_layout_matches_compact_reference_and_remains_usable_on_tablet_mobile(self):
        self.page.locator('#roleShortName').fill('ADM');self.save()
        for width,height in ((1776,886),(768,1024),(390,844)):
            self.page.set_viewport_size({'width':width,'height':height})
            self.assertLessEqual(self.page.evaluate('document.documentElement.scrollWidth-innerWidth'),1)
            for selector in ('#roleName','#roleShortName','[data-role-action="save"]','[data-role-search]'):
                expect(self.page.locator(selector)).to_be_visible()
            if width==1776:
                for action in ('new','save'):
                    self.assertTrue(self.action(action).evaluate("(el)=>{const rgb=getComputedStyle(el).backgroundColor.match(/[0-9]+/g).map(Number);return rgb[0]>180&&rgb[1]<120&&rgb[2]<140;}"))
                left=self.page.locator('.erp-roles-list-panel').bounding_box();right=self.page.locator('.erp-role-editor').bounding_box()
                self.assertLess(left['width'],right['width']);self.assertLessEqual(left['x']+left['width'],right['x'])
                toast=self.page.locator('#erpRoleToastHost').bounding_box();save=self.action('save').bounding_box()
                self.assertLessEqual(toast['y']+toast['height'],save['y']+2)
            self.assertEqual(self.page.locator('.erp-role-tree').evaluate('(el)=>getComputedStyle(el).overflowY'),'auto')
            if width in (1776,390):self.page.screenshot(path=f'output/roles-{width}.png')
