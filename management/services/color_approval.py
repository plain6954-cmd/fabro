import logging
import re
from django.conf import settings
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError, PermissionDenied
from django.db import transaction
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from management.models import (
    ApprovalRoles,
    ColorMaster,
    Notification,
    PatternColorApprovalDecision,
    PatternColorSelection,
    YearRange,
)
from management.services.push_notifications import send_push_on_commit

logger = logging.getLogger(__name__)

HEX_REGEX = re.compile(r'^#([A-Fa-f0-9]{6})$')


def normalize_hex(val):
    if not val:
        return ''
    val = val.strip()
    if not val.startswith('#'):
        val = '#' + val
    val = val.upper()
    if not HEX_REGEX.match(val):
        raise ValidationError(_("Invalid HEX color code: %(val)s. Expected 6 hex characters (e.g. #AF955C).") % {'val': val})
    return val


def derive_rgb_cmyk_from_hex(hex_str):
    h = (hex_str or '').lstrip('#')
    if len(h) != 6:
        return '', ''
    try:
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
        rgb_str = f"{r}, {g}, {b}"
        r_norm, g_norm, b_norm = r / 255.0, g / 255.0, b / 255.0
        k = 1.0 - max(r_norm, g_norm, b_norm)
        if k >= 1.0:
            c_val, m_val, y_val = 0, 0, 0
        else:
            c_val = round((1.0 - r_norm - k) / (1.0 - k) * 100)
            m_val = round((1.0 - g_norm - k) / (1.0 - k) * 100)
            y_val = round((1.0 - b_norm - k) / (1.0 - k) * 100)
        k_val = round(k * 100)
        cmyk_str = f"{c_val}, {m_val}, {y_val}, {k_val}"
        return rgb_str, cmyk_str
    except Exception:
        return '', ''


def get_next_colormaster_code():
    codes = list(ColorMaster.objects.values_list('color_code', flat=True))
    nums = []
    for c in codes:
        digits = re.findall(r'^\d+$', (c or '').strip())
        if digits:
            nums.append(int(digits[0]))
    max_val = max(nums) if nums else 0
    candidate = max_val + 1
    while ColorMaster.objects.filter(color_code=f"{candidate:02d}").exists():
        candidate += 1
    return f"{candidate:02d}"


