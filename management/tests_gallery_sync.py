from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from management.models import (
    ApprovalRoles, Brand, Model, PatternDesignFolder, PatternDesignImage,
    SubModel, WorkflowRoles, YearRange,
)
from management.services.design_approvals import record_design_review_decision, submit_design_for_approval
from management.views import _design_gallery_snapshot, _design_gallery_user_info


class GallerySyncTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.users = {}
        for name, role, approval in [
            ('designer', WorkflowRoles.FREELANCE_3D_DESIGNER, ''),
            ('other', WorkflowRoles.FREELANCE_3D_DESIGNER, ''),
            ('factory', WorkflowRoles.FACTORY_EXECUTIVE, ''),
            ('admin', WorkflowRoles.ADMIN, ''),
        ] + [(value.lower(), WorkflowRoles.APPROVER, value) for value in (ApprovalRoles.CAD, ApprovalRoles.ED, ApprovalRoles.MD, ApprovalRoles.OM, ApprovalRoles.PM)]:
            user = User.objects.create_user('sync_' + name)
            profile = user.workflow_profile
            profile.role, profile.approval_role = role, approval
            profile.save()
            cls.users[name] = user
        brand = Brand.objects.create(name='Sync Brand')
        model = Model.objects.create(brand=brand, name='Sync Model')
        sub = SubModel.objects.create(model=model, name='Sync Sub')
        cls.vehicle = YearRange.objects.create(sub_model=sub, year_start=2026, layout_code='SYNC-1')
        cls.other_vehicle = YearRange.objects.create(sub_model=sub, year_start=2025, layout_code='SYNC-2')
        cls.folder = PatternDesignFolder.objects.create(vehicle=cls.vehicle, name='Sync folder')
        cls.design = PatternDesignImage.objects.create(vehicle=cls.vehicle, uploaded_by=cls.users['designer'],
            image='private_design_pdfs/pending.pdf', title='Pending PDF.pdf', approval_status='pending')
        submit_design_for_approval(cls.design, cls.users['designer'])
        cls.approved = PatternDesignImage.objects.create(folder=cls.folder, uploaded_by=cls.users['other'],
            image='pattern_designs/approved.obj', title='Approved file.obj', approval_status='approved')
        cls.hidden = PatternDesignImage.objects.create(vehicle=cls.vehicle, uploaded_by=cls.users['other'],
            image='pattern_designs/hidden.obj', title='Other pending.obj', approval_status='pending')
        cls.unrelated = PatternDesignImage.objects.create(vehicle=cls.other_vehicle,
            image='pattern_designs/unrelated.obj', title='Other vehicle.obj')
        PatternDesignImage.objects.create(vehicle=cls.vehicle, image='pattern_designs/reference.obj', is_reference=True)
        cls.url = reverse('get_design_folders_api')

    def check(self, user='cad', **query):
        self.client.force_login(self.users[user])
        return self.client.get(self.url, {'vehicle_id': self.vehicle.pk, 'gallery_sync': '1', **query})

    def test_revision_and_metadata_match_existing_role_visibility(self):
        for role in self.users:
            with self.subTest(role=role):
                manifest = self.check(role).json()['gallery_manifest']
                full = self.client.get(self.url, {'vehicle_id': self.vehicle.pk}).json()
                self.assertEqual(set(manifest), {str(file['id']) for file in full['design_files']})
                self.assertEqual(full['gallery_revision'], self.check(role).json()['gallery_revision'])
                response = self.check(role, files=','.join(str(value) for value in [self.design.pk, self.hidden.pk, self.approved.pk, self.unrelated.pk]))
                self.assertEqual({str(file['id']) for file in response.json()['design_files']}, set(manifest))

    def test_unchanged_revision_returns_private_304_without_serializing_files(self):
        first = self.check()
        with patch('management.views._serialize_design_image_details', side_effect=AssertionError('Unchanged check serialized a file')):
            response = self.client.get(self.url, {'vehicle_id': self.vehicle.pk, 'gallery_sync': '1'}, HTTP_IF_NONE_MATCH=first['ETag'])
        self.assertEqual(response.status_code, 304)
        self.assertEqual(response.content, b'')
        self.assertIn('private', response['Cache-Control'])
        self.assertIn('no-store', response['Cache-Control'])
        self.assertIn('Cookie', response['Vary'])
        self.assertNotIn('private_design_pdfs', first.content.decode())
        self.assertNotIn('Pending PDF', first.content.decode())

    def test_partial_reviews_and_overall_approval_change_the_correct_fingerprint(self):
        first = self.check().json()
        record_design_review_decision(self.design, self.users['cad'], 'approved', change_type='minor')
        second = self.check().json()
        self.assertNotEqual(first['gallery_manifest'][str(self.design.pk)], second['gallery_manifest'][str(self.design.pk)])
        self.assertEqual(first['gallery_manifest'][str(self.approved.pk)], second['gallery_manifest'][str(self.approved.pk)])
        metadata = self.check(files=str(self.design.pk)).json()['design_files'][0]
        self.assertEqual(metadata['approval_status'], 'pending')
        self.assertEqual(metadata['cad']['status'], 'approved')
        for role in ('ed', 'md'):
            record_design_review_decision(self.design, self.users[role], 'approved', change_type='minor')
        self.assertEqual(self.check(files=str(self.design.pk)).json()['design_files'][0]['approval_status'], 'approved')

    def test_uploader_skip_and_rejection_precedence_use_existing_backend_values(self):
        image = PatternDesignImage.objects.create(vehicle=self.vehicle, uploaded_by=self.users['cad'],
            image='pattern_designs/cad.obj', title='CAD upload.obj', approval_status='pending')
        submit_design_for_approval(image, self.users['cad'])
        record_design_review_decision(image, self.users['ed'], 'rejected', change_type='major')
        data = self.check(files=str(image.pk)).json()['design_files'][0]
        self.assertEqual((data['approval_status'], data['cad']['status']), ('rejected', 'skipped_uploader'))

    def test_hidden_users_unrelated_vehicles_and_references_do_not_change_revision(self):
        before = self.check('designer').json()['gallery_revision']
        PatternDesignImage.objects.filter(pk=self.hidden.pk).update(title='Still hidden.obj')
        PatternDesignImage.objects.filter(pk=self.unrelated.pk).update(approval_status='rejected')
        self.assertEqual(before, self.check('designer').json()['gallery_revision'])
        PatternDesignImage.objects.create(vehicle=self.vehicle, image='pattern_designs/ref2.obj', is_reference=True)
        self.assertEqual(before, self.check('designer').json()['gallery_revision'])

    def test_add_delete_and_permission_change_invalidate_revision(self):
        before = self.check().json()['gallery_revision']
        image = PatternDesignImage.objects.create(vehicle=self.vehicle, image='pattern_designs/new.obj', title='New.obj')
        added = self.check().json()
        self.assertNotEqual(before, added['gallery_revision'])
        self.assertIn(str(image.pk), added['gallery_manifest'])
        image.delete()
        self.assertNotIn(str(image.pk), self.check().json()['gallery_manifest'])
        profile = self.users['cad'].workflow_profile
        profile.role = WorkflowRoles.FACTORY_EXECUTIVE
        profile.save()
        changed = self.check().json()
        self.assertNotIn(str(self.design.pk), changed['gallery_manifest'])
        self.assertEqual(self.check(files=str(self.design.pk)).json()['design_files'], [])

    def test_authentication_scope_and_id_validation(self):
        self.assertEqual(self.client.get(self.url, {'vehicle_id': self.vehicle.pk, 'gallery_sync': '1'}).status_code, 302)
        self.check()
        for files in ('-1', '0', '1,', '9999999999999999999', ','.join(['1'] * 101)):
            self.assertEqual(self.check(files=files).status_code, 400)
        self.assertEqual(self.client.get(self.url, {'gallery_sync': '1'}).status_code, 400)
        self.assertEqual(self.client.get(self.url, {'vehicle_id': '999999', 'gallery_sync': '1'}).status_code, 404)

    def test_snapshot_query_count_is_constant_without_storage_calls(self):
        user = self.users['cad']
        info = _design_gallery_user_info(user)
        PatternDesignImage.objects.bulk_create([PatternDesignImage(vehicle=self.vehicle,
            image=f'pattern_designs/bulk-{index}.obj') for index in range(100)])
        with patch('management.views._ensure_pattern_thumbnail', side_effect=AssertionError('Snapshot read media')):
            # First access loads the permission profile once, independent of file count.
            with self.assertNumQueries(2):
                _, manifest, revision = _design_gallery_snapshot(user, self.vehicle.pk, info)
            # The request-local permission cache leaves only the compact manifest query.
            with self.assertNumQueries(1):
                _, warmed_manifest, warmed_revision = _design_gallery_snapshot(user, self.vehicle.pk, info)
        self.assertEqual(len(manifest), 103)
        self.assertEqual((warmed_manifest, warmed_revision), (manifest, revision))
