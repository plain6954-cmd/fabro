"""Private matching-photo API regressions; run with isolated local PostgreSQL."""
import hashlib
from concurrent.futures import ThreadPoolExecutor
import importlib
import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from threading import Barrier
from unittest.mock import patch
from uuid import uuid4

from django.apps import apps
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection, connections
from django.test import Client, TestCase, TransactionTestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from PIL import Image

from management.models import (ActivityLog, Brand, ColorMaster, MasterSetting, Model, Notification,
    PatternColorSelection, PickedColorPhoto, PickedColorSelection, SubModel, WorkflowRoles, YearRange)
from management.services import picked_colors
from management.services import swatch_photos

User = get_user_model()


def image_bytes(color='red'):
    stream = io.BytesIO()
    Image.new('RGB', (12, 8), color=color).save(stream, 'PNG')
    return stream.getvalue()


def upload_file(content=None, name='swatch.png'):
    return SimpleUploadedFile(name, image_bytes() if content is None else content, 'image/png')


class MatchingSwatchPhotoTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = cls.account('photo-owner')
        cls.other = cls.account('photo-other')
        cls.admin = User.objects.create_superuser('photo-admin', 'admin@example.test', 'PhotoTest!38')
        brand = Brand.objects.create(name='Photo Brand')
        model = Model.objects.create(brand=brand, name='Photo Model')
        sub = SubModel.objects.create(model=model, name='Photo Submodel')
        cls.country = MasterSetting.objects.create(category='Country', name='Photo Country')
        cls.foreign = MasterSetting.objects.create(category='Country', name='Foreign Photo Country')
        cls.vehicle = YearRange.objects.create(sub_model=sub, layout_code='PHOTO-1', vehicle_country=cls.country)
        cls.second = YearRange.objects.create(sub_model=sub, layout_code='PHOTO-2', vehicle_country=cls.foreign)
        cls.red = ColorMaster.objects.create(name='Photo Red', color_code='PHOTO-R', hex_code='#FF0000', pantone_code='R')
        cls.blue = ColorMaster.objects.create(name='Photo Blue', color_code='PHOTO-B', hex_code='#0000FF', pantone_code='B')

    @classmethod
    def account(cls, name):
        user = User.objects.create_user(name)
        user.workflow_profile.role = WorkflowRoles.FREELANCE_3D_DESIGNER
        user.workflow_profile.save()
        return user

    def setUp(self):
        self.media = TemporaryDirectory(prefix='swatch-api-')
        self.addCleanup(self.media.cleanup)
        settings = override_settings(MEDIA_ROOT=self.media.name, USE_S3_STORAGE=False, USE_SUPABASE_STORAGE=False,
            STORAGES={'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
                      'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'}})
        settings.enable()
        self.addCleanup(settings.disable)
        no_s3 = patch('management.storage_backends.S3Storage._save', side_effect=AssertionError('Live S3 access is forbidden'))
        no_s3.start()
        self.addCleanup(no_s3.stop)
        self.client.force_login(self.owner)

    def values(self, **extra):
        return {'vehicle_id': self.vehicle.pk, 'tone_type': 'single', 'inner_source': 'existing',
            'inner_existing_color_id': self.red.pk, 'client_submission_key': str(uuid4()), **extra}

    def create(self, **extra):
        response = self.client.post(reverse('save_color_selection_api'), self.values(**extra))
        self.assertEqual(response.status_code, 200, response.content)
        return PickedColorSelection.objects.get(pk=response.json()['picked_selection']['id'])

    def upload(self, row, *, content=None, key=None, name='swatch.png', vehicle=None):
        return self.client.post(reverse('upload_picked_color_photo', args=[row.pk]), {
            'vehicle_id': vehicle or row.vehicle_id, 'upload_key': key or str(uuid4()), 'photo': upload_file(content, name)})

    def listing(self, row, client=None, vehicle=None):
        return (client or self.client).get(reverse('list_picked_color_photos', args=[row.pk]), {'vehicle_id': vehicle or row.vehicle_id})

    def files(self):
        return [path for path in Path(self.media.name).rglob('*') if path.is_file()]

    def permissions(self, user, **values):
        user.workflow_profile.activity_permissions = values
        user.workflow_profile.save(update_fields=['activity_permissions'])
        user.__dict__.pop('_activity_grants', None)
        user.__dict__.pop('_workflow_profile', None)

    def body(self, response):
        try:
            return b''.join(response.streaming_content)
        finally:
            if getattr(response, 'file_to_stream', None):
                response.file_to_stream.close()

    def test_single_multiple_and_later_photos_persist_with_private_metadata(self):
        row = self.create()
        first = self.upload(row)
        second = self.upload(row, content=image_bytes('blue'), name='second.png')
        self.assertEqual((first.status_code, second.status_code), (200, 200))
        fresh = Client()
        fresh.force_login(self.owner)
        photos = self.listing(row, fresh).json()['photos']
        self.assertEqual(len(photos), 2)
        self.assertEqual({p['id'] for p in photos}, {first.json()['photo']['id'], second.json()['photo']['id']})
        self.assertTrue(all(p['uploaded_by'] == self.owner.username for p in photos))
        self.assertEqual(len(self.files()), 2)
        self.assertEqual(ActivityLog.objects.filter(action='photo_added').count(), 2)
        self.assertEqual(row.source_selection.swatch_photos.count(), 2)
        self.assertFalse(Notification.objects.exists())
        for photo in photos:
            response = self.client.get(photo['url'])
            if getattr(response, 'file_to_stream', None):
                self.addCleanup(response.file_to_stream.close)
            self.assertEqual(response.status_code, 200)
            self.assertTrue({'private', 'no-store'} <= {part.strip() for part in response['Cache-Control'].split(',')})
            self.assertEqual(response['X-Content-Type-Options'], 'nosniff')
            self.assertTrue(self.body(response).startswith(b'\x89PNG'))
            self.assertNotIn('supabase', photo['url'])

    def test_pre_save_reservations_contain_no_storage_objects(self):
        raw = str(uuid4())
        plans = [{'upload_key': raw, 'filename': 'first.png', 'file_size': len(image_bytes()),
                  'sha256': hashlib.sha256(image_bytes()).hexdigest()}]
        row = self.create(swatch_photos=json.dumps(plans))
        self.assertEqual(self.files(), [])
        self.assertEqual(self.listing(row).json()['photos'], [])
        self.assertEqual(row.swatch_photos.count(), 1)
        self.assertEqual(self.upload(row, key=raw).status_code, 200)
        self.assertEqual(len(self.listing(row).json()['photos']), 1)

    def test_add_only_initial_upload_is_hash_bound_and_does_not_grant_editing(self):
        self.permissions(self.owner, **{'picked_colors.edit_own': 'deny', 'picked_colors.edit_all': 'deny'})
        key = str(uuid4())
        prepared = [{'upload_key': key, 'filename': 'swatch.png', 'file_size': len(image_bytes()),
                     'sha256': hashlib.sha256(image_bytes()).hexdigest()}]
        row = self.create(swatch_photos=json.dumps(prepared))
        self.assertEqual(self.upload(row, key=key, content=image_bytes('blue')).status_code, 400)
        response = self.upload(row, key=key)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertFalse(response.json()['photo']['can_delete'])
        self.assertEqual(self.upload(row, content=image_bytes('blue')).status_code, 403)
        remove = self.client.post(reverse('remove_picked_color_photo', args=[row.pk, response.json()['photo']['id']]), {'vehicle_id': row.vehicle_id})
        self.assertEqual(remove.status_code, 403)

    def test_expired_initial_upload_does_not_bypass_edit_denial(self):
        key = str(uuid4())
        row = self.create(swatch_photos=json.dumps([{'upload_key':key, 'filename':'swatch.png',
            'file_size':len(image_bytes()), 'sha256':hashlib.sha256(image_bytes()).hexdigest()}]))
        row.swatch_photos.update(initial_upload_expires_at=timezone.now() - timezone.timedelta(seconds=1))
        self.permissions(self.owner, **{'picked_colors.edit_own':'deny','picked_colors.edit_all':'deny'})
        self.assertEqual(self.upload(row, key=key).status_code, 403)
        self.assertEqual(self.files(), [])

    def test_retries_and_duplicate_content_do_not_create_duplicates(self):
        row = self.create()
        key = str(uuid4())
        first = self.upload(row, key=key)
        retry = self.upload(row, key=key)
        duplicate = self.upload(row, name='renamed.png')
        self.assertEqual((retry.status_code, duplicate.status_code), (200, 200))
        self.assertEqual(first.json()['photo']['id'], retry.json()['photo']['id'])
        self.assertEqual(first.json()['photo']['id'], duplicate.json()['photo']['id'])
        self.assertFalse(retry.json()['created'])
        self.assertFalse(duplicate.json()['created'])
        self.assertEqual(row.swatch_photos.count(), 1)
        self.assertEqual(len(self.files()), 1)
        self.assertEqual(self.upload(row, key=key, content=image_bytes('blue')).status_code, 400)

    def test_invalid_types_corrupt_images_and_ten_mb_limit(self):
        row = self.create()
        for name, content in [('swatch.txt', b'plain'), ('fake.png', b'not an image'),
                              ('empty.png', b''), ('huge.heic', b'x' * (10*1024*1024+1))]:
            with self.subTest(name=name):
                self.assertEqual(self.upload(row, content=content, name=name).status_code, 400)
        self.assertEqual(self.files(), [])
        self.assertFalse(row.swatch_photos.exists())

    def test_heic_heif_follow_existing_opaque_file_policy(self):
        row = self.create()
        for name in ('sample.heic', 'sample.heif'):
            response = self.upload(row, name=name, content=('opaque test ' + name).encode())
            self.assertEqual(response.status_code, 200, response.content)
            stored = self.client.get(response.json()['photo']['url'])
            self.assertEqual(stored.status_code, 200)
            self.assertEqual(self.body(stored), ('opaque test ' + name).encode())

    def test_storage_failure_is_not_success_and_same_key_can_retry(self):
        row = self.create()
        storage = PickedColorPhoto._meta.get_field('image').storage
        original = storage.save
        def write_then_fail(name, file, **kwargs):
            original(name, file, **kwargs)
            raise OSError('Simulated interrupted private storage write')
        key = str(uuid4())
        with patch.object(storage, 'save', side_effect=write_then_fail):
            self.assertEqual(self.upload(row, key=key).status_code, 503)
        self.assertEqual(self.files(), [])
        self.assertEqual(self.listing(row).json()['photos'], [])
        self.assertEqual(self.upload(row, key=key).status_code, 200)
        self.assertEqual(row.swatch_photos.count(), 1)

    def test_database_audit_failure_rolls_back_record_and_cleans_new_storage(self):
        row = self.create()
        with patch('management.services.swatch_photos._audit', side_effect=RuntimeError('Simulated audit failure')):
            self.assertEqual(self.upload(row).status_code, 503)
        self.assertEqual(self.files(), [])
        self.assertFalse(row.swatch_photos.filter(uploaded_at__isnull=False).exists())
        self.assertEqual(row.swatch_photos.count(), 1)  # Owned pending intent, never a saved image.
        self.assertFalse(ActivityLog.objects.filter(action='photo_added').exists())

    def test_failed_cleanup_keeps_a_durable_owned_key_for_retry(self):
        row = self.create()
        storage = PickedColorPhoto._meta.get_field('image').storage
        original_save, original_delete = storage.save, storage.delete
        key = str(uuid4())
        def write_then_fail(name, file, **kwargs):
            original_save(name, file, **kwargs)
            raise OSError('Simulated lost storage acknowledgement')
        def refuse_existing_delete(name):
            if storage.exists(name):
                raise OSError('Simulated unavailable cleanup')
            return original_delete(name)
        with patch.object(storage, 'save', side_effect=write_then_fail), patch.object(storage, 'delete', side_effect=refuse_existing_delete):
            self.assertEqual(self.upload(row, key=key).status_code, 503)
        pending = row.swatch_photos.get()
        self.assertIsNone(pending.uploaded_at)
        self.assertFalse(pending.image)
        self.assertTrue(pending.pending_storage_key)
        self.assertTrue(storage.exists(pending.pending_storage_key))
        self.assertEqual(self.listing(row).json()['photos'], [])
        self.assertEqual(self.upload(row, key=key).status_code, 200)
        pending.refresh_from_db()
        self.assertFalse(pending.pending_storage_key)
        self.assertEqual(len(self.files()), 1)

    def test_photo_ids_cannot_cross_color_selections_on_the_same_vehicle(self):
        first, second = self.create(), self.create()
        photo = self.upload(second).json()['photo']
        self.assertEqual(self.client.get(reverse('picked_color_photo_file',args=[first.pk,photo['id']]),{'vehicle_id':self.vehicle.pk}).status_code, 404)
        self.assertEqual(self.client.post(reverse('remove_picked_color_photo',args=[first.pk,photo['id']]),{'vehicle_id':self.vehicle.pk}).status_code, 404)
        self.assertEqual(self.client.get(reverse('color_selection_photo_file',args=[first.source_selection_id,photo['id']])).status_code, 404)
        self.assertEqual(self.body(self.client.get(photo['url'])), image_bytes())

    def test_photo_changes_reuse_existing_color_notifications_without_duplicates(self):
        reviewers = []
        for role in ('CAD','ED','MD'):
            user = User.objects.create_user('photo-reviewer-' + role)
            profile = user.workflow_profile
            profile.role, profile.approval_role = WorkflowRoles.APPROVER, role
            profile.save()
            reviewers.append(user)
        with patch('management.services.push_notifications.send_push_to_user') as push:
            with self.captureOnCommitCallbacks(execute=True):
                row = self.create(inner_source='new', inner_pantone_code='PHOTO-NEW', inner_hex_code='#123456', inner_color_name='Proposal')
            self.assertEqual(set(Notification.objects.filter(color_selection=row.source_selection).values_list('recipient_id',flat=True)), {user.pk for user in reviewers})
            self.assertEqual(push.call_count, 3)
            first = self.upload(row).json()['photo']
            self.assertEqual(self.upload(row).status_code, 200)
            self.assertEqual(self.client.post(reverse('remove_picked_color_photo',args=[row.pk,first['id']]),{'vehicle_id':row.vehicle_id}).status_code, 200)
            self.assertEqual(Notification.objects.count(), 3)
            self.assertEqual(push.call_count, 3)

    def test_cancel_before_and_after_transmission_preserves_history(self):
        row = self.create()
        key = str(uuid4())
        cancel = reverse('cancel_picked_color_photo_upload', args=[row.pk])
        self.assertEqual(self.client.post(cancel, {'vehicle_id':row.vehicle_id,'upload_key':key}).status_code, 200)
        self.assertEqual(self.upload(row, key=key).status_code, 400)
        self.assertEqual(self.files(), [])
        key = str(uuid4())
        photo = self.upload(row, key=key).json()['photo']
        self.assertEqual(self.client.post(cancel, {'vehicle_id':row.vehicle_id,'upload_key':key}).status_code, 200)
        self.assertEqual(self.listing(row).json()['photos'], [])
        self.assertEqual(self.client.get(photo['url']).status_code, 404)
        self.assertEqual(len(self.files()), 1)
        self.assertTrue(PickedColorPhoto.objects.get(pk=photo['id']).removed_at)
        historical = reverse('color_selection_photo_file', args=[row.source_selection_id, photo['id']])
        self.assertEqual(self.body(self.client.get(historical)), image_bytes())

    def test_independent_removal_and_color_edits_keep_original_approval_assets(self):
        row = self.create()
        first = self.upload(row).json()['photo']
        second = self.upload(row, content=image_bytes('blue')).json()['photo']
        old_source = row.source_selection_id
        response = self.client.post(reverse('edit_picked_color', args=[row.pk]), self.values(inner_existing_color_id=self.blue.pk))
        self.assertEqual(response.status_code, 200, response.content)
        row.refresh_from_db()
        self.assertNotEqual(row.source_selection_id, old_source)
        self.assertEqual(len(response.json()['selection']['swatch_photos']), 2)
        remove = self.client.post(reverse('remove_picked_color_photo', args=[row.pk, first['id']]), {'vehicle_id':row.vehicle_id})
        self.assertEqual(remove.status_code, 200)
        self.assertEqual([p['id'] for p in remove.json()['photos']], [second['id']])
        self.assertEqual(PatternColorSelection.objects.get(pk=old_source).swatch_photos.count(), 2)
        self.assertEqual(len(self.files()), 2)
        self.assertEqual(self.body(self.client.get(second['url'])), image_bytes('blue'))
        self.assertEqual(self.body(self.client.get(reverse('color_selection_photo_file', args=[old_source, first['id']]))), image_bytes())

    def test_soft_deleted_color_hides_current_gallery_but_keeps_historical_bytes(self):
        row = self.create()
        photo = self.upload(row).json()['photo']
        source_id = row.source_selection_id
        self.assertEqual(self.client.post(reverse('delete_picked_color', args=[row.pk]), {'vehicle_id':row.vehicle_id}).status_code, 200)
        self.assertEqual(self.listing(row).status_code, 404)
        self.assertEqual(self.client.get(photo['url']).status_code, 404)
        self.assertEqual(self.body(self.client.get(reverse('color_selection_photo_file', args=[source_id, photo['id']]))), image_bytes())
        self.assertEqual(len(self.files()), 1)

    def test_authentication_methods_csrf_and_owner_scope(self):
        row = self.create()
        photo = self.upload(row).json()['photo']
        anonymous = Client()
        self.assertEqual(self.listing(row, anonymous).status_code, 302)
        self.assertEqual(anonymous.get(photo['url']).status_code, 302)
        self.client.force_login(self.other)
        self.assertEqual(self.upload(row).status_code, 403)
        self.assertEqual(self.client.post(reverse('remove_picked_color_photo', args=[row.pk,photo['id']]), {'vehicle_id':row.vehicle_id}).status_code, 403)
        self.permissions(self.other, **{'picked_colors.edit_all':'allow'})
        self.assertEqual(self.upload(row, content=image_bytes('blue')).status_code, 200)
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get(reverse('upload_picked_color_photo', args=[row.pk])).status_code, 405)
        csrf = Client(enforce_csrf_checks=True)
        csrf.force_login(self.owner)
        self.assertEqual(csrf.post(reverse('upload_picked_color_photo', args=[row.pk]), {'vehicle_id':row.vehicle_id,'upload_key':str(uuid4()),'photo':upload_file()}).status_code, 403)
        self.assertEqual(csrf.post(reverse('remove_picked_color_photo', args=[row.pk,photo['id']]), {'vehicle_id':row.vehicle_id}).status_code, 403)
        self.assertEqual(csrf.post(reverse('cancel_picked_color_photo_upload', args=[row.pk]), {'vehicle_id':row.vehicle_id,'upload_key':str(uuid4())}).status_code, 403)

    def test_cross_vehicle_and_country_grants_fail_closed(self):
        row = self.create()
        photo = self.upload(row).json()['photo']
        self.assertEqual(self.upload(row, vehicle=self.second.pk).status_code, 404)
        self.assertEqual(self.listing(row, vehicle=self.second.pk).status_code, 404)
        self.assertEqual(self.client.get(reverse('picked_color_photo_file',args=[row.pk,photo['id']]),{'vehicle_id':self.second.pk}).status_code, 404)
        profile = self.owner.workflow_profile
        profile.role, profile.country = WorkflowRoles.COUNTRY_EXECUTIVE, self.foreign
        profile.activity_permissions = {'picked_colors.edit_all':'allow'}
        profile.save()
        self.assertEqual(self.upload(row).status_code, 404)
        self.assertEqual(self.listing(row).status_code, 404)
        self.assertEqual(self.client.get(photo['url']).status_code, 404)
        self.assertEqual(self.client.get(reverse('color_selection_photo_file',args=[row.source_selection_id,photo['id']])).status_code, 404)

    def test_permission_revocation_and_inactive_accounts_cannot_write_or_read(self):
        row = self.create()
        photo = self.upload(row).json()['photo']
        self.permissions(self.owner, **{'picked_colors.edit_own':'deny','picked_colors.edit_all':'deny'})
        self.assertEqual(self.upload(row).status_code, 403)
        self.permissions(self.owner, **{'picked_colors.view':'deny'})
        self.assertEqual(self.client.get(photo['url']).status_code, 403)
        self.assertEqual(self.listing(row).status_code, 403)
        self.assertEqual(self.client.get(reverse('color_selection_photo_file',args=[row.source_selection_id,photo['id']])).status_code, 403)
        self.assertEqual(self.client.get(reverse('color_selection_file',args=[row.source_selection_id])).status_code, 404)
        self.owner.is_active = False
        self.owner.save(update_fields=['is_active'])
        self.assertEqual(self.upload(row).status_code, 302)

    def test_legacy_import_is_idempotent_and_does_not_access_storage(self):
        source = PatternColorSelection.objects.create(vehicle=self.vehicle, submitted_by=self.owner,
            inner_color_name='Historical Red', inner_hex_code='#A00000', swatch_image=upload_file())
        row = PickedColorSelection.objects.create(vehicle=self.vehicle, source_selection=source,
            created_by=self.owner, creator_name=self.owner.username, snapshot={})
        filename = source.swatch_image.name
        before = self.files()
        migration = importlib.import_module('management.migrations.0052_picked_color_photos')
        with patch.object(source.swatch_image.storage, 'open', side_effect=AssertionError('Migration must not access storage')):
            migration.import_existing_swatches(apps, SimpleNamespace(connection=connection))
            migration.import_existing_swatches(apps, SimpleNamespace(connection=connection))
        photo = row.swatch_photos.get()
        self.assertEqual(photo.image.name, filename)
        self.assertEqual(photo.uploaded_at, source.created_at)
        self.assertEqual(photo.approval_selections.get().pk, source.pk)
        self.assertEqual(self.files(), before)
        self.assertEqual(self.body(self.client.get(reverse('picked_color_swatch',args=[row.pk]),{'vehicle_id':self.vehicle.pk})), image_bytes())

    def test_postgresql_photo_tables_follow_existing_rls_policy(self):
        if connection.vendor != 'postgresql':
            self.skipTest('PostgreSQL-specific table security')
        tables = [PickedColorPhoto._meta.db_table, PickedColorPhoto.approval_selections.through._meta.db_table]
        with connection.cursor() as cursor:
            cursor.execute('SELECT relname, relrowsecurity FROM pg_class WHERE relname = ANY(%s)', [tables])
            self.assertEqual(dict(cursor.fetchall()), {table:True for table in tables})

    def test_retained_saved_color_without_source_keeps_its_own_gallery(self):
        row = self.create()
        row.source_selection.delete()
        row.refresh_from_db()
        self.assertIsNone(row.source_selection_id)
        response = self.upload(row)
        self.assertEqual(response.status_code, 200, response.content)
        photo = row.swatch_photos.get(uploaded_at__isnull=False)
        self.assertFalse(photo.approval_selections.exists())
        self.assertEqual(self.body(self.client.get(response.json()['photo']['url'])), image_bytes())

    def test_reuploading_existing_single_image_deduplicates_without_migration_storage_reads(self):
        response = self.client.post(reverse('save_color_selection_api'), {**self.values(), 'swatch_image':upload_file()})
        self.assertEqual(response.status_code, 200)
        row = PickedColorSelection.objects.get(pk=response.json()['picked_selection']['id'])
        original = row.swatch_photos.get()
        self.assertEqual(original.sha256, '')
        duplicate = self.upload(row, name='renamed.png')
        self.assertEqual(duplicate.status_code, 200)
        self.assertFalse(duplicate.json()['created'])
        self.assertEqual(duplicate.json()['photo']['id'], original.pk)
        self.assertEqual(row.swatch_photos.count(), 1)
        self.assertEqual(len(self.files()), 1)


