"""Feature gates layered on top of FABRO's existing role/object/state authorization.

No override rows are created for existing users. Empty dictionaries inherit the
compatibility defaults below. Never use a feature grant as object authorization.
"""
from dataclasses import dataclass
from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Q
from django.utils.translation import gettext_lazy as _
from management.models import WorkflowRoles as R, ApprovalRoles

CATEGORIES = (
    ('dashboard', _('Dashboard & Navigation')), ('vehicle', _('Vehicle Catalog')),
    ('pattern', _('Pattern Master')), ('measurement', _('Measurements')),
    ('reference', _('Reference Images')), ('design', _('Designer Uploads')),
    ('folder', _('Design Folders')), ('design_approval', _('Design Approval')),
    ('color', _('Colors & Color Approval')), ('sku', _('SKU Management')),
    ('complaint', _('Complaints')), ('workflow', _('Complaint Workflow')),
    ('master', _('Master Settings')), ('notification', _('Notifications')),
    ('chat', _('Internal Chat')), ('reports', _('Reports & Activity')),
    ('erp', _('ERP Administration')), ('users', _('User & Access Management')),
)

@dataclass(frozen=True)
class Activity:
    key: str
    category: str
    label: str
    policy: str = 'authenticated'
    requires: tuple = ()
    scope: str = ''

REGISTRY = {}
def activities(category, entries):
    for entry in entries:
        name, label, *options = entry
        policy = options[0] if options else 'authenticated'
        requires = options[1] if len(options) > 1 else ()
        key = category + '.' + name
        REGISTRY[key] = Activity(key, category, _(label), policy, tuple(requires),
                                 'uploader/creator' if name.endswith(('_own', '_all')) else '')

activities('dashboard', [('view', 'View dashboard')])
activities('vehicle', [('view', 'View vehicle catalog'), ('create', 'Create vehicles', 'catalog'),
    ('edit', 'Edit vehicles', 'catalog'), ('delete', 'Delete eligible vehicles', 'catalog'),
    ('import', 'Import vehicle/pattern spreadsheets', 'catalog'), ('photo', 'Upload vehicle photo', 'superuser')])
activities('pattern', [('view', 'View Pattern Master'), ('edit', 'Edit pattern details', 'catalog'),
    ('delete', 'Delete eligible patterns', 'catalog'), ('alter', 'Request pattern alterations', 'catalog'),
    ('decide', 'Decide assigned pattern alterations', 'pattern_review'), ('drive_view', 'View Drive links'),
    ('drive_add', 'Add Drive links', 'drive'), ('drive_delete', 'Delete Drive links', 'superuser')])
for category, noun in [('reference', 'references'), ('design', 'designs'), ('measurement', 'measurement files')]:
    activities(category, [('view_own', 'View own ' + noun), ('view_all', 'View all authorized ' + noun),
        ('upload', 'Upload ' + noun, 'reference_upload' if category == 'reference' else 'design_upload' if category == 'design' else 'authenticated'),
        ('download_own', 'Download own ' + noun), ('download_all', 'Download all authorized ' + noun),
        ('delete_own', 'Delete own eligible ' + noun, 'design_delete_own' if category == 'design' else 'file_delete' if category == 'reference' else 'authenticated'), ('delete_all', 'Delete all authorized eligible ' + noun, 'catalog' if category == 'measurement' else 'file_delete')])
activities('design', [('resubmit_own', 'Resubmit own rejected designs', 'design_upload'), ('resubmit_all', 'Resubmit authorized rejected designs', 'superuser'), ('history', 'View design review/revision history', 'design_view', ('design_approval.view',))])
activities('folder', [('view', 'View design folders'), ('create', 'Create design folders', 'assets'),
    ('rename', 'Rename design folders', 'assets'), ('delete_own', 'Delete own eligible folders', 'file_delete'), ('delete_all', 'Delete all authorized eligible folders', 'file_delete')])
activities('design_approval', [('view', 'View authorized design review queue', 'design_view'),
    ('history', 'View approval history', 'design_view', ('design_approval.view',)), ('comment', 'Add review remarks', 'review', ('design_approval.view',)),
    ('voice', 'Record voice remarks', 'review', ('design_approval.comment',)),
    ('approve', 'Approve assigned stage', 'review', ('design_approval.view',)),
    ('reject', 'Reject assigned stage', 'review', ('design_approval.view',))])
activities('color', [('view', 'View colors'), ('create', 'Create colors', 'catalog'), ('edit', 'Edit colors', 'catalog'),
    ('delete', 'Delete colors', 'catalog'), ('submit', 'Submit color proposals'), ('history', 'View color review history'),
    ('approve', 'Approve assigned color stage', 'color_review', ('color.view',)), ('reject', 'Reject assigned color stage', 'color_review', ('color.view',))])
