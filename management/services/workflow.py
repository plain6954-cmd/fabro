from django.contrib.auth.models import User
from django.db import transaction
from django.db.models import Count, Q
from django.utils import timezone

from management.models import (
    ApprovalRoles,
    ApprovalStages,
    Complaint,
    ComplaintApproval,
    ComplaintEditLog,
    ComplaintTimeline,
    ComplaintTypes,
    DecisionStatuses,
    FactoryPriorities,
    Notification,
    UserProfile,
    WorkflowRoles,
    WorkflowStatuses,
    infer_complaint_type,
)


REPORT_EDITABLE_WORKFLOW_STATUSES = {
    WorkflowStatuses.SUBMITTED,
    WorkflowStatuses.ASSIGNED_TO_FACTORY,
    WorkflowStatuses.FACTORY_REVIEW,
    WorkflowStatuses.REWORK_REQUIRED,
}

REPORT_FIELD_LABELS = {
    'channel': 'Channel',
    'person': 'Reported By',
    'series': 'Series',
    'material': 'Material',
    'sku': 'SKU',
    'brand': 'Brand',
    'model': 'Model',
    'sub_model': 'Sub Model',
    'year': 'Year',
    'priority': 'Reporter Priority',
    'complaint_description': 'Complaint Description',
    'batch_order': 'Batch Order',
    'updated_order_no': 'Update Order Number',
}
REPORT_EDITABLE_FIELDS = frozenset(REPORT_FIELD_LABELS)

JOURNEY_STAGES = (
    ('reported', 'Submitted'),
    ('factory', 'Factory Review'),
    ('approval', 'Approval'),
    ('action', 'Action'),
    ('final', 'Final Update'),
    ('closed', 'Closed'),
)

JOURNEY_STAGE_BY_STATUS = {
    WorkflowStatuses.SUBMITTED: 0,
    WorkflowStatuses.ASSIGNED_TO_FACTORY: 1,
    WorkflowStatuses.FACTORY_REVIEW: 1,
    WorkflowStatuses.AWAITING_APPROVAL: 2,
    WorkflowStatuses.PARTIALLY_APPROVED: 2,
    WorkflowStatuses.REWORK_REQUIRED: 2,
    WorkflowStatuses.APPROVED: 3,
    WorkflowStatuses.ACTION_IN_PROGRESS: 3,
    WorkflowStatuses.PENDING_FINAL_UPDATE: 4,
    WorkflowStatuses.CLOSED: 5,
}


def complaint_journey_steps(complaint):
    """Return the compact, presentation-ready progress stages for a complaint."""
    current_index = JOURNEY_STAGE_BY_STATUS.get(complaint.workflow_status)
    if current_index is None:
        if complaint.closed_at:
            current_index = 5
        elif complaint.fully_approved_at:
            current_index = 3
        elif complaint.last_submitted_for_approval_at:
            current_index = 2
        elif complaint.factory_review_started_at or complaint.assigned_factory_executive_id:
            current_index = 1
        else:
            current_index = 0

    is_rework = complaint.workflow_status == WorkflowStatuses.REWORK_REQUIRED
    is_closed = complaint.workflow_status == WorkflowStatuses.CLOSED
    steps = []
    for index, (key, label) in enumerate(JOURNEY_STAGES):
        state = 'pending'
        if index < current_index or (is_closed and index == current_index):
            state = 'completed'
        elif index == current_index:
            state = 'attention' if is_rework else 'current'
        steps.append({'key': key, 'label': label, 'state': state})
    return steps


def get_user_profile(user):
    if not user or not user.is_authenticated:
        return None
    if not hasattr(user, '_workflow_profile'):
        profile, _ = UserProfile.objects.get_or_create(user=user)
        user._workflow_profile = profile
    return user._workflow_profile


def is_country_executive(user):
    profile = get_user_profile(user)
    return bool(profile and profile.role == WorkflowRoles.COUNTRY_EXECUTIVE)


