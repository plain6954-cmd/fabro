"""Frozen legacy-access initialization. Does not change workflow identity or groups."""
from types import SimpleNamespace
from django.conf import settings
from django.db import migrations

R = SimpleNamespace(COUNTRY_EXECUTIVE='country_executive', FACTORY_EXECUTIVE='factory_executive',
    FACTORY_VIEWER='factory_viewer', FACTORY_COMPLAINT_REGISTRAR='factory_complaint_registrar',
    APPROVER='approver', ADMIN='admin', FREELANCE_3D_DESIGNER='freelance_3d_designer')
ApprovalRoles = SimpleNamespace(MD='MD')
SPEC = {'dashboard.view': {'policy': 'authenticated', 'requires': []},
 'vehicle.view': {'policy': 'authenticated', 'requires': []},
 'vehicle.create': {'policy': 'catalog', 'requires': []},
 'vehicle.edit': {'policy': 'catalog', 'requires': []},
 'vehicle.delete': {'policy': 'catalog', 'requires': []},
 'vehicle.import': {'policy': 'catalog', 'requires': []},
 'vehicle.photo': {'policy': 'superuser', 'requires': []},
 'pattern.view': {'policy': 'authenticated', 'requires': []},
 'pattern.edit': {'policy': 'catalog', 'requires': []},
 'pattern.delete': {'policy': 'catalog', 'requires': []},
 'pattern.alter': {'policy': 'catalog', 'requires': []},
 'pattern.decide': {'policy': 'pattern_review', 'requires': []},
 'pattern.drive_view': {'policy': 'authenticated', 'requires': []},
 'pattern.drive_add': {'policy': 'drive', 'requires': []},
 'pattern.drive_delete': {'policy': 'superuser', 'requires': []},
 'reference.view_own': {'policy': 'authenticated', 'requires': []},
 'reference.view_all': {'policy': 'authenticated', 'requires': []},
 'reference.upload': {'policy': 'reference_upload', 'requires': []},
 'reference.download_own': {'policy': 'authenticated', 'requires': []},
 'reference.download_all': {'policy': 'authenticated', 'requires': []},
 'reference.delete_own': {'policy': 'file_delete', 'requires': []},
 'reference.delete_all': {'policy': 'file_delete', 'requires': []},
 'design.view_own': {'policy': 'authenticated', 'requires': []},
 'design.view_all': {'policy': 'authenticated', 'requires': []},
 'design.upload': {'policy': 'design_upload', 'requires': []},
 'design.download_own': {'policy': 'authenticated', 'requires': []},
 'design.download_all': {'policy': 'authenticated', 'requires': []},
 'design.delete_own': {'policy': 'design_delete_own', 'requires': []},
 'design.delete_all': {'policy': 'file_delete', 'requires': []},
 'measurement.view_own': {'policy': 'authenticated', 'requires': []},
 'measurement.view_all': {'policy': 'authenticated', 'requires': []},
 'measurement.upload': {'policy': 'authenticated', 'requires': []},
 'measurement.download_own': {'policy': 'authenticated', 'requires': []},
 'measurement.download_all': {'policy': 'authenticated', 'requires': []},
 'measurement.delete_own': {'policy': 'authenticated', 'requires': []},
 'measurement.delete_all': {'policy': 'catalog', 'requires': []},
 'design.delete_uploaded': {'policy': 'design_delete', 'requires': []},
 'design.resubmit_own': {'policy': 'design_upload', 'requires': []},
 'design.resubmit_all': {'policy': 'superuser', 'requires': []},
 'design.history': {'policy': 'design_view', 'requires': ['design_approval.view']},
 'folder.view': {'policy': 'authenticated', 'requires': []},
 'folder.create': {'policy': 'assets', 'requires': []},
 'folder.rename': {'policy': 'assets', 'requires': []},
 'folder.delete_own': {'policy': 'file_delete', 'requires': []},
 'folder.delete_all': {'policy': 'file_delete', 'requires': []},
 'design_approval.view': {'policy': 'design_view', 'requires': []},
 'design_approval.history': {'policy': 'design_view', 'requires': ['design_approval.view']},
 'design_approval.comment': {'policy': 'review', 'requires': ['design_approval.view']},
 'design_approval.voice': {'policy': 'review', 'requires': ['design_approval.comment']},
 'design_approval.approve': {'policy': 'review', 'requires': ['design_approval.view']},
 'design_approval.reject': {'policy': 'review', 'requires': ['design_approval.view']},
 'color.view': {'policy': 'authenticated', 'requires': []},
 'color.create': {'policy': 'catalog', 'requires': []},
 'color.edit': {'policy': 'catalog', 'requires': []},
 'color.delete': {'policy': 'catalog', 'requires': []},
 'color.submit': {'policy': 'authenticated', 'requires': []},
 'color.history': {'policy': 'authenticated', 'requires': []},
 'color.approve': {'policy': 'color_review', 'requires': ['color.view']},
 'color.reject': {'policy': 'color_review', 'requires': ['color.view']},
 'sku.view': {'policy': 'authenticated', 'requires': []},
 'sku.create': {'policy': 'catalog', 'requires': []},
 'sku.edit': {'policy': 'catalog', 'requires': []},
 'sku.delete': {'policy': 'catalog', 'requires': []},
 'picked_colors.view': {'policy': 'authenticated', 'requires': ['pattern.view']},
 'picked_colors.add': {'policy': 'authenticated', 'requires': ['picked_colors.view', 'color.submit']},
 'picked_colors.edit_own': {'policy': 'authenticated', 'requires': ['picked_colors.view', 'color.submit']},
 'picked_colors.edit_all': {'policy': 'catalog', 'requires': ['picked_colors.view', 'color.submit']},
 'picked_colors.delete_own': {'policy': 'authenticated', 'requires': ['picked_colors.view']},
 'picked_colors.delete_all': {'policy': 'catalog', 'requires': ['picked_colors.view']},
 'complaint.view': {'policy': 'authenticated', 'requires': []},
 'complaint.create': {'policy': 'complaint_create', 'requires': []},
 'complaint.edit': {'policy': 'report_edit', 'requires': []},
 'complaint.delete': {'policy': 'erp', 'requires': []},
 'complaint.export': {'policy': 'authenticated', 'requires': []},
 'complaint.media_view': {'policy': 'authenticated', 'requires': []},
 'complaint.media_upload': {'policy': 'authenticated', 'requires': []},
 'complaint.media_delete': {'policy': 'authenticated', 'requires': []},
 'workflow.view': {'policy': 'approvals_view', 'requires': []},
 'workflow.factory_review': {'policy': 'factory', 'requires': []},
 'workflow.approve': {'policy': 'complaint_review', 'requires': []},
 'workflow.reject': {'policy': 'complaint_review', 'requires': []},
 'workflow.start': {'policy': 'factory', 'requires': []},
 'workflow.verify_submit': {'policy': 'factory', 'requires': []},
 'workflow.close': {'policy': 'factory', 'requires': []},
 'master.view': {'policy': 'erp', 'requires': []},
 'master.create': {'policy': 'erp', 'requires': []},
 'master.edit': {'policy': 'erp', 'requires': []},
 'master.delete': {'policy': 'erp', 'requires': []},
 'notification.view': {'policy': 'authenticated', 'requires': []},
 'notification.read': {'policy': 'authenticated', 'requires': []},
 'chat.view': {'policy': 'authenticated', 'requires': []},
 'chat.send': {'policy': 'authenticated', 'requires': ['chat.view']},
 'reports.pattern_history': {'policy': 'authenticated', 'requires': []},
 'reports.activity': {'policy': 'erp', 'requires': []},
 'erp.view': {'policy': 'erp', 'requires': []},
 'erp.control_tower': {'policy': 'erp', 'requires': []},
 'erp.sessions_view': {'policy': 'erp', 'requires': []},
 'erp.sessions_terminate': {'policy': 'erp', 'requires': []},
 'users.create': {'policy': 'admin', 'requires': []},
 'users.manage': {'policy': 'erp', 'requires': []},
 'users.permissions': {'policy': 'admin', 'requires': []},
 'users.groups': {'policy': 'admin', 'requires': []},
 'users.password': {'policy': 'erp', 'requires': []},
 'users.photo_delete': {'policy': 'erp', 'requires': []}}
