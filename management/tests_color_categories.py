"""Color Selector categories without changing color or approval semantics."""
from unittest import skipUnless
from unittest.mock import patch
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import connection, IntegrityError, transaction
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase, TransactionTestCase
from django.urls import reverse

from management.models import (ActivityLog, Brand, ColorMaster, MasterSetting, Model,
    PatternColorApprovalDecision, PatternColorSelection, PickedColorSelection, SubModel, WorkflowRoles, YearRange)


class ColorCategoryTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = get_user_model().objects.create_user('category-owner')
        cls.other = get_user_model().objects.create_user('category-other')
        for user in (cls.owner, cls.other):
            user.workflow_profile.role = WorkflowRoles.FREELANCE_3D_DESIGNER
            user.workflow_profile.save()
        brand = Brand.objects.create(name='Category Brand')
        model = Model.objects.create(brand=brand, name='Category Model')
        sub = SubModel.objects.create(model=model, name='Category Sub')
        cls.vehicle = YearRange.objects.create(sub_model=sub, layout_code='CAT-1')
        cls.second = YearRange.objects.create(sub_model=sub, layout_code='CAT-2')
        cls.red = ColorMaster.objects.create(name='Black', color_code='CAT-B', hex_code='#111111')
        cls.cream = ColorMaster.objects.create(name='L.CREAM', color_code='CAT-C', hex_code='#F4E6C3')

    def setUp(self):
        self.client.force_login(self.owner)

    def values(self, **changes):
        return {'vehicle_id': self.vehicle.pk, 'tone_type':'single', 'inner_source':'existing',
            'inner_existing_color_id':self.red.pk, 'client_submission_key':str(uuid4()), **changes}

    def create(self, **changes):
        response = self.client.post(reverse('save_color_selection_api'), self.values(**changes))
        self.assertEqual(response.status_code, 200, response.content)
        return PickedColorSelection.objects.get(pk=response.json()['picked_selection']['id'])

    def edit(self, row, **changes):
        return self.client.post(reverse('edit_picked_color', args=[row.pk]), self.values(**changes))

    def listing(self, vehicle=None):
        return self.client.get(reverse('list_picked_colors'), {'vehicle_id':vehicle or self.vehicle.pk}).json()

    def test_both_categories_with_all_four_modes_save_and_reload(self):
        for category in ('interior_match', 'fabro_color'):
            for new in (False, True):
                for dual in (False, True):
                    with self.subTest(category=category, new=new, dual=dual):
                        values = dict(category=category, tone_type='dual' if dual else 'single')
                        if new:
                            values.update(inner_source='new', inner_hex_code='#123456', inner_pantone_code='CAT-P', inner_color_name='Stored inner')
                        if dual:
                            values.update(outer_source='new' if new else 'existing', outer_existing_color_id=self.cream.pk,
                                outer_hex_code='#F4E6C3', outer_pantone_code='CAT-C', outer_color_name='Stored outer')
                        row = self.create(**values)
                        saved = next(item for item in self.listing()['selections'] if item['id'] == row.pk)
                        self.assertEqual(saved['category'], category)
                        self.assertEqual(saved['snapshot']['tone_type'], values['tone_type'])
                        self.assertEqual(saved['snapshot']['inner']['hex'], '#123456' if new else '#111111')
                        if dual:
                            self.assertEqual(saved['snapshot']['outer']['hex'], '#F4E6C3')
                        self.assertEqual(row.source_selection.status, 'pending' if new else 'approved')
        self.assertEqual(self.listing()['counts'], {'interior_match':4, 'fabro_color':4})

    def test_missing_category_is_compatible_on_create_and_edit(self):
        row = self.create()
        self.assertEqual(row.category, 'interior_match')
        self.assertEqual(self.edit(row, category='fabro_color').status_code, 200)
        self.assertEqual(self.edit(row, remarks='Old client without category').status_code, 200)
        row.refresh_from_db()
        self.assertEqual(row.category, 'fabro_color')

    def test_category_moves_same_record_and_preserves_approval_and_audit(self):
        row = self.create(inner_source='new', inner_hex_code='#123456', inner_pantone_code='P', remarks='Keep this')
        before = (row.pk, row.created_at, row.created_by_id, row.source_selection_id, row.snapshot)
        decisions = list(PatternColorApprovalDecision.objects.filter(selection_id=row.source_selection_id).values())
        for category in ('fabro_color', 'interior_match'):
            with self.captureOnCommitCallbacks(execute=True), patch('management.services.push_notifications.send_push_to_user') as push:
                result = self.edit(row, category=category, inner_source='new', inner_hex_code='#123456', inner_pantone_code='P', remarks='Keep this')
            self.assertEqual(result.status_code, 200, result.content)
            self.assertEqual(result.json()['selection']['category'], category)
            row.refresh_from_db()
            self.assertEqual((row.pk, row.created_at, row.created_by_id, row.source_selection_id, row.snapshot), before)
            self.assertEqual(PickedColorSelection.objects.count(), 1)
            self.assertEqual(list(PatternColorApprovalDecision.objects.filter(selection_id=row.source_selection_id).values()), decisions)
            self.assertEqual(row.source_selection.status, 'pending')
            self.assertEqual(row.audit_events[-1]['after']['category'], category)
            self.assertNotEqual(row.audit_events[-1]['before']['category'], category)
            push.assert_not_called()

    def test_invalid_categories_fail_atomically_in_api_model_and_database(self):
        row = self.create(category='fabro_color', remarks='Original')
        for invalid in ('', 'other', 'Interior Match', None):
            with self.subTest(category=invalid):
                # HTTP clients encode null as an empty value; service validation
                # separately covers non-string inputs below.
                value = '' if invalid is None else invalid
                self.assertEqual(self.client.post(reverse('save_color_selection_api'), self.values(category=value)).status_code, 400)
                self.assertEqual(self.edit(row, category=value, remarks='Must not persist').status_code, 400)
        from management.services import picked_colors
        for invalid in (None, [], {}, 7):
            with self.assertRaises(ValidationError):
                picked_colors.save(self.owner, self.vehicle.pk, self.values(category=invalid))
        row.refresh_from_db()
        self.assertEqual((row.category, row.remarks, len(row.audit_events)), ('fabro_color', 'Original', 1))
        self.assertEqual(PatternColorSelection.objects.count(), 1)
        self.assertEqual(ActivityLog.objects.filter(object_type='Picked Color').count(), 1)
        row.category = 'invalid'
        with self.assertRaises(ValidationError):
            row.full_clean()
        with self.assertRaises(IntegrityError), transaction.atomic():
            PickedColorSelection.objects.filter(pk=row.pk).update(category='invalid')

    def test_counts_delete_each_category_and_vehicle_isolation(self):
        first, second = self.create(), self.create(category='fabro_color')
        self.assertEqual(self.listing()['counts'], {'interior_match':1, 'fabro_color':1})
        self.assertEqual(self.listing(self.second.pk)['counts'], {'interior_match':0, 'fabro_color':0})
        for row in (first, second):
            self.assertEqual(self.client.post(reverse('delete_picked_color',args=[row.pk]), {'vehicle_id':self.vehicle.pk}).status_code, 200)
            row.refresh_from_db()
            self.assertIsNotNone(row.deleted_at)
            self.assertTrue(PatternColorSelection.objects.filter(pk=row.source_selection_id).exists())
        self.assertEqual(self.listing()['counts'], {'interior_match':0, 'fabro_color':0})
        self.assertIsNone(self.client.get(reverse('get_color_selection_details_api'), {'vehicle_id':self.vehicle.pk}).json()['selection'])

    def test_category_never_bypasses_ownership_country_or_permission_denials(self):
        row = self.create()
        self.client.force_login(self.other)
        self.assertEqual(self.edit(row, category='fabro_color').status_code, 403)
        self.assertEqual(self.edit(row, category='fabro_color', vehicle_id=self.second.pk).status_code, 404)
        person = self.other.workflow_profile
        person.role = WorkflowRoles.COUNTRY_EXECUTIVE
        person.country = MasterSetting.objects.create(category='Country', name='Other country')
        person.activity_permissions = {'picked_colors.edit_all':'allow'}
        person.save()
        self.assertEqual(self.edit(row, category='fabro_color').status_code, 404)
        self.client.force_login(self.owner)
        person = self.owner.workflow_profile
        person.activity_permissions = {'picked_colors.edit_own':'deny', 'picked_colors.delete_own':'deny'}
        person.save()
        self.assertEqual(self.edit(row, category='fabro_color').status_code, 403)
        self.assertEqual(self.client.post(reverse('delete_picked_color',args=[row.pk]), {'vehicle_id':self.vehicle.pk}).status_code, 403)
        self.assertFalse(self.listing()['selections'][0]['can_edit'])
        self.assertFalse(self.listing()['selections'][0]['can_delete'])

    def test_replayed_create_and_move_do_not_duplicate(self):
        values = self.values(category='fabro_color')
        first = self.client.post(reverse('save_color_selection_api'), values).json()
        self.assertFalse(self.client.post(reverse('save_color_selection_api'), values).json()['created'])
        row = PickedColorSelection.objects.get(pk=first['picked_selection']['id'])
        values.update(category='interior_match', client_submission_key=str(uuid4()))
        url = reverse('edit_picked_color',args=[row.pk])
        self.assertTrue(self.client.post(url, values).json()['changed'])
        self.assertFalse(self.client.post(url, values).json()['changed'])
        self.assertEqual(PickedColorSelection.objects.count(), 1)
        self.assertEqual(PatternColorSelection.objects.count(), 1)


