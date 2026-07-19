from .models import WorkflowRoles
from .services.workflow import (
    can_user_create_complaint,
    can_user_manage_catalog,
    get_user_profile,
    is_workflow_admin,
)


def workflow_access(request):
    user = getattr(request, 'user', None)
    if not user or not user.is_authenticated:
        return {}

    profile = get_user_profile(user)
    role_label = dict(WorkflowRoles.CHOICES).get(
        getattr(profile, 'role', ''),
        'User',
    )
    return {
        'workflow_profile': profile,
        'workflow_role_label': role_label,
        'can_create_complaint': can_user_create_complaint(user),
        'can_manage_catalog': can_user_manage_catalog(user),
        'can_manage_workflow': is_workflow_admin(user),
        'is_workflow_approver': bool(
            profile and profile.role == WorkflowRoles.APPROVER
        ),
    }
