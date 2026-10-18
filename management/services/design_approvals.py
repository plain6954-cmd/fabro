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
from management.services.workflow import is_active_superuser

logger = logging.getLogger(__name__)


def get_approvers_for_role(approval_role):
    """
    Find active approver accounts configured for the given review role.
    """
    return list(User.objects.filter(
        is_active=True,
        workflow_profile__role=WorkflowRoles.APPROVER,
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
    CAD, ED, and MD reviewers receive in-app and Web Push notifications.
    """
    with transaction.atomic():
        # Serialize review-cycle changes on the design row. The caller's copy
        # may be stale after another tab has already resubmitted it.
        design_image = PatternDesignImage.objects.select_for_update().get(pk=design_image.pk)
        if is_resubmission:
            latest = get_latest_approval_request(design_image)
            if not latest or latest.status != 'rejected' or design_image.approval_status != 'rejected':
                raise ValidationError(_("Only a rejected current review can be resubmitted."))
            next_cycle = (latest.cycle + 1) if latest else 1
            approval = PatternDesignApproval.objects.create(
                design_image=design_image,
                designer=designer,
                cycle=next_cycle,
                status='pending',
                cad_status='pending',
                ed_status='pending',
                md_status='pending',
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
                    'md_status': 'pending',
                }
            )
            if not created:
                return approval
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

        review_url = f"/design-approvals/{design_image.id}/"
        tag = f"design-approval-{design_image.id}"

        if is_resubmission:
            notif_title = _("Design Resubmitted for Approval")
            notif_body = _("A revised 3D design has been resubmitted for your review.")
        else:
            notif_title = _("New Design Approval Request")
            notif_body = _("A new design is waiting for your approval.")

        # One notification per reviewer account, even if role data is unusual.
        recipients = {
            reviewer.pk: reviewer
            for role in (ApprovalRoles.CAD, ApprovalRoles.ED, ApprovalRoles.MD)
            for reviewer in get_approvers_for_role(role)
            if reviewer.pk != designer.pk
        }
        for reviewer in recipients.values():
            Notification.objects.create(
                recipient=reviewer,
                design_image=design_image,
                title=notif_title,
                message=notif_body,
                notification_type='design_approval',
            )
            send_push_on_commit(
                user=reviewer,
                title=notif_title,
                body=notif_body,
                url=review_url,
                tag=tag,
            )

    return approval


def record_design_review_decision(design_image, reviewer_user, decision, comment='', stage=None, change_type=''):
    """
    Record an independent CAD, ED, or MD review decision for a submitted design.
    - Reviewer identity is verified via request.user and their profile approval_role,
      or via active superuser status with an explicit/inferred review stage ('cad', 'ed', or 'md').
    - CAD cannot submit an ED/MD decision; ED cannot submit CAD/MD; MD cannot submit CAD/ED.
    - Mandatory change classification ('minor' or 'major') required for all decisions.
    - Designer cannot approve their own design.
    - Decline/Reject REQUIRES a mandatory comment.
    - CAD, ED, and MD must each approve before final approval.
    - Any reviewer declining shifts overall status to changes required ('rejected').
    - Submitting designer is notified via in-app notification and Web Push.
    """
    if not reviewer_user or not reviewer_user.is_authenticated:
        raise PermissionDenied(_("Authentication required."))

    # Designer cannot approve their own design
    if design_image.uploaded_by_id == reviewer_user.id:
        raise PermissionDenied(_("Designer cannot approve their own design."))

    is_su = is_active_superuser(reviewer_user)
    prof = getattr(reviewer_user, 'workflow_profile', None)
    user_approval_role = getattr(prof, 'approval_role', None) if prof else None

    # Fetch latest approval request to inspect current stages if needed
    approval = get_latest_approval_request(design_image)
    if not approval:
        raise ValidationError(_("This design has not been submitted for review."))

    # Determine reviewer_role
    if is_su:
        stage_clean = str(stage).strip().lower() if stage else ''
        if stage_clean in ('cad', ApprovalRoles.CAD.lower()):
            reviewer_role = ApprovalRoles.CAD
        elif stage_clean in ('ed', ApprovalRoles.ED.lower()):
            reviewer_role = ApprovalRoles.ED
        elif stage_clean in ('md', ApprovalRoles.MD.lower()):
            reviewer_role = ApprovalRoles.MD
        elif not stage_clean:
            # If not explicitly specified, inspect pending stage on latest approval
            if approval.cad_status == 'pending' and approval.ed_status != 'pending' and approval.md_status != 'pending':
                reviewer_role = ApprovalRoles.CAD
            elif approval.ed_status == 'pending' and approval.cad_status != 'pending' and approval.md_status != 'pending':
                reviewer_role = ApprovalRoles.ED
            elif approval.md_status == 'pending' and approval.cad_status != 'pending' and approval.ed_status != 'pending':
                reviewer_role = ApprovalRoles.MD
            elif user_approval_role in (ApprovalRoles.CAD, ApprovalRoles.ED, ApprovalRoles.MD):
                reviewer_role = user_approval_role
            else:
                raise ValidationError(_("Please specify whether you are reviewing for CAD, ED, or MD stage."))
        else:
            raise ValidationError(_("Invalid review stage. Must be 'cad', 'ed', or 'md'."))
    else:
        # Reviewer must have an approval role of CAD, ED, or MD
        if not prof or prof.role != WorkflowRoles.APPROVER or user_approval_role not in (ApprovalRoles.CAD, ApprovalRoles.ED, ApprovalRoles.MD):
            raise PermissionDenied(_("Only authorized CAD, ED, or MD approvers may review designs."))
        reviewer_role = user_approval_role
        if stage:
            stage_clean = str(stage).strip().lower()
            if stage_clean in ('cad', 'ed', 'md') and stage_clean != reviewer_role.lower():
                raise PermissionDenied(_("You cannot review a stage other than your assigned role."))

    decision = (decision or '').strip().lower()
    if decision in ('decline', 'declined'):
        decision = 'rejected'
    elif decision in ('approve',):
        decision = 'approved'

    if decision not in ('approved', 'rejected'):
        raise ValidationError(_("Invalid decision. Must be 'approved' or 'rejected'."))

    change_type_clean = (change_type or '').strip().lower()
    if change_type_clean not in ('minor', 'major'):
        raise ValidationError(_("Please select either Minor Change or Major Change."))

    comment_clean = (comment or '').strip()
    if decision == 'rejected' and not comment_clean:
        raise ValidationError(_("A comment is mandatory when declining a design."))

    with transaction.atomic():
        design_image = PatternDesignImage.objects.select_for_update().get(pk=design_image.pk)
        approval = get_latest_approval_request(design_image)
        if not approval:
            raise ValidationError(_("This design has not been submitted for review."))

        now = timezone.now()

        if reviewer_role == ApprovalRoles.CAD:
            if approval.cad_status != 'pending':
                raise ValueError(_("CAD decision has already been submitted for this revision cycle."))
            approval.cad_status = decision
            approval.cad_comment = comment_clean
            approval.cad_change_type = change_type_clean
            approval.cad_reviewer = reviewer_user
            approval.cad_decided_at = now
        elif reviewer_role == ApprovalRoles.ED:
            if approval.ed_status != 'pending':
                raise ValueError(_("ED decision has already been submitted for this revision cycle."))
            approval.ed_status = decision
            approval.ed_comment = comment_clean
            approval.ed_change_type = change_type_clean
            approval.ed_reviewer = reviewer_user
            approval.ed_decided_at = now
        elif reviewer_role == ApprovalRoles.MD:
            if approval.md_status != 'pending':
                raise ValueError(_("MD decision has already been submitted for this revision cycle."))
            approval.md_status = decision
            approval.md_comment = comment_clean
            approval.md_change_type = change_type_clean
            approval.md_reviewer = reviewer_user
            approval.md_decided_at = now

        # Compute overall status:
        # CAD Approved + ED Approved + MD Approved = APPROVED
        # Any of CAD, ED, MD Rejected = REJECTED (Changes Required)
        # Otherwise = PENDING / PARTIALLY APPROVED
        cad_ok = (approval.cad_status == 'approved')
        ed_ok = (approval.ed_status == 'approved')
        md_ok = (approval.md_status in ('approved', 'not_required'))

        rejecters = []
        if approval.cad_status == 'rejected':
            rejecters.append(('CAD', approval.cad_reviewer or reviewer_user, approval.cad_comment))
        if approval.ed_status == 'rejected':
            rejecters.append(('ED', approval.ed_reviewer or reviewer_user, approval.ed_comment))
        if approval.md_status == 'rejected':
            rejecters.append(('MD', approval.md_reviewer or reviewer_user, approval.md_comment))

        if rejecters:
            approval.status = 'rejected'
            design_image.approval_status = 'rejected'
            if len(rejecters) > 1:
                design_image.rejected_by = rejecters[0][1]
                design_image.rejection_reason = " | ".join(f"{r_role}: {r_comm}" for r_role, _, r_comm in rejecters)
            else:
                design_image.rejected_by = rejecters[0][1]
                design_image.rejection_reason = rejecters[0][2]
            design_image.rejected_at = now
            design_image.approved_by = None
            design_image.approved_at = None
        elif cad_ok and ed_ok and md_ok:
            approval.status = 'approved'
            design_image.approval_status = 'approved'
            design_image.approved_by = reviewer_user
            design_image.approved_at = now
            design_image.rejected_by = None
            design_image.rejected_at = None
            design_image.rejection_reason = ''
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
            role_label = reviewer_role
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
