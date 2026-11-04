from .models import WorkflowRoles, ChatMessage, Complaint, WorkflowStatuses, ComplaintApproval, DecisionStatuses
from django.utils.translation import get_language
from django.conf import settings
from django.core.cache import cache
from .services.workflow import (
    can_user_create_complaint,
    can_user_manage_catalog,
    can_user_manage_design_assets,
    can_user_manage_drive_links,
    can_user_view_approvals,
    get_user_profile,
    is_workflow_admin,
    visible_complaints_for_user,
)
from .services.cache_versions import cache_version


def workflow_access(request):
    is_htmx_request = request.headers.get('HX-Request') == 'true'
    user = getattr(request, 'user', None)
    if not user or not user.is_authenticated:
        return {'is_htmx_request': is_htmx_request}

    from .services.activity_permissions import granted, REGISTRY
    from .services.activity_sync import access_snapshot
    snapshot = access_snapshot(user)
    activity_map = {}
    for key in REGISTRY:
        category, action = key.split('.', 1)
        activity_map.setdefault(category, {})[action] = granted(user, key)
    profile = getattr(request, '_user_profile', None)
    if profile is None:
        profile = get_user_profile(user)
        request._user_profile = profile
    role_label = getattr(profile, 'display_role', '') if profile else ('Admin' if user.is_superuser else 'User')
    supplied = getattr(request, '_fabro_badges', {})
    badge_key = f'fabro:badges:v{cache_version()}:user:{user.pk}'
    cached_badges = cache.get(badge_key) or {}
    unread_chat_count = supplied.get('unread_chat_count', cached_badges.get('unread_chat_count'))
    if unread_chat_count is None:
        unread_chat_count = ChatMessage.objects.filter(recipient=user, is_read=False).count()
    
    can_view_approvals_flag = can_user_view_approvals(user)
    pending_approvals_count = supplied.get('pending_approvals_count', cached_badges.get('pending_approvals_count'))
    if not can_view_approvals_flag or (profile and profile.role == WorkflowRoles.FREELANCE_3D_DESIGNER):
        pending_approvals_count = 0
    elif pending_approvals_count is None:
        if profile and profile.role == WorkflowRoles.APPROVER:
            pending_approvals_count = ComplaintApproval.objects.filter(
                approver_user=user,
                status=DecisionStatuses.PENDING,
                complaint__workflow_status__in=[
                    WorkflowStatuses.AWAITING_APPROVAL,
                    WorkflowStatuses.PARTIALLY_APPROVED,
                    WorkflowStatuses.AWAITING_EXECUTION_VERIFICATION,
                    WorkflowStatuses.EXECUTION_PARTIALLY_VERIFIED,
                ],
            ).count()
        else:
            pending_approvals_count = visible_complaints_for_user(
                user,
                Complaint.objects.filter(
                    workflow_status__in=[
                        WorkflowStatuses.AWAITING_APPROVAL,
                        WorkflowStatuses.PARTIALLY_APPROVED,
                        WorkflowStatuses.AWAITING_EXECUTION_VERIFICATION,
                        WorkflowStatuses.EXECUTION_PARTIALLY_VERIFIED,
                    ]
                )
            ).count()
    badges = {
        'unread_chat_count': unread_chat_count,
        'pending_approvals_count': pending_approvals_count,
    }
    # Do not renew stale values indefinitely on every page visit.
    if badges != cached_badges:
        cache.set(badge_key, badges, settings.BADGE_CACHE_TTL)

    return {
        'activities': activity_map,
        'activity_data': snapshot['permissions'],
        'activity_sync': {key: snapshot[key] for key in ('user_id', 'version', 'context_version')},
        'is_htmx_request': is_htmx_request,
        'workflow_profile': profile,
        'workflow_role_label': role_label,
        'can_create_complaint': can_user_create_complaint(user),
        'can_manage_catalog': can_user_manage_catalog(user),
        'can_manage_design_assets': can_user_manage_design_assets(user),
        'can_manage_drive_links': can_user_manage_drive_links(user),
        'is_designer_freelancer': bool(
            profile and profile.role == WorkflowRoles.FREELANCE_3D_DESIGNER
        ),
        'can_manage_workflow': is_workflow_admin(user),
        'is_workflow_approver': bool(
            profile and profile.role == WorkflowRoles.APPROVER
        ),
        'can_view_approvals': can_view_approvals_flag,
        'pending_approvals_count': pending_approvals_count,
        'unread_chat_count': unread_chat_count,
        'current_language': get_language() or 'en',
        'portal_languages': [
            ('en', 'English'),
            ('ar', 'العربية'),
            ('hi', 'हिन्दी'),
        ],
    }