ADMIN_KEYS = frozenset(['vehicle.view', 'vehicle.create', 'vehicle.edit', 'vehicle.delete', 'vehicle.import', 'pattern.view', 'pattern.edit', 'pattern.delete', 'pattern.alter', 'folder.view', 'folder.create', 'folder.rename', 'color.view', 'color.create', 'color.edit', 'color.delete', 'sku.view', 'sku.create', 'sku.edit', 'sku.delete', 'master.view', 'master.create', 'master.edit', 'master.delete', 'reports.activity', 'erp.view', 'erp.control_tower', 'erp.sessions_view', 'erp.sessions_terminate', 'users.create', 'users.manage', 'users.permissions', 'users.groups', 'users.password', 'users.photo_delete'])
REGISTRY = {key: SimpleNamespace(key=key, **item) for key,item in SPEC.items()}

def eligible(policy, identity):
    role, stage = identity.get('role', ''), identity.get('approval_role', '')
    su = identity.get('is_superuser', False)
    admin = su or role == R.ADMIN
    erp = admin or stage == ApprovalRoles.MD
    catalog = erp or identity.get('is_staff', False)
    reviewer = role == R.APPROVER and stage in ('CAD', 'ED', 'MD')
    policies = {
        'authenticated': True, 'file_delete': su or identity.get('file_delete', False),
        'design_delete_own': su or identity.get('file_delete', False) or role == R.FREELANCE_3D_DESIGNER, 'admin': admin, 'superuser': su, 'erp': erp, 'catalog': catalog,
        'assets': catalog or role == R.FREELANCE_3D_DESIGNER,
        'drive': catalog or role == R.FREELANCE_3D_DESIGNER or (role == R.APPROVER and stage == 'CAD'),
        'reference_upload': su or reviewer,
        'design_upload': role in (R.ADMIN, R.FREELANCE_3D_DESIGNER) or role == R.APPROVER,
        'design_view': su or role in (R.ADMIN, R.FREELANCE_3D_DESIGNER, R.APPROVER),
        'review': role == R.ADMIN or reviewer,
        'color_review': reviewer,
        'complaint_create': erp or role in (R.COUNTRY_EXECUTIVE, R.FACTORY_EXECUTIVE, R.FACTORY_COMPLAINT_REGISTRAR),
        'report_edit': erp or role == R.COUNTRY_EXECUTIVE,
        'approvals_view': erp or role in (R.COUNTRY_EXECUTIVE, R.FACTORY_EXECUTIVE, R.APPROVER, R.FREELANCE_3D_DESIGNER),
        'complaint_review': erp or role == R.APPROVER,
        'pattern_review': su or role == R.APPROVER or stage in ('CAD', 'ED', 'MD', 'PM', 'OM'),
        'factory': erp or role == R.FACTORY_EXECUTIVE,
        'design_delete': True,
    }
    return bool(policies[policy])

