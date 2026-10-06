import logging
import os
from django.conf import settings
from django.contrib.auth.models import User
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from management.models import (
    ActivityLog,
    ApprovalRoles,
    ChatMessage,
    Notification,
    PatternDesignApproval,
    PatternDesignImage,
    WorkflowRoles,
)
from management.services.push_notifications import send_push_on_commit

logger = logging.getLogger(__name__)


def get_approvers_for_role(approval_role):
    """
    Find active approver accounts configured for the given role (CAD or ED).
    """
    return list(User.objects.filter(
        is_active=True,
        workflow_profile__approval_role=approval_role,
    ).distinct())


def get_latest_approval_request(design_image):
    """
    Retrieve the most recent PatternDesignApproval record for a design image.
    """
    return design_image.approval_requests.order_by('-cycle').first()


def submit_design_for_approval(design_image, designer, is_resubmission=False, comment=''):
    """
    Create or advance an explicit approval request for a PatternDesignImage.
    Both CAD and ED reviewers will receive in-app and Web Push notifications.
    """
    with transaction.atomic():
        if is_resubmission:
            latest = get_latest_approval_request(design_image)
            next_cycle = (latest.cycle + 1) if latest else 1
            approval = PatternDesignApproval.objects.create(
                design_image=design_image,
                designer=designer,
                cycle=next_cycle,
                status='pending',
                cad_status='pending',
                ed_status='pending',
            )
            design_image.approval_status = 'pending'
            design_image.approved_by = None
            design_image.approved_at = None
            design_image.rejected_by = None
            design_image.rejected_at = None
            design_image.rejection_reason = ''
            design_image.save(update_fields=[
                'approval_status', 'approved_by', 'approved_at',
                'rejected_by', 'rejected_at', 'rejection_reason',
            ])
            action_label = 'resubmitted'
        else:
            approval, created = PatternDesignApproval.objects.get_or_create(
                design_image=design_image,
                cycle=1,
                defaults={
                    'designer': designer,
                    'status': 'pending',
                    'cad_status': 'pending',
                    'ed_status': 'pending',
                }
            )
            design_image.approval_status = 'pending'
            design_image.save(update_fields=['approval_status'])
            action_label = 'submitted'

        # Record activity
        ActivityLog.objects.create(
            user=designer,
            action=action_label,
            object_type='Design Image',
            object_name=design_image.title or str(design_image.id),
        )

        # Notify CAD and ED
        cad_users = get_approvers_for_role(ApprovalRoles.CAD)
        ed_users = get_approvers_for_role(ApprovalRoles.ED)

        review_url = f"/design-approvals/{design_image.id}/"
        tag = f"design-approval-{design_image.id}"

        if is_resubmission:
            notif_title = _("Design Resubmitted for Approval")
            notif_body = _("A revised 3D design has been resubmitted for your review.")
        else:
            notif_title = _("New Design Approval Request")
            notif_body = _("A new design is waiting for your approval.")

        # Dispatch CAD notifications
        for cad_user in cad_users:
            if cad_user == designer:
                continue
            Notification.objects.create(
                recipient=cad_user,
                design_image=design_image,
                title=notif_title,
                message=notif_body,
                notification_type='design_approval',
            )
            send_push_on_commit(
                user=cad_user,
                title=notif_title,
                body=notif_body,
                url=review_url,
                tag=tag,
            )

        # Dispatch ED notifications
        for ed_user in ed_users:
            if ed_user == designer:
                continue
            Notification.objects.create(
                recipient=ed_user,
                design_image=design_image,
                title=notif_title,
                message=notif_body,
                notification_type='design_approval',
            )
            send_push_on_commit(
                user=ed_user,
                title=notif_title,
                body=notif_body,
                url=review_url,
                tag=tag,
            )

    return approval