def is_factory_executive(user):
    profile = get_user_profile(user)
    return bool(
        profile and (
            profile.role == WorkflowRoles.FACTORY_EXECUTIVE
            or profile.can_receive_factory_assignments
        )
    )


def is_workflow_admin(user):
    if not user or not user.is_authenticated:
        return False
    profile = get_user_profile(user)
    return bool(
        user.is_superuser
        or (profile and (
            profile.role == WorkflowRoles.ADMIN
            or profile.approval_role == ApprovalRoles.MD
        ))
    )


def can_user_manage_catalog(user):
    """Catalog writes are limited to Django staff and workflow administrators."""
    return bool(
        user
        and user.is_authenticated
        and (user.is_staff or is_workflow_admin(user))
    )


def can_user_create_complaint(user):
    """Only reporting/execution roles and workflow administrators create reports."""
    if not user or not user.is_authenticated:
        return False
    if is_workflow_admin(user):
        return True
    profile = get_user_profile(user)
    return bool(
        profile
        and profile.role in {
            WorkflowRoles.COUNTRY_EXECUTIVE,
            WorkflowRoles.FACTORY_EXECUTIVE,
        }
    )


def can_user_view_approvals(user):
    """
    Approvals window access is granted to:
    - Country Executive (for their assigned country)
    - All Approvers (PM, OM, CAD, ED, MD)
    - Workflow Admin / Superuser
    - Factory Executive
    Normal viewer (factory_viewer) is restricted.
    """
    if not user or not user.is_authenticated:
        return False
    if is_workflow_admin(user):
        return True
    profile = get_user_profile(user)
    if not profile:
        return False
    return profile.role in {
        WorkflowRoles.COUNTRY_EXECUTIVE,
        WorkflowRoles.APPROVER,
        WorkflowRoles.ADMIN,
        WorkflowRoles.FACTORY_EXECUTIVE,
    }


def visible_complaints_for_user(user, queryset=None):
    if queryset is None:
        queryset = Complaint.objects.all()
    if is_workflow_admin(user):
        return queryset

    profile = get_user_profile(user)
    if not profile:
        return queryset.none()

    if profile.role == WorkflowRoles.COUNTRY_EXECUTIVE:
        if not profile.country_id:
            return queryset.none()
        return queryset.filter(
            country_id=profile.country_id,
            complaint_type__in=[ComplaintTypes.PATTERN, ComplaintTypes.PRODUCTION],
        )

    if profile.role == WorkflowRoles.FACTORY_EXECUTIVE:
        return queryset.filter(assigned_factory_executive_id=user.id)

    if profile.role in {WorkflowRoles.FACTORY_VIEWER, WorkflowRoles.APPROVER}:
        return queryset

    # A newly created or malformed role must fail closed until configured.
    return queryset.none()


def can_user_edit_report_step(user, complaint):
    if not user or not user.is_authenticated:
        return False

    if (
        complaint.status == 'Closed'
        or complaint.workflow_status not in REPORT_EDITABLE_WORKFLOW_STATUSES
    ):
        return False

    if is_workflow_admin(user):
        return True

    profile = get_user_profile(user)
    if not profile:
        return False

    if profile.role != WorkflowRoles.COUNTRY_EXECUTIVE:
        return False

    if complaint.complaint_type == ComplaintTypes.LINE:
        return False

    if not profile.country_id or complaint.country_id != profile.country_id:
        return False

    return True


def _display_change_value(value):
    if value is None:
        return ''
    if hasattr(value, 'isoformat'):
        return value.isoformat()
    return str(value)


