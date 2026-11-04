"""Read-only operational projections of existing design reviews and audit records."""
import os
from datetime import timedelta

from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.db.models import Case, Count, IntegerField, Min, OuterRef, Q, Subquery, Value, When
from django.db.models.functions import Coalesce
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext as _, ngettext

from management.models import ActivityLog, PatternDesignApproval, PatternDesignImage
from management.services.workflow import is_workflow_admin

QUEUE_LIMIT = 12
ACTIVITY_LIMIT = 16
AUDIT_WINDOW = 80
ROLES = ('cad', 'ed', 'md')
PENDING = Q(cad_status='pending') | Q(ed_status='pending') | Q(md_status='pending')
REJECTED = Q(status='rejected') | Q(cad_status='rejected') | Q(ed_status='rejected') | Q(md_status='rejected')
VEHICLE_RELATIONS = ('vehicle__sub_model__model__brand', 'folder__vehicle__sub_model__model__brand')


def _age(start, current):
    seconds = max(0, int((current - start).total_seconds()))
    hours = seconds // 3600
    if hours >= 48:
        days = hours // 24
        label = ngettext('%(n)s day', '%(n)s days', days) % {'n': days}
    elif hours:
        label = ngettext('%(n)s hour', '%(n)s hours', hours) % {'n': hours}
    else:
        minutes = seconds // 60
        label = ngettext('%(n)s minute', '%(n)s minutes', minutes) % {'n': minutes}
    return {'seconds': seconds, 'label': label}


def _design_context(image):
    vehicle = image.vehicle or (image.folder.vehicle if image.folder else None)
    name, pattern = '', ''
    if vehicle:
        sub = vehicle.sub_model
        years = '–'.join(str(value) for value in (vehicle.year_start, vehicle.year_end) if value is not None)
        name = ' '.join(part for part in (sub.model.brand.name, sub.model.name, sub.name if sub.name != '-' else '', years) if part)
        pattern = vehicle.serial_number or ''
    return {
        'vehicle': name or _('Vehicle not linked'), 'pattern': pattern, 'design_id': image.pk,
        'title': image.title or os.path.basename(image.image.name) or _('Untitled design'),
        'url': (reverse('car_details') + f'?vehicle_id={vehicle.pk}#design-options' if image.is_reference and vehicle
                else None if image.is_reference else reverse('design_approval_detail', args=[image.pk])),
    }


