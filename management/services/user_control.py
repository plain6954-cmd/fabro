"""Atomic adapter around FABRO's existing user/profile forms."""
import json
import logging
from django import forms
from django.contrib.auth import get_user_model, update_session_auth_hash
from django.contrib.auth.models import Group
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Q
from django.utils.translation import gettext as _
from management.forms import UserCreationForm, UserWorkflowProfileForm, UnifiedWorkflowRoles
from management.models import ActivityLog, UserAccessAudit, PatternDesignApproval, WorkflowRoles
from management.services.activity_permissions import (ADMIN_KEYS, CATEGORIES, REGISTRY, eligible, granted,
    identity, protected_admin, administrative_account, role_defaults, validate_overrides, self_access_recovery)

logger = logging.getLogger(__name__)
User = get_user_model()

class IdentityForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ['username', 'email', 'first_name', 'last_name']


def public_user(user):
    p = user.workflow_profile
    return {'id': user.pk, 'username': user.username, 'email': user.email,
        'first_name': user.first_name, 'last_name': user.last_name,
        'full_name': user.get_full_name() or user.username, 'phone': p.phone_number,
        'role': p.approval_role if p.role == WorkflowRoles.APPROVER else p.role,
        'role_label': str(p.display_role), 'approval_role': p.approval_role,
        'country_id': str(p.country_id or ''), 'country_name': p.country.name if p.country else '',
        'country_flag_url': p.country_flag_url or '', 'department': p.department,
        'can_factory': int(p.can_receive_factory_assignments), 'is_staff': int(user.is_staff),
        'is_superuser': int(user.is_superuser), 'is_active': user.is_active,
        'photo_url': p.avatar_url or '', 'groups': list(user.groups.values_list('pk', flat=True))}


def control_data(actor, target=None, prospective=None):
    recovery = bool(target and target.pk == actor.pk and self_access_recovery(actor))
    superuser_editor = bool(actor.is_authenticated and actor.is_active and actor.is_superuser)
    can_edit = recovery or protected_admin(actor) and granted(actor, 'users.permissions')
    info = identity(target) if target else {'role': WorkflowRoles.FACTORY_VIEWER, 'approval_role': '', 'is_staff': False, 'is_superuser': False}
    if prospective:
        info.update(prospective)
    role_options = [(value, str(label)) for value, label in UnifiedWorkflowRoles.CHOICES if value != WorkflowRoles.APPROVER]
    role_maps = {}
    for value, label in role_options:
        candidate = dict(info, role=WorkflowRoles.APPROVER if value in ('CAD', 'ED', 'MD', 'PM', 'OM') else value,
                         approval_role=value if value in ('CAD', 'ED', 'MD', 'PM', 'OM') else '')
        role_maps[value] = {'defaults': role_defaults(candidate),
            'eligible': {key: eligible(item.policy, candidate) for key, item in REGISTRY.items()},
            'protected': bool(candidate['is_superuser'] or candidate['role'] == WorkflowRoles.ADMIN)}
    return {'user': public_user(target) if target else None,
        'overrides': target.workflow_profile.activity_permissions if target else {},
        'can_delete_user': bool(target and target.pk != actor.pk and not PatternDesignApproval.objects.filter(Q(designer=target) | Q(cad_reviewer=target) | Q(ed_reviewer=target) | Q(md_reviewer=target)).exists()),
        'can_manage_permissions': bool(can_edit), 'recovery_only': recovery,
        'can_manage_security': superuser_editor and not recovery, 'can_override_all_activities': superuser_editor and can_edit, 'role_maps': role_maps,
        'groups': list((target.groups if recovery else Group.objects).order_by('name').values('id', 'name')),
        'categories': [{'key': key, 'label': str(label), 'actions': [
            {'key': item.key, 'label': str(item.label), 'requires': item.requires, 'protected': item.key in ADMIN_KEYS}
            for item in REGISTRY.values() if item.category == key]} for key, label in CATEGORIES]}


def _access_notification(user):
    try:
        from management.services.workflow import notify_user
        notify_user(user, _('Your FABRO access settings changed'),
                    _('An administrator updated your account access. Open your profile for account details.'),
                    notification_type='access_change')
    except Exception:
        logger.exception('Unable to notify account %s of access update', user.pk)


