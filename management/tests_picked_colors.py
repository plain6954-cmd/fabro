import importlib
from unittest.mock import patch
from uuid import uuid4
from types import SimpleNamespace
from django.apps import apps
from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.db import connection
from django.test import Client, TestCase
from django.urls import reverse
from management.models import (ActivityLog, Brand, ColorMaster, MasterSetting, Model, Notification,
    PatternColorApprovalDecision, PatternColorSelection, PickedColorSelection, SubModel, WorkflowRoles, YearRange)
from management.services import picked_colors
from management.services.activity_permissions import REGISTRY, granted

User = get_user_model()


class PickedColorsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = cls.user('picked-owner')
        cls.other = cls.user('picked-other')
        cls.admin = User.objects.create_superuser('picked-admin', 'admin@example.com', 'StrongPicked!369')
        brand = Brand.objects.create(name='Picked Brand')
        model = Model.objects.create(brand=brand, name='Picked Model')
        sub = SubModel.objects.create(model=model, name='Picked Sub')
        cls.country = MasterSetting.objects.create(category='Country', name='Picked Country')
        cls.foreign = MasterSetting.objects.create(category='Country', name='Other Picked Country')
        cls.vehicle = YearRange.objects.create(sub_model=sub, layout_code='PC-1', vehicle_country=cls.country)
        cls.second = YearRange.objects.create(sub_model=sub, layout_code='PC-2', vehicle_country=cls.foreign)
        cls.red = ColorMaster.objects.create(name='Recorded Red', color_code='PC-RED', hex_code='#B11226', pantone_code='RED-P')
        cls.blue = ColorMaster.objects.create(name='Recorded Blue', color_code='PC-BLUE', hex_code='#173B72')
        for role in ('CAD', 'ED', 'MD'):
            user = cls.user('picked-' + role.lower())
            person = user.workflow_profile; person.role = WorkflowRoles.APPROVER; person.approval_role = role; person.save()

    @classmethod
    def user(cls, name):
        user = User.objects.create_user(name, name+'@example.com', 'StrongPicked!369', first_name='Actual', last_name=name)
        person = user.workflow_profile; person.role = WorkflowRoles.FACTORY_VIEWER; person.save()
        return user

    def setUp(self):
        self.client.force_login(self.owner)

    def values(self, **changes):
        return {'vehicle_id': self.vehicle.pk, 'tone_type': 'single', 'inner_source': 'existing',
            'inner_existing_color_id': self.red.pk, 'client_submission_key': str(uuid4()), **changes}

    def add(self, **changes):
        response = self.client.post(reverse('save_color_selection_api'), self.values(**changes))
        self.assertEqual(response.status_code, 200, response.content)
        return PickedColorSelection.objects.get(pk=response.json()['picked_selection']['id'])

    def edit(self, row, **changes):
        return self.client.post(reverse('edit_picked_color', args=[row.pk]), self.values(**changes))

    def permissions(self, user, values):
        person = user.workflow_profile; person.activity_permissions = values; person.save(update_fields=['activity_permissions'])
        user.__dict__.pop('_activity_grants', None); user.__dict__.pop('_workflow_profile', None)

    def test_registry_defaults_and_server_creator(self):
        self.assertEqual(sum(key.startswith('picked_colors.') for key in REGISTRY), 6)
        self.assertTrue(granted(self.owner, 'picked_colors.add'))
        self.assertTrue(granted(self.owner, 'picked_colors.edit_own'))
        self.assertFalse(granted(self.owner, 'picked_colors.edit_all'))
        row = self.add(created_by=self.other.pk, creator_name='Forged', remarks='Actual remark')
        self.assertEqual(row.created_by, self.owner)
        self.assertEqual(row.creator_name, self.owner.get_full_name())
        self.assertEqual(row.remarks, 'Actual remark')

    def test_multiple_saves_snapshots_and_newest_first(self):
        first = self.add()
        second = self.add(inner_existing_color_id=self.blue.pk)
        self.red.name = 'Renamed'; self.red.hex_code = '#000000'; self.red.color_code = 'CHANGED'; self.red.save()
        data = self.client.get(reverse('list_picked_colors'), {'vehicle_id': self.vehicle.pk}).json()['selections']
        self.assertEqual([row['id'] for row in data], [second.pk, first.pk])
        self.assertEqual(data[1]['snapshot']['inner']['name'], 'Recorded Red')
        self.assertEqual(data[1]['snapshot']['inner']['code'], 'PC-RED')
        self.assertEqual(data[1]['snapshot']['inner']['hex'], '#B11226')

    def test_dual_create_and_edit_preserve_creator_date_and_original_proposal(self):
        row = self.add(tone_type='dual', outer_source='existing', outer_existing_color_id=self.blue.pk)
        created_at, original = row.created_at, row.source_selection_id
        self.assertEqual(row.snapshot['outer']['hex'], '#173B72')
        response = self.edit(row, remarks='Updated', inner_existing_color_id=self.blue.pk)
        self.assertEqual(response.status_code, 200, response.content)
        row.refresh_from_db()
        self.assertEqual(row.created_at, created_at)
        self.assertEqual(row.created_by, self.owner)
        self.assertEqual(row.edited_by, self.owner)
        self.assertEqual(row.snapshot['tone_type'], 'single')
        self.assertNotEqual(row.source_selection_id, original)
        self.assertEqual(PatternColorSelection.objects.get(pk=original).tone_type, 'dual')
        self.assertEqual(PickedColorSelection.objects.count(), 1)
        self.assertEqual(len(row.audit_events), 2)

    def test_remarks_edit_keeps_snapshot_even_if_master_changes(self):
        row = self.add()
        self.red.name = 'Changed later'; self.red.save()
        response = self.edit(row, remarks='Safe <script>alert(1)</script> text')
        self.assertEqual(response.status_code, 200)
        row.refresh_from_db()
        self.assertEqual(row.snapshot['inner']['name'], 'Recorded Red')
        self.assertEqual(PatternColorSelection.objects.count(), 1)
        self.assertEqual(row.audit_events[-1]['before']['remarks'], '')

    def test_own_all_and_unknown_ownership_are_checked_on_every_write(self):
        row = self.add()
        self.client.force_login(self.other)
        self.assertEqual(self.edit(row).status_code, 403)
        self.assertEqual(self.client.post(reverse('delete_picked_color', args=[row.pk]), {'vehicle_id': self.vehicle.pk}).status_code, 403)
        self.permissions(self.other, {'picked_colors.edit_all': 'allow', 'picked_colors.delete_all': 'allow'})
        self.assertEqual(self.edit(row, remarks='Authorized all').status_code, 200)
        row.refresh_from_db(); self.assertEqual(row.created_by, self.owner)
        self.assertEqual(self.client.post(reverse('delete_picked_color', args=[row.pk]), {'vehicle_id': self.vehicle.pk}).status_code, 200)
        unknown = self.add(inner_existing_color_id=self.blue.pk)
        unknown.created_by = None; unknown.save(update_fields=['created_by'])
        self.permissions(self.other, {})
        self.assertEqual(self.edit(unknown).status_code, 403)

    def test_all_does_not_bypass_country_scope(self):
        row = self.add()
        executive = self.user('picked-country-user')
        person = executive.workflow_profile; person.role = WorkflowRoles.COUNTRY_EXECUTIVE; person.country = self.foreign
        person.activity_permissions = {'picked_colors.edit_all': 'allow', 'picked_colors.delete_all': 'allow'}; person.save()
        self.client.force_login(executive)
        self.assertEqual(self.client.get(reverse('list_picked_colors'), {'vehicle_id': self.vehicle.pk}).status_code, 404)
        self.assertEqual(self.edit(row).status_code, 404)
        self.assertEqual(self.client.post(reverse('delete_picked_color', args=[row.pk]), {'vehicle_id': self.vehicle.pk}).status_code, 404)

    def test_cross_vehicle_idor_and_list_isolation(self):
        row = self.add()
        self.assertEqual(self.edit(row, vehicle_id=self.second.pk).status_code, 404)
        self.assertEqual(self.client.post(reverse('delete_picked_color', args=[row.pk]), {'vehicle_id': self.second.pk}).status_code, 404)
        self.assertEqual(self.client.get(reverse('list_picked_colors'), {'vehicle_id': self.second.pk}).json()['selections'], [])

    def test_soft_delete_retains_master_media_approval_subject_and_audit(self):
        row = self.add()
        proposal = row.source_selection
        details_url = reverse('get_color_selection_details_api')
        before = self.client.get(details_url, {'vehicle_id': self.vehicle.pk})
        self.assertEqual(before.status_code, 200)
        self.assertEqual(before.json()['selection']['id'], proposal.pk)
        proposal.swatch_image.save('shared.png', ContentFile(b'kept shared media'))
        filename, storage = proposal.swatch_image.name, proposal.swatch_image.storage
        self.addCleanup(storage.delete, filename)
        self.assertEqual(self.client.post(reverse('delete_picked_color', args=[row.pk]), {'vehicle_id': self.vehicle.pk}).status_code, 200)
        row.refresh_from_db()
        self.assertIsNotNone(row.deleted_at)
        after = self.client.get(details_url, {'vehicle_id': self.vehicle.pk})
        self.assertEqual(after.status_code, 200)
        self.assertIsNone(after.json()['selection'])
        self.assertTrue(storage.exists(filename))
        self.assertTrue(PatternColorSelection.objects.filter(pk=proposal.pk).exists())
        self.assertTrue(ColorMaster.objects.filter(pk=self.red.pk).exists())
        self.assertEqual(row.audit_events[-1]['action'], 'deleted')
        self.assertEqual(self.client.get(reverse('list_picked_colors'), {'vehicle_id': self.vehicle.pk}).json()['selections'], [])
        self.assertEqual(self.edit(row).status_code, 404)

    def test_anonymous_methods_csrf_and_authenticated_swatch(self):
        anonymous = Client()
        self.assertEqual(anonymous.get(reverse('list_picked_colors'), {'vehicle_id': self.vehicle.pk}).status_code, 302)
        row = self.add()
        self.assertEqual(self.client.get(reverse('edit_picked_color', args=[row.pk])).status_code, 405)
        self.assertEqual(self.client.get(reverse('delete_picked_color', args=[row.pk])).status_code, 405)
        guarded = Client(enforce_csrf_checks=True); guarded.force_login(self.owner)
        guarded.get(reverse('car_details'))
        self.assertEqual(guarded.post(reverse('save_color_selection_api'), self.values()).status_code, 403)
        self.assertEqual(guarded.post(reverse('edit_picked_color', args=[row.pk]), self.values()).status_code, 403)
        self.assertEqual(guarded.post(reverse('delete_picked_color', args=[row.pk]), {'vehicle_id': self.vehicle.pk}).status_code, 403)
        self.assertEqual(guarded.post(reverse('save_color_selection_api'), self.values(), HTTP_X_CSRFTOKEN=guarded.cookies['csrftoken'].value).status_code, 200)
        proposal = row.source_selection; proposal.swatch_image.save('private.png', ContentFile(b'private'))
        self.addCleanup(proposal.swatch_image.storage.delete, proposal.swatch_image.name)
        url = reverse('picked_color_swatch', args=[row.pk]) + f'?vehicle_id={self.vehicle.pk}'
        response = self.client.get(url); self.assertEqual(response.status_code, 200); self.assertEqual(b''.join(response.streaming_content), b'private')
        self.permissions(self.owner, {'picked_colors.view': 'deny'})
        self.assertEqual(self.client.get(url).status_code, 403)
        self.assertEqual(anonymous.get(url).status_code, 302)

    def test_revocation_is_immediate_and_inactive_accounts_fail_closed(self):
        row = self.add()
        for key, request in [
            ('picked_colors.add', lambda: self.client.post(reverse('save_color_selection_api'), self.values())),
            ('picked_colors.edit_own', lambda: self.edit(row)),
            ('picked_colors.delete_own', lambda: self.client.post(reverse('delete_picked_color', args=[row.pk]), {'vehicle_id': self.vehicle.pk})),
            ('picked_colors.view', lambda: self.client.get(reverse('list_picked_colors'), {'vehicle_id': self.vehicle.pk}))]:
            self.permissions(self.owner, {key: 'deny'})
            self.assertEqual(request().status_code, 403, key)
        self.permissions(self.owner, {})
        self.assertEqual(self.edit(row).status_code, 200)
        self.owner.is_active = False; self.owner.save(update_fields=['is_active'])
        self.assertEqual(self.client.get(reverse('list_picked_colors'), {'vehicle_id': self.vehicle.pk}).status_code, 302)

    def test_bad_inputs_and_master_ids_do_not_partially_write(self):
        for values in ({'remarks': 'x'*2001}, {'tone_type': 'bad'}, {'inner_existing_color_id': 'NaN'},
            {'inner_source': 'new', 'inner_hex_code': 'url(evil)', 'inner_pantone_code': 'BAD'},
            {'inner_source': 'new', 'inner_hex_code': '#123456', 'inner_pantone_code': ''},
            {'inner_source': 'new', 'inner_hex_code': '#123456', 'inner_pantone_code': 'P', 'inner_color_name': 'x'*101}):
            response = self.client.post(reverse('save_color_selection_api'), self.values(**values))
            self.assertEqual(response.status_code, 400, response.content)
        self.red.status = 'Discontinued'; self.red.save()
        self.assertEqual(self.client.post(reverse('save_color_selection_api'), self.values()).status_code, 400)
        self.assertEqual((PickedColorSelection.objects.count(), PatternColorSelection.objects.count(), ActivityLog.objects.filter(object_type='Picked Color').count()), (0, 0, 0))

    def test_duplicate_keys_are_namespaced_and_replayed_edits_do_not_duplicate(self):
        data = self.values()
        first = self.client.post(reverse('save_color_selection_api'), data).json()['picked_selection']
        self.assertFalse(self.client.post(reverse('save_color_selection_api'), data).json()['created'])
        self.client.force_login(self.other)
        other = self.client.post(reverse('save_color_selection_api'), data).json()['picked_selection']
        self.assertNotEqual(first['id'], other['id'])
        self.client.force_login(self.owner)
        row = PickedColorSelection.objects.get(pk=first['id']); key = str(uuid4())
        self.assertEqual(self.edit(row, client_submission_key=key, remarks='Once').status_code, 200)
        self.assertFalse(self.edit(row, client_submission_key=key, remarks='Once').json()['changed'])
        row.refresh_from_db(); self.assertEqual(len(row.audit_events), 2)

    def test_atomic_rollback_and_backfill_preserve_original_values(self):
        with patch('management.services.picked_colors.audit', side_effect=RuntimeError('synthetic failure')):
            with self.assertRaises(RuntimeError):
                self.add()
        self.assertEqual((PickedColorSelection.objects.count(), PatternColorSelection.objects.count()), (0, 0))
        proposal = PatternColorSelection.objects.create(vehicle=self.vehicle, submitted_by=self.owner,
            inner_source='existing', inner_existing_color=self.red, inner_color_name='Original stored name', inner_hex_code='#ABCDEF', client_submission_key='legacy-key')
        migration = importlib.import_module('management.migrations.0051_picked_color_snapshots')
        migration.backfill_picked_colors(apps, SimpleNamespace(connection=connection))
        row = PickedColorSelection.objects.get(source_selection=proposal)
        self.assertEqual(row.created_at, proposal.created_at)
        self.assertEqual(row.snapshot['inner']['name'], 'Original stored name')
        self.assertEqual(row.snapshot['inner']['hex'], '#ABCDEF')
        self.assertFalse(self.client.post(reverse('save_color_selection_api'), self.values(client_submission_key='legacy-key')).json()['created'])
        self.assertEqual(PickedColorSelection.objects.count(), 1)

    @patch('management.services.push_notifications.send_push_to_user')
    def test_color_changes_reuse_notifications_once_and_remarks_do_not_notify(self, push):
        data = self.values(inner_source='new', inner_hex_code='#123456', inner_pantone_code='PC-NEW', inner_color_name='New color')
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(reverse('save_color_selection_api'), data)
        self.assertEqual(response.status_code, 200, response.content)
        row = PickedColorSelection.objects.get(pk=response.json()['picked_selection']['id'])
        self.assertEqual(push.call_count, 3)
        self.assertEqual(set(Notification.objects.values_list('recipient__username', flat=True)), {'picked-cad', 'picked-ed', 'picked-md'})
        self.assertTrue(all(call.kwargs['url'] == '/approvals/?stage=colors' for call in push.call_args_list))
        data.update(remarks='Only a note', client_submission_key=str(uuid4()))
        with self.captureOnCommitCallbacks(execute=True):
            self.assertEqual(self.client.post(reverse('edit_picked_color', args=[row.pk]), data).status_code, 200)
        self.assertEqual(push.call_count, 3)
        data.update(inner_hex_code='#654321', client_submission_key=str(uuid4()))
        with self.captureOnCommitCallbacks(execute=True):
            self.assertEqual(self.client.post(reverse('edit_picked_color', args=[row.pk]), data).status_code, 200)
        self.assertEqual(push.call_count, 6)
        self.assertEqual(PatternColorApprovalDecision.objects.count(), 6)
        self.assertFalse(Notification.objects.filter(recipient__in=[self.owner, self.other]).exists())

    @patch('management.services.push_notifications.send_push_to_user', side_effect=RuntimeError('offline'))
    def test_external_push_failure_does_not_break_save(self, push):
        with self.captureOnCommitCallbacks(execute=True):
            row = self.add(inner_source='new', inner_hex_code='#123456', inner_pantone_code='P')
        self.assertTrue(PickedColorSelection.objects.filter(pk=row.pk).exists())
        self.assertEqual(push.call_count, 3)