def role_defaults(info):
    """Compatibility defaults; optional policy configuration never mutates overrides."""
    defaults = {key: (False if key == 'design.delete_uploaded' else eligible(item.policy, info)) for key, item in REGISTRY.items()}
    role_key = info.get('approval_role') if info.get('role') == R.APPROVER else info.get('role')
    changes = getattr(settings, 'ACTIVITY_ROLE_DEFAULTS', {}).get(role_key, {})
    defaults.update({key: value and eligible(REGISTRY[key].policy, info)
                     for key, value in changes.items() if key in REGISTRY and type(value) is bool})
    if info.get('is_superuser') or info.get('role') == R.ADMIN:
        defaults.update({key: True for key in ADMIN_KEYS})
    defaults['design.delete_uploaded'] = False
    for item in REGISTRY.values():
        if any(not defaults[dep] for dep in item.requires):
            defaults[item.key] = False
    return defaults

SYSTEM_ROLES = [
    ('admin','Admin','ADM'), ('country_executive','Country Executive','CE'),
    ('factory_executive','Factory Executive','FE'), ('factory_viewer','Factory Viewer','FV'),
    ('factory_complaint_registrar','Factory Complaint Registrar','FCR'),
    ('freelance_3d_designer','3D Designer Freelancer','3DD'),
    ('PM','PM','PM'), ('OM','OM','OM'), ('CAD','CAD','CAD'), ('ED','ED','ED'), ('MD','MD','MD')]


