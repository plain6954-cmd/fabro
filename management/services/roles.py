"""Role CRUD uses the existing activity resolver and mandatory workflow guards."""
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Count, Q
from django.utils.translation import gettext as _
from management.models import ActivityRole, RoleAccessAudit, ActivityLog, UserProfile, WorkflowRoles
from management.services.activity_permissions import ADMIN_KEYS, REGISTRY, eligible, protected_admin, require
from management.services.role_hierarchy import tree, paths, window_keys, ancestors_enabled


def members_filter(role):
    query = Q(activity_role_id=role.pk)
    if role.system_code:
        fallback = Q(role=WorkflowRoles.APPROVER, approval_role=role.system_code) if role.system_code in ('PM','OM','CAD','ED','MD') else Q(role=role.system_code)
        query |= Q(activity_role__isnull=True) & fallback
    return query


def authorize(actor, action='view'):
    if not protected_admin(actor):
        raise PermissionDenied(_('Only an active Admin may manage roles.'))
    require(actor, 'erp.view', 'roles.view', 'roles.'+action)


def locked(role):
    protected = bool(role and (role.system_code == WorkflowRoles.ADMIN or UserProfile.objects.filter(members_filter(role), user__is_active=True).filter(Q(user__is_superuser=True)|Q(role=WorkflowRoles.ADMIN)).exists()))
    if not protected:
        return [], []
    return [key for key in ADMIN_KEYS if role.permissions.get(key)], sorted({parent for key in ADMIN_KEYS for parent in paths()[key]})


def snapshot(role):
    return {'id':role.pk, 'name':role.name, 'short_name':role.short_name, 'system_code':role.system_code,
            'permissions':role.permissions, 'windows':role.windows, 'revision':role.revision}


def list_roles():
    roles = list(ActivityRole.objects.order_by('pk'))
    counts = dict(UserProfile.objects.exclude(activity_role_id=None).values('activity_role_id').annotate(total=Count('pk')).values_list('activity_role_id','total'))
    legacy = UserProfile.objects.filter(activity_role_id=None).values('role','approval_role').annotate(total=Count('pk'))
    fallback = {(row['approval_role'] if row['role']==WorkflowRoles.APPROVER else row['role']):row['total'] for row in legacy}
    return [dict(snapshot(role), user_count=counts.get(role.pk,0)+fallback.get(role.system_code,0)) for role in roles]


def control_data(actor, role=None):
    authorize(actor)
    from management.services.activity_permissions import granted
    def serialize(items):
        return [dict(item, actions=[{'key':key,'label':str(REGISTRY[key].label),'requires':REGISTRY[key].requires} for key in item['actions']], children=serialize(item['children'])) for item in items]
    permissions_lock, windows_lock = locked(role)
    return dict(roles=list_roles(), selected=dict(snapshot(role), locked_permissions=permissions_lock, locked_windows=windows_lock) if role else None,
        hierarchy=serialize(tree()), can={action:granted(actor,'roles.'+action) for action in ('create','edit','delete','permissions')})


def validate_config(permissions, windows, system_code=None):
    if not isinstance(permissions,dict) or any(key not in REGISTRY or type(value) is not bool for key,value in permissions.items()):
        raise ValidationError(_('Invalid activity keys or selections.'))
    if not isinstance(windows,dict) or any(key not in window_keys() or type(value) is not bool for key,value in windows.items()):
        raise ValidationError(_('Invalid window selections.'))
    role = ActivityRole(permissions=permissions,windows=windows,system_code=system_code)
    for key,selected in permissions.items():
        if selected and ancestors_enabled(role,key) and any(not permissions.get(dep,False) or not ancestors_enabled(role,dep) for dep in REGISTRY[key].requires):
            raise ValidationError(_('Enable the required view/remarks activity before its dependent actions.'))


@transaction.atomic
def save_role(actor, data):
    allowed = {'id','revision','name','short_name','permissions','windows'}
    if not isinstance(data,dict) or set(data)-allowed:
        raise ValidationError(_('Invalid role submission.'))
    identifier = data.get('id')
    if identifier is not None and (type(identifier) is not int or not 0 < identifier <= 2**63-1):
        raise ValidationError(_('Invalid role identifier.'))
    authorize(actor,'edit' if identifier else 'create')
    role = ActivityRole.objects.select_for_update().get(pk=identifier) if identifier else ActivityRole()
    before = snapshot(role) if role.pk else {}
    if role.pk and (type(data.get('revision')) is not int or data['revision'] != role.revision):
        raise ValidationError(_('This role changed in another window. Reload it before saving.'))
    name, short = data.get('name',''), data.get('short_name','')
    if not isinstance(name,str) or not name.strip() or len(name.strip())>150:
        raise ValidationError(_('Role Name is required and must be 150 characters or fewer.'))
    if not isinstance(short,str) or len(short.strip())>20:
        raise ValidationError(_('Short Name must be 20 characters or fewer.'))
    if ActivityRole.objects.filter(name_key=name.strip().casefold()).exclude(pk=role.pk).exists():
        raise ValidationError(_('A role with this name already exists.'))
    permissions, windows = data.get('permissions',{}), data.get('windows',{})
    validate_config(permissions,windows,role.system_code)
    if permissions != role.permissions or windows != role.windows:
        require(actor,'roles.permissions')
    locked_permissions, locked_windows = locked(role) if role.pk else ([],[])
    if any(not permissions.get(key) for key in locked_permissions) or any(not windows.get(key,bool(role.system_code)) for key in locked_windows):
        raise ValidationError(_('Protected administrative access cannot be removed from this role.'))
    if before and (name.strip(),short.strip(),permissions,windows) == (role.name,role.short_name,role.permissions,role.windows):
        return role
    role.name, role.short_name = name.strip(), short.strip()
    role.permissions, role.windows = dict(permissions), dict(windows)
    role.revision += bool(role.pk)
    role.save()
    RoleAccessAudit.objects.create(actor=actor,role=role,action='updated' if before else 'created',before=before,after=snapshot(role))
    ActivityLog.objects.create(user=actor,action='edited' if before else 'created',object_type='ActivityRole',object_name=role.name)
    actor.__dict__.pop('_activity_grants',None)
    if before:
        from management.services.user_control import _access_notification
        affected = list(get_user_model().objects.filter(workflow_profile__in=UserProfile.objects.filter(members_filter(role))))
        for member in affected:
            transaction.on_commit(lambda user=member:_access_notification(user))
    return role


@transaction.atomic
def delete_role(actor, identifier, revision):
    authorize(actor,'delete')
    if type(identifier) is not int or not 0 < identifier <= 2**63-1:
        raise ValidationError(_('Invalid role identifier.'))
    role = ActivityRole.objects.select_for_update().get(pk=identifier)
    if type(revision) is not int or revision != role.revision:
        raise ValidationError(_('This role changed in another window. Reload it before deleting.'))
    if role.system_code or UserProfile.objects.filter(members_filter(role)).exists():
        raise ValidationError(_('System roles and roles assigned to users cannot be deleted.'))
    RoleAccessAudit.objects.create(actor=actor,role=role,action='deleted',before=snapshot(role))
    ActivityLog.objects.create(user=actor,action='deleted',object_type='ActivityRole',object_name=role.name)
    role.delete()