def record_design_review_decision(design_image, reviewer_user, decision, comment=''):
    """
    Record an independent CAD or ED review decision for a submitted design.
    - Reviewer identity is verified via request.user and their profile approval_role.
    - CAD cannot submit an ED decision; ED cannot submit a CAD decision.
    - Designer cannot approve their own design.
    - Decline REQUIRES a mandatory comment.
    - Both CAD and ED must approve for the design to be fully approved.
    - Either reviewer declining shifts overall status to changes required ('rejected').
    - Submitting designer is notified via in-app notification and Web Push.
    """
    if not reviewer_user or not reviewer_user.is_authenticated:
        raise PermissionDenied(_("Authentication required."))

    prof = getattr(reviewer_user, 'workflow_profile', None)
    reviewer_role = getattr(prof, 'approval_role', None) if prof else None

    # Reviewer must have an approval role of CAD or ED
    if reviewer_role not in (ApprovalRoles.CAD, ApprovalRoles.ED):
        raise PermissionDenied(_("Only authorized CAD or ED approvers may review designs."))

    # Designer cannot approve their own design
    if design_image.uploaded_by_id == reviewer_user.id:
        raise PermissionDenied(_("Designer cannot approve their own design."))

    decision = (decision or '').strip().lower()
    if decision in ('decline', 'declined'):
        decision = 'rejected'
    elif decision in ('approve',):
        decision = 'approved'

    if decision not in ('approved', 'rejected'):
        raise ValidationError(_("Invalid decision. Must be 'approved' or 'rejected'."))

    comment_clean = (comment or '').strip()
    if decision == 'rejected' and not comment_clean:
        raise ValidationError(_("A comment is mandatory when declining a design."))

    with transaction.atomic():
        approval = get_latest_approval_request(design_image)
        if not approval:
            approval = PatternDesignApproval.objects.create(
                design_image=design_image,
                designer=design_image.uploaded_by or reviewer_user,
                cycle=1,
                status='pending',
            )

        now = timezone.now()

        if reviewer_role == ApprovalRoles.CAD:
            if approval.cad_status != 'pending':
                raise ValueError(_("CAD decision has already been submitted for this revision cycle."))
            approval.cad_status = decision
            approval.cad_comment = comment_clean
            approval.cad_reviewer = reviewer_user
            approval.cad_decided_at = now
        elif reviewer_role == ApprovalRoles.ED:
            if approval.ed_status != 'pending':
                raise ValueError(_("ED decision has already been submitted for this revision cycle."))
            approval.ed_status = decision
            approval.ed_comment = comment_clean
            approval.ed_reviewer = reviewer_user
            approval.ed_decided_at = now

        # Compute overall status:
        # CAD Approved + ED Approved = APPROVED
        # Either CAD or ED Rejected = REJECTED (Changes Required)
        # Otherwise = PENDING / PARTIALLY APPROVED
        if approval.cad_status == 'approved' and approval.ed_status == 'approved':
            approval.status = 'approved'
            design_image.approval_status = 'approved'
            design_image.approved_by = reviewer_user
            design_image.approved_at = now
            design_image.rejected_by = None
            design_image.rejected_at = None
            design_image.rejection_reason = ''
        elif approval.cad_status == 'rejected' or approval.ed_status == 'rejected':
            approval.status = 'rejected'
            design_image.approval_status = 'rejected'
            design_image.rejected_by = reviewer_user
            design_image.rejected_at = now
            design_image.rejection_reason = comment_clean
            design_image.approved_by = None
            design_image.approved_at = None
        else:
            approval.status = 'partially_approved'
            design_image.approval_status = 'pending'

        approval.save()
        design_image.save(update_fields=[
            'approval_status', 'approved_by', 'approved_at',
            'rejected_by', 'rejected_at', 'rejection_reason',
        ])

        # Record activity
        ActivityLog.objects.create(
            user=reviewer_user,
            action=f"design_{decision}_{reviewer_role.lower()}",
            object_type='Design Image',
            object_name=f"{design_image.title or design_image.id} ({reviewer_role}: {decision})",
        )

        # Notify the submitting designer
        designer = design_image.uploaded_by
        if designer and designer.is_active:
            role_label = "CAD" if reviewer_role == ApprovalRoles.CAD else "ED"
            review_url = f"/design-approvals/{design_image.id}/"
            tag = f"design-decision-{design_image.id}"

            if decision == 'approved':
                push_title = f"{role_label} Review Completed"
                push_body = f"{role_label} approved your design."
                inapp_title = f"{role_label} Review Completed"
                inapp_message = f"{role_label} approved your design '{design_image.title}'."
                if comment_clean:
                    inapp_message += f" Note: {comment_clean}"
            else:
                push_title = f"{role_label} Review Completed"
                push_body = f"{role_label} requested changes to your design."
                inapp_title = f"{role_label} Review Completed"
                inapp_message = f"{role_label} requested changes to your design '{design_image.title}'. Comment: {comment_clean}"

                # Also create ChatMessage for feedback continuity
                try:
                    chat_text = _("Design \"%(title)s\" - %(role)s review feedback: %(comment)s") % {
                        'title': design_image.title or os.path.basename(design_image.image.name),
                        'role': role_label,
                        'comment': comment_clean,
                    }
                    ChatMessage.objects.create(
                        sender=reviewer_user,
                        recipient=designer,
                        message=chat_text,
                    )
                except Exception as exc:
                    logger.warning("Could not create chat message for design review: %s", exc)

            Notification.objects.create(
                recipient=designer,
                design_image=design_image,
                title=inapp_title,
                message=inapp_message,
                notification_type='design_approval',
            )

            send_push_on_commit(
                user=designer,
                title=push_title,
                body=push_body,
                url=review_url,
                tag=tag,
            )

    return approval, design_image