class SwatchPhotoConcurrencyTests(TransactionTestCase):
    def test_parallel_editors_store_identical_bytes_only_once(self):
        if connection.vendor != 'postgresql':
            self.skipTest('PostgreSQL row-lock integration test')
        with TemporaryDirectory(prefix='swatch-concurrent-') as directory, override_settings(
            MEDIA_ROOT=directory, USE_S3_STORAGE=False, USE_SUPABASE_STORAGE=False,
            STORAGES={'default':{'BACKEND':'django.core.files.storage.FileSystemStorage'},
                      'staticfiles':{'BACKEND':'django.contrib.staticfiles.storage.StaticFilesStorage'}}):
            owner = User.objects.create_user('concurrent-photo-owner')
            owner.workflow_profile.role = WorkflowRoles.FREELANCE_3D_DESIGNER
            owner.workflow_profile.save()
            admin = User.objects.create_superuser('concurrent-photo-admin','admin@example.test','SyntheticOnly!381')
            brand = Brand.objects.create(name='Concurrent Photo Brand')
            model = Model.objects.create(brand=brand,name='Concurrent Photo Model')
            sub = SubModel.objects.create(model=model,name='Concurrent Photo Sub')
            vehicle = YearRange.objects.create(sub_model=sub,layout_code='CONCURRENT-PHOTO')
            color = ColorMaster.objects.create(name='Concurrent Red',color_code='CONCURRENT-R',hex_code='#FF0000')
            row, _ = picked_colors.save(owner, vehicle.pk, {'tone_type':'single','inner_source':'existing',
                'inner_existing_color_id':color.pk,'client_submission_key':str(uuid4())})
            start = Barrier(2)
            def send(user_id):
                try:
                    actor = User.objects.get(pk=user_id)
                    start.wait(timeout=10)
                    _, photo, created = swatch_photos.upload(actor,vehicle.pk,row.pk,str(uuid4()),upload_file())
                    return photo.pk, created
                finally:
                    connections.close_all()
            with ThreadPoolExecutor(max_workers=2) as workers:
                results = list(workers.map(send, [owner.pk,admin.pk]))
            self.assertEqual(len({result[0] for result in results}), 1)
            self.assertEqual(sorted(result[1] for result in results), [False,True])
            self.assertEqual(row.swatch_photos.filter(uploaded_at__isnull=False).count(), 1)
            self.assertEqual(len([path for path in Path(directory).rglob('*') if path.is_file()]), 1)
            self.assertEqual(ActivityLog.objects.filter(action='photo_added').count(), 1)