def control_tower_snapshot(user, *, at=None):
    if not user.is_authenticated or not user.is_active or not is_workflow_admin(user):
        raise PermissionDenied(_('ERP administrator access is required.'))
    current = at or timezone.now()
    delay_hours = max(1, int(getattr(settings, 'CONTROL_TOWER_REVIEW_DELAY_HOURS', 48)))
    cutoff = current - timedelta(hours=delay_hours)
    latest = PatternDesignApproval.objects.filter(design_image_id=OuterRef('design_image_id')).order_by('-cycle').values('pk')[:1]
    # One row per design's current cycle; historical pending votes never enter the counts.
    reviews = PatternDesignApproval.objects.filter(pk=Subquery(latest), design_image__is_reference=False)
    aggregates = {
        'pending_designs': Count('pk', filter=PENDING),
        'delayed': Count('pk', filter=PENDING & Q(submitted_at__lte=cutoff)),
        'revisions': Count('pk', filter=PENDING & Q(cycle__gt=1)),
        'attention': Count('pk', filter=PENDING | REJECTED),
    }
    for role in ROLES:
        aggregates[role] = Count('pk', filter=Q(**{role + '_status': 'pending'}))
        aggregates[role + '_oldest'] = Min('submitted_at', filter=Q(**{role + '_status': 'pending'}))
    counts = reviews.aggregate(**aggregates)
    counts['pending'] = sum(counts[role] for role in ROLES)
    stages = [{'role': role.upper(), 'count': counts[role],
               'oldest': counts[role + '_oldest'],
               'age': _age(counts[role + '_oldest'], current) if counts[role + '_oldest'] else None,
               'percent': round(counts[role] * 100 / max(1, max(counts[r] for r in ROLES)))} for role in ROLES]
    rejected_cycles = PatternDesignApproval.objects.filter(design_image_id=OuterRef('design_image_id')).filter(REJECTED).values('design_image_id').annotate(n=Count('pk')).values('n')[:1]
    queue = reviews.filter(PENDING | REJECTED).annotate(rejected_cycles=Coalesce(Subquery(rejected_cycles), Value(0))).annotate(
        urgency=Case(
            When(REJECTED & Q(rejected_cycles__gte=2), then=Value(0)),
            When(PENDING & Q(submitted_at__lte=cutoff), then=Value(1)),
            When(REJECTED, then=Value(2)), When(cycle__gt=1, then=Value(3)),
            default=Value(4), output_field=IntegerField(),
        ),
    ).select_related(*('design_image__' + relation for relation in VEHICLE_RELATIONS), *[role + '_reviewer' for role in ROLES]).order_by('urgency', 'submitted_at', 'pk')[:QUEUE_LIMIT]
    reasons = (_('Repeated rejection'), _('Delayed review'), _('Changes required'), _('Revision awaiting review'), _('Pending review'))
    attention = []
    for approval in queue:
        pending = [role for role in ROLES if getattr(approval, role + '_status') == 'pending']
        named = [f'{role.upper()}: {getattr(approval, role + "_reviewer").username}' for role in pending if getattr(approval, role + '_reviewer')]
        attention.append({**_design_context(approval.design_image), 'cycle': approval.cycle,
                          'status': approval.status, 'status_label': approval.get_status_display(),
                          'stages': ' · '.join(role.upper() for role in pending) or _('Designer revision'),
                          'reviewer': ', '.join(named) or (_('Role-based review · Admin permitted') if pending else _('Awaiting designer revision')),
                          'reason': reasons[approval.urgency], 'urgency': approval.urgency,
                          'submitted_at': approval.submitted_at, 'age': _age(approval.submitted_at, current)})
    activity = []
    # Primary-key windows are bounded/indexed. Audit entries have no reliable design FK;
    # retain their recorded context and link to Logs instead of guessing by filename.
    actions = {'submitted': (_('Submitted design for review'), 'paper-plane'),
               'resubmitted': (_('Resubmitted design for review'), 'redo'),
               'deleted': (_('Deleted design record'), 'trash-alt'),
               'created': (_('Created design record'), 'plus')}
    for log in ActivityLog.objects.select_related('user').order_by('-pk')[:AUDIT_WINDOW]:
        if log.object_type not in ('Design Image', 'Design Folder'):
            continue
        action = actions.get(log.action)
        for role in ROLES:
            if log.action == 'design_approved_' + role:
                action = (_('%(stage)s approved design') % {'stage': role.upper()}, 'check')
            elif log.action == 'design_rejected_' + role:
                action = (_('%(stage)s rejected design') % {'stage': role.upper()}, 'times')
        if action:
            activity.append({'key': f'audit-{log.pk}', 'actor': log.user.username if log.user else _('Account unavailable'),
                             'action': action[0], 'icon': action[1], 'context': log.object_name,
                             'timestamp': log.timestamp, 'url': reverse('admin_panel') + '?section=logs#logs', 'source': 'audit'})
    for image in PatternDesignImage.objects.select_related('uploaded_by', *VEHICLE_RELATIONS).order_by('-pk')[:ACTIVITY_LIMIT]:
        context = _design_context(image)
        activity.append({'key': f'upload-{image.pk}', 'actor': image.uploaded_by.username if image.uploaded_by else _('Account unavailable'),
                         'action': _('Uploaded reference file') if image.is_reference else _('Uploaded design file'), 'icon': 'upload',
                         'context': ' · '.join(part for part in (context['vehicle'], context['pattern'], context['title']) if part),
                         'timestamp': image.uploaded_at, 'url': context['url'], 'source': 'upload'})
    activity.sort(key=lambda event: (event['timestamp'], event['key']), reverse=True)
    return {
        'counts': {key: counts[key] for key in ('pending', 'pending_designs', 'delayed', 'revisions', 'attention')},
        'pipeline': stages, 'attention': attention, 'activity': activity[:ACTIVITY_LIMIT],
        'queue_limit': QUEUE_LIMIT, 'activity_limit': ACTIVITY_LIMIT,
        'delay_hours': delay_hours, 'generated_at': current,
        'updated_label': timezone.localtime(current).strftime('%H:%M:%S'),
        'reviews_url': reverse('approvals_list') + '?stage=designer&status=all',
        'logs_url': reverse('admin_panel') + '?section=logs#logs',
    }