@transaction.atomic
def record_report_edit(complaint, user, changes=None, media_added=0, media_removed=0):
    changes = changes or {}
    descriptions = []

    for field_name, values in changes.items():
        if field_name not in REPORT_EDITABLE_FIELDS:
            continue
        old_value, new_value = values
        old_display = _display_change_value(old_value)
        new_display = _display_change_value(new_value)
        if old_display == new_display:
            continue
        ComplaintEditLog.objects.create(
            complaint=complaint,
            edited_by=user,
            field_name=field_name,
            old_value=old_display,
            new_value=new_display,
        )
        descriptions.append(
            f'{REPORT_FIELD_LABELS[field_name]}: {old_display or "-"} -> {new_display or "-"}'
        )

    if media_added:
        ComplaintEditLog.objects.create(
            complaint=complaint,
            edited_by=user,
            field_name='media_added',
            old_value='',
            new_value=str(media_added),
        )
        descriptions.append(f'Added {media_added} media file(s)')

    if media_removed:
        ComplaintEditLog.objects.create(
            complaint=complaint,
            edited_by=user,
            field_name='media_removed',
            old_value=str(media_removed),
            new_value='',
        )
        descriptions.append(f'Removed {media_removed} media file(s)')

    if not descriptions:
        return None

    event = add_timeline_event(
        complaint,
        'report_updated',
        'Complaint report updated',
        '; '.join(descriptions),
        user,
    )
    if (
        complaint.assigned_factory_executive_id
        and complaint.assigned_factory_executive_id != getattr(user, 'id', None)
    ):
        notify_user(
            complaint.assigned_factory_executive,
            'Complaint report updated',
            f'{complaint.complaint_id} was edited. Review the updated report and media before continuing.',
            complaint=complaint,
            notification_type='report_updated',
        )
    return event


def can_user_review_factory_step(user, complaint):
    if not user or not user.is_authenticated:
        return False
    if is_workflow_admin(user):
        return True
    if not is_factory_executive(user):
        return False
    if complaint.assigned_factory_executive_id:
        return complaint.assigned_factory_executive_id == user.id
    return True


def can_start_factory_review(complaint):
    return complaint.status != 'Closed' and complaint.workflow_status in [
        WorkflowStatuses.SUBMITTED,
        WorkflowStatuses.ASSIGNED_TO_FACTORY,
        WorkflowStatuses.FACTORY_REVIEW,
        WorkflowStatuses.REWORK_REQUIRED,
    ]


def mark_factory_review_started(complaint, user=None):
    update_fields = []
    if not complaint.factory_review_started_at:
        complaint.factory_review_started_at = timezone.now()
        update_fields.append('factory_review_started_at')
    if complaint.workflow_status in [WorkflowStatuses.SUBMITTED, WorkflowStatuses.ASSIGNED_TO_FACTORY]:
        complaint.workflow_status = WorkflowStatuses.FACTORY_REVIEW
        update_fields.append('workflow_status')
    if update_fields:
        complaint.save(update_fields=update_fields)
        add_timeline_event(
            complaint,
            'factory_review_started',
            'Factory review started',
            'Factory executive opened the review step.',
            user,
        )
    return complaint


def prepare_complaint_for_create(complaint, user):
    complaint.created_by = user if user and user.is_authenticated else None
    valid_types = {value for value, _ in ComplaintTypes.CHOICES}
    if complaint.complaint_type not in valid_types and complaint.case_sub_category_id:
        complaint.complaint_type = infer_complaint_type(complaint.case_sub_category.name)
    if is_country_executive(user):
        profile = get_user_profile(user)
        if not profile or not profile.country_id:
            raise PermissionError('Your account must be assigned to a country before reporting complaints.')
        if complaint.complaint_type == ComplaintTypes.LINE:
            raise PermissionError('Country executives cannot create line complaints.')
        complaint.country = profile.country
    complaint.workflow_status = WorkflowStatuses.SUBMITTED
    return complaint