@transaction.atomic
def save_control_user(request, *, creating=False):
    actor, data = request.user, request.POST
    from management.services.workflow import is_workflow_admin
    if not actor.is_authenticated or not actor.is_active or not is_workflow_admin(actor):
        raise PermissionDenied(_('Only an active workflow administrator may manage users.'))
    recovery = self_access_recovery(actor) and not creating and data.get('user_id') == str(actor.pk)
    # Stable lock order also serializes the existing single-active-reviewer validation.
    list(User.objects.select_for_update(of=('self',)).filter(Q(is_superuser=True) | Q(workflow_profile__role=WorkflowRoles.ADMIN)).order_by('pk').values_list('pk', flat=True))
    if creating and not granted(actor, 'users.create'):
        raise PermissionDenied(_('Only Admin may create user accounts.'))
    if not granted(actor, 'users.manage') and not recovery:
        raise PermissionDenied(_('User management is disabled.'))
    if not creating and data.get('new_password') and data.get('new_password') != data.get('confirm_password', ''):
        raise ValidationError(_('The two password fields did not match.'))
    if not creating and not str(data.get('user_id', '')).isdecimal():
        raise ValidationError(_('Invalid user identifier.'))
    target = None if creating else User.objects.select_for_update(of=('self',)).select_related('workflow_profile').get(pk=data.get('user_id'))
    if target and (target.is_superuser and not actor.is_superuser or administrative_account(target) and not protected_admin(actor)):
        raise PermissionDenied(_('Only an authorized administrator may edit this account.'))
    old_role = identity(target) if target else {}
    old_overrides = dict(target.workflow_profile.activity_permissions) if target else {}
    old_groups = list(target.groups.values_list('pk', flat=True)) if target else []
    if recovery:
        allowed_fields = {'user_id', 'activity_permissions', 'control_panel', 'csrfmiddlewaretoken'}
        if set(data) - allowed_fields or request.FILES or 'activity_permissions' not in data:
            raise ValidationError(_('Recovery can change only your own activity permissions.'))
        try:
            submitted = json.loads(data['activity_permissions'])
        except (TypeError, ValueError):
            raise ValidationError(_('Invalid permission selections.'))
        overrides = validate_overrides(submitted, old_role, superuser_editor=True)
        saved_profile = target.workflow_profile
        saved_profile.activity_permissions = overrides
        saved_profile.save(update_fields=['activity_permissions'])
        for attribute in ('_activity_grants', '_workflow_profile'):
            target.__dict__.pop(attribute, None)
        record_access_audit(actor, target, old_role, old_overrides, old_groups, old_groups, overrides)
        ActivityLog.objects.create(user=actor, action='restored activity access', object_type='User', object_name=target.username)
        return target
    if creating:
        if data.get('control_panel') == '1' and data.get('password') != data.get('confirm_password'):
            raise ValidationError(_('The two password fields did not match.'))
        form = UserCreationForm(data, request.FILES)
        if not actor.is_superuser:
            form.fields.pop('is_staff', None)
            form.fields.pop('is_superuser', None)
        if not form.is_valid():
            raise ValidationError([str(message) for errors in form.errors.values() for message in errors])
        if not form.cleaned_data.get('email'):
            raise ValidationError(_('Email is required.'))
        target = form.save(commit=False)
        target.set_password(form.cleaned_data['password'])
        target.is_staff = target.is_staff or target.is_superuser
        candidate = {'file_delete': False, 'role': form.cleaned_data['mapped_role'], 'approval_role': form.cleaned_data['mapped_approval_role'],
                     'is_staff': target.is_staff, 'is_superuser': target.is_superuser}
    else:
        form = IdentityForm(data, instance=target)
        if not form.is_valid():
            raise ValidationError([str(message) for errors in form.errors.values() for message in errors])
        target = form.save(commit=False)
        profile_form = UserWorkflowProfileForm(data, request.FILES, instance=target.workflow_profile)
        if not profile_form.is_valid():
            raise ValidationError([str(message) for errors in profile_form.errors.values() for message in errors])
        candidate = identity(target)
        candidate.update(role=profile_form.cleaned_data['mapped_role'], approval_role=profile_form.cleaned_data['mapped_approval_role'])
        if actor.is_superuser:
            candidate['is_superuser'] = data.get('is_superuser') == 'on'
            candidate['is_staff'] = data.get('is_staff') == 'on' or candidate['is_superuser']
        target.is_superuser, target.is_staff = candidate['is_superuser'], candidate['is_staff']
    if not protected_admin(actor) and (creating or candidate != old_role):
        raise PermissionDenied(_('Only Admin may assign roles or reviewer authority.'))
    group_ids = old_groups
    if data.get('control_panel') == '1' and protected_admin(actor):
        try:
            group_ids = sorted({int(value) for value in data.getlist('groups')})
        except (TypeError, ValueError):
            raise ValidationError(_('Invalid group selection.'))
        if Group.objects.filter(pk__in=group_ids).count() != len(set(group_ids)):
            raise ValidationError(_('Invalid group selection.'))
    candidate['file_delete'] = bool(candidate.get('is_superuser') or Group.objects.filter(pk__in=group_ids, permissions__codename='delete_patterndesignimage', permissions__content_type__app_label='management').exists() or (target.pk and target.user_permissions.filter(codename='delete_patterndesignimage', content_type__app_label='management').exists()))
    overrides = old_overrides
    if 'activity_permissions' in data:
        if not protected_admin(actor) or not granted(actor, 'users.permissions'):
            raise PermissionDenied(_('Only Admin may manage permission overrides.'))
        try:
            submitted = json.loads(data['activity_permissions'])
        except (TypeError, ValueError):
            raise ValidationError(_('Invalid permission selections.'))
        overrides = validate_overrides(submitted, candidate, superuser_editor=bool(actor.is_superuser), existing=old_overrides)
    if data.get('control_panel') == '1':
        target.is_active = data.get('is_active') == 'on'
    if not creating:
        # Serialize the protected-account guard, including concurrent demotions.
        protected = list(User.objects.select_for_update(of=('self',)).filter(is_active=True).filter(
            Q(is_superuser=True) | Q(workflow_profile__role=WorkflowRoles.ADMIN)).values_list('pk', flat=True))
        if target.pk in protected and not (target.is_active and (target.is_superuser or candidate['role'] == WorkflowRoles.ADMIN)) and len(protected) <= 1:
            raise ValidationError(_('The final active administrator cannot be disabled or demoted.'))
        if old_role.get('is_superuser') and not (target.is_superuser and target.is_active) and not User.objects.filter(is_superuser=True, is_active=True).exclude(pk=target.pk).exists():
            raise ValidationError(_('The final active superuser cannot be demoted.'))
    new_password = data.get('new_password') or ''
    if not creating and new_password:
        if new_password != data.get('confirm_password', ''):
            raise ValidationError(_('The two password fields did not match.'))
        validate_password(new_password, user=target)
        target.set_password(new_password)
    target.save()
    if creating:
        saved_profile = form.save_profile(target)
    else:
        saved_profile = profile_form.save()
    saved_profile.activity_permissions = overrides
    saved_profile.save(update_fields=['activity_permissions'])
    target.groups.set(group_ids)
    target._state.fields_cache['workflow_profile'] = saved_profile
    for attr in ('_activity_grants', '_workflow_profile', '_perm_cache', '_user_perm_cache', '_group_perm_cache'):
        target.__dict__.pop(attr, None)
    record_access_audit(actor, target, old_role, old_overrides, old_groups, group_ids, overrides, creating=creating)
    ActivityLog.objects.create(user=actor, action='created' if creating else 'edited', object_type='User', object_name=target.username)
    if new_password and not creating:
        from management.views import _invalidate_user_authentication
        if target.pk == actor.pk:
            update_session_auth_hash(request, target)
        else:
            _invalidate_user_authentication(target.pk)
        ActivityLog.objects.create(user=actor, action='reset password', object_type='User', object_name=target.username)
    return target


def record_access_audit(actor, target, old_role, old_overrides, old_groups, group_ids, overrides, *, creating=False):
    """One audit/notification trigger for control-panel and legacy group saves."""
    changes = {key: {'old': old_overrides.get(key, 'inherit'), 'new': overrides.get(key, 'inherit')}
               for key in old_overrides.keys() | overrides.keys() if old_overrides.get(key) != overrides.get(key)}
    UserAccessAudit.objects.create(actor=actor, target=target, target_username=target.username,
        old_role=old_role, new_role=identity(target), changes={'permissions': changes,
            'groups': {'old': old_groups, 'new': group_ids}, 'active': target.is_active})
    if not creating and (changes or old_role != identity(target) or set(old_groups) != set(group_ids)):
        transaction.on_commit(lambda: _access_notification(target))