activities('sku', [('view', 'View SKUs'), ('create', 'Create SKUs', 'catalog'), ('edit', 'Edit SKUs', 'catalog'), ('delete', 'Delete SKUs', 'catalog')])
activities('complaint', [('view', 'View authorized complaints'), ('create', 'Register permitted complaint types', 'complaint_create'),
    ('edit', 'Edit eligible complaint reports', 'report_edit'), ('delete', 'Delete authorized complaints', 'erp'),
    ('export', 'Export authorized complaints'), ('media_view', 'View authorized complaint media'),
    ('media_upload', 'Upload complaint media'), ('media_delete', 'Remove eligible complaint media')])
activities('workflow', [('view', 'View authorized approval workspace', 'approvals_view'),
    ('factory_review', 'Submit assigned factory review', 'factory'),
    ('approve', 'Approve assigned complaint stage', 'complaint_review'), ('reject', 'Reject assigned complaint stage', 'complaint_review'),
    ('start', 'Start authorized action execution', 'factory'), ('verify_submit', 'Submit execution for verification', 'factory'),
    ('close', 'Save final execution update', 'factory')])
activities('master', [('view', 'View master settings', 'erp'), ('create', 'Create master settings', 'erp'),
    ('edit', 'Edit master settings', 'erp'), ('delete', 'Delete master settings', 'erp')])
activities('notification', [('view', 'View own notifications'), ('read', 'Mark own notifications read')])
activities('chat', [('view', 'View authorized internal conversations'), ('send', 'Send messages', 'authenticated', ('chat.view',))])
activities('reports', [('pattern_history', 'View pattern activity history'), ('activity', 'View system activity logs', 'erp')])
activities('erp', [('view', 'Open ERP Admin', 'erp'), ('control_tower', 'View Control Tower', 'erp'),
    ('sessions_view', 'View active sessions', 'erp'), ('sessions_terminate', 'Terminate sessions', 'erp')])
activities('users', [('create', 'Create user accounts', 'admin'), ('manage', 'Manage user accounts', 'erp'), ('permissions', 'Manage activity permissions', 'admin'),
    ('groups', 'Manage Django groups', 'admin'), ('password', 'Reset user passwords', 'erp'), ('photo_delete', 'Remove user profile photos', 'erp')])

ADMIN_KEYS = frozenset(key for key, item in REGISTRY.items() if (item.category in ('erp', 'users', 'master', 'reports') and item.policy in ('erp', 'admin')) or (item.category in ('vehicle', 'sku', 'color', 'pattern') and item.policy == 'catalog') or key in ('vehicle.view', 'sku.view', 'color.view', 'pattern.view', 'folder.view', 'folder.create', 'folder.rename'))

def profile(user):
    from management.services.workflow import get_user_profile
    return get_user_profile(user)

def administrative_account(user):
    return bool(user and (user.is_superuser or getattr(profile(user), 'role', '') == R.ADMIN))

def protected_admin(user):
    return bool(user and user.is_authenticated and user.is_active and
                (user.is_superuser or getattr(profile(user), 'role', '') == R.ADMIN))

def self_access_recovery(user):
    """Only active, authenticated Django superusers can recover their own gates."""
    return bool(user and user.is_authenticated and user.is_active and user.is_superuser
                and any(not granted(user, key) for key in ('erp.view', 'users.manage', 'users.permissions')))

def identity(user):
    p = profile(user)
    file_delete = bool(user.has_perm('management.delete_patterndesignimage'))
    if not user.is_active:
        # Display dormant configuration accurately; actual grants still fail closed for inactive users.
        file_delete = bool(user.is_superuser or user.user_permissions.filter(codename='delete_patterndesignimage', content_type__app_label='management').exists() or user.groups.filter(permissions__codename='delete_patterndesignimage', permissions__content_type__app_label='management').exists())
    return {'role': getattr(p, 'role', ''), 'approval_role': getattr(p, 'approval_role', ''), 'is_active': bool(user.is_active),
            'is_staff': bool(user.is_staff), 'is_superuser': bool(user.is_superuser),
            'file_delete': file_delete}

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
    }
    return bool(policies[policy])

def role_defaults(info):
    """Compatibility defaults; optional policy configuration never mutates overrides."""
    defaults = {key: eligible(item.policy, info) for key, item in REGISTRY.items()}
    role_key = info.get('approval_role') if info.get('role') == R.APPROVER else info.get('role')
    changes = getattr(settings, 'ACTIVITY_ROLE_DEFAULTS', {}).get(role_key, {})
    defaults.update({key: value and eligible(REGISTRY[key].policy, info)
                     for key, value in changes.items() if key in REGISTRY and type(value) is bool})
    if info.get('is_superuser') or info.get('role') == R.ADMIN:
        defaults.update({key: True for key in ADMIN_KEYS})
    for item in REGISTRY.values():
        if any(not defaults[dep] for dep in item.requires):
            defaults[item.key] = False
    return defaults

def granted(user, key):
    if key not in REGISTRY or not user or not user.is_authenticated or not user.is_active:
        return False
    cache = getattr(user, '_activity_grants', None)
    if cache is None:
        info = identity(user)
        defaults = role_defaults(info)
        overrides = getattr(profile(user), 'activity_permissions', {}) or {}
        # Explicit grants can extend role eligibility; inherited defaults cannot.
        cache = {name: (overrides[name] == 'allow' if name in overrides else value and eligible(REGISTRY[name].policy, info)) for name, value in defaults.items()}
        user._activity_grants = cache
    return cache[key] and all(granted(user, dependency) for dependency in REGISTRY[key].requires)

