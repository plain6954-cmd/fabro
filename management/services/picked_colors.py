"""Picked-color snapshots, scoped mutations and immutable proposal/audit history."""
import re
from django import forms
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.http import Http404
from django.utils import timezone
from management.models import ActivityLog, ColorMaster, PatternColorSelection, PickedColorSelection, WorkflowRoles, YearRange
from management.services.activity_permissions import granted, require, protected_admin, profile
from management.services.color_approval import normalize_hex, save_color_selection


def vehicle_for_user(user, vehicle_id):
    require(user, 'pattern.view')
    if not str(vehicle_id or '').isdigit() or not 0 < int(vehicle_id) < 2**63:
        raise ValidationError('A valid vehicle ID is required.')
    try:
        vehicle = YearRange.objects.select_related('sub_model__model__brand').get(pk=vehicle_id)
    except YearRange.DoesNotExist:
        raise Http404
    person = profile(user)
    # Vehicles have country metadata, not a team/factory assignment relation.
    # Preserve existing catalogue visibility for other roles; never widen CE scope.
    if not protected_admin(user) and person and person.role == WorkflowRoles.COUNTRY_EXECUTIVE:
        if not person.country_id or person.country_id != (vehicle.vehicle_country_id or vehicle.measurement_country_id):
            raise Http404
    return vehicle


def permitted(user, row, action):
    return granted(user, 'picked_colors.' + action + '_all') or (
        row.created_by_id is not None and row.created_by_id == user.pk and granted(user, 'picked_colors.' + action + '_own'))


def snapshot_of(selection):
    def color(side):
        master = getattr(selection, side + '_existing_color')
        return {'source': getattr(selection, side + '_source'), 'master_id': master.pk if master else None,
            'name': getattr(selection, side + '_color_name'), 'code': master.color_code if master else '',
            'pantone': getattr(selection, side + '_pantone_code'), 'hex': getattr(selection, side + '_hex_code')}
    return {'tone_type': selection.tone_type, 'inner': color('inner'),
            'outer': color('outer') if selection.is_dual else None}


def serialize(row, user):
    return {'id': row.pk, 'vehicle_id': row.vehicle_id, 'snapshot': row.snapshot, 'remarks': row.remarks,
        'created_by': row.created_by_id, 'creator_name': row.creator_name,
        'created_at': row.created_at.isoformat(), 'updated_at': row.updated_at.isoformat(),
        'can_edit': permitted(user, row, 'edit'), 'can_delete': permitted(user, row, 'delete'),
        'swatch_url': f'/picked-colors/{row.pk}/swatch/?vehicle_id={row.vehicle_id}'
            if row.source_selection and row.source_selection.swatch_image else None}


def validated_data(user, data):
    clean = {}
    tone = data.get('tone_type', 'single')
    if tone not in ('single', 'dual'):
        raise ValidationError('Choose Single Tone or Dual Tone.')
    clean['tone_type'] = tone
    remarks = data.get('remarks', '')
    if not isinstance(remarks, str) or len(remarks) > 2000:
        raise ValidationError('Remarks must be text of at most 2000 characters.')
    clean['remarks'] = remarks.strip()
    for side in ('inner', 'outer') if tone == 'dual' else ('inner',):
        source = data.get(side + '_source', 'existing')
        if source not in ('existing', 'new'):
            raise ValidationError('Invalid color source.')
        clean[side + '_source'] = source
        if source == 'existing':
            value = data.get(side + '_existing_color_id')
            if not str(value or '').isdigit() or not 0 < int(value) < 2**63:
                raise ValidationError('Choose a valid Color Master entry.')
            clean[side + '_existing_color_id'] = int(value)
        else:
            if not isinstance(data.get(side + '_hex_code'), str):
                raise ValidationError('A valid HEX color is required.')
            clean[side + '_hex_code'] = normalize_hex(data.get(side + '_hex_code'))
            if not clean[side + '_hex_code']:
                raise ValidationError('A HEX color is required.')
            for name, limit in (('pantone_code', 50), ('color_name', 100)):
                value = data.get(side + '_' + name, '')
                if not isinstance(value, str) or len(value) > limit:
                    raise ValidationError('Color names/codes exceed their allowed length.')
                clean[side + '_' + name] = value.strip()
            if not clean[side + '_pantone_code']:
                raise ValidationError('Pantone code is required for new colors.')
    return clean


def same_colors(snapshot, data):
    if snapshot.get('tone_type') != data['tone_type']:
        return False
    for side in ('inner', 'outer') if data['tone_type'] == 'dual' else ('inner',):
        color = snapshot[side]
        if color['source'] != data[side + '_source']:
            return False
        if color['source'] == 'existing':
            if color['master_id'] != data[side + '_existing_color_id']:
                return False
        elif any(color[key] != data[side + '_' + field] for key, field in
                 (('hex', 'hex_code'), ('pantone', 'pantone_code'), ('name', 'color_name'))):
            return False
    return True