def assign_factory_executive(complaint):
    candidates = User.objects.filter(
        is_active=True,
        workflow_profile__role=WorkflowRoles.FACTORY_EXECUTIVE,
    ) | User.objects.filter(
        is_active=True,
        workflow_profile__can_receive_factory_assignments=True,
    )
    candidates = candidates.distinct().annotate(
        open_assignment_count=Count(
            'assigned_factory_complaints',
            filter=~Q(assigned_factory_complaints__workflow_status=WorkflowStatuses.CLOSED),
        )
    ).order_by('open_assignment_count', 'id')

    assignee = candidates.first()
    if assignee:
        complaint.assigned_factory_executive = assignee
        complaint.workflow_status = WorkflowStatuses.ASSIGNED_TO_FACTORY
        complaint.save(update_fields=['assigned_factory_executive', 'workflow_status'])
    return assignee


def add_timeline_event(complaint, action_type, title, description='', user=None):
    return ComplaintTimeline.objects.create(
        complaint=complaint,
        action_type=action_type,
        title=title,
        description=description,
        user=user if user and user.is_authenticated else None,
    )


def notify_user(recipient, title, message='', complaint=None, notification_type='workflow'):
    if not recipient:
        return None
    return Notification.objects.create(
        recipient=recipient,
        complaint=complaint,
        title=title,
        message=message,
        notification_type=notification_type,
    )


def notify_factory_assignment(complaint, assignee):
    if not assignee:
        return
    notify_user(
        assignee,
        'New complaint assigned',
        f'{complaint.complaint_id} is ready for factory review.',
        complaint=complaint,
        notification_type='assignment',
    )


def required_approval_roles(priority):
    normalized = (priority or '').strip().lower()
    roles = [ApprovalRoles.PM, ApprovalRoles.OM, ApprovalRoles.CAD]
    if normalized in [FactoryPriorities.MEDIUM, 'medium', 'high']:
        roles.append(ApprovalRoles.ED)
    if normalized in [FactoryPriorities.TOP, 'top']:
        roles.extend([ApprovalRoles.ED, ApprovalRoles.MD])
    return list(dict.fromkeys(roles))


def find_approver_for_role(role):
    profiles = UserProfile.objects.filter(
        role=WorkflowRoles.APPROVER,
        approval_role=role,
        user__is_active=True,
    ).select_related('user').order_by('user_id')
    configured = list(profiles[:2])
    if len(configured) > 1:
        raise ValueError(
            f'Multiple active approver accounts are configured for {role}. '
            'Keep exactly one active account for each approval role.'
        )
    return configured[0].user if configured else None


def latest_approval_round_number(complaint):
    if hasattr(complaint, '_prefetched_objects_cache') and 'approvals' in complaint._prefetched_objects_cache:
        approvals = complaint._prefetched_objects_cache['approvals']
        if approvals:
            return max(a.approval_round for a in approvals)
        return 0
    latest = complaint.approvals.order_by('-approval_round').values_list('approval_round', flat=True).first()
    return latest or 0


def current_round_approvals(complaint):
    approval_round = latest_approval_round_number(complaint)
    if not approval_round:
        if hasattr(complaint, '_prefetched_objects_cache') and 'approvals' in complaint._prefetched_objects_cache:
            return []
        return ComplaintApproval.objects.none()

    if hasattr(complaint, '_prefetched_objects_cache') and 'approvals' in complaint._prefetched_objects_cache:
        return [a for a in complaint._prefetched_objects_cache['approvals'] if a.approval_round == approval_round and a.required]

    return complaint.approvals.filter(
        approval_round=approval_round,
        required=True,
    ).select_related('approver_user', 'trigger_approval', 'trigger_approval__approver_user')


def approval_progress(complaint):
    approvals = list(current_round_approvals(complaint))
    decided = [approval for approval in approvals if approval.status != DecisionStatuses.PENDING]
    return {
        'round': approvals[0].approval_round if approvals else 0,
        'stage': approvals[0].review_stage if approvals else ApprovalStages.INITIAL,
        'total': len(approvals),
        'decided': len(decided),
        'approved': sum(approval.status == DecisionStatuses.APPROVED for approval in approvals),
        'rejected': sum(approval.status == DecisionStatuses.REJECTED for approval in approvals),
        'pending': sum(approval.status == DecisionStatuses.PENDING for approval in approvals),
        'approvals': approvals,
    }


