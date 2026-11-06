import json
from unittest.mock import patch
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from django.urls import reverse, get_resolver
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient
from management.models import (ActivityLog, ApprovalRoles, Brand, Model, Notification, PatternDesignApproval,
    PatternDesignFolder, PatternDesignImage, PatternMeasurementFile, SubModel, UserAccessAudit, WorkflowRoles as R, YearRange)
from management.services.activity_permissions import (ADMIN_KEYS, CATEGORIES, REGISTRY, granted, identity,
    role_defaults, validate_overrides)
from management.services.activity_routes import ROUTES, ESSENTIAL_ROUTES
from management.services.design_approvals import submit_design_for_approval, record_design_review_decision

User = get_user_model()

class ActivityPermissionTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_superuser('access-admin', 'admin@example.com', 'TestStrong!369')
        cls.designer = cls.account('access-designer', R.FREELANCE_3D_DESIGNER)
        cls.other = cls.account('access-other', R.FREELANCE_3D_DESIGNER)
        cls.cad = cls.account('access-cad', R.APPROVER, 'CAD')
        cls.ed = cls.account('access-ed', R.APPROVER, 'ED')
        cls.md = cls.account('access-md', R.APPROVER, 'MD')
        cls.viewer = cls.account('access-viewer', R.FACTORY_VIEWER)
        brand = Brand.objects.create(name='Permission Brand')
        model = Model.objects.create(brand=brand, name='Permission Model')
        sub = SubModel.objects.create(model=model, name='Permission Sub')
        cls.vehicle = YearRange.objects.create(sub_model=sub, layout_code='ACCESS-TEST', year_start=2024)
        cls.group = Group.objects.create(name='Existing file group')
        cls.group.permissions.add(Permission.objects.get(codename='delete_patterndesignimage'))

    @classmethod
    def account(cls, username, role, stage=''):
        user = User.objects.create_user(username, username+'@example.com', 'TestStrong!369')
        profile = user.workflow_profile
        profile.role, profile.approval_role = role, stage
        profile.save()
        return user

    def override(self, user, values):
        profile = user.workflow_profile
        profile.activity_permissions = values
        profile.save(update_fields=['activity_permissions'])
        user.__dict__.pop('_activity_grants', None)
        user.__dict__.pop('_workflow_profile', None)

    def image(self, **kwargs):
        return PatternDesignImage.objects.create(**({'vehicle': self.vehicle, 'image': 'pattern_designs/not-public.png',
            'uploaded_by': self.designer, 'approval_status': 'pending', 'title': 'Private design'} | kwargs))

    def post_user(self, user=None, **kwargs):
        self.client.force_login(self.admin)
        data = {'username': 'new-access-user', 'email': 'new@example.com', 'role': R.FACTORY_VIEWER,
            'password': 'NewStrong!369', 'confirm_password': 'NewStrong!369', 'control_panel': '1', 'is_active': 'on', 'activity_permissions': '{}'}
        if user:
            data.update(user_id=user.pk, username=user.username, email=user.email,
                role=user.workflow_profile.approval_role or user.workflow_profile.role)
            data.pop('password')
        data.update(kwargs)
        return self.client.post(reverse('user_control_save'), data)

    def test_registry_has_eighteen_real_categories_and_all_routes_are_inventoried(self):
        self.assertEqual(len(CATEGORIES), 18)
        self.assertEqual(set(category for category, _ in CATEGORIES), {item.category for item in REGISTRY.values()})
        from management.urls import urlpatterns
        names = {pattern.name for pattern in urlpatterns}
        self.assertFalse(names - set(ROUTES) - ESSENTIAL_ROUTES)
        for key, item in REGISTRY.items():
            self.assertIn(key.split('.')[0], dict(CATEGORIES))
            self.assertTrue(item.label)

    def test_existing_accounts_inherit_and_keep_roles_groups_and_reviewer_assignment(self):
        self.cad.groups.add(self.group)
        self.assertEqual(self.cad.workflow_profile.activity_permissions, {})
        for user, key in [(self.designer, 'design.upload'), (self.cad, 'design_approval.approve'),
                          (self.viewer, 'measurement.upload'), (self.md, 'erp.control_tower')]:
            self.assertTrue(granted(user, key))
        self.assertEqual(self.cad.workflow_profile.approval_role, 'CAD')
        self.assertTrue(self.cad.groups.filter(pk=self.group.pk).exists())

    @override_settings(ACTIVITY_ROLE_DEFAULTS={R.FACTORY_VIEWER: {'chat.send': False}})
    def test_role_configuration_changes_inheritance_and_explicit_allow_can_override_default_deny(self):
        fresh = User.objects.get(pk=self.viewer.pk)
        self.assertFalse(granted(fresh, 'chat.send'))
        self.override(fresh, {'chat.send': 'allow'})
        self.assertTrue(granted(fresh, 'chat.send'))
        with override_settings(ACTIVITY_ROLE_DEFAULTS={}):
            self.assertTrue(granted(User.objects.get(pk=self.viewer.pk), 'chat.send'))

    def test_explicit_deny_beats_default_allow_and_is_immediate_without_logout(self):
        self.client.force_login(self.viewer)
        self.assertEqual(self.client.get(reverse('chat_users_api')).status_code, 200)
        self.override(self.viewer, {'chat.view': 'deny'})
        self.assertEqual(self.client.get(reverse('chat_users_api')).status_code, 403)
        self.assertEqual(self.client.get(reverse('chat_view')).status_code, 403)
        self.assertFalse(self.client.get(reverse('user_activity_state')).json()['permissions']['chat.send'])
        self.override(self.viewer, {})
        self.assertEqual(self.client.get(reverse('chat_users_api')).status_code, 200)

    def test_allow_never_confers_catalog_or_reviewer_authority(self):
        with self.assertRaises(ValidationError):
            validate_overrides({'vehicle.create': 'allow'}, identity(self.viewer))
        self.override(self.viewer, {'vehicle.create': 'allow', 'design_approval.approve': 'allow'})
        self.client.force_login(self.viewer)
        self.assertEqual(self.client.post(reverse('car_details'), {}).status_code, 403)
        image = self.image()
        review = submit_design_for_approval(image, self.designer)
        with self.assertRaises(PermissionDenied):
            record_design_review_decision(image, self.viewer, 'approved', stage='cad', change_type='minor')
        review.refresh_from_db()
        self.assertEqual(review.cad_status, 'pending')

    def test_unknown_keys_dependencies_and_protected_admin_denials_are_rejected(self):
        for values in ({'not.a.permission': 'allow'}, {'chat.view': 'no'}, {'chat.view': 'deny'}, {'users.manage': 'deny'}):
            if values == {'chat.view': 'deny'}:
                values['chat.send'] = 'allow'
            with self.assertRaises(ValidationError):
                validate_overrides(values, identity(self.admin))
        self.override(self.admin, {'users.manage': 'deny', 'erp.view': 'deny', 'vehicle.create': 'deny', 'sku.delete': 'deny'})
        self.assertFalse(granted(self.admin, 'users.manage'))
        self.assertFalse(granted(self.admin, 'erp.view'))
        self.assertFalse(granted(self.admin, 'vehicle.create'))
        self.assertFalse(granted(self.admin, 'sku.delete'))

    def test_superuser_can_disable_and_restore_own_admin_permissions(self):
        # Include dependent activities so the override remains valid.
        blocked = {'users.manage', 'erp.view', 'users.permissions'}
        while True:
            expanded = blocked | {
                key for key, item in REGISTRY.items()
                if any(dependency in blocked for dependency in item.requires)
            }
            if expanded == blocked:
                break
            blocked = expanded

        defaults = role_defaults(identity(self.admin))
        denials = {key: 'deny' for key in blocked if defaults.get(key)}
        self.assertIn('users.manage', denials)
        self.assertIn('erp.view', denials)

        response = self.post_user(
            self.admin, is_superuser='on', is_staff='on',
            activity_permissions=json.dumps(denials)
        )
        self.assertEqual(response.status_code, 200, response.content)

        fresh_admin = User.objects.get(pk=self.admin.pk)
        self.assertFalse(granted(fresh_admin, 'users.manage'))
        self.assertFalse(granted(fresh_admin, 'erp.view'))

        # Ordinary management stays denied, but self-recovery works.
        self.assertEqual(
            self.client.get(reverse('admin_panel_alias'),
                            {'section': 'dashboard'}).status_code, 403
        )
        self.assertEqual(
            self.client.get(reverse('admin_panel_alias'),
                            {'section': 'users'}).status_code, 200
        )
        self.assertEqual(
            self.client.get(reverse('user_control_data'),
                            {'user_id': str(self.viewer.pk)}).status_code, 403
        )
        own_data = self.client.get(
            reverse('user_control_data'), {'user_id': str(self.admin.pk)}
        )
        self.assertEqual(own_data.status_code, 200)
        self.assertTrue(own_data.json()['can_override_all_activities'])
        self.assertTrue(own_data.json()['can_manage_permissions'])
        self.assertTrue(own_data.json()['recovery_only'])
        page = self.client.get(reverse('admin_panel_alias'), {'section': 'users', 'edit_user': self.viewer.pk})
        self.assertEqual([person.pk for person in page.context['users']], [self.admin.pk])
        self.assertEqual(page.context['edit_user_id'], str(self.admin.pk))
        self.assertEqual(page.context['active_sessions'], [])
        self.assertEqual(page.context['groups'], [])
        self.assertEqual(page.context['permissions'], [])
        self.assertTrue(all(country.user_count == 1 for country in page.context['workflow_countries']))

        other_save = self.post_user(self.viewer)
        self.assertEqual(other_save.status_code, 403)

        restored = self.client.post(reverse('user_control_save'), {'user_id': self.admin.pk, 'activity_permissions': '{}'})
        self.assertEqual(restored.status_code, 200, restored.content)
        fresh_admin = User.objects.get(pk=self.admin.pk)
        self.assertTrue(granted(fresh_admin, 'users.manage'))
        self.assertTrue(granted(fresh_admin, 'erp.view'))

        # A non-superuser administrator has no recovery bypass.
        self.override(self.md, {'users.manage': 'deny', 'erp.view': 'deny'})
        self.client.force_login(self.md)
        self.assertEqual(
            self.client.get(reverse('user_control_data'),
                            {'user_id': str(self.md.pk)}).status_code, 403
        )

    def test_superuser_permission_denial_blocks_other_account_overrides(self):
        self.override(self.admin, {'users.permissions': 'deny'})
        self.client.force_login(self.admin)
        data = self.client.get(reverse('user_control_data'), {'user_id': self.viewer.pk}).json()
        self.assertFalse(data['can_manage_permissions'])
        self.assertFalse(data['can_override_all_activities'])
        self.assertEqual(self.post_user(self.viewer, activity_permissions='{"chat.send":"deny"}').status_code, 403)
        self.viewer.workflow_profile.refresh_from_db()
        self.assertEqual(self.viewer.workflow_profile.activity_permissions, {})

    def test_recovery_only_changes_own_permissions_and_rejects_unrelated_fields(self):
        self.override(self.admin, {'users.manage': 'deny', 'erp.view': 'deny', 'users.permissions': 'deny'})
        self.client.force_login(self.admin)
        before = (self.admin.username, self.admin.password, UserAccessAudit.objects.count())
        for extra in ({'role': R.FACTORY_VIEWER}, {'is_active': ''}, {'is_superuser': ''},
                      {'new_password': 'NotRecovery!369'}, {'groups': [self.group.pk]}, {'username': 'Changed'}):
            response = self.client.post(reverse('user_control_save'), {'user_id': self.admin.pk, 'activity_permissions': '{}', **extra})
            self.assertEqual(response.status_code, 400, response.content)
        self.assertEqual(self.client.post(reverse('admin_panel_alias')+'?section=users', {'add_group': '1', 'name': 'Forbidden recovery group'}).status_code, 403)
        self.assertEqual(self.client.get(reverse('user_control_data')).status_code, 403)
        self.admin.refresh_from_db()
        self.assertEqual(before, (self.admin.username, self.admin.password, UserAccessAudit.objects.count()))
        self.assertTrue(self.admin.is_superuser)
        self.assertTrue(self.admin.is_active)

    def test_superuser_ineligible_allow_is_retained_while_inheritance_remains_eligible(self):
        values = {'vehicle.create': 'allow', 'users.permissions': 'allow'}
        with override_settings(ACTIVITY_ROLE_DEFAULTS={R.FACTORY_VIEWER: {key: True for key in values}}):
            info = identity(self.viewer)
            self.assertFalse(role_defaults(info)['vehicle.create'])
            self.assertFalse(granted(self.viewer, 'vehicle.create'))
            self.assertEqual(validate_overrides(values, info, superuser_editor=True), values)
            self.override(self.viewer, values)
            self.assertTrue(granted(self.viewer, 'vehicle.create'))
            self.assertTrue(granted(self.viewer, 'users.permissions'))

    def test_explicit_privileged_grants_do_not_confer_admin_or_stage_identity(self):
        self.override(self.viewer, {key: 'allow' for key in ('users.manage', 'users.permissions', 'users.create', 'erp.view', 'design_approval.view', 'design_approval.approve')})
        self.client.force_login(self.viewer)
        self.assertIn(self.client.get(reverse('user_control_data'), {'user_id': self.other.pk}).status_code, (302, 403))
        from django.test import RequestFactory
        from management.services.user_control import save_control_user
        request = RequestFactory().post(reverse('user_control_save'), {'user_id': self.other.pk})
        request.user = self.viewer
        with self.assertRaises(PermissionDenied):
            save_control_user(request)
        image = self.image()
        review = submit_design_for_approval(image, self.designer)
        with self.assertRaises(PermissionDenied):
            record_design_review_decision(image, self.viewer, 'approved', stage='ed', change_type='minor')
        review.refresh_from_db()
        self.assertEqual(review.ed_status, 'pending')

    def test_non_superuser_cannot_mint_privileged_overrides_or_remove_protected_denials(self):
        actor = self.account('ordinary-access-admin', R.ADMIN)
        target = self.account('restricted-access-admin', R.ADMIN)
        self.override(target, {'erp.view': 'deny'})
        self.client.force_login(actor)
        for permissions in ({}, {'erp.view': 'allow'}, {'erp.view': 'deny', 'users.manage': 'deny'}):
            response = self.client.post(reverse('user_control_save'), {'user_id': target.pk, 'username': target.username,
                'email': target.email, 'role': R.ADMIN, 'activity_permissions': json.dumps(permissions)})
            self.assertEqual(response.status_code, 400, response.content)
        response = self.client.post(reverse('user_control_save'), {'user_id': self.viewer.pk, 'username': self.viewer.username,
            'email': self.viewer.email, 'role': R.FACTORY_VIEWER, 'activity_permissions': '{"users.permissions":"allow"}'})
        self.assertEqual(response.status_code, 400, response.content)

    def test_non_superuser_preserves_saved_locked_override_during_profile_edit(self):
        actor = self.account('preserving-access-admin', R.ADMIN)
        self.client.force_login(actor)
        for target, values in ((self.viewer, {'users.permissions': 'allow'}), (self.account('locked-access-admin', R.ADMIN), {'erp.view': 'deny'})):
            self.override(target, values)
            response = self.client.post(reverse('user_control_save'), {'user_id': target.pk, 'username': target.username,
                'email': target.email, 'role': target.workflow_profile.role, 'first_name': 'Kept', 'activity_permissions': json.dumps(values)})
            self.assertEqual(response.status_code, 200, response.content)
            target.refresh_from_db()
            self.assertEqual(target.first_name, 'Kept')
            self.assertEqual(target.workflow_profile.activity_permissions, values)

    def test_superuser_dependency_violations_reject_atomically(self):
        before = (User.objects.count(), UserAccessAudit.objects.count())
        response = self.post_user(activity_permissions='{"chat.view":"deny","chat.send":"allow"}')
        self.assertEqual(response.status_code, 400)
        self.assertEqual(before, (User.objects.count(), UserAccessAudit.objects.count()))
        with self.assertRaises(ValidationError):
            validate_overrides({'chat.view': 'deny', 'chat.send': 'allow'}, identity(self.viewer), superuser_editor=True)

    def test_inactive_superusers_and_explicit_grantees_fail_closed(self):
        self.override(self.viewer, {'users.manage': 'allow'})
        self.assertTrue(granted(self.viewer, 'users.manage'))
        self.viewer.is_active = False
        self.assertFalse(granted(self.viewer, 'users.manage'))
        self.admin.is_active = False
        from django.test import RequestFactory
        from management.services.user_control import save_control_user, control_data
        request = RequestFactory().post(reverse('user_control_save'), {'user_id': self.admin.pk, 'activity_permissions': '{}'})
        request.user = self.admin
        self.assertFalse(control_data(self.admin, self.admin)['can_manage_permissions'])
        with self.assertRaises(PermissionDenied):
            save_control_user(request)

    def test_final_active_superuser_and_administrator_safeguards_survive_overrides(self):
        for changes in ({'is_active': ''}, {'is_superuser': ''}):
            data = dict(is_superuser='on', is_staff='on', activity_permissions='{}')
            data.update(changes)
            response = self.post_user(self.admin, **data)
            self.assertEqual(response.status_code, 400, response.content)
            self.admin.refresh_from_db()
            self.assertTrue(self.admin.is_active and self.admin.is_superuser)
        ordinary = self.account('last-active-admin', R.ADMIN)
        self.admin.is_active = False
        self.admin.save(update_fields=['is_active'])
        self.client.force_login(ordinary)
        response = self.client.post(reverse('user_control_save'), {'user_id': ordinary.pk, 'username': ordinary.username,
            'email': ordinary.email, 'role': R.FACTORY_VIEWER, 'activity_permissions': '{}'})
        self.assertEqual(response.status_code, 400, response.content)
        ordinary.refresh_from_db()
        self.assertEqual(ordinary.workflow_profile.role, R.ADMIN)

    @patch('management.services.push_notifications.send_push_on_commit')
    def test_self_recovery_audits_once_and_keeps_existing_notification_trigger(self, push):
        self.override(self.admin, {'users.manage': 'deny'})
        self.client.force_login(self.admin)
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(reverse('user_control_save'), {'user_id': self.admin.pk, 'activity_permissions': '{}'})
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(UserAccessAudit.objects.filter(actor=self.admin, target=self.admin).count(), 1)
        self.assertEqual(Notification.objects.filter(recipient=self.admin, notification_type='access_change').count(), 1)
        self.assertEqual(Notification.objects.exclude(recipient=self.admin).count(), 0)
        push.assert_called_once()

    def test_each_assigned_design_stage_is_preserved(self):
        image = self.image()
        submit_design_for_approval(image, self.designer)
        for user, wrong in [(self.cad, 'ed'), (self.ed, 'md'), (self.md, 'cad')]:
            self.client.force_login(user)
            response = self.client.post(reverse('approve_design_image_api', args=[image.pk]),
                {'stage': wrong, 'change_type': 'minor'})
            self.assertEqual(response.status_code, 403)
        self.override(self.cad, {'design_approval.approve': 'deny', 'design_approval.reject': 'deny'})
        self.client.force_login(self.cad)
        self.assertEqual(self.client.post(reverse('approve_design_image_api', args=[image.pk]),
            {'stage': 'cad', 'change_type': 'minor'}).status_code, 403)

    def test_own_scope_filters_gallery_manifest_and_unknown_ownership(self):
        own = self.image(is_reference=True)
        other = self.image(is_reference=True, uploaded_by=self.other)
        unknown = self.image(is_reference=True, uploaded_by=None)
        self.override(self.designer, {'reference.view_all': 'deny', 'design.view_all': 'deny'})
        self.client.force_login(self.designer)
        data = self.client.get(reverse('design_comparison_manifest', args=[own.pk])).json()
        self.assertEqual([entry['id'] for entry in data['references']], [own.pk])
        for image in (other, unknown):
            self.assertEqual(self.client.get(reverse('design_comparison_manifest', args=[image.pk])).status_code, 403)
        self.assertNotIn('pattern_designs/not-public.png', json.dumps(data))

    def test_all_scope_keeps_existing_freelancer_record_visibility(self):
        hidden = self.image(uploaded_by=self.other)
        self.client.force_login(self.designer)
        self.assertEqual(self.client.get(reverse('design_comparison_manifest', args=[hidden.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse('design_approval_detail', args=[hidden.pk])).status_code, 403)

    def test_download_deny_does_not_disable_permitted_inline_view(self):
        image = self.image(is_reference=True)
        self.override(self.designer, {'reference.download_own': 'deny', 'reference.download_all': 'deny'})
        self.client.force_login(self.designer)
        data = self.client.get(reverse('design_comparison_manifest', args=[image.pk])).json()
        self.assertIsNone(data['references'][0]['download'])
        self.assertEqual(self.client.get(reverse('design_comparison_file', args=[image.pk])+'?download=1').status_code, 403)

    def test_history_denial_redacts_all_review_presentations(self):
        image = self.image()
        review = submit_design_for_approval(image, self.designer)
        review.cad_status, review.cad_comment, review.cad_change_type = 'approved', 'SECRET HISTORY', 'major'
        review.save()
        self.override(self.designer, {'design.history': 'deny'})
        self.client.force_login(self.designer)
        for url in (reverse('design_approval_detail', args=[image.pk]),
                    reverse('design_approval_detail', args=[image.pk])+'?workspace=comparison',
                    reverse('design_comparison_manifest', args=[image.pk]),
                    reverse('get_design_folders_api')+f'?vehicle_id={self.vehicle.pk}',
                    reverse('approvals_list')+'?stage=designer&status=all'):
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200, url)
            self.assertNotIn('SECRET HISTORY', response.content.decode(), url)

    def test_submitted_files_cannot_be_deleted_even_by_superuser(self):
        image = self.image()
        submit_design_for_approval(image, self.designer)
        for user in (self.admin, self.designer):
            self.client.force_login(user)
            self.assertEqual(self.client.post(reverse('delete_design_image_api', args=[image.pk])).status_code, 403)
        self.assertTrue(PatternDesignImage.objects.filter(pk=image.pk).exists())

    def test_parent_deletion_does_not_bypass_protected_files(self):
        folder = PatternDesignFolder.objects.create(vehicle=self.vehicle, name='Protected', created_by=self.designer)
        image = self.image(folder=folder)
        submit_design_for_approval(image, self.designer)
        self.client.force_login(self.admin)
        for url in (reverse('delete_design_folder_api', args=[folder.pk]), reverse('delete_car_detail', args=[self.vehicle.pk])):
            self.assertEqual(self.client.post(url).status_code, 403)
        self.assertTrue(PatternDesignApproval.objects.filter(design_image=image).exists())

    def test_eligible_unsubmitted_reference_can_be_deleted_by_existing_authorized_user(self):
        image = self.image(is_reference=True)
        self.client.force_login(self.admin)
        self.assertEqual(self.client.post(reverse('delete_design_image_api', args=[image.pk])).status_code, 200)
        self.assertFalse(PatternDesignImage.objects.filter(pk=image.pk).exists())

    def test_unknown_owner_is_not_treated_as_freelancers_own_file(self):
        image = self.image(uploaded_by=None)
        self.client.force_login(self.designer)
        self.assertEqual(self.client.post(reverse('delete_design_image_api', args=[image.pk])).status_code, 403)

    def test_token_authenticated_mobile_api_obeys_permission_denial(self):
        self.override(self.viewer, {'sku.view': 'deny'})
        api = APIClient()
        token = Token.objects.create(user=self.viewer)
        api.credentials(HTTP_AUTHORIZATION='Token '+token.key)
        self.assertEqual(api.get(reverse('api_skus_list_create')).status_code, 403)
        self.assertEqual(api.get(reverse('api_profile')).status_code, 200)

    def test_create_saves_user_details_groups_and_overrides_together(self):
        response = self.post_user(first_name='A', last_name='Designer', phone_number='123',
            groups=[str(self.group.pk)], activity_permissions=json.dumps({'chat.send': 'deny'}))
        self.assertEqual(response.status_code, 200, response.content)
        user = User.objects.get(username='new-access-user')
        self.assertTrue(user.check_password('NewStrong!369'))
        self.assertEqual(user.first_name, 'A')
        self.assertEqual(user.workflow_profile.phone_number, '123')
        self.assertEqual(user.workflow_profile.activity_permissions, {'chat.send': 'deny'})
        self.assertTrue(user.groups.filter(pk=self.group.pk).exists())
        audit = UserAccessAudit.objects.get(target=user)
        self.assertEqual(audit.actor, self.admin)
        self.assertEqual(audit.changes['permissions']['chat.send'], {'old': 'inherit', 'new': 'deny'})
        self.assertNotIn('NewStrong', json.dumps(audit.changes))

    def test_validation_is_atomic_for_user_profile_groups_and_permissions(self):
        self.designer.groups.add(self.group)
        before = (User.objects.count(), ActivityLog.objects.count(), UserAccessAudit.objects.count())
        response = self.post_user(self.designer, first_name='SHOULD NOT SAVE', activity_permissions='{"invalid.key":"allow"}')
        self.assertEqual(response.status_code, 400)
        self.designer.refresh_from_db()
        self.assertEqual(self.designer.first_name, '')
        self.assertTrue(self.designer.groups.filter(pk=self.group.pk).exists())
        self.assertEqual(before, (User.objects.count(), ActivityLog.objects.count(), UserAccessAudit.objects.count()))
        response = self.post_user(activity_permissions='{"users.permissions":"allow"}')
        self.assertEqual(response.status_code, 200, response.content)
        created = User.objects.get(username='new-access-user')
        self.assertEqual(created.workflow_profile.activity_permissions, {'users.permissions': 'allow'})
        self.assertFalse(created.is_superuser)
        self.assertTrue(granted(created, 'users.permissions'))
        self.assertFalse(granted(self.viewer, 'users.permissions'))
        with self.assertRaises(ValidationError):
            validate_overrides({'users.permissions': 'allow'}, identity(self.viewer))

    def test_blank_password_preserves_hash_and_edit_response_does_not_expose_it(self):
        password_hash = self.designer.password
        response = self.post_user(self.designer, first_name='Changed', new_password='', confirm_password='')
        self.assertEqual(response.status_code, 200, response.content)
        self.designer.refresh_from_db()
        self.assertEqual(self.designer.password, password_hash)
        self.assertEqual(self.designer.first_name, 'Changed')
        self.assertNotIn(password_hash, response.content.decode())
        config = self.client.get(reverse('user_control_data'), {'user_id': self.designer.pk})
        self.assertNotIn(password_hash, config.content.decode())
        self.assertNotIn('password', config.json()['user'])

    def test_password_rules_role_validation_and_username_uniqueness(self):
        for extra in ({'password': '123'}, {'role': 'made_up_admin'}, {'username': self.designer.username}, {'email': 'bad-email'}):
            self.assertEqual(self.post_user(**extra).status_code, 400, extra)
        response = self.post_user(self.designer, new_password='ChangedStrong!245', confirm_password='ChangedStrong!245')
        self.assertEqual(response.status_code, 200)
        self.designer.refresh_from_db()
        self.assertTrue(self.designer.check_password('ChangedStrong!245'))

    def test_nonadmin_erp_reviewer_cannot_assign_roles_or_permissions(self):
        self.client.force_login(self.md)
        payload = {'user_id': self.designer.pk, 'username': self.designer.username, 'email': self.designer.email,
                   'role': 'admin', 'activity_permissions': '{}'}
        self.assertEqual(self.client.post(reverse('user_control_save'), payload).status_code, 403)
        payload['role'] = R.FREELANCE_3D_DESIGNER
        self.assertEqual(self.client.post(reverse('user_control_save'), payload).status_code, 403)
        self.designer.refresh_from_db()
        self.assertEqual(self.designer.workflow_profile.role, R.FREELANCE_3D_DESIGNER)

    def test_account_essentials_remain_accessible_when_features_are_denied(self):
        self.override(self.viewer, {key: 'deny' for key in REGISTRY})
        self.client.force_login(self.viewer)
        for name in ('profile_settings', 'user_activity_state'):
            self.assertEqual(self.client.get(reverse(name)).status_code, 200)
        self.assertEqual(self.client.get(reverse('index')).status_code, 403)

    def test_checks_cache_once_per_request_not_per_button(self):
        user = User.objects.get(pk=self.viewer.pk)
        with CaptureQueriesContext(connection) as queries:
            for _ in range(3):
                for key in REGISTRY:
                    granted(user, key)
        self.assertLessEqual(len(queries), 3)

    @patch('management.services.push_notifications.send_push_on_commit')
    def test_access_notification_after_commit_targets_only_changed_user_and_safe_profile(self, push):
        with self.captureOnCommitCallbacks(execute=True):
            response = self.post_user(self.designer, activity_permissions='{"chat.send":"deny"}')
        self.assertEqual(response.status_code, 200)
        notices = Notification.objects.filter(notification_type='access_change')
        self.assertEqual(list(notices.values_list('recipient_id', flat=True)), [self.designer.pk])
        # notify_user imports the existing push helper at call time.
        self.assertEqual(notices.count(), 1)
        push.assert_called_once()
        self.assertEqual(push.call_args.kwargs['user'].pk, self.designer.pk)
        self.assertEqual(push.call_args.kwargs['url'], '/profile/')
        self.override(self.designer, {'chat.send': 'deny', 'notification.read': 'deny', 'notification.view': 'deny'})
        self.client.force_login(self.designer)
        self.assertRedirects(self.client.get(reverse('open_notification', args=[notices.get().pk])), reverse('profile_settings'))

    @patch('management.services.user_control._access_notification')
    def test_failed_transaction_never_notifies_and_noop_does_not_duplicate(self, notify):
        with self.captureOnCommitCallbacks(execute=True):
            self.post_user(self.designer, activity_permissions='{"unknown":"allow"}')
            self.post_user(self.designer)
        notify.assert_not_called()

    def test_other_users_cannot_read_or_save_control_data(self):
        self.client.force_login(self.cad)
        self.assertNotEqual(self.client.get(reverse('user_control_data')).status_code, 200)
        self.assertEqual(self.client.post(reverse('user_control_save'), {}).status_code, 403)


    def test_nonadmin_cannot_reset_or_reactivate_an_administrative_account(self):
        admin = self.account('inactive-access-admin', R.ADMIN)
        admin.is_active = False
        admin.save()
        self.client.force_login(self.md)
        response = self.client.post(reverse('edit_user'), {'user_id': admin.pk, 'reset_password': '1',
            'new_password': 'Escalation!369', 'confirm_password': 'Escalation!369'})
        self.assertEqual(response.status_code, 403)
        response = self.client.post(reverse('user_control_save'), {'user_id': admin.pk, 'username': admin.username,
            'email': admin.email, 'role': 'admin', 'is_active': 'on', 'control_panel': '1'})
        self.assertEqual(response.status_code, 403)
        admin.refresh_from_db()
        self.assertFalse(admin.is_active)
        self.assertFalse(admin.check_password('Escalation!369'))

    def test_container_permissions_do_not_override_child_file_scope_denials(self):
        image = self.image(is_reference=True)
        self.override(self.admin, {'reference.delete_own': 'deny', 'reference.delete_all': 'deny'})
        self.client.force_login(self.admin)
        response = self.client.post(reverse('delete_car_detail', args=[self.vehicle.pk]))
        self.assertEqual(response.status_code, 403)
        self.assertTrue(PatternDesignImage.objects.filter(pk=image.pk).exists())

    def test_user_deletion_does_not_erase_design_review_history(self):
        image = self.image()
        review = submit_design_for_approval(image, self.designer)
        self.client.force_login(self.admin)
        self.assertEqual(self.client.post(reverse('delete_user'), {'user_id': self.designer.pk}).status_code, 403)
        self.assertTrue(PatternDesignApproval.objects.filter(pk=review.pk).exists())

    @patch('management.services.push_notifications.send_push_on_commit', side_effect=RuntimeError('offline'))
    def test_access_notification_push_failure_does_not_break_permission_save(self, push):
        with self.captureOnCommitCallbacks(execute=True):
            response = self.post_user(self.designer, activity_permissions='{"chat.send":"deny"}')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Notification.objects.filter(notification_type='access_change', recipient=self.designer).count(), 1)
        self.assertEqual(UserAccessAudit.objects.filter(target=self.designer).count(), 1)

    def test_dashboard_denial_keeps_successful_login_on_account_profile(self):
        self.override(self.viewer, {'dashboard.view': 'deny'})
        response = self.client.post(reverse('login'), {'username': self.viewer.username, 'password': 'TestStrong!369'})
        self.assertRedirects(response, reverse('profile_settings'))


    def test_group_default_changes_and_individual_difference_save_atomically(self):
        response = self.post_user(self.viewer, groups=[self.group.pk], activity_permissions='{"reference.delete_all":"deny"}')
        self.assertEqual(response.status_code, 200, response.content)
        fresh = User.objects.get(pk=self.viewer.pk)
        self.assertTrue(fresh.has_perm('management.delete_patterndesignimage'))
        self.assertFalse(granted(fresh, 'reference.delete_all'))
        self.assertTrue(granted(fresh, 'reference.delete_own'))
        self.assertEqual(fresh.workflow_profile.activity_permissions, {'reference.delete_all': 'deny'})


    def test_private_measurement_preview_download_scope_and_video_ranges(self):
        import tempfile
        from django.core.files.base import ContentFile
        from django.core.files.storage import FileSystemStorage

        # Exercise real file reads without depending on external S3 availability.
        with tempfile.TemporaryDirectory() as media_dir:
            field = PatternMeasurementFile._meta.get_field('file')
            with patch.object(field, 'storage', FileSystemStorage(location=media_dir)):
                item = PatternMeasurementFile.objects.create(vehicle=self.vehicle, uploaded_by=self.viewer,
                    category=PatternMeasurementFile.CATEGORY_INTERIOR, filename='range.mp4', file=ContentFile(b'0123456789', name='range.mp4'))
                self.client.force_login(self.viewer)
                response = self.client.get(reverse('measurement_file_download', args=[item.pk]), HTTP_RANGE='bytes=3-5')
                self.assertEqual(response.status_code, 206)
                self.assertEqual(response['Content-Range'], 'bytes 3-5/10')
                self.assertEqual(b''.join(response.streaming_content), b'345')
                # Exhausting the range iterator closes its file in finally;
                # the test client's wrapper safely closes the response too.
                # A second response.close() would fire request_finished again.
                self.assertTrue(response.closed)
                self.override(self.viewer, {'measurement.download_own': 'deny', 'measurement.download_all': 'deny'})
                response = self.client.get(reverse('get_measurement_files_api'), {'vehicle_id': self.vehicle.pk})
                self.assertIsNone(response.json()['interior_files'][0]['download_url'])
                self.assertEqual(self.client.get(reverse('measurement_file_download', args=[item.pk])+'?download=1').status_code, 403)


    def test_protected_assets_block_approved_deletion_but_not_rejecting_the_request(self):
        from management.models import PatternAlteration
        image = self.image()
        submit_design_for_approval(image, self.designer)
        alteration = PatternAlteration.objects.create(requested_by=self.admin, action_type='delete',
            pattern_ids=[self.vehicle.pk], summary='Isolated protected deletion request')
        self.client.force_login(self.cad)
        url = reverse('decide_pattern_alteration_api', args=[alteration.pk])
        self.assertEqual(self.client.post(url, {'decision': 'approve'}).status_code, 403)
        self.assertEqual(self.client.post(url, {'decision': 'reject', 'reason': 'Keep protected evidence'}).status_code, 200)
        alteration.refresh_from_db()
        self.assertEqual(alteration.status, 'rejected')
        self.assertTrue(PatternDesignImage.objects.filter(pk=image.pk).exists())


    @patch('management.services.push_notifications.send_push_on_commit')
    def test_legacy_group_assignment_uses_the_same_access_audit_and_notification(self, push):
        self.client.force_login(self.admin)
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(reverse('admin_panel'), {'assign_group': '1', 'user': self.viewer.pk, 'group': self.group.pk})
        self.assertEqual(response.status_code, 200)
        audit = UserAccessAudit.objects.get(target=self.viewer)
        self.assertIn(self.group.pk, audit.changes['groups']['new'])
        self.assertEqual(Notification.objects.filter(recipient=self.viewer, notification_type='access_change').count(), 1)
        push.assert_called_once()


    @patch('management.services.push_notifications.send_push_on_commit')
    def test_inactive_account_keeps_group_configuration_and_saved_denials(self, push):
        self.viewer.groups.add(self.group)
        self.viewer.is_active = False
        self.viewer.save()
        self.override(self.viewer, {'reference.delete_all': 'deny'})
        self.client.force_login(self.admin)
        response = self.client.get(reverse('user_control_data'), {'user_id': self.viewer.pk})
        data = response.json()
        self.assertTrue(data['role_maps'][R.FACTORY_VIEWER]['eligible']['reference.delete_all'])
        self.assertEqual(data['overrides']['reference.delete_all'], 'deny')
        self.assertFalse(granted(self.viewer, 'reference.delete_all'))
        with self.captureOnCommitCallbacks(execute=True):
            response = self.post_user(self.viewer, is_active='on', groups=[self.group.pk], activity_permissions='{"reference.delete_all":"deny"}')
        self.assertEqual(response.status_code, 200, response.content)
        user = User.objects.get(pk=self.viewer.pk)
        self.assertTrue(user.is_active)
        self.assertFalse(granted(user, 'reference.delete_all'))
        audit = UserAccessAudit.objects.get(target=user)
        self.assertFalse(audit.old_role['is_active'])
        self.assertTrue(audit.new_role['is_active'])
        push.assert_called_once()


    def test_all_file_deletion_grants_still_require_business_record_visibility(self):
        self.viewer.groups.add(self.group)
        folder = PatternDesignFolder.objects.create(vehicle=self.vehicle, name='Hidden pending files', created_by=self.viewer)
        hidden = self.image(folder=folder, uploaded_by=self.other)
        self.client.force_login(self.viewer)
        self.assertEqual(self.client.post(reverse('delete_design_image_api', args=[hidden.pk])).status_code, 404)
        self.assertEqual(self.client.post(reverse('delete_design_folder_api', args=[folder.pk])).status_code, 403)
        visible = self.image(is_reference=True, uploaded_by=self.other)
        self.override(self.viewer, {'reference.view_all': 'deny'})
        self.assertEqual(self.client.post(reverse('delete_design_image_api', args=[visible.pk])).status_code, 403)
        self.assertTrue(PatternDesignImage.objects.filter(pk=hidden.pk).exists())
        self.assertTrue(PatternDesignImage.objects.filter(pk=visible.pk).exists())

    def test_live_snapshot_is_private_compact_and_detects_next_request_revocation(self):
        self.client.force_login(self.designer)
        url = reverse('user_activity_state')
        first = self.client.get(url).json()
        self.assertEqual(first['user_id'], self.designer.pk)
        self.assertEqual(first['type'], 'activity_access')
        self.assertTrue(first['permissions']['chat.send'])
        unchanged = self.client.get(url, {'version': first['version']})
        self.assertNotIn('permissions', unchanged.json())
        self.assertIn('no-store', unchanged['Cache-Control'])
        self.override(self.designer, {'chat.send': 'deny'})
        changed = self.client.get(url, {'version': first['version'], 'user_id': self.admin.pk}).json()
        self.assertNotEqual(first['version'], changed['version'])
        self.assertEqual(changed['user_id'], self.designer.pk)
        self.assertFalse(changed['permissions']['chat.send'])
        self.assertEqual(self.client.post('/api/chat/send/').status_code, 403)

    def test_live_token_tracks_role_defaults_groups_and_business_scope(self):
        from management.services.activity_sync import access_snapshot
        def current():
            return access_snapshot(User.objects.get(pk=self.designer.pk))['version']
        before = current()
        with override_settings(ACTIVITY_ROLE_DEFAULTS={R.FREELANCE_3D_DESIGNER: {'chat.send': False}}):
            self.assertNotEqual(before, current())
        self.assertEqual(before, current())
        self.designer.groups.add(self.group)
        grouped = current()
        self.assertNotEqual(before, grouped)
        self.designer.workflow_profile.department = 'Not an authorization field'
        self.designer.workflow_profile.save(update_fields=['department'])
        self.assertEqual(grouped, current())

    def test_rolled_back_changes_do_not_publish_a_different_snapshot(self):
        from django.db import transaction
        from management.services.activity_sync import access_snapshot
        before = access_snapshot(User.objects.get(pk=self.designer.pk))['version']
        with transaction.atomic():
            type(self.designer.workflow_profile).objects.filter(user=self.designer).update(activity_permissions={'chat.send': 'deny'})
            transaction.set_rollback(True)
        self.assertEqual(before, access_snapshot(User.objects.get(pk=self.designer.pk))['version'])

    def test_live_page_revocation_and_anonymous_session_do_not_expose_permissions(self):
        self.client.force_login(self.designer)
        self.override(self.designer, {'chat.view': 'deny'})
        response = self.client.get(reverse('user_activity_state'), {'page': '/chat/'})
        self.assertFalse(response.json()['page_allowed'])
        self.assertTrue(self.client.get(reverse('user_activity_state'), {'page': '/profile/'}).json()['page_allowed'])
        self.client.logout()
        self.assertEqual(self.client.get(reverse('user_activity_state')).status_code, 302)

    def test_live_grants_do_not_make_submitted_or_foreign_reference_files_deletable(self):
        self.designer.groups.add(self.group)
        own = self.image(is_reference=True)
        foreign = self.image(is_reference=True, uploaded_by=self.other)
        protected = self.image(is_reference=True, approved_at=timezone.now())
        self.override(self.designer, {'reference.delete_all': 'deny'})
        self.client.force_login(self.designer)
        payload = self.client.get(reverse('get_design_folders_api'), {'vehicle_id': self.vehicle.pk}).json()
        images = {entry['id']: entry for entry in payload['reference_images']}
        self.assertTrue(images[own.pk]['can_delete'])
        self.assertFalse(images.get(foreign.pk, {}).get('can_delete', False))
        self.assertFalse(images[protected.pk]['can_delete'])

    def test_live_page_checks_preserve_section_query_and_bound_snapshot_queries(self):
        from management.services.activity_sync import access_snapshot
        self.override(self.md, {'users.manage': 'deny'})
        self.client.force_login(self.md)
        url = reverse('user_activity_state')
        self.assertFalse(self.client.get(url, {'page': '/admin_panel/?section=users'}).json()['page_allowed'])
        self.assertTrue(self.client.get(url, {'page': '/admin_panel/?section=dashboard'}).json()['page_allowed'])
        self.assertFalse(self.client.get(url, {'page': '//other.example/private/'}).json()['page_allowed'])
        fresh = User.objects.get(pk=self.designer.pk)
        with CaptureQueriesContext(connection) as queries:
            access_snapshot(fresh)
        self.assertLessEqual(len(queries), 4)

    def test_reference_delete_grants_never_override_submitted_or_reviewed_protection(self):
        """Both own/all grants must respect reference review and deletion safeguards."""
        self.designer.groups.add(self.group)
        own = self.image(is_reference=True, title='Eligible own reference')
        foreign = self.image(is_reference=True, uploaded_by=self.other, title='Foreign reference')
        reviewed = self.image(is_reference=True, approved_at=timezone.now(), title='Reviewed reference')
        submitted = self.image(is_reference=True, title='Submitted reference')
        submit_design_for_approval(submitted, self.designer)
        self.client.force_login(self.designer)
        url = reverse('get_design_folders_api')

        for overrides in (
            {'reference.delete_own': 'deny', 'reference.delete_all': 'deny'},
            {'reference.delete_own': 'allow', 'reference.delete_all': 'deny'},
            {'reference.delete_own': 'deny', 'reference.delete_all': 'allow'},
            {'reference.delete_own': 'allow', 'reference.delete_all': 'allow'},
        ):
            with self.subTest(overrides=overrides):
                self.override(self.designer, overrides)
                response = self.client.get(url, {'vehicle_id': self.vehicle.pk})
                self.assertEqual(response.status_code, 200)
                images = {entry['id']: entry for entry in response.json()['reference_images']}
                for image in (reviewed, submitted):
                    self.assertFalse(images[image.pk]['can_delete'])
                    delete = self.client.post(reverse('delete_design_image_api', args=[image.pk]))
                    self.assertEqual(delete.status_code, 403)
                    self.assertTrue(PatternDesignImage.objects.filter(pk=image.pk).exists())
                if overrides['reference.delete_own'] == 'deny' and overrides['reference.delete_all'] == 'deny':
                    self.assertFalse(images[own.pk]['can_delete'])
                    self.assertEqual(self.client.post(reverse('delete_design_image_api', args=[own.pk])).status_code, 403)
                # An all-file grant does not override unrelated record-visibility restrictions.
                self.assertFalse(images.get(foreign.pk, {}).get('can_delete', False))

        self.assertTrue(PatternDesignImage.objects.filter(pk=reviewed.pk).exists())
        self.assertTrue(PatternDesignImage.objects.filter(pk=submitted.pk).exists())
