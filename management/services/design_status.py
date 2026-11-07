"""Read-only, version-specific presentation for comparison and 3D Status."""
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import Case, F, IntegerField, OuterRef, Q, Subquery, Value, When
from django.db.models.functions import Coalesce, Concat, NullIf, Trim
from django.utils.translation import gettext as _

from management.models import PatternDesignApproval, PatternDesignImage, WorkflowRoles
from management.services.activity_permissions import granted, protected_admin
from management.services.design_approvals import design_review_roles


def clean(value):
    text = str(value).strip() if value is not None else ''
    return '' if text.lower() in ('', '-', 'none', 'null') else text


def vehicle_identity(vehicle):
    if not vehicle:
        return dict(pattern='', heading='', label='', full='')
    variant = getattr(vehicle, 'sub_model', None)
    model = getattr(variant, 'model', None)
    brand = getattr(model, 'brand', None)
    # Preserve the catalogue's established labels: BR is "Sub Model" and
    # the SubModel relation's name is displayed as "Variant".
    brand_name, model_name, sub_name, variant_name = map(clean, (
        getattr(brand, 'name', ''), getattr(model, 'name', ''), vehicle.br, getattr(variant, 'name', '')))
    years = '–'.join(str(value) for value in (vehicle.year_start, vehicle.year_end) if value is not None)
    pattern = clean(vehicle.serial_number) or f'S{vehicle.pk:04d}'
    heading = ' '.join(filter(None, (brand_name, model_name, sub_name, years, variant_name)))
    label = ' '.join(filter(None, (brand_name, model_name, sub_name, variant_name, f'({years})' if years else '')))
    return dict(pattern=pattern, heading=heading, label=label, full=' — '.join(filter(None, (pattern, label))))


def final_outcome(image):
    """The newest persisted cycle wins over denormalized/legacy image state."""
    approval = image.latest_approval
    value = approval.status if approval else image.approval_status
    return value if value in ('approved', 'rejected') else 'pending'


def latest_designer_upload(images):
    return max((image for image in images if not image.is_reference and image.image),
        key=lambda image:(image.uploaded_at is not None,image.uploaded_at,image.pk), default=None)


def can_view_status(user):
    return granted(user, 'pattern.view') and any(granted(user, key) for key in ('design.view_own', 'design.view_all'))