def get_user_current_approval(user, complaint):
    if not user or not user.is_authenticated:
        return None
    approval_round = latest_approval_round_number(complaint)
    if not approval_round:
        return None

    if hasattr(complaint, '_prefetched_objects_cache') and 'approvals' in complaint._prefetched_objects_cache:
        for a in complaint._prefetched_objects_cache['approvals']:
            if a.approval_round == approval_round and a.approver_user_id == user.id and a.required:
                return a
        return None

    return complaint.approvals.filter(
        approval_round=approval_round,
        approver_user=user,
        required=True,
    ).first()


def can_user_decide_approval(user, approval):
    if not user or not user.is_authenticated or not approval:
        return False
    profile = get_user_profile(user)
    if not profile or profile.role != WorkflowRoles.APPROVER:
        return False
    if approval.approver_user_id != user.id or profile.approval_role != approval.approver_role:
        return False
    if approval.complaint.workflow_status not in [
        WorkflowStatuses.AWAITING_APPROVAL,
        WorkflowStatuses.PARTIALLY_APPROVED,
    ]:
        return False
    return approval.approval_round == latest_approval_round_number(approval.complaint)


@transaction.atomic
def create_approval_round(complaint, requested_by=None):
    latest = complaint.approvals.order_by('-approval_round').first()
    if latest and complaint.approvals.filter(
        approval_round=latest.approval_round,
        required=True,
        status=DecisionStatuses.PENDING,
    ).exists():
        raise ValueError('The current approval round is still in progress.')
    approval_round = latest.approval_round + 1 if latest else 1

    required_roles = required_approval_roles(complaint.factory_priority or complaint.priority)
    approvers = {role: find_approver_for_role(role) for role in required_roles}
    missing_roles = [role for role, approver in approvers.items() if not approver]
    if missing_roles:
        raise ValueError(
            f"Approval accounts are not configured for: {', '.join(missing_roles)}. "
            'Ask an administrator to assign these workflow roles.'
        )

    approvals = []
    for role in required_roles:
        approvals.append(ComplaintApproval.objects.create(
            complaint=complaint,
            approval_round=approval_round,
            review_stage=ApprovalStages.INITIAL,
            approver_role=role,
            approver_user=approvers[role],
            status=DecisionStatuses.PENDING,
            required=True,
        ))

    complaint.workflow_status = WorkflowStatuses.AWAITING_APPROVAL
    complaint.save(update_fields=['workflow_status'])

    add_timeline_event(
        complaint,
        'approval_requested',
        'Approval requested',
        'Factory review was submitted for parallel approval.',
        requested_by,
    )

    for approval in approvals:
        notify_user(
            approval.approver_user,
            'Complaint waiting for approval',
            f'{complaint.complaint_id} requires {approval.approver_role} approval.',
            complaint=complaint,
            notification_type='approval',
        )

    return approvals