class ColorCategoryMigrationTests(TransactionTestCase):
    @skipUnless(connection.vendor == 'postgresql', 'Migration preservation is rehearsed on local PostgreSQL')
    def test_previous_schema_records_media_and_reviews_are_unchanged(self):
        self.assertIn(connection.settings_dict['HOST'], ('localhost','127.0.0.1'))
        self.assertTrue(connection.settings_dict['NAME'].startswith('test_'))
        old, new = ('management','0052_picked_color_photos'), ('management','0053_picked_color_category')
        executor = MigrationExecutor(connection)
        executor.migrate([old])
        try:
            apps = executor.loader.project_state([old]).apps
            get = lambda name: apps.get_model('management',name)
            user = apps.get_model('auth','User').objects.create(username='migration-category', password='!')
            brand = get('Brand').objects.create(name='Migration Category Brand')
            model = get('Model').objects.create(brand_id=brand.pk, name='Model')
            sub = get('SubModel').objects.create(model_id=model.pk, name='Sub')
            vehicle = get('YearRange').objects.create(sub_model_id=sub.pk, layout_code='CAT-MIGRATION')
            source = get('PatternColorSelection').objects.create(vehicle_id=vehicle.pk, submitted_by_id=user.pk,
                swatch_image='color_swatches/retained.png', status='approved', tone_type='dual')
            decision = get('PatternColorApprovalDecision').objects.create(selection_id=source.pk, department='CAD',
                decision='approved', remarks='Recorded approval', approver_id=user.pk)
            row = get('PickedColorSelection').objects.create(vehicle_id=vehicle.pk, source_selection_id=source.pk,
                created_by_id=user.pk, creator_name='Original uploader', remarks='Preserved remarks',
                snapshot={'tone_type':'dual','inner':{'name':'BLACK','hex':'#111111','pantone':'P-1'},
                          'outer':{'name':'L.CREAM','hex':'#F4E6C3'}}, audit_events=[{'action':'created'}])
            photo = get('PickedColorPhoto').objects.create(selection_id=row.pk, image='picked_color_photos/retained.png',
                upload_key='migration-category-photo', uploaded_by_id=user.pk)
            photo.approval_selections.add(source)
            before = get('PickedColorSelection').objects.get(pk=row.pk)
            values = {field.attname:getattr(before,field.attname) for field in before._meta.fields}
            decision_values = get('PatternColorApprovalDecision').objects.filter(pk=decision.pk).values().get()
            executor = MigrationExecutor(connection)
            executor.migrate([new])
            apps = executor.loader.project_state([new]).apps
            after = apps.get_model('management','PickedColorSelection').objects.get(pk=row.pk)
            self.assertEqual(after.category, 'interior_match')
            self.assertEqual({key:getattr(after,key) for key in values}, values)
            self.assertEqual(apps.get_model('management','PatternColorApprovalDecision').objects.filter(pk=decision.pk).values().get(), decision_values)
            retained = apps.get_model('management','PickedColorPhoto').objects.get(pk=photo.pk)
            self.assertEqual(retained.image.name, 'picked_color_photos/retained.png')
            self.assertEqual(list(retained.approval_selections.values_list('pk',flat=True)), [source.pk])
            self.assertEqual(apps.get_model('management','PickedColorSelection').objects.count(), 1)
        finally:
            MigrationExecutor(connection).migrate([new])
