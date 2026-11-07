"""Real Chromium Color Selector regressions, using isolated data and local files."""
import json
from tempfile import TemporaryDirectory
from unittest.mock import patch
from urllib.parse import urlparse
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import Client, override_settings
from django.urls import reverse
from playwright.sync_api import expect, sync_playwright

from management import tests_browser_swatch_photos as browser_support
from management.models import (Brand, ColorMaster, Model, PatternColorSelection,
    PickedColorSelection, SubModel, WorkflowRoles, YearRange)


class ColorSelectorBrowserTests(StaticLiveServerTestCase):
    server_thread_class = browser_support.SwatchLiveServerThread

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
        self.media = TemporaryDirectory(prefix='category-browser-')
        self.addCleanup(self.media.cleanup)
        config = override_settings(MEDIA_ROOT=self.media.name, USE_S3_STORAGE=False, USE_SUPABASE_STORAGE=False,
            STORAGES={'default':{'BACKEND':'django.core.files.storage.FileSystemStorage'},
                      'staticfiles':{'BACKEND':'django.contrib.staticfiles.storage.StaticFilesStorage'}})
        config.enable()
        self.addCleanup(config.disable)
        push = patch('management.services.push_notifications.send_push_to_user')
        self.push = push.start()
        self.addCleanup(push.stop)
        self.owner = get_user_model().objects.create_user('category-browser')
        self.owner.workflow_profile.role = WorkflowRoles.FREELANCE_3D_DESIGNER
        self.owner.workflow_profile.save()
        brand = Brand.objects.create(name='Category Browser Brand')
        model = Model.objects.create(brand=brand, name='Category Browser Model')
        sub = SubModel.objects.create(model=model, name='Category Browser Sub')
        self.vehicle = YearRange.objects.create(sub_model=sub, layout_code='CATEGORY-BROWSER')
        self.black = ColorMaster.objects.create(name='BLACK', color_code='CAT-BLACK', hex_code='#111111')
        self.cream = ColorMaster.objects.create(name='L.CREAM', color_code='CAT-CREAM', hex_code='#F4E6C3')
        self.context = self.browser.new_context(viewport={'width':1440,'height':900}, reduced_motion='reduce', has_touch=True)
        self.addCleanup(self.context.close)
        self.client = Client()
        self.client.force_login(self.owner)
        self.context.add_cookies([{'name':'sessionid','value':self.client.session.session_key,
            'domain':urlparse(self.live_server_url).hostname,'path':'/'}])
        self.page = self.context.new_page()
        self.accept_dialogs = True
        self.page.on('dialog', lambda dialog: dialog.accept() if self.accept_dialogs else dialog.dismiss())
        self.errors, self.server_errors = [], []
        self.page.on('pageerror', lambda error:self.errors.append(str(error)))
        self.page.on('response', lambda response:self.server_errors.append(response.url) if response.status == 500 else None)
        self.page.goto(f'{self.live_server_url}/car-details/?vehicle_id={self.vehicle.pk}#measurements')
        expect(self.page.locator('#panelColorPicker')).to_be_visible()

    def tearDown(self):
        self.context.close()
        self.assertTrue(self.server_thread.httpd.drain())
        self.assertEqual((self.errors,self.server_errors), ([],[]))
        super().tearDown()

    def category(self, value):
        return self.page.locator(f'#pickedCategoryToggle [data-color-category="{value}"]')

    def counts(self, interior, fabro):
        expect(self.page.locator('#pickedColorsCount')).to_have_text(str(interior))
        expect(self.page.locator('#fabroColorsCount')).to_have_text(str(fabro))

    def tile(self, pk):
        return self.page.locator(f'[data-picked-id="{pk}"]')

    def prepare(self, category='interior_match', new=False, dual=False):
        if self.page.locator('#btnCancelPickedEdit').is_visible():
            self.page.locator('#btnCancelPickedEdit').click()
            expect(self.category('interior_match')).to_have_attribute('aria-checked','true')
        self.category(category).click()
        self.page.locator('#colorTopTabNew' if new else '#colorTopTabExisting').click()
        self.page.locator('.tone-radio-label').filter(has_text='Dual Tone' if dual else 'Single Tone').click()
        if new:
            if dual:
                self.page.locator('.dual-inner-src-btn[data-source="new"]').click()
                self.page.locator('.dual-outer-src-btn[data-source="new"]').click()
            for prefix, name, hex_code in ([('dualInnerNew','BLACK','#111111'),('dualOuterNew','L.CREAM','#F4E6C3')] if dual else [('newSingle','BLACK','#111111')]):
                self.page.locator('#'+prefix+'HexInput').fill(hex_code)
                self.page.locator('#'+prefix+'PantoneInput').fill('P-'+name)
                self.page.locator('#'+prefix+'NameInput').fill(name)
        else:
            self.page.locator('#selectExistingDualInnerColor' if dual else '#selectExistingSingleColor').select_option(str(self.black.pk))
            if dual:
                self.page.locator('#selectExistingDualOuterColor').select_option(str(self.cream.pk))

    def save(self):
        with self.page.expect_response(lambda response:response.request.method == 'POST' and
                ('/api/picked-colors/' in response.url and response.url.endswith('/edit/') or response.url.endswith('/api/pattern-color-selection/save/'))) as result:
            self.page.locator('#btnSaveColorSelection').click()
        response = result.value
        self.assertEqual(response.status,200,response.text())
        data = response.json()
        row = data.get('picked_selection') or data['selection']
        expect(self.tile(row['id'])).to_be_visible()
        expect(self.page.locator('#btnSaveColorSelection')).to_be_enabled()
        return row

    def test_initial_sections_toggle_keyboard_and_category_persistence(self):
        # Simulates an existing client with no category field; migration test
        # separately proves actual pre-schema records retain their values/IDs.
        seeded = self.client.post(reverse('save_color_selection_api'), {'vehicle_id':self.vehicle.pk,
            'inner_source':'existing','inner_existing_color_id':self.black.pk,'client_submission_key':'old-client'}).json()['picked_selection']
        self.page.reload()
        for panel, title in [('panelColorPicker','Color Picker'),('panelPickedColors','Interior Match Color'),('panelFabroColors','Fabro Color Options')]:
            expect(self.page.locator('#'+panel+' h3')).to_have_text(title)
        expect(self.page.locator('#panelPickedColors').locator(f'[data-picked-id="{seeded["id"]}"]')).to_be_visible()
        self.counts(1,0)
        self.category('interior_match').focus()
        self.category('interior_match').press('ArrowRight')
        expect(self.category('fabro_color')).to_be_focused()
        expect(self.page.locator('#pickedCategoryToggle [aria-checked="true"]')).to_have_count(1)
        self.assertNotEqual(self.page.locator('#pickedCategoryToggle').evaluate('(el)=>getComputedStyle(el,"::before").transform'),'none')
        self.page.locator('#selectExistingSingleColor').select_option(str(self.cream.pk))
        saved = self.save()
        self.assertEqual(saved['category'],'fabro_color')
        self.counts(1,1)
        self.page.reload()
        expect(self.page.locator('#panelFabroColors').locator(f'[data-picked-id="{saved["id"]}"]')).to_be_visible()
        self.counts(1,1)

    def test_all_modes_in_both_categories_and_nested_live_saved_previews(self):
        for category in ('interior_match','fabro_color'):
            for new in (False,True):
                for dual in (False,True):
                    self.prepare(category,new,dual)
                    live = self.page.locator('#pickedColorLivePreview')
                    expect(live).to_have_css('background-color','rgb(244, 230, 195)' if dual else 'rgb(17, 17, 17)')
                    expect(live.locator('.color-preview-inner')).to_have_count(int(dual))
                    if dual:
                        expect(live.locator('.color-preview-inner')).to_have_css('background-color','rgb(17, 17, 17)')
                    if dual and not new:
                        self.page.locator('#selectExistingDualOuterColor').select_option(str(self.black.pk))
                        expect(live).to_have_css('background-color','rgb(17, 17, 17)')
                        expect(live.locator('.color-preview-inner')).to_have_css('background-color','rgb(17, 17, 17)')
                        self.page.locator('#selectExistingDualOuterColor').select_option(str(self.cream.pk))
                        self.page.locator('#selectExistingDualInnerColor').select_option(str(self.cream.pk))
                        expect(live).to_have_css('background-color','rgb(244, 230, 195)')
                        expect(live.locator('.color-preview-inner')).to_have_css('background-color','rgb(244, 230, 195)')
                        self.page.locator('#selectExistingDualInnerColor').select_option(str(self.black.pk))
                    saved = self.save()
                    tile = self.tile(saved['id'])
                    expect(tile.locator('.picked-color-swatch')).to_have_css('background-color','rgb(244, 230, 195)' if dual else 'rgb(17, 17, 17)')
                    expect(tile.locator('.color-preview-inner')).to_have_count(int(dual))
                    self.assertEqual(saved['snapshot']['inner']['hex'],'#111111')
                    self.assertEqual(PickedColorSelection.objects.get(pk=saved['id']).source_selection.status,'pending' if new else 'approved')
        self.counts(4,4)
        self.page.reload()
        self.counts(4,4)
        expect(self.page.locator('.picked-color-tile .color-preview-inner')).to_have_count(4)
        # Empty/invalid input shows no fabricated color, and switching to single
        # removes the nested box immediately.
        self.prepare(new=True,dual=True)
        self.page.locator('#dualInnerNewHexInput').fill('invalid')
        expect(self.page.locator('#pickedColorLivePreview .color-preview-inner')).to_have_class('color-preview-inner is-unavailable')
        self.page.locator('.tone-radio-label').filter(has_text='Single Tone').click()
        expect(self.page.locator('#pickedColorLivePreview .color-preview-inner')).to_have_count(0)
        self.page.locator('#newSingleHexInput').fill('112233')
        expect(self.page.locator('#pickedColorLivePreview')).to_have_css('background-color','rgb(17, 34, 51)')

    def test_moves_cancellations_failures_retries_and_deletion_banner(self):
        self.prepare()
        first = self.save()
        source_id = PickedColorSelection.objects.get(pk=first['id']).source_selection_id
        for category, interior, fabro in [('fabro_color',0,1),('interior_match',1,0)]:
            self.tile(first['id']).get_by_role('button',name='Edit Color',exact=True).click()
            expect(self.category('interior_match' if category=='fabro_color' else 'fabro_color')).to_have_attribute('aria-checked','true')
            self.category(category).click()
            self.counts(1-interior,1-fabro)
            saved = self.save()
            self.assertEqual(saved['id'],first['id'])
            self.counts(interior,fabro)
            self.page.reload()
            self.counts(interior,fabro)
        self.tile(first['id']).get_by_role('button',name='Edit Color').click()
        self.category('fabro_color').click()
        self.page.locator('#btnCancelPickedEdit').click()
        self.counts(1,0)
        self.assertEqual(PickedColorSelection.objects.get(pk=first['id']).category,'interior_match')
        self.tile(first['id']).get_by_role('button',name='Edit Color').click()
        self.category('fabro_color').click()
        edit_route = '**/api/picked-colors/*/edit/'
        self.page.route(edit_route,lambda route:route.fulfill(status=503,content_type='application/json',body=json.dumps({'message':'Controlled edit failure'})))
        self.page.locator('#btnSaveColorSelection').click()
        expect(self.page.locator('#pickedEditNotice')).to_contain_text('Controlled edit failure')
        self.counts(1,0)
        expect(self.category('fabro_color')).to_have_attribute('aria-checked','true')
        self.page.unroute(edit_route)
        self.save()
        self.counts(0,1)
        self.assertEqual(PickedColorSelection.objects.get(pk=first['id']).source_selection_id,source_id)
        self.assertEqual(PatternColorSelection.objects.get(pk=source_id).status,'approved')
        self.accept_dialogs = False
        self.tile(first['id']).get_by_role('button',name='Delete Color').click()
        self.counts(0,1)
        self.assertIsNone(PickedColorSelection.objects.get(pk=first['id']).deleted_at)
        self.accept_dialogs = True
        delete_route = '**/api/picked-colors/*/delete/'
        self.page.route(delete_route,lambda route:route.abort('failed'))
        self.tile(first['id']).get_by_role('button',name='Delete Color').click()
        expect(self.page.locator('#pickedEditNotice')).to_contain_text('Failed to fetch')
        self.counts(0,1)
        self.assertIsNone(PickedColorSelection.objects.get(pk=first['id']).deleted_at)
        self.page.unroute(delete_route)
        self.tile(first['id']).get_by_role('button',name='Delete Color').click()
        self.counts(0,0)
        expect(self.page.locator('#patternColorStatusCard')).not_to_be_visible()
        self.assertTrue(PatternColorSelection.objects.filter(pk=source_id,status='approved').exists())
        self.prepare(category='interior_match')
        interior = self.save()
        self.tile(interior['id']).get_by_role('button',name='Delete Color').click()
        self.counts(0,0)
        self.prepare(category='fabro_color')
        create_route = '**/api/pattern-color-selection/save/'
        self.page.route(create_route,lambda route:route.fulfill(status=400,content_type='application/json',body=json.dumps({'message':'Choose Interior Match or Fabro Color.'})))
        self.page.locator('#btnSaveColorSelection').click()
        expect(self.page.locator('#pickedEditNotice')).to_contain_text('Choose Interior Match')
        self.counts(0,0)
        expect(self.category('fabro_color')).to_have_attribute('aria-checked','true')
        self.page.unroute(create_route)
        self.save()
        self.counts(0,1)
        self.assertEqual(PickedColorSelection.objects.filter(deleted_at=None).count(),1)

    def test_responsive_right_icons_and_permission_revocation(self):
        ColorMaster.objects.filter(pk=self.black.pk).update(name='BLACK ' + 'LongName'*8)
        self.page.reload()
        self.prepare(dual=True)
        first = self.save()
        self.prepare(category='fabro_color',dual=True)
        second = self.save()
        for width,height in [(1440,900),(768,1024),(390,844)]:
            self.page.set_viewport_size({'width':width,'height':height})
            self.assertLessEqual(self.page.evaluate('document.documentElement.scrollWidth-innerWidth'),1)
            for pk in (first['id'],second['id']):
                tile = self.tile(pk)
                expect(tile.locator('.picked-color-actions button')).to_have_count(2)
                self.assertEqual(tile.locator('.picked-color-actions button').all_text_contents(),['',''])
                boxes = tile.evaluate('el=>[...el.children].map(child=>({x:child.getBoundingClientRect().x,right:child.getBoundingClientRect().right}))')
                self.assertGreaterEqual(boxes[2]['x'],boxes[1]['right'])
                self.assertGreaterEqual(boxes[1]['x'],boxes[0]['right'])
                self.assertEqual(tile.locator('.picked-color-details .picked-color-actions').count(),0)
                expect(tile.get_by_role('button',name='Edit Color')).to_have_attribute('title','Edit Color')
                expect(tile.get_by_role('button',name='Delete Color')).to_have_attribute('title','Delete Color')
            for button in [self.category('interior_match'),self.category('fabro_color')]:
                expect(button).to_be_visible()
                self.assertGreaterEqual(button.bounding_box()['width'],70)
            if width in (1440,390):
                self.page.locator('#panelColorPicker').scroll_into_view_if_needed()
                self.page.screenshot(path=f'output/color-selector-{width}.png')
                self.page.locator('#panelFabroColors').scroll_into_view_if_needed()
                self.page.screenshot(path=f'output/color-selector-{width}-saved.png')
        person = self.owner.workflow_profile
        person.activity_permissions = {'picked_colors.edit_own':'deny','picked_colors.delete_own':'deny'}
        person.save()
        self.page.reload()
        expect(self.page.locator('[data-picked-action]')).to_have_count(0)
        for name, args in [('edit_picked_color',self.values_for_direct_edit(first['id'])),('delete_picked_color',{'vehicle_id':self.vehicle.pk})]:
            response = self.client.post(reverse(name,args=[first['id']]),args)
            self.assertEqual(response.status_code,403)
        self.assertEqual(PickedColorSelection.objects.filter(deleted_at=None).count(),2)

    def values_for_direct_edit(self, pk):
        return {'vehicle_id':self.vehicle.pk,'inner_source':'existing','inner_existing_color_id':self.black.pk,
                'client_submission_key':f'denied-{pk}','category':'fabro_color'}

    def test_single_and_multiple_saved_color_visual_geometry(self):
        # Phase A: Exactly 1 saved color in both sections
        for cat in ('interior_match', 'fabro_color'):
            res = self.client.post(reverse('save_color_selection_api'), {
                'vehicle_id': self.vehicle.pk,
                'category': cat,
                'tone_type': 'single',
                'inner_source': 'existing',
                'inner_existing_color_id': self.black.pk,
                'client_submission_key': str(uuid4()),
                'remarks': f'Single {cat}',
            })
            self.assertEqual(res.status_code, 200, res.content)
        self.page.reload()
        self.counts(1, 1)

        self.page.set_viewport_size({'width': 1440, 'height': 900})
        for list_id, panel_id in [('#pickedColorsList', '#panelPickedColors'), ('#fabroColorsList', '#panelFabroColors')]:
            tile = self.page.locator(f'{list_id} .picked-color-tile').first
            expect(tile).to_be_visible()
            t_box = tile.evaluate('el => el.getBoundingClientRect()')
            body_box = self.page.locator(f'{panel_id} .measurement-panel-body').evaluate('el => el.getBoundingClientRect()')

            # 1. Tile does not stretch vertically to fill the panel body
            self.assertLess(t_box['height'], 70)  # Compact height ~40-62px
            self.assertGreater(body_box['height'], 100)
            self.assertLess(t_box['height'], body_box['height'] * 0.6)

            # 2. Tile is content-sized horizontally, not stretched to fill width
            self.assertLess(t_box['width'], 320)
            self.assertLess(t_box['width'], body_box['width'] * 0.75)

            # 3. Action icons are kept close to the details instead of pushed to far right
            details = tile.locator('.picked-color-details')
            actions = tile.locator('.picked-color-actions')
            d_box = details.evaluate('el => el.getBoundingClientRect()')
            a_box = actions.evaluate('el => el.getBoundingClientRect()')
            gap = a_box['x'] - (d_box['x'] + d_box['width'])
            self.assertGreaterEqual(gap, 0)
            self.assertLess(gap, 12)  # Tightly adjacent, under 12px

        # Phase B: Multiple saved colors (add 7 more to each category = 8 each)
        for cat in ('interior_match', 'fabro_color'):
            for i in range(2, 9):
                res = self.client.post(reverse('save_color_selection_api'), {
                    'vehicle_id': self.vehicle.pk,
                    'category': cat,
                    'tone_type': 'dual' if i % 2 == 0 else 'single',
                    'inner_source': 'existing',
                    'inner_existing_color_id': self.black.pk,
                    'outer_source': 'existing' if i % 2 == 0 else '',
                    'outer_existing_color_id': self.cream.pk if i % 2 == 0 else '',
                    'client_submission_key': str(uuid4()),
                    'remarks': f'Color #{i}',
                })
                self.assertEqual(res.status_code, 200, res.content)
        self.page.reload()
        self.counts(8, 8)

        # Check two-column grid layout and independent vertical scrolling
        for list_id in ('#pickedColorsList', '#fabroColorsList'):
            tiles = self.page.locator(f'{list_id} .picked-color-tile').all()
            self.assertEqual(len(tiles), 8)
            boxes = [t.evaluate('el => el.getBoundingClientRect()') for t in tiles]
            y_levels = {round(b['y'] / 5) * 5 for b in boxes}
            self.assertEqual(len(y_levels), 4, f"Expected 4 rows in {list_id}, got {len(y_levels)}")
            # Row 1: (0, 1), Row 2: (2, 3), Row 3: (4, 5), Row 4: (6, 7)
            self.assertLessEqual(abs(boxes[0]['y'] - boxes[1]['y']), 3)
            self.assertLessEqual(abs(boxes[2]['y'] - boxes[3]['y']), 3)
            self.assertLessEqual(abs(boxes[4]['y'] - boxes[5]['y']), 3)
            self.assertLessEqual(abs(boxes[6]['y'] - boxes[7]['y']), 3)
            self.assertGreater(boxes[1]['x'], boxes[0]['x'] + 20)
            self.assertGreater(boxes[3]['x'], boxes[2]['x'] + 20)
            self.assertGreater(boxes[5]['x'], boxes[4]['x'] + 20)
            self.assertGreater(boxes[7]['x'], boxes[6]['x'] + 20)
            # Column 1 alignment (0, 2, 4, 6) and Column 2 alignment (1, 3, 5, 7)
            self.assertLessEqual(abs(boxes[0]['x'] - boxes[2]['x']), 3)
            self.assertLessEqual(abs(boxes[2]['x'] - boxes[4]['x']), 3)
            self.assertLessEqual(abs(boxes[4]['x'] - boxes[6]['x']), 3)
            self.assertLessEqual(abs(boxes[1]['x'] - boxes[3]['x']), 3)
            self.assertLessEqual(abs(boxes[3]['x'] - boxes[5]['x']), 3)
            self.assertLessEqual(abs(boxes[5]['x'] - boxes[7]['x']), 3)
            # Each tile remains compact
            for b in boxes:
                self.assertLess(b['height'], 95)
                self.assertLess(b['width'], 350)

        int_list = self.page.locator('#pickedColorsList')
        fab_list = self.page.locator('#fabroColorsList')
        # No horizontal scrollbar
        self.assertLessEqual(int_list.evaluate('el => el.scrollWidth - el.clientWidth'), 1)
        self.assertLessEqual(fab_list.evaluate('el => el.scrollWidth - el.clientWidth'), 1)

        # Independent vertical scrolling check
        int_list.evaluate('el => el.scrollTop = 50')
        self.assertGreater(int_list.evaluate('el => el.scrollTop'), 0)
        self.assertEqual(fab_list.evaluate('el => el.scrollTop'), 0)
        fab_list.evaluate('el => el.scrollTop = 50')
        self.assertGreater(fab_list.evaluate('el => el.scrollTop'), 0)
        int_list.evaluate('el => el.scrollTop = 0')
        fab_list.evaluate('el => el.scrollTop = 0')

        # Zero page-level horizontal overflow across viewports
        for width, height in [(1440, 900), (768, 1024), (390, 844)]:
            self.page.set_viewport_size({'width': width, 'height': height})
            self.assertLessEqual(self.page.evaluate('document.documentElement.scrollWidth - innerWidth'), 1)

    def test_saved_colors_geometry_limits_scrolling_and_viewports(self):
        # Seed 8 saved colors in each category (4 rows)
        for cat in ('interior_match', 'fabro_color'):
            for i in range(8):
                payload = {
                    'vehicle_id': self.vehicle.pk,
                    'category': cat,
                    'tone_type': 'dual' if i % 2 == 1 else 'single',
                    'inner_source': 'existing',
                    'inner_existing_color_id': self.black.pk,
                    'client_submission_key': str(uuid4()),
                    'remarks': f'Color {cat} #{i+1}',
                }
                if i % 2 == 1:
                    payload['outer_source'] = 'existing'
                    payload['outer_existing_color_id'] = self.cream.pk
                res = self.client.post(reverse('save_color_selection_api'), payload)
                self.assertEqual(res.status_code, 200, res.content)
        self.page.reload()
        self.counts(8, 8)

        # 1. Desktop section positions & matched column heights at 1440x900
        self.page.set_viewport_size({'width': 1440, 'height': 900})
        picker = self.page.locator('#panelColorPicker')
        saved_col = self.page.locator('#savedColorsColumn')
        interior = self.page.locator('#panelPickedColors')
        fabro = self.page.locator('#panelFabroColors')

        bp = picker.bounding_box()
        bs = saved_col.bounding_box()
        bi = interior.bounding_box()
        bf = fabro.bounding_box()

        # Section 3 is on the left; Section 4 & 5 are on the right
        self.assertLess(bp['x'] + bp['width'], bs['x'] + 10)
        # Section 4 stacked directly above Section 5
        self.assertLessEqual(abs(bi['x'] - bf['x']), 2)
        self.assertLess(bi['y'], bf['y'])
        self.assertLessEqual(bi['y'] + bi['height'], bf['y'] + 1)
        # Combined height of Sections 4 and 5 matches Section 3
        self.assertLessEqual(abs(bp['height'] - bs['height']), 3)
        self.assertLessEqual(abs(bi['y'] - bp['y']), 3)
        self.assertLessEqual(abs((bf['y'] + bf['height']) - (bp['y'] + bp['height'])), 3)

        # 2. Dynamic adaptation when Section 3 changes height
        # Switch to Dual Tone (Existing)
        self.page.locator('.tone-radio-label').filter(has_text='Dual Tone').click()
        self.page.wait_for_timeout(100)
        bp_dual = picker.bounding_box()
        bs_dual = saved_col.bounding_box()
        self.assertLessEqual(abs(bp_dual['height'] - bs_dual['height']), 3)

        # Switch to Pantone / New Color mode
        self.page.locator('#colorTopTabNew').click()
        self.page.wait_for_timeout(100)
        bp_new = picker.bounding_box()
        bs_new = saved_col.bounding_box()
        self.assertGreater(bp_new['height'], bp['height'])  # Section 3 expanded
        self.assertLessEqual(abs(bp_new['height'] - bs_new['height']), 3)  # Column matched

        # Switch back to Single Tone Existing
        self.page.locator('#colorTopTabExisting').click()
        self.page.locator('.tone-radio-label').filter(has_text='Single Tone').click()
        self.page.wait_for_timeout(100)
        bp_reset = picker.bounding_box()
        bs_reset = saved_col.bounding_box()
        self.assertLessEqual(abs(bp_reset['height'] - bs_reset['height']), 3)

        # 3. Two-column grid with row-wise placement
        for list_id in ('#pickedColorsList', '#fabroColorsList'):
            tiles = self.page.locator(f'{list_id} .picked-color-tile').all()
            self.assertEqual(len(tiles), 8)
            # Distinct y coordinates rounded to clusters of 5px: 4 rows for 8 items
            y_levels = {round(t.bounding_box()['y'] / 5) * 5 for t in tiles}
            self.assertEqual(len(y_levels), 4, f"Expected 4 rows in {list_id}, got {len(y_levels)}")

        # 4. Independent vertical scrolling and zero horizontal overflow
        int_list = self.page.locator('#pickedColorsList')
        fab_list = self.page.locator('#fabroColorsList')
        self.assertLessEqual(int_list.evaluate('el => el.scrollWidth - el.clientWidth'), 1)
        self.assertLessEqual(fab_list.evaluate('el => el.scrollWidth - el.clientWidth'), 1)

        # Scroll Interior list vertically
        int_list.evaluate('el => el.scrollTop = 60')
        self.assertGreater(int_list.evaluate('el => el.scrollTop'), 0)
        self.assertEqual(fab_list.evaluate('el => el.scrollTop'), 0)

        # Scroll Fabro list vertically
        fab_list.evaluate('el => el.scrollTop = 60')
        self.assertGreater(fab_list.evaluate('el => el.scrollTop'), 0)
        int_list.evaluate('el => el.scrollTop = 0')
        fab_list.evaluate('el => el.scrollTop = 0')

        # 5. No clipped controls, swatches, or details
        for list_id in ('#pickedColorsList', '#fabroColorsList'):
            for btn_name in ('Edit Color', 'Delete Color'):
                buttons = self.page.locator(f'{list_id} button[title="{btn_name}"]').all()
                self.assertEqual(len(buttons), 8)
                for btn in buttons:
                    bb = btn.bounding_box()
                    self.assertIsNotNone(bb)
                    self.assertGreater(bb['width'], 20)
                    self.assertGreater(bb['height'], 20)
            swatches = self.page.locator(f'{list_id} .picked-color-swatch').all()
            self.assertEqual(len(swatches), 8)
            for sw in swatches:
                sb = sw.bounding_box()
                self.assertIsNotNone(sb)
                self.assertGreater(sb['width'], 30)
                self.assertGreater(sb['height'], 30)

        # 6. Responsive behavior and zero page overflow at 1440x900, 768x1024, 390x844
        for width, height in [(1440, 900), (768, 1024), (390, 844)]:
            self.page.set_viewport_size({'width': width, 'height': height})
            self.assertLessEqual(self.page.evaluate('document.documentElement.scrollWidth - innerWidth'), 1)
            if width <= 700:
                # Vertical stacking on mobile
                p_b = self.page.locator('#panelColorPicker').bounding_box()
                i_b = self.page.locator('#panelPickedColors').bounding_box()
                f_b = self.page.locator('#panelFabroColors').bounding_box()
                self.assertLess(p_b['y'], i_b['y'])
                self.assertLess(i_b['y'], f_b['y'])
                # Mobile vertical scroll is contained and zero horizontal overflow
                self.assertGreater(self.page.locator('#pickedColorsList').evaluate('el => el.scrollHeight'),
                                   self.page.locator('#pickedColorsList').evaluate('el => el.clientHeight'))
                self.assertLessEqual(self.page.locator('#pickedColorsList').evaluate('el => el.scrollWidth - el.clientWidth'), 1)

    def test_two_column_vertical_scrolling_and_persistence_lifecycle(self):
        int_saved = []
        fab_saved = []

        # 1. Save 10 distinct Interior Match colors through the UI (5 rows)
        for i in range(1, 11):
            if i == 1:
                self.prepare(category='interior_match', new=False, dual=False)
            elif i == 2:
                self.prepare(category='interior_match', new=False, dual=True)
            elif i == 3:
                self.prepare(category='interior_match', new=True, dual=False)
                self.page.locator('#newSingleHexInput').fill('#112233')
                self.page.locator('#newSinglePantoneInput').fill('P-INT-3')
                self.page.locator('#newSingleNameInput').fill('NAVY')
            elif i == 4:
                self.prepare(category='interior_match', new=True, dual=True)
                self.page.locator('#dualInnerNewHexInput').fill('#223344')
                self.page.locator('#dualInnerNewPantoneInput').fill('P-INT-4A')
                self.page.locator('#dualInnerNewNameInput').fill('SLATE')
                self.page.locator('#dualOuterNewHexInput').fill('#334455')
                self.page.locator('#dualOuterNewPantoneInput').fill('P-INT-4B')
                self.page.locator('#dualOuterNewNameInput').fill('ICE')
            elif i == 5:
                self.prepare(category='interior_match', new=True, dual=False)
                self.page.locator('#newSingleHexInput').fill('#445566')
                self.page.locator('#newSinglePantoneInput').fill('P-INT-5')
                self.page.locator('#newSingleNameInput').fill('STEEL')
            elif i == 6:
                self.prepare(category='interior_match', new=True, dual=True)
                self.page.locator('#dualInnerNewHexInput').fill('#556677')
                self.page.locator('#dualInnerNewPantoneInput').fill('P-INT-6A')
                self.page.locator('#dualInnerNewNameInput').fill('TEAL')
                self.page.locator('#dualOuterNewHexInput').fill('#667788')
                self.page.locator('#dualOuterNewPantoneInput').fill('P-INT-6B')
                self.page.locator('#dualOuterNewNameInput').fill('MIST')
            elif i == 7:
                self.prepare(category='interior_match', new=True, dual=False)
                self.page.locator('#newSingleHexInput').fill('#778899')
                self.page.locator('#newSinglePantoneInput').fill('P-INT-7')
                self.page.locator('#newSingleNameInput').fill('GRAPHITE')
            elif i == 8:
                self.prepare(category='interior_match', new=True, dual=True)
                self.page.locator('#dualInnerNewHexInput').fill('#8899AA')
                self.page.locator('#dualInnerNewPantoneInput').fill('P-INT-8A')
                self.page.locator('#dualInnerNewNameInput').fill('CHROME')
                self.page.locator('#dualOuterNewHexInput').fill('#99AABB')
                self.page.locator('#dualOuterNewPantoneInput').fill('P-INT-8B')
                self.page.locator('#dualOuterNewNameInput').fill('SILVER')
            elif i == 9:
                self.prepare(category='interior_match', new=True, dual=False)
                self.page.locator('#newSingleHexInput').fill('#B0C4DE')
                self.page.locator('#newSinglePantoneInput').fill('P-INT-9')
                self.page.locator('#newSingleNameInput').fill('STEELBLUE')
            else:
                self.prepare(category='interior_match', new=True, dual=True)
                self.page.locator('#dualInnerNewHexInput').fill('#D2B48C')
                self.page.locator('#dualInnerNewPantoneInput').fill('P-INT-10A')
                self.page.locator('#dualInnerNewNameInput').fill('TAN')
                self.page.locator('#dualOuterNewHexInput').fill('#E6E6FA')
                self.page.locator('#dualOuterNewPantoneInput').fill('P-INT-10B')
                self.page.locator('#dualOuterNewNameInput').fill('LAVENDER')
            self.page.locator('#pickedColorRemarks').fill(f'Interior Match Color #{i}')
            row = self.save()
            int_saved.append(row)
            for prev in int_saved:
                expect(self.page.locator(f'#pickedColorsList [data-picked-id="{prev["id"]}"]')).to_be_visible()
            self.counts(i, 0)

        # 2. Save 10 distinct Fabro Color options through the UI (5 rows)
        for i in range(1, 11):
            if i == 1:
                self.prepare(category='fabro_color', new=False, dual=False)
                self.page.locator('#selectExistingSingleColor').select_option(str(self.cream.pk))
            elif i == 2:
                self.prepare(category='fabro_color', new=False, dual=True)
                self.page.locator('#selectExistingDualInnerColor').select_option(str(self.cream.pk))
                self.page.locator('#selectExistingDualOuterColor').select_option(str(self.black.pk))
            elif i == 3:
                self.prepare(category='fabro_color', new=True, dual=False)
                self.page.locator('#newSingleHexInput').fill('#556677')
                self.page.locator('#newSinglePantoneInput').fill('P-FAB-3')
                self.page.locator('#newSingleNameInput').fill('ONYX')
            elif i == 4:
                self.prepare(category='fabro_color', new=True, dual=True)
                self.page.locator('#dualInnerNewHexInput').fill('#667788')
                self.page.locator('#dualInnerNewPantoneInput').fill('P-FAB-4A')
                self.page.locator('#dualInnerNewNameInput').fill('CHARCOAL')
                self.page.locator('#dualOuterNewHexInput').fill('#778899')
                self.page.locator('#dualOuterNewPantoneInput').fill('P-FAB-4B')
                self.page.locator('#dualOuterNewNameInput').fill('PEARL')
            elif i == 5:
                self.prepare(category='fabro_color', new=True, dual=False)
                self.page.locator('#newSingleHexInput').fill('#8899AA')
                self.page.locator('#newSinglePantoneInput').fill('P-FAB-5')
                self.page.locator('#newSingleNameInput').fill('PLATINUM')
            elif i == 6:
                self.prepare(category='fabro_color', new=True, dual=True)
                self.page.locator('#dualInnerNewHexInput').fill('#99AABB')
                self.page.locator('#dualInnerNewPantoneInput').fill('P-FAB-6A')
                self.page.locator('#dualInnerNewNameInput').fill('COPPER')
                self.page.locator('#dualOuterNewHexInput').fill('#CCDDEE')
                self.page.locator('#dualOuterNewPantoneInput').fill('P-FAB-6B')
                self.page.locator('#dualOuterNewNameInput').fill('SAND')
            elif i == 7:
                self.prepare(category='fabro_color', new=True, dual=False)
                self.page.locator('#newSingleHexInput').fill('#AABBCC')
                self.page.locator('#newSinglePantoneInput').fill('P-FAB-7')
                self.page.locator('#newSingleNameInput').fill('TITANIUM')
            elif i == 8:
                self.prepare(category='fabro_color', new=True, dual=True)
                self.page.locator('#dualInnerNewHexInput').fill('#CCDDEE')
                self.page.locator('#dualInnerNewPantoneInput').fill('P-FAB-8A')
                self.page.locator('#dualInnerNewNameInput').fill('BRONZE')
                self.page.locator('#dualOuterNewHexInput').fill('#EEFFFF')
                self.page.locator('#dualOuterNewPantoneInput').fill('P-FAB-8B')
                self.page.locator('#dualOuterNewNameInput').fill('GOLD')
            elif i == 9:
                self.prepare(category='fabro_color', new=True, dual=False)
                self.page.locator('#newSingleHexInput').fill('#FFD700')
                self.page.locator('#newSinglePantoneInput').fill('P-FAB-9')
                self.page.locator('#newSingleNameInput').fill('AMBER')
            else:
                self.prepare(category='fabro_color', new=True, dual=True)
                self.page.locator('#dualInnerNewHexInput').fill('#FFE4E1')
                self.page.locator('#dualInnerNewPantoneInput').fill('P-FAB-10A')
                self.page.locator('#dualInnerNewNameInput').fill('ROSE')
                self.page.locator('#dualOuterNewHexInput').fill('#FFF0F5')
                self.page.locator('#dualOuterNewPantoneInput').fill('P-FAB-10B')
                self.page.locator('#dualOuterNewNameInput').fill('BLUSH')
            self.page.locator('#pickedColorRemarks').fill(f'Fabro Color #{i}')
            row = self.save()
            fab_saved.append(row)
            for prev in fab_saved:
                expect(self.page.locator(f'#fabroColorsList [data-picked-id="{prev["id"]}"]')).to_be_visible()
            self.counts(10, i)

        # 3. Verify all 20 records exist with distinct IDs
        all_saved = int_saved + fab_saved
        saved_ids = [s['id'] for s in all_saved]
        self.assertEqual(len(saved_ids), 20)
        self.assertEqual(len(set(saved_ids)), 20)
        self.assertEqual(PickedColorSelection.objects.filter(deleted_at=None).count(), 20)
        self.assertEqual(PickedColorSelection.objects.filter(category='interior_match', deleted_at=None).count(), 10)
        self.assertEqual(PickedColorSelection.objects.filter(category='fabro_color', deleted_at=None).count(), 10)

        # 4. Verify 2-column grid and row positions: (1,2), (3,4), (5,6), (7,8), (9,10)
        self.page.set_viewport_size({'width': 1440, 'height': 900})
        # Reset Section 3 to Single Tone Existing
        self.page.locator('#colorTopTabExisting').click()
        self.page.locator('.tone-radio-label').filter(has_text='Single Tone').click()
        self.page.wait_for_timeout(100)

        for list_id in ('#pickedColorsList', '#fabroColorsList'):
            list_el = self.page.locator(list_id)
            tiles = self.page.locator(f'{list_id} .picked-color-tile').all()
            self.assertEqual(len(tiles), 10)
            boxes = [t.evaluate('el => el.getBoundingClientRect()') for t in tiles]

            # Row 1: tiles 0 & 1
            self.assertLessEqual(abs(boxes[0]['y'] - boxes[1]['y']), 3, f"Row 1 tiles in {list_id} misaligned")
            self.assertGreater(boxes[1]['x'], boxes[0]['x'] + 20)
            # Row 2: tiles 2 & 3
            self.assertLessEqual(abs(boxes[2]['y'] - boxes[3]['y']), 3, f"Row 2 tiles in {list_id} misaligned")
            self.assertGreater(boxes[3]['x'], boxes[2]['x'] + 20)
            self.assertGreater(boxes[2]['y'], boxes[0]['y'] + 25)
            # Row 3: tiles 4 & 5
            self.assertLessEqual(abs(boxes[4]['y'] - boxes[5]['y']), 3, f"Row 3 tiles in {list_id} misaligned")
            self.assertGreater(boxes[5]['x'], boxes[4]['x'] + 20)
            self.assertGreater(boxes[4]['y'], boxes[2]['y'] + 25)
            # Row 4: tiles 6 & 7
            self.assertLessEqual(abs(boxes[6]['y'] - boxes[7]['y']), 3, f"Row 4 tiles in {list_id} misaligned")
            self.assertGreater(boxes[7]['x'], boxes[6]['x'] + 20)
            self.assertGreater(boxes[6]['y'], boxes[4]['y'] + 25)
            # Row 5: tiles 8 & 9
            self.assertLessEqual(abs(boxes[8]['y'] - boxes[9]['y']), 3, f"Row 5 tiles in {list_id} misaligned")
            self.assertGreater(boxes[9]['x'], boxes[8]['x'] + 20)
            self.assertGreater(boxes[8]['y'], boxes[6]['y'] + 25)

            # Column 1 vertical alignment (tiles 0, 2, 4, 6, 8)
            self.assertLessEqual(abs(boxes[0]['x'] - boxes[2]['x']), 3)
            self.assertLessEqual(abs(boxes[2]['x'] - boxes[4]['x']), 3)
            self.assertLessEqual(abs(boxes[4]['x'] - boxes[6]['x']), 3)
            self.assertLessEqual(abs(boxes[6]['x'] - boxes[8]['x']), 3)
            # Column 2 vertical alignment (tiles 1, 3, 5, 7, 9)
            self.assertLessEqual(abs(boxes[1]['x'] - boxes[3]['x']), 3)
            self.assertLessEqual(abs(boxes[3]['x'] - boxes[5]['x']), 3)
            self.assertLessEqual(abs(boxes[5]['x'] - boxes[7]['x']), 3)
            self.assertLessEqual(abs(boxes[7]['x'] - boxes[9]['x']), 3)

            # No horizontal scrollbar
            self.assertLessEqual(list_el.evaluate('el => el.scrollWidth - el.clientWidth'), 1)

        # 5. Verify vertical scrolling reveals later rows and scrolling Section 4 does not scroll Section 5
        int_list = self.page.locator('#pickedColorsList')
        fab_list = self.page.locator('#fabroColorsList')
        self.assertGreater(int_list.evaluate('el => el.scrollHeight'), int_list.evaluate('el => el.clientHeight'))
        self.assertGreater(fab_list.evaluate('el => el.scrollHeight'), fab_list.evaluate('el => el.clientHeight'))

        # Scroll Interior list down vertically
        int_list.evaluate('el => el.scrollTop = el.scrollHeight')
        self.assertGreater(int_list.evaluate('el => el.scrollTop'), 0)
        self.assertEqual(fab_list.evaluate('el => el.scrollTop'), 0, "Scrolling Section 4 must not scroll Section 5")
        # Tile 9 of Interior Match is now visible in the list viewport
        t9_int = self.page.locator('#pickedColorsList .picked-color-tile').nth(9).bounding_box()
        int_bb = int_list.bounding_box()
        self.assertLessEqual(t9_int['y'] + t9_int['height'], int_bb['y'] + int_bb['height'] + 5)
        self.assertGreaterEqual(t9_int['y'], int_bb['y'] - 5)
        int_list.evaluate('el => el.scrollTop = 0')

        # Scroll Fabro list down vertically
        fab_list.evaluate('el => el.scrollTop = el.scrollHeight')
        self.assertGreater(fab_list.evaluate('el => el.scrollTop'), 0)
        self.assertEqual(int_list.evaluate('el => el.scrollTop'), 0, "Scrolling Section 5 must not scroll Section 4")
        t9_fab = self.page.locator('#fabroColorsList .picked-color-tile').nth(9).bounding_box()
        fab_bb = fab_list.bounding_box()
        self.assertLessEqual(t9_fab['y'] + t9_fab['height'], fab_bb['y'] + fab_bb['height'] + 5)
        self.assertGreaterEqual(t9_fab['y'], fab_bb['y'] - 5)
        fab_list.evaluate('el => el.scrollTop = 0')

        # 6. Refresh and verify all saved colors persist
        self.page.reload()
        self.counts(10, 10)
        for row in all_saved:
            tile = self.tile(row['id'])
            expect(tile).to_be_visible()

        # 7. Edit one color and verify only that record changes
        edit_target = int_saved[1]
        self.tile(edit_target['id']).get_by_role('button', name='Edit Color').click()
        expect(self.page.locator('#btnSaveColorSelection')).to_have_text('Save Changes')
        self.page.locator('#pickedColorRemarks').fill('Updated Remarks For Int 2')
        updated_row = self.save()
        self.assertEqual(updated_row['id'], edit_target['id'])
        self.assertEqual(PickedColorSelection.objects.filter(deleted_at=None).count(), 20)
        self.assertEqual(PickedColorSelection.objects.get(pk=edit_target['id']).remarks, 'Updated Remarks For Int 2')
        # All other 19 records remain unchanged
        for other in all_saved:
            if other['id'] != edit_target['id']:
                db_item = PickedColorSelection.objects.get(pk=other['id'])
                self.assertNotEqual(db_item.remarks, 'Updated Remarks For Int 2')

        # 8. Delete one color and verify only that record is removed
        del_target = fab_saved[0]
        self.tile(del_target['id']).get_by_role('button', name='Delete Color').click()
        self.counts(10, 9)
        self.assertEqual(PickedColorSelection.objects.filter(deleted_at=None).count(), 19)
        self.assertIsNotNone(PickedColorSelection.objects.get(pk=del_target['id']).deleted_at)
        expect(self.tile(del_target['id'])).not_to_be_visible()
        self.assertEqual(self.page.locator('.picked-color-tile').count(), 19)

        # 9. Viewports: 1440x900, 768x1024, 390x844
        import os
        os.makedirs('output', exist_ok=True)
        for width, height in [(1440, 900), (768, 1024), (390, 844)]:
            self.page.set_viewport_size({'width': width, 'height': height})
            # No page-level horizontal overflow
            self.assertLessEqual(self.page.evaluate('document.documentElement.scrollWidth - innerWidth'), 1)
            # Section 4 stacked above Section 5
            bi = self.page.locator('#panelPickedColors').bounding_box()
            bf = self.page.locator('#panelFabroColors').bounding_box()
            self.assertLess(bi['y'], bf['y'])
            if width > 700:
                # Combined height of Sections 4 and 5 matches Section 3
                bp = self.page.locator('#panelColorPicker').bounding_box()
                bs = self.page.locator('#savedColorsColumn').bounding_box()
                self.assertLessEqual(abs(bp['height'] - bs['height']), 3)
            # Screenshot
            if width in (1440, 390):
                self.page.locator('#savedColorsColumn').scroll_into_view_if_needed()
                self.page.screenshot(path=f'output/saved-colors-two-column-{width}.png')