def save_color_selection(vehicle, user, data, swatch_file=None, client_key=None):
    if client_key:
        existing = PatternColorSelection.objects.filter(client_submission_key=client_key).first()
        if existing:
            return existing, False

    tone_type = (data.get('tone_type') or PatternColorSelection.TONE_SINGLE).strip().lower()
    if tone_type not in (PatternColorSelection.TONE_SINGLE, PatternColorSelection.TONE_DUAL):
        tone_type = PatternColorSelection.TONE_SINGLE

    # Process Inner / Single Tone Color
    inner_source = (data.get('inner_source') or PatternColorSelection.SOURCE_EXISTING).strip().lower()
    inner_existing = None
    inner_pantone = (data.get('inner_pantone_code') or '').strip()
    inner_hex = ''
    inner_name = (data.get('inner_color_name') or '').strip()

    if inner_source == PatternColorSelection.SOURCE_EXISTING:
        inner_id = data.get('inner_existing_color_id')
        if not inner_id:
            raise ValidationError(_("Please select an existing color."))
        try:
            inner_existing = ColorMaster.objects.get(id=inner_id)
            inner_hex = inner_existing.hex_code
            inner_pantone = inner_existing.pantone_code
            inner_name = inner_existing.name
        except ColorMaster.DoesNotExist:
            raise ValidationError(_("Selected inner color does not exist."))
    else:
        inner_hex = normalize_hex(data.get('inner_hex_code'))
        if not inner_pantone:
            raise ValidationError(_("Pantone code is required for new colors."))

    # Process Outer Color (if Dual Tone)
    outer_source = PatternColorSelection.SOURCE_EXISTING
    outer_existing = None
    outer_pantone = ''
    outer_hex = ''
    outer_name = ''

    if tone_type == PatternColorSelection.TONE_DUAL:
        outer_source = (data.get('outer_source') or PatternColorSelection.SOURCE_EXISTING).strip().lower()
        if outer_source == PatternColorSelection.SOURCE_EXISTING:
            outer_id = data.get('outer_existing_color_id')
            if not outer_id:
                raise ValidationError(_("Please select an outer existing color."))
            try:
                outer_existing = ColorMaster.objects.get(id=outer_id)
                outer_hex = outer_existing.hex_code
                outer_pantone = outer_existing.pantone_code
                outer_name = outer_existing.name
            except ColorMaster.DoesNotExist:
                raise ValidationError(_("Selected outer color does not exist."))
        else:
            outer_hex = normalize_hex(data.get('outer_hex_code'))
            outer_pantone = (data.get('outer_pantone_code') or '').strip()
            outer_name = (data.get('outer_color_name') or '').strip()
            if not outer_pantone:
                raise ValidationError(_("Pantone code is required for new outer color."))

    is_new = (inner_source == PatternColorSelection.SOURCE_NEW) or (
        tone_type == PatternColorSelection.TONE_DUAL and outer_source == PatternColorSelection.SOURCE_NEW
    )

    with transaction.atomic():
        selection = PatternColorSelection.objects.create(
            vehicle=vehicle,
            tone_type=tone_type,
            inner_source=inner_source,
            inner_existing_color=inner_existing,
            inner_pantone_code=inner_pantone,
            inner_hex_code=inner_hex,
            inner_color_name=inner_name,
            outer_source=outer_source if tone_type == PatternColorSelection.TONE_DUAL else '',
            outer_existing_color=outer_existing if tone_type == PatternColorSelection.TONE_DUAL else None,
            outer_pantone_code=outer_pantone if tone_type == PatternColorSelection.TONE_DUAL else '',
            outer_hex_code=outer_hex if tone_type == PatternColorSelection.TONE_DUAL else '',
            outer_color_name=outer_name if tone_type == PatternColorSelection.TONE_DUAL else '',
            swatch_image=swatch_file or None,
            status=PatternColorSelection.STATUS_PENDING if is_new else PatternColorSelection.STATUS_APPROVED,
            is_new_color=is_new,
            submitted_by=user,
            client_submission_key=client_key or None,
        )

        if is_new:
            # Create MD, ED, CAD approval tickets
            for dept in (
                PatternColorApprovalDecision.DEPT_MD,
                PatternColorApprovalDecision.DEPT_ED,
                PatternColorApprovalDecision.DEPT_CAD,
            ):
                PatternColorApprovalDecision.objects.create(
                    selection=selection,
                    department=dept,
                    decision=PatternColorApprovalDecision.STATUS_PENDING,
                )

            # Dispatch notifications to MD, ED, CAD
            _notify_approvers_new_color_proposal(selection, vehicle, user)

        return selection, True


def _notify_approvers_new_color_proposal(selection, vehicle, submitter):
    target_roles = [ApprovalRoles.MD, ApprovalRoles.ED, ApprovalRoles.CAD]
    approver_users = list(
        User.objects.filter(
            workflow_profile__approval_role__in=target_roles,
            is_active=True,
        ).select_related('workflow_profile')
    )

    title = _("New Color Approval Request")
    vehicle_name = f"{vehicle.sub_model.model.brand.name} {vehicle.sub_model.model.name} {vehicle.serial_number}".strip() if vehicle.sub_model else f"Pattern #{vehicle.serial_number}"
    message = _("A new color selection for %(vehicle)s is awaiting your review.") % {'vehicle': vehicle_name}
    target_url = f"/approvals/?stage=colors"

    for approver in approver_users:
        Notification.objects.create(
            recipient=approver,
            color_selection=selection,
            title=title,
            message=message,
            notification_type='color_approval',
        )
        send_push_on_commit(
            user=approver,
            title=title,
            body=message,
            url=target_url,
            tag=f"color_approval_{selection.id}",
        )