def _create_reconsideration_round(complaint, rejected_approval, approvals):
    other_approvals = [
        approval for approval in approvals
        if approval.approver_role != rejected_approval.approver_role
    ]
    if not other_approvals:
        raise ValueError('No other required approvers are configured for reconsideration.')

    missing_roles = [
        approval.approver_role for approval in other_approvals
        if not approval.approver_user_id
    ]
    if missing_roles:
        raise ValueError(
            f"Reconsideration accounts are not configured for: {', '.join(missing_roles)}."
        )

    now = timezone.now()
    ComplaintApproval.objects.filter(
        complaint=complaint,
        approval_round=rejected_approval.approval_round,
        status=DecisionStatuses.PENDING,
    ).update(status=DecisionStatuses.SUPERSEDED, decided_at=now)

    reconsideration_round = latest_approval_round_number(complaint) + 1
    reconsideration_approvals = [
        ComplaintApproval.objects.create(
            complaint=complaint,
            approval_round=reconsideration_round,
            review_stage=ApprovalStages.RECONSIDERATION,
            trigger_approval=rejected_approval,
            approver_role=approval.approver_role,
            approver_user=approval.approver_user,
            status=DecisionStatuses.PENDING,
            required=True,
        )
        for approval in other_approvals
    ]

    complaint.workflow_status = WorkflowStatuses.AWAITING_APPROVAL
    complaint.fully_approved_at = None
    complaint.save(update_fields=['workflow_status', 'fully_approved_at'])

    reason = rejected_approval.comment or 'No rejection reason was provided.'
    add_timeline_event(
        complaint,
        'reconsideration_requested',
        'Rejection reconsideration requested',
        (
            f'{rejected_approval.approver_role} rejected the factory review. '
            f'Every other required approver must reconsider it. Reason: {reason}'
        ),
        rejected_approval.approver_user,
    )
    for approval in reconsideration_approvals:
        notify_user(
            approval.approver_user,
            'Rejection requires reconsideration',
            (
                f'{rejected_approval.approver_role} rejected {complaint.complaint_id}. '
                f'Reason: {reason} Review the complaint again and choose whether to '
                'proceed or return it for rework.'
            ),
            complaint=complaint,
            notification_type='approval_reconsideration',
        )
    return reconsideration_approvals


def _resolve_completed_approval_round(complaint, approvals):
    if not approvals:
        return 'pending'

    review_stage = approvals[0].review_stage
    rejected = [approval for approval in approvals if approval.status == DecisionStatuses.REJECTED]

    if review_stage == ApprovalStages.INITIAL and rejected:
        _create_reconsideration_round(complaint, rejected[0], approvals)
        return 'reconsideration'

    pending = [approval for approval in approvals if approval.status == DecisionStatuses.PENDING]
    if pending:
        next_status = WorkflowStatuses.PARTIALLY_APPROVED
        if complaint.workflow_status != next_status:
            complaint.workflow_status = next_status
            complaint.save(update_fields=['workflow_status'])
        return 'pending'

    if rejected:
        complaint.workflow_status = WorkflowStatuses.REWORK_REQUIRED
        complaint.fully_approved_at = None
        complaint.save(update_fields=['workflow_status', 'fully_approved_at'])
        rejected_roles = ', '.join(approval.approver_role for approval in rejected)
        add_timeline_event(
            complaint,
            'approval_round_rejected',
            'Reconsideration completed - rework required',
            f'All reconsideration reviews are complete. Rework requested by: {rejected_roles}.',
        )
        notify_user(
            complaint.assigned_factory_executive,
            'Complaint returned for rework',
            f'{complaint.complaint_id} completed reconsideration and requires rework. Review every approver comment.',
            complaint=complaint,
            notification_type='rework',
        )
        return 'rejected'

    complaint.workflow_status = WorkflowStatuses.APPROVED
    complaint.fully_approved_at = timezone.now()
    complaint.save(update_fields=['workflow_status', 'fully_approved_at'])
    add_timeline_event(
        complaint,
        'fully_approved',
        'Green light - ready to go',
        (
            'Every other required approver chose to proceed after reconsideration.'
            if review_stage == ApprovalStages.RECONSIDERATION
            else 'Every required approver approved the factory action plan.'
        ),
    )
    notify_user(
        complaint.assigned_factory_executive,
        'Green light - ready to go',
        f'{complaint.complaint_id} is fully approved. Proceed with the factory action plan.',
        complaint=complaint,
        notification_type='fully_approved',
    )
    return 'approved'