def status_context(request):
    if not can_view_status(request.user):
        raise PermissionDenied(_('3D design access is disabled.'))
    from management.views import _comparison_visible_files

    genuine = PatternDesignImage.objects.filter(is_reference=False).exclude(image='').annotate(
        pattern_id=Coalesce('vehicle_id', 'folder__vehicle_id'))
    # Select the actual latest version first, not the latest *visible* older
    # version. If that current file is unauthorized, omit the pattern entirely.
    latest = genuine.filter(Q(vehicle_id=OuterRef('pattern_id')) |
        Q(vehicle__isnull=True,folder__vehicle_id=OuterRef('pattern_id'))).order_by('-uploaded_at', '-pk')
    images = _comparison_visible_files(request.user).filter(is_reference=False).exclude(image='').annotate(
        pattern_id=Coalesce('vehicle_id', 'folder__vehicle_id')).filter(
        pattern_id__isnull=False, pk=Subquery(latest.values('pk')[:1]))
    if not granted(request.user, 'folder.view'):
        images = images.filter(folder__isnull=True)
    person = getattr(request.user, 'workflow_profile', None)
    if person and person.role == WorkflowRoles.COUNTRY_EXECUTIVE and not protected_admin(request.user):
        if not person.country_id:
            images = images.none()
        else:
            country = person.country_id
            images = images.filter(
                Q(vehicle__vehicle_country_id=country) |
                Q(vehicle__vehicle_country__isnull=True, vehicle__measurement_country_id=country) |
                Q(vehicle__isnull=True, folder__vehicle__vehicle_country_id=country) |
                Q(vehicle__isnull=True, folder__vehicle__vehicle_country__isnull=True,
                  folder__vehicle__measurement_country_id=country))
    cycle = PatternDesignApproval.objects.filter(design_image_id=OuterRef('pk')).order_by('-cycle', '-pk')
    images = images.annotate(
        uploader_label=Coalesce(NullIf(Trim(Concat('uploaded_by__first_name',Value(' '),'uploaded_by__last_name')),Value('')),
                               F('uploaded_by__username'),Value('')),
        current_review_id=Subquery(cycle.values('pk')[:1]),
        current_outcome=Coalesce(Subquery(cycle.values('status')[:1]), F('approval_status')),
        **{f'stage_{stage}':Subquery(cycle.values(stage+'_status')[:1]) for stage in ('cad','ed','md')})
    actionable = Q(pk__in=[])
    if granted(request.user, 'design_approval.view') and any(granted(request.user, 'design_approval.'+action) for action in ('approve','reject')):
        for role in design_review_roles(request.user):
            actionable |= Q(**{'stage_'+role.lower():'pending'})
        actionable &= ~Q(uploaded_by_id=request.user.pk) & Q(current_review_id__isnull=False)
    pending = Q(current_outcome__in=['pending','partially_approved'])
    images = images.annotate(work_priority=Case(
        When(pending & actionable, then=Value(0)), When(pending, then=Value(1)),
        When(current_outcome='rejected', then=Value(2)), When(current_outcome='approved', then=Value(3)),
        default=Value(1), output_field=IntegerField()))
    search = (request.GET.get('status_search') or '').strip()[:200]
    if search:
        query = Q(title__icontains=search) | Q(uploaded_by__username__icontains=search)
        for field in ('serial_number','br','sub_model__name','sub_model__model__name','sub_model__model__brand__name'):
            query |= Q(**{'vehicle__'+field+'__icontains':search}) | Q(vehicle__isnull=True, **{'folder__vehicle__'+field+'__icontains':search})
        images = images.filter(query)
    # Sorting uses the effective pattern relationship, including folder uploads.
    fields = dict(pattern='serial_number', brand='sub_model__model__brand__name', model='sub_model__model__name',
                  year='year_start', sub_model='br', variant='sub_model__name', seats='number_of_seats', doors='number_of_doors')
    images = images.annotate(**{f'sort_{key}':Case(When(vehicle__isnull=False,then=F('vehicle__'+field)),
        default=F('folder__vehicle__'+field)) for key,field in fields.items()})
    sorts = {**{key:'sort_'+key for key in fields}, 'uploaded':'uploaded_at', 'uploader':'uploader_label',
             'cad':'stage_cad', 'md_ed':'stage_ed'}
    sort = request.GET.get('status_sort', '')
    direction = 'desc' if request.GET.get('status_direction') == 'desc' else 'asc'
    ordering = [('-' if direction=='desc' else '')+sorts[sort]] if sort in sorts else ['work_priority']
    if sort == 'md_ed':
        ordering.append(('-' if direction=='desc' else '')+'stage_md')
    images = images.order_by(*ordering, '-uploaded_at', '-pk').select_related(
        'uploaded_by', 'vehicle__sub_model__model__brand', 'folder__vehicle__sub_model__model__brand').prefetch_related('approval_requests')
    size = request.GET.get('status_page_size','20')
    size = int(size) if size in ('20','50','100') else 20
    page = Paginator(images, size).get_page(request.GET.get('status_page'))
    review_view = granted(request.user,'design_approval.view')
    history = review_view and granted(request.user,'design.history') and granted(request.user,'design_approval.history')
    rows = []
    for image in page.object_list:
        vehicle = image.vehicle or image.folder.vehicle
        approval = image.latest_approval
        stages = []
        for stage in ('cad','ed','md'):
            status = getattr(approval, stage+'_status', 'not_submitted') if review_view else 'restricted'
            stages.append(dict(role=stage.upper(), status=status, label=PatternDesignApproval.review_status_label(status),
                date=getattr(approval, stage+'_decided_at', None) if history else None))
        identity = vehicle_identity(vehicle)
        rows.append(dict(image=image, vehicle=vehicle, identity=identity, stages=stages,
            outcome=final_outcome(image), outcome_label={'approved':_('Approved'),'rejected':_('Rejected'),'pending':_('Pending')}[final_outcome(image)],
            uploader=image.uploader_label,
            cycle=approval.cycle if approval else None, priority=image.work_priority))
    params = request.GET.copy()
    params['subwindow'] = '3d-status'
    for key in ('status_fragment','status_page'):
        params.pop(key,None)
    columns = [('pattern',_('Pattern Number')),('brand',_('Brand')),('model',_('Model')),('year',_('Year Range')),
        ('sub_model',_('Sub Model')),('variant',_('Variant')),('seats',_('Seats')),('doors',_('Doors')),
        ('uploaded',_('3D Uploaded Date & Time')),('uploader',_('Uploaded User')),('cad',_('Approval (CAD) Status/Date')),
        ('md_ed',_('Approval (MD/ED) Status/Date'))]
    headers = []
    for key,label in columns:
        link = params.copy(); link['status_sort']=key; link['status_direction']='desc' if sort==key and direction=='asc' else 'asc'
        headers.append(dict(key=key,label=label,url='?'+link.urlencode(),selected=sort==key,direction=direction))
    return dict(status_rows=rows,status_page=page,status_headers=headers,status_search=search,
        status_sort=sort if sort in sorts else '',status_direction=direction,status_page_size=size,
        status_page_sizes=(20,50,100),status_pagination=params.urlencode())
