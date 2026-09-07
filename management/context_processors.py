from .models import WorkflowRoles, ChatMessage, Complaint, WorkflowStatuses, ComplaintApproval, DecisionStatuses
from django.utils.translation import get_language
from django.conf import settings
from django.core.cache import cache
from .services.workflow import (
    can_user_create_complaint,
    can_user_manage_catalog,
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

    profile = get_user_profile(user)
    role_label = dict(WorkflowRoles.CHOICES).get(
        getattr(profile, 'role', ''),
        'User',
    )
    supplied = getattr(request, '_fabro_badges', {})
    badge_key = f'fabro:badges:v{cache_version()}:user:{user.pk}'
    cached_badges = cache.get(badge_key) or {}
    unread_chat_count = supplied.get('unread_chat_count', cached_badges.get('unread_chat_count'))
    if unread_chat_count is None:
        unread_chat_count = ChatMessage.objects.filter(recipient=user, is_read=False).count()
    
    can_view_approvals_flag = can_user_view_approvals(user)
    pending_approvals_count = supplied.get('pending_approvals_count', cached_badges.get('pending_approvals_count'))
    if not can_view_approvals_flag:
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
    cache.set(badge_key, {
        'unread_chat_count': unread_chat_count,
        'pending_approvals_count': pending_approvals_count,
    }, settings.BADGE_CACHE_TTL)

    return {
        'is_htmx_request': is_htmx_request,
        'workflow_profile': profile,
        'workflow_role_label': role_label,
        'can_create_complaint': can_user_create_complaint(user),
        'can_manage_catalog': can_user_manage_catalog(user),
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