@transaction.atomic
def record_approval_decision(approval_id, user, decision, comment=''):
    decision = (decision or '').strip().lower()
    comment = (comment or '').strip()
    if decision not in [DecisionStatuses.APPROVED, DecisionStatuses.REJECTED]:
        raise ValueError('Choose Approve or Reject.')
    if decision == DecisionStatuses.REJECTED and not comment:
        raise ValueError('A review comment is required when rejecting an approval.')

    approval_reference = ComplaintApproval.objects.only('complaint_id').filter(pk=approval_id).first()
    if not approval_reference:
        raise ValueError('Approval request was not found.')

    complaint = Complaint.objects.select_for_update().get(pk=approval_reference.complaint_id)
    approvals = list(
        # Lock only approval rows. Joining the nullable approver_user relation here
        # produces an outer join that PostgreSQL cannot lock with FOR UPDATE.
        ComplaintApproval.objects.select_for_update().filter(
            complaint=complaint,
            approval_round=latest_approval_round_number(complaint),
            required=True,
        )
    )
    approval = next((item for item in approvals if item.pk == approval_id), None)
    if not can_user_decide_approval(user, approval):
        raise PermissionError('You are not allowed to decide this approval request.')

    old_status = approval.status
    old_comment = approval.comment
    approval.status = decision
    approval.comment = comment
    approval.decided_at = timezone.now()
    approval.save(update_fields=['status', 'comment', 'decided_at'])

    action_word = 'updated' if old_status != DecisionStatuses.PENDING else 'submitted'
    if approval.review_stage == ApprovalStages.RECONSIDERATION:
        decision_label = 'chose to proceed' if decision == DecisionStatuses.APPROVED else 'requested rework'
        description = f'{approval.approver_role} {decision_label} during reconsideration.'
    else:
        description = f'{approval.approver_role} {decision} the factory review.'
    if comment:
        description += f' Comment: {comment}'
    add_timeline_event(
        complaint,
        f'approval_{action_word}',
        f'{approval.approver_role} review {action_word}',
        description,
        user,
    )

    ComplaintEditLog.objects.create(
        complaint=complaint,
        edited_by=user,
        field_name=f'approval_round_{approval.approval_round}_{approval.approver_role}',
        old_value=f'{old_status}: {old_comment}'.strip(),
        new_value=f'{decision}: {comment}'.strip(),
    )
    notify_user(
        complaint.assigned_factory_executive,
        f'{approval.approver_role} review {action_word}',
        f'{approval.approver_role} marked {complaint.complaint_id} as {decision}.',
        complaint=complaint,
        notification_type='approval_decision',
    )

    outcome = _resolve_completed_approval_round(complaint, approvals)
    return approval, outcome


def can_user_execute_action(user, complaint):
    if not user or not user.is_authenticated:
        return False
    if not (is_workflow_admin(user) or complaint.assigned_factory_executive_id == user.id):
        return False
    return complaint.workflow_status in [
        WorkflowStatuses.APPROVED,
        WorkflowStatuses.ACTION_IN_PROGRESS,
    ]


@transaction.atomic
def start_action_execution(complaint, user):
    complaint = Complaint.objects.select_for_update().get(pk=complaint.pk)
    if not can_user_execute_action(user, complaint):
        raise PermissionError('You are not allowed to execute this complaint action plan.')
    if complaint.workflow_status == WorkflowStatuses.ACTION_IN_PROGRESS:
        return complaint
    if complaint.workflow_status != WorkflowStatuses.APPROVED:
        raise ValueError('This complaint has not received full approval.')

    complaint.workflow_status = WorkflowStatuses.ACTION_IN_PROGRESS
    complaint.save(update_fields=['workflow_status'])
    add_timeline_event(
        complaint,
        'action_started',
        'Approved action plan started',
        'The assigned factory executive started executing the approved action plan.',
        user,
    )
    return complaint


