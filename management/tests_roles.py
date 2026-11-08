"""Roles integrate with, rather than replace, existing activity/workflow security."""
import importlib
import json
from unittest.mock import patch
from django.apps import apps
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models.deletion import ProtectedError
from django.db import transaction
from django.test import TestCase, Client
from django.urls import reverse
from management.models import (ActivityRole, RoleAccessAudit, Notification, WorkflowRoles as R,
    Brand, Model, SubModel, YearRange, PatternDesignFolder, PatternDesignImage, ColorMaster)
from management.services.activity_permissions import REGISTRY, CATEGORIES, granted, identity, validate_overrides, legacy_role_defaults, role_defaults
from management.services.activity_sync import access_snapshot
from management.services.role_hierarchy import paths, window_keys
from management.services.roles import save_role, delete_role
from management.services.user_control import save_control_user

User = get_user_model()
seed = importlib.import_module('management.migrations.0056_initialize_activity_roles').seed


class RolesTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_superuser('role-admin','admin@example.com','StrongTest!369')
        p=cls.admin.workflow_profile;p.role=R.ADMIN;p.save()
        cls.viewer = User.objects.create_user('role-viewer','viewer@example.com','StrongTest!369')
        cls.cad = User.objects.create_user('role-cad','cad@example.com','StrongTest!369')
        p=cls.cad.workflow_profile;p.role=R.APPROVER;p.approval_role='CAD';p.save()
        cls.staff = User.objects.create_user('role-staff','staff@example.com','StrongTest!369',is_staff=True)
        cls.before={}
        for account in (cls.admin,cls.viewer,cls.cad,cls.staff):
            fresh=User.objects.get(pk=account.pk)
            cls.before[account.pk]={key:granted(fresh,key) for key in REGISTRY}
        seed(apps,None)

    def setUp(self):
        self.admin=User.objects.get(pk=self.admin.pk)
        self.client.force_login(self.admin)
        push=patch('management.services.push_notifications.send_push_to_user');self.push=push.start();self.addCleanup(push.stop)

    def create(self,name='Custom role',**values):
        return save_role(self.admin,dict(name=name,short_name='',permissions={},windows={})|values)

    def update(self,role,**values):
        return save_role(self.admin,dict(id=role.pk,revision=role.revision,name=role.name,short_name=role.short_name,
            permissions=dict(role.permissions),windows=dict(role.windows))|values)

    def assign(self,user,role,overrides=None):
        p=user.workflow_profile;p.activity_role=role
        if overrides is not None:p.activity_permissions=overrides
        p.save(update_fields=['activity_role','activity_permissions'])
        return User.objects.get(pk=user.pk)

    def post(self,name,payload):
        return self.client.post(reverse(name),json.dumps(payload),content_type='application/json')

    def test_inventory_covers_every_activity_once(self):
        self.assertEqual(set(paths()),set(REGISTRY));self.assertEqual(len(paths()),112)
        self.assertEqual(len(CATEGORIES),22)
        self.assertIn('patterns.status',window_keys());self.assertIn('admin.roles',window_keys())

    def test_initialization_preserves_existing_access_workflows_and_overrides(self):
        for pk,before in self.before.items():
            user=User.objects.get(pk=pk)
            self.assertEqual({key:granted(user,key) for key in REGISTRY},before)
            self.assertIsNotNone(user.workflow_profile.activity_role_id)
        self.cad.refresh_from_db();self.assertEqual(self.cad.workflow_profile.approval_role,'CAD')
        self.assertFalse(Notification.objects.exists())

    def test_builtin_defaults_preserve_all_workflow_and_security_flag_combinations(self):
        for role in ActivityRole.objects.exclude(system_code=None):
            for staff in (False,True):
                for superuser in (False,True):
                    for file_delete in (False,True):
                        code=role.system_code
                        info=dict(role=R.APPROVER if code in ('PM','OM','CAD','ED','MD') else code,
                            approval_role=code if code in ('PM','OM','CAD','ED','MD') else '',
                            is_staff=staff,is_superuser=superuser,file_delete=file_delete)
                        with self.subTest(role=code,staff=staff,superuser=superuser,file_delete=file_delete):
                            self.assertEqual(role_defaults(info,role=role),legacy_role_defaults(info))

    def test_new_superuser_binding_and_unrelated_edit_keep_workflow_identity(self):
        user=User.objects.create_superuser('role-cli-admin','cli@example.com','StrongTest!369')
        self.assertEqual(user.workflow_profile.role,R.FACTORY_VIEWER)
        self.assertTrue(granted(user,'roles.view'))
        response=self.client.post(reverse('user_control_save'),{'user_id':user.pk,'username':user.username,'email':user.email,
            'role':'admin','is_superuser':'on','is_staff':'on','is_active':'on','control_panel':'1','activity_permissions':'{}'})
        self.assertEqual(response.status_code,200,response.content)
        user=User.objects.get(pk=user.pk)
        self.assertEqual(user.workflow_profile.role,R.FACTORY_VIEWER)
        from management.services.design_approvals import can_admin_review_designs
        self.assertFalse(can_admin_review_designs(user))

    def test_create_requires_name_short_name_optional_and_deny_default(self):
        for name in ('','   '):
            with self.assertRaises(ValidationError):self.create(name)
        role=self.create();self.assertEqual(role.short_name,'')
        user=self.assign(self.viewer,role)
        self.assertFalse(any(granted(user,key) for key in REGISTRY))
        self.assertEqual(self.client.get(reverse('role_control_data'),{'id':role.pk}).status_code,200)

    def test_duplicate_names_are_case_insensitive_and_invalid_save_is_atomic(self):
        role=self.create('Operations')
        with self.assertRaises(ValidationError):self.create(' OPERATIONS ')
        count=RoleAccessAudit.objects.count()
        with self.assertRaises(ValidationError):self.update(role,name='Changed',permissions={'not.real':True})
        role.refresh_from_db();self.assertEqual(role.name,'Operations');self.assertEqual(RoleAccessAudit.objects.count(),count)

    def test_update_revision_conflict_and_noop_does_not_duplicate_events(self):
        role=self.create();old=role.revision
        role=self.update(role,name='Renamed')
        self.assertEqual(role.revision,old+1)
        with self.assertRaises(ValidationError):save_role(self.admin,{'id':role.pk,'revision':old,'name':'Stale','permissions':{},'windows':{}})
        count=RoleAccessAudit.objects.count();self.update(role)
        self.assertEqual(RoleAccessAudit.objects.count(),count)

    def test_duplicate_is_separate_and_has_no_assignments(self):
        source=self.create(permissions={'dashboard.view':True},windows={'dashboard':True})
        self.assign(self.viewer,source)
        copy=self.create('Custom role Copy',permissions=source.permissions,windows=source.windows)
        self.assertNotEqual(source.pk,copy.pk);self.assertEqual(copy.permissions,source.permissions)
        self.assertEqual(copy.members.count(),0)

    def test_delete_guards_and_retained_audit(self):
        system=ActivityRole.objects.get(system_code='admin')
        with self.assertRaises(ValidationError):delete_role(self.admin,system.pk,system.revision)
        role=self.create();self.assign(self.viewer,role)
        with self.assertRaises(ValidationError):delete_role(self.admin,role.pk,role.revision)
        with self.assertRaises(ProtectedError):role.delete()
        empty=self.create('Unused role');pk=empty.pk;delete_role(self.admin,pk,empty.revision)
        self.assertFalse(ActivityRole.objects.filter(pk=pk).exists())
        audit=RoleAccessAudit.objects.get(action='deleted',before__id=pk);self.assertIsNone(audit.role_id)

    def test_parent_disabled_preserves_selection_and_blocks_individual_allow(self):
        role=self.create(permissions={'chat.view':True,'chat.send':True},windows={'chat':True})
        user=self.assign(self.viewer,role,{'chat.send':'allow'})
        self.assertTrue(granted(user,'chat.send'))
        role=self.update(role,windows={'chat':False})
        self.assertTrue(role.permissions['chat.send'])
        self.assertFalse(granted(User.objects.get(pk=user.pk),'chat.send'))
        role=self.update(role,windows={'chat':True})
        self.assertTrue(granted(User.objects.get(pk=user.pk),'chat.send'))

    def test_subwindow_ancestors_are_enforced(self):
        role=self.create(permissions={'pattern.view':True,'pattern.list':True},windows={'patterns':True,'patterns.master':True})
        user=self.assign(self.viewer,role)
        self.assertTrue(granted(user,'pattern.list'))
        self.update(role,windows={'patterns':True,'patterns.master':False})
        self.assertFalse(granted(User.objects.get(pk=user.pk),'pattern.list'))

    def test_dependency_validation_and_disabled_selections(self):
        with self.assertRaises(ValidationError):self.create(permissions={'chat.send':True},windows={'chat':True})
        role=self.create(permissions={'chat.send':True},windows={'chat':False})
        self.assertTrue(role.permissions['chat.send'])
        with self.assertRaises(ValidationError):self.update(role,windows={'chat':True})

    def test_individual_inherit_allow_deny_and_preserved_explicit_deny(self):
        role=self.create(permissions={'dashboard.view':True,'chat.view':True},windows={'dashboard':True,'chat':True})
        user=self.assign(self.viewer,role,{'dashboard.view':'deny','chat.send':'allow'})
        self.assertFalse(granted(user,'dashboard.view'));self.assertTrue(granted(user,'chat.view'));self.assertTrue(granted(user,'chat.send'))
        self.update(role,permissions={'chat.view':True})
        user=User.objects.get(pk=user.pk)
        self.assertEqual(validate_overrides({'dashboard.view':'deny','chat.send':'allow'},identity(user),superuser_editor=True,existing=user.workflow_profile.activity_permissions)['dashboard.view'],'deny')

    def test_custom_assignment_keeps_workflow_identity_and_new_user_is_viewer(self):
        role=self.create(permissions={'dashboard.view':True},windows={'dashboard':True})
        response=self.client.post(reverse('user_control_save'),{'user_id':self.cad.pk,'username':self.cad.username,
            'email':self.cad.email,'role':f'activity:{role.pk}','is_active':'on','control_panel':'1','activity_permissions':'{}'})
        self.assertEqual(response.status_code,200,response.content)
        self.cad.refresh_from_db();p=self.cad.workflow_profile
        self.assertEqual((p.role,p.approval_role,p.activity_role_id),(R.APPROVER,'CAD',role.pk))
        response=self.client.post(reverse('user_control_save'),{'username':'role-new-user','email':'new@example.com',
            'password':'StrongTest!369','confirm_password':'StrongTest!369','role':f'activity:{role.pk}',
            'is_active':'on','control_panel':'1','activity_permissions':'{}'})
        self.assertEqual(response.status_code,200,response.content)
        self.assertEqual(User.objects.get(username='role-new-user').workflow_profile.role,R.FACTORY_VIEWER)

    def test_role_never_grants_administrator_or_other_reviewer_authority(self):
        role=self.create(permissions={'roles.view':True,'roles.edit':True,'erp.view':True},windows={'admin':True,'admin.roles':True})
        user=self.assign(self.viewer,role,{'roles.view':'allow','roles.edit':'allow','erp.view':'allow'})
        self.client.force_login(user)
        self.assertEqual(self.client.get(reverse('role_control_data')).status_code,403)
        self.assertEqual(self.post('role_control_save',{'name':'Attack'}).status_code,403)
        from management.services.design_approvals import resolve_design_review_role
        with self.assertRaises(PermissionDenied):resolve_design_review_role(self.cad,'ed')

    def test_non_admin_user_manager_cannot_change_activity_role_through_direct_post(self):
        md=User.objects.create_user('role-md-manager','md@example.com','StrongTest!369')
        p=md.workflow_profile;p.role=R.APPROVER;p.approval_role='MD';p.save()
        custom=self.create();self.client.force_login(md)
        payload={'user_id':self.viewer.pk,'username':self.viewer.username,'email':self.viewer.email,'role':R.FACTORY_VIEWER}
        self.assertEqual(self.client.post(reverse('user_control_save'),payload).status_code,200)
        before=User.objects.get(pk=self.viewer.pk).workflow_profile.activity_role_id
        payload.update(role=f'activity:{custom.pk}',username='unauthorized-role-edit')
        self.assertEqual(self.client.post(reverse('user_control_save'),payload).status_code,403)
        self.viewer.refresh_from_db()
        self.assertEqual(self.viewer.username,'role-viewer')
        self.assertEqual(self.viewer.workflow_profile.activity_role_id,before)

    def test_inactive_and_protected_admin_rules(self):
        role=self.create(permissions={'dashboard.view':True},windows={'dashboard':True})
        user=self.assign(self.viewer,role);user.is_active=False;user.save()
        self.assertFalse(granted(user,'dashboard.view'))
        system=ActivityRole.objects.get(system_code='admin')
        with self.assertRaises(ValidationError):self.update(system,windows={'admin':False})
        with self.assertRaises(ValidationError):self.update(system,permissions=dict(system.permissions,**{'users.manage':False}))

    def test_admin_assignment_cannot_remove_mandatory_access_through_empty_defaults(self):
        role=self.create(windows={key:True for key in window_keys()})
        response=self.client.post(reverse('user_control_save'),{'user_id':self.admin.pk,
            'username':self.admin.username,'email':self.admin.email,'role':f'activity:{role.pk}',
            'is_superuser':'on','is_staff':'on','is_active':'on','control_panel':'1','activity_permissions':'{}'})
        self.assertEqual(response.status_code,400)
        self.assertIn('administrative role defaults',' '.join(response.json()['messages']))
        self.assertEqual(User.objects.get(pk=self.admin.pk).workflow_profile.activity_role.system_code,'admin')

    def test_backend_revocation_without_logout_and_version_updates(self):
        role=self.create(permissions={'chat.view':True},windows={'chat':True})
        user=self.assign(self.viewer,role);client=Client();client.force_login(user)
        self.assertEqual(client.get(reverse('chat_users_api')).status_code,200)
        before=client.get(reverse('user_activity_state')).json()['version']
        self.update(role,windows={'chat':False})
        self.assertEqual(client.get(reverse('chat_users_api')).status_code,403)
        self.assertNotEqual(client.get(reverse('user_activity_state')).json()['version'],before)

    def test_role_update_notifies_only_assigned_users_once_after_commit(self):
        role=self.create();self.assign(self.viewer,role)
        with self.captureOnCommitCallbacks(execute=True):self.update(role,name='Updated role')
        notifications=Notification.objects.filter(notification_type='access_change')
        self.assertEqual(list(notifications.values_list('recipient_id',flat=True)),[self.viewer.pk])
        self.assertEqual(self.push.call_count,1)
        self.assertEqual(self.push.call_args.args[0].pk,self.viewer.pk)
        self.assertEqual(self.push.call_args.kwargs['url'],'/profile/')
        self.assertNotIn('Updated role',self.push.call_args.args[2])
        self.assertFalse(Notification.objects.filter(recipient=self.cad).exists())

    def test_role_notification_rollback_noop_and_push_failure_are_safe(self):
        role=self.create();self.assign(self.viewer,role)
        with self.captureOnCommitCallbacks(execute=True):
            try:
                with transaction.atomic():
                    self.update(role,name='Rolled back')
                    raise RuntimeError('Synthetic rollback')
            except RuntimeError:pass
        role.refresh_from_db();self.assertEqual(role.name,'Custom role')
        self.assertFalse(Notification.objects.exists());self.push.assert_not_called()
        with self.captureOnCommitCallbacks(execute=True):self.update(role)
        self.push.assert_not_called()
        self.push.side_effect=RuntimeError('Synthetic push failure')
        with self.captureOnCommitCallbacks(execute=True):self.update(role,name='Committed despite push failure')
        role.refresh_from_db();self.assertEqual(role.name,'Committed despite push failure')
        self.assertEqual(Notification.objects.filter(recipient=self.viewer).count(),1)

    def test_dormant_individual_allow_is_preserved_but_cannot_bypass_disabled_parent(self):
        role=self.create(windows={'chat':False})
        user=self.assign(self.viewer,role,{'chat.send':'allow'})
        self.assertFalse(granted(user,'chat.send'))
        self.assertEqual(validate_overrides({'chat.send':'allow'},identity(user),
            superuser_editor=True,existing={'chat.send':'allow'}),{'chat.send':'allow'})
        self.update(role,windows={'chat':True})
        with self.assertRaises(ValidationError):
            validate_overrides({'chat.send':'allow'},identity(User.objects.get(pk=user.pk)),superuser_editor=True)

    def test_independent_measurement_metadata_and_file_loader_do_not_leak_denied_data(self):
        brand=Brand.objects.create(name='Role scoped brand')
        model=Model.objects.create(brand=brand,name='Role scoped model')
        sub=SubModel.objects.create(model=model,name='Role scoped sub')
        vehicle=YearRange.objects.create(sub_model=sub,layout_code='ROLE-SCOPE',google_drive_url='https://drive.google.com/private')
        color=ColorMaster.objects.create(name='Restricted color',color_code='RESTRICTED')
        folder=PatternDesignFolder.objects.create(vehicle=vehicle,name='Restricted folder',created_by=self.viewer)
        hidden=PatternDesignImage.objects.create(vehicle=vehicle,folder=folder,uploaded_by=self.viewer,image='private.pdf',title='Folder file')
        direct=PatternDesignImage.objects.create(vehicle=vehicle,uploaded_by=self.viewer,image='direct.pdf',title='Own file')
        other=PatternDesignImage.objects.create(vehicle=vehicle,uploaded_by=self.cad,image='other.pdf',title='Other file')
        role=self.create(permissions={'pattern.view':True,'measurement.view_own':True},windows={'patterns':True,'patterns.measurements':True})
        user=self.assign(self.viewer,role);client=Client();client.force_login(user)
        url=reverse('get_design_folders_api')
        self.assertEqual(client.get(url,{'vehicle_id':vehicle.pk}).status_code,403)
        context=client.get(url,{'vehicle_id':vehicle.pk,'context_only':'1'}).json()
        self.assertEqual(set(context),{'status','vehicle'})
        self.assertEqual((context['vehicle']['drive_links'],context['vehicle']['google_drive_url'],context['vehicle']['photo_url']),([],'',''))
        page=client.get(reverse('car_details'),{'vehicle_id':vehicle.pk})
        self.assertEqual(page.status_code,200)
        self.assertEqual(page.context['car_data'],[]);self.assertEqual(page.context['colors'],[])
        self.assertEqual(page.context['page_obj'].paginator.count,0)
        self.assertEqual(client.get(reverse('car_details')).status_code,403)
        self.update(role,permissions={'pattern.view':True,'design.view_own':True},windows={'patterns':True,'patterns.design':True})
        with patch('management.views._ensure_pattern_thumbnail',return_value=''):
            payload=client.get(url,{'vehicle_id':vehicle.pk}).json()
        self.assertEqual(payload['folders'],[])
        self.assertEqual([item['id'] for item in payload['design_files']],[direct.pk])
        self.assertEqual(set(payload['gallery_manifest']),{str(direct.pk)})

    def test_csrf_and_api_validation(self):
        client=Client(enforce_csrf_checks=True);client.force_login(self.admin)
        self.assertEqual(client.post(reverse('role_control_save'),json.dumps({'name':'No CSRF'}),content_type='application/json').status_code,403)
        self.assertEqual(self.client.get(reverse('role_control_data'),{'id':'9'*100}).status_code,404)
        for payload in ({'id':10**100,'name':'Overflow'},{'name':''},{'name':'Bad','windows':{'imaginary':True}},{'name':'Bad','permissions':{'chat.view':'allow'}},{'name':'Bad','system_code':'admin'}):
            self.assertEqual(self.post('role_control_save',payload).status_code,400)