def complete_defaults(info):
    defaults = role_defaults(info)
    defaults.update({key: bool(info.get('is_superuser') or info.get('role')=='admin')
        for key in ('roles.view','roles.create','roles.edit','roles.delete','roles.permissions')})
    defaults.update({'pattern.list':bool(defaults['pattern.view']),'approvals.workspace':True,'design_status.view':bool(defaults['pattern.view'])})
    return defaults


def seed(apps, schema_editor):
    alias = schema_editor.connection.alias if schema_editor else 'default'
    Role = apps.get_model('management','ActivityRole')
    Profile = apps.get_model('management','UserProfile')
    Audit = apps.get_model('management','RoleAccessAudit')
    codes = list(SYSTEM_ROLES)
    if Profile.objects.using(alias).filter(role='approver',approval_role='').exists():
        codes.append(('approver','Unassigned Approver',''))
    records = {}
    for code,name,short in codes:
        info = dict(role='approver' if code in ('PM','OM','CAD','ED','MD') else code,
            approval_role=code if code in ('PM','OM','CAD','ED','MD') else '',
            # Compatibility ceiling; the resolver still applies each actual
            # user's workflow identity, staff/superuser flags and file grants.
            is_staff=True,is_superuser=True,file_delete=True)
        records[code],_ = Role.objects.using(alias).get_or_create(system_code=code,
            defaults=dict(name=name,name_key=name.casefold(),short_name=short,
                          permissions=complete_defaults(info),windows={}))
    for person in Profile.objects.using(alias).select_related('user').iterator():
        if person.activity_role_id:
            continue
        code = person.approval_role if person.role=='approver' and person.approval_role else person.role
        role = records.get(code)
        if role is None:
            continue  # Unknown legacy workflow identities are never rewritten.
        user = person.user
        file_delete = bool(user.is_superuser or user.user_permissions.using(alias).filter(
            codename='delete_patterndesignimage',content_type__app_label='management').exists() or user.groups.using(alias).filter(
            permissions__codename='delete_patterndesignimage',permissions__content_type__app_label='management').exists())
        info = dict(role=person.role,approval_role=person.approval_role,
                    is_staff=user.is_staff,is_superuser=user.is_superuser,file_delete=file_delete)
        old = dict(person.activity_permissions or {})
        preserved = dict(old)
        for key,default in complete_defaults(info).items():
            policy = SPEC[key]['policy'] if key in SPEC else 'admin' if key.startswith('roles.') else 'authenticated'
            inherited = bool(role.permissions.get(key) and eligible(policy,info))
            if key not in old and inherited != default:
                preserved[key] = 'allow' if default else 'deny'
        Profile.objects.using(alias).filter(pk=person.pk).update(activity_role_id=role.pk,activity_permissions=preserved)
        Audit.objects.using(alias).create(role_id=role.pk,action='initialized_user',
            before=dict(profile_id=person.pk,activity_permissions=old),after=dict(activity_permissions=preserved))


def unseed(apps, schema_editor):
    alias = schema_editor.connection.alias
    Role = apps.get_model('management','ActivityRole')
    Profile = apps.get_model('management','UserProfile')
    Audit = apps.get_model('management','RoleAccessAudit')
    for entry in Audit.objects.using(alias).filter(action='initialized_user').iterator():
        Profile.objects.using(alias).filter(pk=entry.before['profile_id'],activity_role_id=entry.role_id,
            activity_permissions=entry.after['activity_permissions']).update(
                activity_role_id=None,activity_permissions=entry.before['activity_permissions'])
    # PROTECT intentionally blocks rollback after subsequent assignments/edits.
    Role.objects.using(alias).filter(system_code__in=[code for code,_,_ in SYSTEM_ROLES]+['approver']).delete()


class Migration(migrations.Migration):
    dependencies = [('management','0055_activity_roles')]
    operations = [migrations.RunPython(seed, unseed)]