def submit_color_decision(user, decision_id, decision_choice, remarks):
    decision_choice = (decision_choice or '').strip().lower()
    if decision_choice not in ('approved', 'rejected'):
        raise ValidationError(_("Decision must be either 'approved' or 'rejected'."))

    remarks = (remarks or '').strip()
    if decision_choice == 'rejected' and not remarks:
        raise ValidationError(_("A remark is mandatory when rejecting a color proposal."))

    with transaction.atomic():
        try:
            decision = PatternColorApprovalDecision.objects.select_for_update().get(id=decision_id)
        except PatternColorApprovalDecision.DoesNotExist:
            raise ValidationError(_("Approval decision record not found."))

        selection = PatternColorSelection.objects.select_for_update().get(id=decision.selection_id)
        if selection.status == PatternColorSelection.STATUS_APPROVED:
            raise ValidationError(_("This color selection is already fully approved."))

        profile = getattr(user, 'workflow_profile', None)
        user_approval_role = getattr(profile, 'approval_role', '')

        # Enforce authorized department match
        if user_approval_role != decision.department:
            raise PermissionDenied(
                _("You are not authorized to submit decisions for the %(dept)s department.") % {'dept': decision.department}
            )

        # Update decision
        decision.decision = decision_choice
        decision.remarks = remarks
        decision.approver = user
        decision.decided_at = timezone.now()
        decision.save(update_fields=['decision', 'remarks', 'approver', 'decided_at'])

        # Check all decisions for this selection
        all_decisions = list(selection.decisions.all())
        any_rejected = any(d.decision == PatternColorApprovalDecision.STATUS_REJECTED for d in all_decisions)
        all_approved = len(all_decisions) == 3 and all(d.decision == PatternColorApprovalDecision.STATUS_APPROVED for d in all_decisions)

        vehicle_name = str(selection.vehicle)

        if any_rejected:
            selection.status = PatternColorSelection.STATUS_REJECTED
            selection.save(update_fields=['status', 'updated_at'])

            if selection.submitted_by and selection.submitted_by != user:
                title = _("Color Proposal Rejected")
                msg = _("%(dept)s requested changes on %(vehicle)s: %(remarks)s") % {
                    'dept': decision.department,
                    'vehicle': vehicle_name,
                    'remarks': remarks or _("Rejected"),
                }
                Notification.objects.create(
                    recipient=selection.submitted_by,
                    color_selection=selection,
                    title=title,
                    message=msg,
                    notification_type='color_approval',
                )
                send_push_on_commit(
                    user=selection.submitted_by,
                    title=title,
                    body=msg,
                    url=f"/car-details/?vehicle_id={selection.vehicle_id}#measurements",
                    tag=f"color_rej_{selection.id}",
                )

        elif all_approved:
            selection.status = PatternColorSelection.STATUS_APPROVED
            selection.save(update_fields=['status', 'updated_at'])

            # Automatically integrate new colors into ColorMaster
            _integrate_approved_colors_into_color_master(selection)

            if selection.submitted_by and selection.submitted_by != user:
                title = _("Color Proposal Approved")
                msg = _("Your color proposal for %(vehicle)s has received unanimous approval.") % {
                    'vehicle': vehicle_name
                }
                Notification.objects.create(
                    recipient=selection.submitted_by,
                    color_selection=selection,
                    title=title,
                    message=msg,
                    notification_type='color_approval',
                )
                send_push_on_commit(
                    user=selection.submitted_by,
                    title=title,
                    body=msg,
                    url=f"/car-details/?vehicle_id={selection.vehicle_id}#measurements",
                    tag=f"color_app_{selection.id}",
                )

        return decision