def require(user, *keys):
    if not all(granted(user, key) for key in keys):
        raise PermissionDenied(_('This activity is disabled for your account.'))

def scoped(user, resource, action, owner_id):
    own = owner_id is not None and owner_id == user.pk
    if action != 'view' and resource in ('reference', 'design', 'measurement') and not scoped(user, resource, 'view', owner_id):
        return False
    if resource == 'folder' and not granted(user, 'folder.view'):
        return False
    return granted(user, f'{resource}.{action}_all') or (own and granted(user, f'{resource}.{action}_own'))

def visible_files(user, queryset):
    permitted = Q(pk__in=[])
    for resource, condition in [('reference', Q(is_reference=True)), ('design', Q(is_reference=False))]:
        if granted(user, resource + '.view_all'):
            permitted |= condition
        elif granted(user, resource + '.view_own'):
            permitted |= condition & Q(uploaded_by_id=user.pk)
    return queryset.filter(permitted)

def protected_files(queryset):
    return queryset.filter(Q(approval_requests__isnull=False) | Q(approved_at__isnull=False) |
        Q(rejected_at__isnull=False) | Q(approved_by__isnull=False) | Q(rejected_by__isnull=False) |
        Q(is_reference=False, approval_status__in=['approved', 'rejected']))

def deletable(image):
    if image.approved_at or image.rejected_at or image.approved_by_id or image.rejected_by_id or (not image.is_reference and image.approval_status in ('approved', 'rejected')):
        return False
    return not image.approval_requests.exists()

def validate_overrides(data, info, *, superuser_editor=False, existing=None):
    if not isinstance(data, dict) or any(key not in REGISTRY or value not in ('allow', 'deny') for key, value in data.items()):
        raise ValidationError(_('Invalid activity permission keys or values.'))
    protected = info.get('is_superuser') or info.get('role') == R.ADMIN
    defaults = role_defaults(info)
    existing = existing or {}
    if not superuser_editor:
        # Ordinary editors may preserve, but cannot alter or silently remove,
        # a Superuser-managed override outside their editing authority.
        for key in data.keys() | existing.keys():
            locked = protected and key in ADMIN_KEYS or not eligible(REGISTRY[key].policy, info)
            if locked and data.get(key) != existing.get(key):
                raise ValidationError(_('Only a Django superuser may change this protected activity override.'))
    for key, value in data.items():
        if not superuser_editor and protected and key in ADMIN_KEYS and value == 'deny' and existing.get(key) != value:
            raise ValidationError(_('Protected administrative access cannot be removed.'))
        if not superuser_editor and value == 'allow' and not eligible(REGISTRY[key].policy, info) and existing.get(key) != value:
            raise ValidationError(_('An activity grant cannot confer administrative or reviewer authority.'))
    effective = {key: data.get(key, 'allow' if default else 'deny') == 'allow' for key, default in defaults.items()}
    for key, value in effective.items():
        if value and any(not effective[dep] for dep in REGISTRY[key].requires):
            raise ValidationError(_('Enable the required view/remarks activity before its dependent actions.'))
    # Canonical tri-state representation: absence means inherit.
    return {key: value for key, value in data.items() if (value == 'allow') != defaults[key]}


def lock_eligible_files(queryset, user=None):
    """Call within the mutation transaction; review submission locks the same rows."""
    images = list(queryset.select_for_update(of=('self',)))
    if user is not None:
        from management.views import _visible_design_images_qs
        visible = _visible_design_images_qs(user, queryset).values('pk')
        if queryset.exclude(pk__in=visible).exists():
            raise PermissionDenied(_('Container deletion cannot bypass record visibility.'))
        permitted = Q(pk__in=[])
        for resource, condition in [('reference', Q(is_reference=True)), ('design', Q(is_reference=False))]:
            if granted(user, resource + '.delete_all'):
                permitted |= condition
            elif granted(user, resource + '.delete_own'):
                permitted |= condition & Q(uploaded_by_id=user.pk)
        if queryset.exclude(permitted).exists():
            raise PermissionDenied(_('Container deletion cannot bypass individual file permissions.'))
    if protected_files(queryset).exists():
        raise PermissionDenied(_('Submitted, reviewed or approved files cannot be deleted.'))
    return images


def protect_vehicle_files(vehicle_ids, user=None):
    from management.models import PatternDesignFolder, PatternDesignImage, YearRange
    list(YearRange.objects.filter(pk__in=vehicle_ids).select_for_update().values_list('pk', flat=True))
    list(PatternDesignFolder.objects.filter(vehicle_id__in=vehicle_ids).select_for_update().values_list('pk', flat=True))
    return lock_eligible_files(PatternDesignImage.objects.filter(Q(vehicle_id__in=vehicle_ids) | Q(folder__vehicle_id__in=vehicle_ids)), user)