def audit(row, user, action, before=None, operation_key=None):
    row.audit_events = [*row.audit_events, {'action': action, 'actor_id': user.pk,
        'actor_name': user.get_full_name() or user.username, 'at': timezone.now().isoformat(),
        'vehicle_id': row.vehicle_id, 'operation_key': operation_key, 'before': before,
        'after': {'snapshot': row.snapshot, 'remarks': row.remarks, 'source_selection_id': row.source_selection_id}}]
    ActivityLog.objects.create(user=user, action=action, object_type='Picked Color', object_name=f'{row.pk} / vehicle {row.vehicle_id}')


@transaction.atomic
def save(user, vehicle_id, data, *, row_id=None, swatch_file=None):
    vehicle = vehicle_for_user(user, vehicle_id)
    require(user, 'picked_colors.view')
    if not row_id:
        require(user, 'picked_colors.add')
    # Serialize accidental double-submission across tabs/vehicles for this user.
    get_user_model().objects.select_for_update().get(pk=user.pk)
    raw_key = data.get('client_submission_key') or ''
    if not isinstance(raw_key, str) or not re.fullmatch(r'[A-Za-z0-9-]{1,64}', raw_key):
        raise ValidationError('A valid submission key is required.')
    key = f'picked:{user.pk}:{raw_key}'
    row = None
    if row_id:
        try:
            row = PickedColorSelection.objects.select_for_update().select_related('source_selection').get(pk=row_id, vehicle=vehicle, deleted_at=None)
        except PickedColorSelection.DoesNotExist:
            raise Http404
        if not permitted(user, row, 'edit'):
            raise PermissionDenied('Editing this color selection is not permitted.')
        if any(event.get('operation_key') == key for event in row.audit_events):
            return row, False
    else:
        row = PickedColorSelection.objects.filter(client_submission_key=key).first()
        if row:
            if row.vehicle_id != vehicle.pk or row.created_by_id != user.pk or row.deleted_at:
                raise ValidationError('This submission key was already used.')
            return row, False
    clean = validated_data(user, data)
    if swatch_file:
        from management.services.measurement_files import validate_measurement_file
        from management.models import PatternMeasurementFile
        _, extension, size, _ = validate_measurement_file(swatch_file, PatternMeasurementFile.CATEGORY_REFERENCE)
        if size > 10 * 1024 * 1024:
            raise ValidationError('Matching swatch photos are limited to 10 MB.')
        # Retain the existing opaque HEIC/HEIF upload support without adding a decoder.
        if extension not in ('.heic', '.heif'):
            forms.ImageField().clean(swatch_file)
        swatch_file.seek(0)
    before = {'snapshot': row.snapshot, 'remarks': row.remarks, 'source_selection_id': row.source_selection_id} if row else None
    if not row or not same_colors(row.snapshot, clean) or swatch_file:
        for side in ('inner', 'outer') if clean['tone_type'] == 'dual' else ('inner',):
            if clean[side + '_source'] == 'existing':
                require(user, 'color.view')
                master = ColorMaster.objects.filter(pk=clean[side + '_existing_color_id'], status='Active').first()
                if not master:
                    raise ValidationError('The selected Color Master entry is unavailable.')
                if not normalize_hex(master.hex_code):
                    raise ValidationError('The selected Color Master entry has no valid color.')
        if PatternColorSelection.objects.filter(client_submission_key=key).exists():
            raise ValidationError('This submission key was already used.')
        proposal, _ = save_color_selection(vehicle, user, clean, swatch_file=swatch_file, client_key=key)
        if row and not swatch_file and row.source_selection and row.source_selection.swatch_image:
            proposal.swatch_image = row.source_selection.swatch_image.name
            proposal.save(update_fields=['swatch_image'])
        if row is None:
            row = PickedColorSelection(vehicle=vehicle, created_by=user,
                creator_name=user.get_full_name() or user.username, client_submission_key=key)
        row.source_selection = proposal
        row.snapshot = snapshot_of(proposal)
    row.remarks = clean['remarks']
    if row.pk:
        row.edited_by = user
    row.save()
    audit(row, user, 'edited' if before else 'created', before, key)
    row.save(update_fields=['audit_events'])
    return row, True


@transaction.atomic
def delete(user, vehicle_id, row_id):
    vehicle = vehicle_for_user(user, vehicle_id)
    require(user, 'picked_colors.view')
    try:
        row = PickedColorSelection.objects.select_for_update().get(pk=row_id, vehicle=vehicle, deleted_at=None)
    except PickedColorSelection.DoesNotExist:
        raise Http404
    if not permitted(user, row, 'delete'):
        raise PermissionDenied('Deleting this color selection is not permitted.')
    row.deleted_at = timezone.now()
    row.edited_by = user
    audit(row, user, 'deleted')
    row.save(update_fields=['deleted_at', 'edited_by', 'updated_at', 'audit_events'])
