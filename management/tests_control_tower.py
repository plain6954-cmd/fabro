from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from management.models import (
    ActivityLog, ApprovalRoles, Brand, Model, PatternDesignApproval,
    PatternDesignFolder, PatternDesignImage, SubModel, WorkflowRoles, YearRange,
)
from management.services.control_tower import control_tower_snapshot


class ControlTowerTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = get_user_model().objects.create_superuser('tower-admin', 'admin@example.com', 'test-password')
        cls.designer = get_user_model().objects.create_user('tower-designer')
        brand = Brand.objects.create(name='Tower Brand')
        model = Model.objects.create(brand=brand, name='Tower Model')
        sub = SubModel.objects.create(model=model, name='Tower Sub')
        cls.vehicle = YearRange.objects.create(sub_model=sub, year_start=2024, year_end=2026, layout_code='TOWER')

    def setUp(self):
        self.now = timezone.now()

    def image(self, **kwargs):
        values = {'image': 'private/no-public-path.png', 'uploaded_by': self.designer, 'title': 'Recorded design'}
        return PatternDesignImage.objects.create(**(values | kwargs))

    def review(self, image=None, *, age=0, **kwargs):
        review = PatternDesignApproval.objects.create(design_image=image or self.image(vehicle=self.vehicle),
                                                      designer=self.designer, **kwargs)
        PatternDesignApproval.objects.filter(pk=review.pk).update(submitted_at=self.now - timedelta(hours=age))
        return review

    def snapshot(self):
        return control_tower_snapshot(self.admin, at=self.now)

    def test_access_uses_existing_erp_authority_and_get_only(self):
        endpoint = reverse('admin_control_tower')
        self.assertEqual(self.client.get(endpoint).status_code, 302)
        for role, approval_role, expected in (
            (WorkflowRoles.COUNTRY_EXECUTIVE, '', 403),
            (WorkflowRoles.FACTORY_EXECUTIVE, '', 403),
            (WorkflowRoles.APPROVER, ApprovalRoles.CAD, 403),
            (WorkflowRoles.APPROVER, ApprovalRoles.ED, 403),
            (WorkflowRoles.APPROVER, ApprovalRoles.MD, 200),
            (WorkflowRoles.ADMIN, '', 200),
        ):
            profile = self.designer.workflow_profile
            profile.role, profile.approval_role = role, approval_role
            profile.save()
            self.client.force_login(self.designer)
            self.assertEqual(self.client.get(endpoint).status_code, expected, (role, approval_role))
        self.client.force_login(self.admin)
        self.assertEqual(self.client.post(endpoint).status_code, 405)
        self.admin.is_active = False
        with self.assertRaises(PermissionDenied):
            self.snapshot()

    def test_latest_cycle_only_skipped_completed_and_reference_excluded(self):
        image = self.image(vehicle=self.vehicle)
        self.review(image, cycle=1, age=100)
        self.review(image, cycle=2, cad_status='approved', ed_status='pending', md_status='skipped_uploader')
        self.review(cad_status='approved', ed_status='approved', md_status='approved', status='approved')
        self.review(self.image(is_reference=True))
        data = self.snapshot()
        self.assertEqual(data['counts'], {'pending': 1, 'pending_designs': 1, 'delayed': 0, 'revisions': 1, 'attention': 1})
        self.assertEqual([stage['count'] for stage in data['pipeline']], [0, 1, 0])
        self.assertEqual(data['attention'][0]['cycle'], 2)

    def test_independent_pending_stages_survive_rejection_without_duplicates(self):
        self.review(cad_status='rejected', status='rejected')
        # Additional authorized reviewers do not multiply role-based stage requests.
        for number in range(3):
            user = get_user_model().objects.create_user(f'admin-{number}')
            profile = user.workflow_profile
            profile.role = WorkflowRoles.ADMIN
            profile.save()
        data = self.snapshot()
        self.assertEqual(data['counts']['pending'], 2)
        self.assertEqual(data['counts']['pending_designs'], 1)
        self.assertEqual(len(data['attention']), 1)
        self.assertEqual(data['attention'][0]['status'], 'rejected')

    @override_settings(CONTROL_TOWER_REVIEW_DELAY_HOURS=48)
    def test_delay_boundary_and_cycle_age(self):
        self.review(age=48)
        self.review(age=47.99)
        self.review(age=100, cad_status='approved', ed_status='approved', md_status='approved', status='approved')
        data = self.snapshot()
        self.assertEqual(data['counts']['delayed'], 1)
        self.assertEqual(data['pipeline'][0]['age']['seconds'], 48 * 3600)
        with override_settings(CONTROL_TOWER_REVIEW_DELAY_HOURS=24):
            self.assertEqual(self.snapshot()['counts']['delayed'], 2)

    def test_attention_priority_age_and_one_row_per_design(self):
        fresh = self.review()
        revision = self.review(cycle=2)
        rejected = self.review(cad_status='rejected', ed_status='approved', md_status='approved', status='rejected')
        delayed = self.review(age=50)
        older = self.review(age=70)
        repeat_image = self.image()
        self.review(repeat_image, cycle=1, cad_status='rejected', status='rejected', age=200)
        repeated = self.review(repeat_image, cycle=2, cad_status='rejected', status='rejected')
        data = self.snapshot()
        self.assertEqual([item['design_id'] for item in data['attention']],
                         [review.design_image_id for review in (repeated, older, delayed, rejected, revision, fresh)])
        self.assertEqual(data['counts']['attention'], 6)

    def test_vehicle_folder_and_unlinked_navigation(self):
        folder = PatternDesignFolder.objects.create(name='Recorded folder', vehicle=self.vehicle)
        direct = self.review(self.image(vehicle=self.vehicle, folder=folder), cad_reviewer=self.admin)
        via_folder = self.review(self.image(folder=folder))
        unlinked = self.review(self.image())
        by_id = {item['design_id']: item for item in self.snapshot()['attention']}
        for review in (direct, via_folder):
            item = by_id[review.design_image_id]
            self.assertIn('Tower Brand Tower Model Tower Sub', item['vehicle'])
            self.assertEqual(item['url'], reverse('design_approval_detail', args=[review.design_image_id]))
        self.assertIn(self.admin.username, by_id[direct.design_image_id]['reviewer'])
        self.assertEqual(by_id[unlinked.design_image_id]['vehicle'], 'Vehicle not linked')
        self.assertIn('Role-based review', by_id[unlinked.design_image_id]['reviewer'])

    def test_activity_uses_persisted_events_and_safe_links(self):
        self.review(status='approved', cad_status='approved', ed_status='approved', md_status='approved')
        log = ActivityLog.objects.create(user=self.admin, action='design_approved_ed', object_type='Design Image',
                                         object_name='Recorded title [Admin on behalf of ED]')
        ActivityLog.objects.create(user=self.admin, action='login', object_type='User', object_name='not a design event')
        data = self.snapshot()
        audit = [event for event in data['activity'] if event['source'] == 'audit']
        self.assertEqual(len(audit), 1)  # Never infer CAD/MD approvals from current status.
        self.assertEqual(audit[0]['key'], f'audit-{log.pk}')
        self.assertEqual(audit[0]['actor'], self.admin.username)
        self.assertEqual(audit[0]['context'], log.object_name)
        self.assertEqual(audit[0]['timestamp'], log.timestamp)
        self.assertEqual(audit[0]['url'], reverse('admin_panel') + '?section=logs#logs')
        self.assertEqual(len({event['key'] for event in data['activity']}), len(data['activity']))
        self.assertIn('Uploaded design file', [event['action'] for event in data['activity']])
        self.assertEqual([event['timestamp'] for event in data['activity']],
                         sorted((event['timestamp'] for event in data['activity']), reverse=True))

    def test_empty_states_and_no_sensitive_data_in_read_only_endpoint(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse('admin_control_tower'))
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['counts']['pending'], 0)
        self.assertIn('No pending approvals', data['fragments']['attention'])
        self.assertIn('No recent recorded activity', data['fragments']['activity'])
        self.assertIn('no-store', response['Cache-Control'])
        self.assertNotIn(self.client.session.session_key, response.content.decode())
        review = self.review(cad_comment='SECRET REVIEW COMMENT')
        counts_before = (PatternDesignApproval.objects.count(), ActivityLog.objects.count())
        response = self.client.get(reverse('admin_control_tower'))
        self.assertNotIn('private/no-public-path', response.content.decode())
        self.assertNotIn('SECRET REVIEW COMMENT', response.content.decode())
        self.assertEqual(counts_before, (PatternDesignApproval.objects.count(), ActivityLog.objects.count()))
        review.refresh_from_db()
        self.assertEqual(review.cad_status, 'pending')

    def test_bounded_query_count_and_result_limits(self):
        for number in range(24):
            self.review(self.image(vehicle=self.vehicle, title=f'Queue {number}'))
        with CaptureQueriesContext(connection) as queries:
            data = self.snapshot()
        self.assertEqual(len(queries), 5)  # One request-cached profile gate plus four projections.
        self.assertEqual(len(data['attention']), 12)
        self.assertEqual(data['counts']['attention'], 24)
        self.assertEqual(len(data['activity']), 16)

    def test_dashboard_keeps_summary_cards_and_session_forms(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse('admin_panel'))
        self.assertContains(response, 'class="erp-stat-tile', count=6)
        self.assertContains(response, 'id="fabroControlTower"', count=1)
        self.assertContains(response, 'CURRENT')
        self.assertContains(response, 'ct-session-panel')