@transaction.atomic
def close_complaint_after_execution(complaint, user, cad_date, container_number=''):
    complaint = Complaint.objects.select_for_update().get(pk=complaint.pk)
    if not can_user_execute_action(user, complaint):
        raise PermissionError('You are not allowed to close this complaint.')
    if complaint.workflow_status != WorkflowStatuses.ACTION_IN_PROGRESS:
        raise ValueError('Start the approved action plan before submitting final updates.')
    if not cad_date:
        raise ValueError('CAD Updated Date is mandatory.')
    if cad_date > timezone.localdate():
        raise ValueError('CAD Updated Date cannot be in the future.')

    container_number = (container_number or '').strip()
    if complaint.complaint_type != ComplaintTypes.LINE and not container_number:
        raise ValueError('New Production Container Number is mandatory.')

    complaint.cad_date = cad_date
    complaint.production_updates_container = container_number if complaint.complaint_type != ComplaintTypes.LINE else ''
    complaint.workflow_status = WorkflowStatuses.CLOSED
    complaint.status = 'Closed'
    complaint.closed_at = timezone.now()
    complaint.closed_by = user
    complaint.save(update_fields=[
        'cad_date',
        'production_updates_container',
        'workflow_status',
        'status',
        'closed_at',
        'closed_by',
    ])

    final_description = f'CAD updated on {cad_date}.'
    if container_number:
        final_description += f' New production container: {container_number}.'
    add_timeline_event(
        complaint,
        'closed',
        'Complaint resolved and closed',
        final_description,
        user,
    )
    notify_user(
        complaint.created_by,
        'Complaint resolved',
        f'{complaint.complaint_id} has been resolved and closed.',
        complaint=complaint,
        notification_type='closed',
    )
    return complaint


@transaction.atomic
def submit_factory_review(complaint, user, reason, action_plan, priority):
    complaint = Complaint.objects.select_for_update().get(pk=complaint.pk)
    if not can_user_review_factory_step(user, complaint):
        raise PermissionError('You are not allowed to review this complaint.')
    if not can_start_factory_review(complaint):
        raise ValueError('This complaint is not ready for factory review.')
    reason = (reason or '').strip()
    action_plan = (action_plan or '').strip()
    priority = (priority or '').strip().lower()
    valid_priorities = {value for value, _ in FactoryPriorities.CHOICES}
    if not reason or not action_plan or not priority:
        raise ValueError('Factory reason, action plan, and priority are mandatory.')
    if priority not in valid_priorities:
        raise ValueError('Choose a valid factory priority.')

    if not complaint.factory_review_started_at:
        complaint.factory_review_started_at = timezone.now()

    complaint.factory_reason = reason
    complaint.factory_action_plan = action_plan
    complaint.factory_priority = priority
    complaint.justification_from_factory = reason
    complaint.action_from_factory = action_plan
    complaint.last_submitted_for_approval_at = timezone.now()
    complaint.workflow_status = WorkflowStatuses.AWAITING_APPROVAL
    complaint.save(update_fields=[
        'factory_review_started_at',
        'factory_reason',
        'factory_action_plan',
        'factory_priority',
        'justification_from_factory',
        'action_from_factory',
        'last_submitted_for_approval_at',
        'workflow_status',
    ])

    add_timeline_event(
        complaint,
        'factory_review_submitted',
        'Factory review submitted',
        'Real reason, action plan, and priority were submitted for approval.',
        user,
    )
    approvals = create_approval_round(complaint, requested_by=user)

    if complaint.created_by_id:
        notify_user(
            complaint.created_by,
            'Factory review submitted',
            f'{complaint.complaint_id} has been sent for approval.',
            complaint=complaint,
            notification_type='factory_review',
        )

    return approvals


@transaction.atomic
def initialize_created_complaint(complaint, user):
    assignee = assign_factory_executive(complaint)
    add_timeline_event(
        complaint,
        'created',
        'Complaint submitted',
        f'{complaint.get_complaint_type_display()} was submitted.',
        user,
    )
    if assignee:
        add_timeline_event(
            complaint,
            'assigned',
            'Assigned to factory executive',
            f'Assigned to {assignee.get_username()}.',
            user,
        )
        notify_factory_assignment(complaint, assignee)
    return complaint