def _integrate_approved_colors_into_color_master(selection):
    # Inner / Single color if new
    if selection.inner_source == PatternColorSelection.SOURCE_NEW and not selection.inner_existing_color:
        rgb_str, cmyk_str = derive_rgb_cmyk_from_hex(selection.inner_hex_code)
        code = get_next_colormaster_code()
        name = selection.inner_color_name or f"Color {code}"
        cm = ColorMaster.objects.create(
            color_code=code,
            name=name.upper(),
            hex_code=selection.inner_hex_code,
            pantone_code=selection.inner_pantone_code,
            rgb_code=rgb_str,
            cmyk_code=cmyk_str,
            status='Active',
        )
        selection.inner_existing_color = cm

    # Outer color if dual tone and new
    if selection.is_dual and selection.outer_source == PatternColorSelection.SOURCE_NEW and not selection.outer_existing_color:
        rgb_str, cmyk_str = derive_rgb_cmyk_from_hex(selection.outer_hex_code)
        code = get_next_colormaster_code()
        name = selection.outer_color_name or f"Color {code}"
        cm = ColorMaster.objects.create(
            color_code=code,
            name=name.upper(),
            hex_code=selection.outer_hex_code,
            pantone_code=selection.outer_pantone_code,
            rgb_code=rgb_str,
            cmyk_code=cmyk_str,
            status='Active',
        )
        selection.outer_existing_color = cm

    selection.save(update_fields=['inner_existing_color', 'outer_existing_color'])


def serialize_color_selection(selection, current_user=None):
    decisions = list(selection.decisions.select_related('approver').all())
    decisions_map = {d.department: d for d in decisions}

    profile = getattr(current_user, 'workflow_profile', None) if current_user else None
    user_approval_role = getattr(profile, 'approval_role', '') if profile else ''

    def _dept_data(dept):
        d = decisions_map.get(dept)
        if not d:
            return {
                'id': None,
                'status': 'pending',
                'remarks': '',
                'approver': '',
                'decided_at': '',
                'can_decide': False,
            }
        can_decide = bool(
            current_user
            and user_approval_role == dept
            and selection.status == PatternColorSelection.STATUS_PENDING
        )
        return {
            'id': d.id,
            'status': d.decision,
            'remarks': d.remarks or '',
            'approver': d.approver.username if d.approver else '',
            'decided_at': timezone.localtime(d.decided_at).strftime('%b %d, %Y %H:%M') if d.decided_at else '',
            'can_decide': can_decide,
        }

    vehicle = selection.vehicle
    vehicle_info = {
        'id': vehicle.id,
        'serial_number': vehicle.serial_number or f"{vehicle.id}",
        'brand': vehicle.sub_model.model.brand.name if vehicle.sub_model and vehicle.sub_model.model and vehicle.sub_model.model.brand else '',
        'model': vehicle.sub_model.model.name if vehicle.sub_model and vehicle.sub_model.model else '',
        'sub_model': vehicle.sub_model.name if vehicle.sub_model and vehicle.sub_model.name != '-' else '',
        'year_range': f"{vehicle.year_start or ''}–{vehicle.year_end or ''}".strip('–'),
    }

    return {
        'id': selection.id,
        'vehicle': vehicle_info,
        'tone_type': selection.tone_type,
        'is_dual': selection.is_dual,
        'is_new_color': selection.is_new_color,
        'status': selection.status,
        'status_display': selection.get_status_display(),
        'swatch_url': selection.swatch_image.url if selection.swatch_image else '',
        'submitted_by': selection.submitted_by.username if selection.submitted_by else '',
        'submitted_at': timezone.localtime(selection.created_at).strftime('%b %d, %Y %H:%M'),
        'inner_color': {
            'source': selection.inner_source,
            'name': selection.inner_existing_color.name if selection.inner_existing_color else selection.inner_color_name,
            'code': selection.inner_existing_color.color_code if selection.inner_existing_color else '',
            'pantone': selection.inner_pantone_code,
            'hex': selection.inner_hex_code,
        },
        'outer_color': {
            'source': selection.outer_source,
            'name': selection.outer_existing_color.name if selection.outer_existing_color else selection.outer_color_name,
            'code': selection.outer_existing_color.color_code if selection.outer_existing_color else '',
            'pantone': selection.outer_pantone_code,
            'hex': selection.outer_hex_code,
        } if selection.is_dual else None,
        'decisions': {
            'MD': _dept_data('MD'),
            'ED': _dept_data('ED'),
            'CAD': _dept_data('CAD'),
        },
        'current_user_department': user_approval_role if user_approval_role in ('MD', 'ED', 'CAD') else None,
    }
