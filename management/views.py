import csv
import io
import json
import logging
import os
import re
import uuid
from io import StringIO, TextIOWrapper

from django.contrib import messages
from django.conf import settings
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth.forms import PasswordChangeForm
from django.contrib.auth.models import Group, Permission, User
from django.contrib.auth.password_validation import validate_password
from django.contrib.sessions.models import Session
from rest_framework.authtoken.models import Token
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.storage import default_storage
from django.core.files.base import ContentFile
from django.core.paginator import Paginator
from django.core.cache import cache
from django.core.validators import validate_email
from django.db import IntegrityError, transaction
from django.db.models import Count, Q, Case, When, Value, IntegerField, Max, OuterRef, Subquery
from django.http import HttpResponse, JsonResponse, QueryDict
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.dateparse import parse_date
from django.utils.text import get_valid_filename
from django.utils.timezone import now
from django.utils import translation
from django.utils.translation import gettext as _, ngettext
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST
from PIL import Image, UnidentifiedImageError

from .forms import (
    AssignUserToGroupForm,
    CarDetailsForm,
    ComplaintForm,
    ApprovalDecisionForm,
    FactoryReviewForm,
    FinalComplaintUpdateForm,
    GroupCreationForm,
    MasterSettingForm,
    SKUForm,
    SKUUploadForm,
    UploadCSVForm,
    UserCreationForm,
    UserWorkflowProfileForm,
)
from .models import (
    ActivityLog,
    ApprovalRoles,
    ApprovalStages,
    Brand,
    ChatMessage,
    Complaint,
    ComplaintApproval,
    ComplaintMedia,
    ComplaintMediaUploadBatch,
    ComplaintTypes,
    complaint_type_master_category,
    DecisionStatuses,
    MasterSetting,
    Model,
    Notification,
    PatternDesignFolder,
    PatternDesignImage,
    SKU,
    SubModel,
    UserProfile,
    WorkflowRoles,
    WorkflowStatuses,
    YearRange,
    format_pattern_serial,
    get_country_letter,
    get_next_pattern_serial,
)
from .services.workflow import (
    REPORT_EDITABLE_FIELDS,
    approval_progress,
    can_start_factory_review,
    allowed_complaint_types_for_user,
    can_user_create_complaint,
    can_user_create_complaint_type,
    can_user_decide_approval,
    can_user_edit_report_step,
    can_user_execute_action,
    can_user_manage_catalog,
    can_user_review_factory_step,
    can_user_view_approvals,
    close_complaint_after_execution,
    complaint_journey_steps,
    get_user_current_approval,
    initialize_created_complaint,
    get_user_profile,
    prepare_complaint_for_create,
    record_approval_decision,
    record_report_edit,
    reporting_country_for_user,
    start_action_execution,
    submit_execution_for_verification,
    submit_factory_review,
    is_workflow_admin,
    visible_complaints_for_user,
)
from .services.media_uploads import (
    MAX_COMPLAINT_MEDIA_FILES,
    attach_verified_uploads,
    create_upload_batch,
    create_upload_ticket,
    discard_uploads,
    get_owned_batch,
    validate_media_metadata,
    verify_pending_uploads,
)
from .services.s3_storage import (
    S3StorageError,
    create_signed_download_url,
)
from .services.cache_versions import cache_version


MAX_CSV_IMPORT_ROWS = 5000
logger = logging.getLogger(__name__)


def _ensure_pattern_thumbnail(design_image):
    """Create a bounded WebP preview while preserving the original asset."""
    if design_image.thumbnail:
        return design_image.thumbnail.url
    if not design_image.image:
        return ''
    try:
        design_image.image.open('rb')
        with Image.open(design_image.image) as source:
            source.seek(0)
            preview = source.convert('RGB')
            preview.thumbnail((640, 480), Image.Resampling.LANCZOS)
            output = io.BytesIO()
            preview.save(output, format='WEBP', quality=82, method=6)
        stem = os.path.splitext(os.path.basename(design_image.image.name))[0][:80]
        design_image.thumbnail.save(
            f'{stem}-{design_image.pk}.webp', ContentFile(output.getvalue()), save=True,
        )
        return design_image.thumbnail.url
    except (OSError, ValueError, UnidentifiedImageError):
        logger.warning('Unable to generate pattern thumbnail for image %s.', design_image.pk, exc_info=True)
        return ''


def _iter_csv_rows(uploaded_file, required_headers):
    """Yield normalized CSV rows while enforcing encoding, headers, and row limits."""
    uploaded_file.seek(0)
    wrapper = TextIOWrapper(uploaded_file.file, encoding='utf-8-sig', newline='')
    try:
        reader = csv.DictReader(wrapper)
        headers = {
            (header or '').strip().lower()
            for header in (reader.fieldnames or [])
        }
        missing = sorted(set(required_headers) - headers)
        if missing:
            raise ValidationError(_("Missing required CSV columns: %(columns)s.") % {'columns': ', '.join(missing)})
        for row_number, row in enumerate(reader, start=2):
            if row_number > MAX_CSV_IMPORT_ROWS + 1:
                raise ValidationError(_('CSV files may contain at most %(count)s data rows.') % {'count': MAX_CSV_IMPORT_ROWS})
            yield row_number, {
                (key or '').strip().lower(): (value or '').strip()
                for key, value in row.items()
            }
    except UnicodeDecodeError as exc:
        raise ValidationError(_('CSV must use UTF-8 encoding.')) from exc
    except csv.Error as exc:
        raise ValidationError(_('CSV could not be parsed: %(error)s.') % {'error': exc}) from exc
    finally:
        try:
            wrapper.detach()
        except (ValueError, OSError):
            pass


def _parse_csv_int(value, label, minimum, maximum):
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f'{label} must be a whole number') from exc
    if not minimum <= parsed <= maximum:
        raise ValueError(f'{label} must be between {minimum} and {maximum}')
    return parsed


def _can_manage_catalog(user):
    return can_user_manage_catalog(user)


def _configure_complaint_form(form, user):
    # Workflow status is advanced by workflow actions, not by report editing.
    if 'status' in form.fields:
        form.fields['status'].disabled = True
    if form.instance.pk:
        for field_name in ('case_sub_category',):
            if field_name in form.fields:
                form.fields[field_name].disabled = True


def _validate_complaint_media_files(uploaded_files, existing_count=0):
    if existing_count + len(uploaded_files) > MAX_COMPLAINT_MEDIA_FILES:
        raise ValidationError(_('Keep at most %(count)s media files on one complaint.') % {'count': MAX_COMPLAINT_MEDIA_FILES})

    for uploaded_file in uploaded_files:
        try:
            validate_media_metadata(
                uploaded_file.name,
                uploaded_file.size,
                getattr(uploaded_file, 'content_type', ''),
            )
        except ValidationError as exc:
            raise ValidationError(f'{uploaded_file.name}: {exc.message}') from exc


def _save_complaint_media_files(complaint, uploaded_files, existing_count=0):
    _validate_complaint_media_files(uploaded_files, existing_count=existing_count)
    stored_names = []
    try:
        for uploaded_file in uploaded_files:
            safe_name = get_valid_filename(uploaded_file.name) or 'media'
            stem, extension = os.path.splitext(safe_name)
            safe_name = f'{stem[:80]}-{uuid.uuid4().hex[:12]}{extension.lower()}'
            relative_path = f'complaint_media/complaint_{complaint.complaint_id}/{safe_name}'
            stored_name = default_storage.save(relative_path, uploaded_file)
            stored_names.append(stored_name)
            ComplaintMedia.objects.create(complaint=complaint, file=stored_name)
    except Exception:
        for stored_name in stored_names:
            default_storage.delete(stored_name)
        raise
    return stored_names


def _delete_complaint_media_record(media):
    # ComplaintMedia's post-delete signal owns physical storage cleanup. Keeping
    # one cleanup path avoids a second unguarded attempt for Windows-locked files.
    media.delete()


def _media_upload_template_context(user, complaint=None):
    if not settings.USE_S3_STORAGE:
        return {'direct_media_uploads': False, 'media_upload_batch': None}
    batch = create_upload_batch(user, complaint=complaint)
    return {'direct_media_uploads': True, 'media_upload_batch': batch}


@login_required
@require_POST
def complaint_media_signed_upload(request):
    if not settings.USE_S3_STORAGE:
        return JsonResponse({'error': 'Direct media uploads are disabled.'}, status=400)
    try:
        payload = json.loads(request.body or b'{}')
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({'error': 'Invalid JSON request.'}, status=400)

    try:
        batch = ComplaintMediaUploadBatch.objects.select_related('complaint').get(
            id=payload.get('batch_id'),
            user=request.user,
        )
    except (ComplaintMediaUploadBatch.DoesNotExist, ValueError, TypeError):
        return JsonResponse({'error': 'Invalid media upload session.'}, status=400)

    complaint = batch.complaint
    if complaint:
        complaint = get_object_or_404(
            visible_complaints_for_user(request.user, Complaint.objects.all()),
            pk=complaint.pk,
        )
        if not can_user_edit_report_step(request.user, complaint):
            raise PermissionDenied('You cannot add media to this complaint.')
    elif not can_user_create_complaint(request.user):
        raise PermissionDenied('Your role cannot create complaints.')

    try:
        with transaction.atomic():
            batch = get_owned_batch(
                request.user,
                batch.id,
                complaint=complaint,
                for_update=True,
            )
            upload, signed_url = create_upload_ticket(
                request.user,
                batch,
                filename=payload.get('filename'),
                size=payload.get('size'),
                content_type=payload.get('content_type'),
                removal_ids=payload.get('delete_media_ids') or [],
            )
    except ValidationError as exc:
        return JsonResponse({'error': '; '.join(exc.messages)}, status=400)
    except S3StorageError:
        logger.exception('Unable to create an S3 signed upload URL.')
        return JsonResponse({'error': 'Unable to prepare the media upload.'}, status=502)

    return JsonResponse({
        'upload_id': str(upload.id),
        'storage_path': upload.storage_path,
        'signed_url': signed_url,
        'content_type': upload.expected_content_type,
        'expires_in': settings.S3_SIGNED_UPLOAD_TTL_SECONDS,
    })


@login_required
@require_POST
def complaint_media_discard_uploads(request):
    try:
        payload = json.loads(request.body or b'{}')
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({'error': 'Invalid JSON request.'}, status=400)
    discarded = discard_uploads(request.user, payload.get('upload_ids') or [])
    return JsonResponse({'discarded': discarded})


@login_required
def complaint_media_download(request, media_id):
    media = get_object_or_404(
        ComplaintMedia.objects.select_related('complaint').filter(
            complaint__in=visible_complaints_for_user(
                request.user,
                Complaint.objects.all(),
            )
        ),
        pk=media_id,
    )
    if settings.USE_S3_STORAGE:
        try:
            return redirect(create_signed_download_url(media.storage_name))
        except S3StorageError:
            logger.exception('Unable to create a signed media download URL for %s.', media.pk)
            return HttpResponse('Media is temporarily unavailable.', status=503)
    return redirect(default_storage.url(media.storage_name))


@login_required
def pattern_design_image_download(request, image_id):
    design_image = get_object_or_404(PatternDesignImage, pk=image_id)
    if not design_image.image:
        return HttpResponse('Image is unavailable.', status=404)
    return redirect(design_image.image.url)

@login_required
def index(request):
    # Get dashboard statistics
    visible_complaints = visible_complaints_for_user(request.user, Complaint.objects.all())
    today = now().date()
    summary_key = f'fabro:dashboard:v{cache_version()}:user:{request.user.pk}:{today:%Y%m}'
    summary = cache.get(summary_key)
    if summary is None:
        summary = visible_complaints.aggregate(
            total_complaints=Count('pk'),
            open_complaints=Count('pk', filter=Q(status='Open')),
            closed_complaints=Count('pk', filter=Q(status='Closed')),
            on_hold_complaints=Count('pk', filter=Q(status='On Hold')),
            pattern_complaints=Count('pk', filter=Q(complaint_type=ComplaintTypes.PATTERN)),
            production_complaints=Count('pk', filter=Q(complaint_type=ComplaintTypes.PRODUCTION)),
            quality_complaints=Count('pk', filter=Q(complaint_type=ComplaintTypes.QUALITY)),
            line_complaints=Count('pk', filter=Q(complaint_type=ComplaintTypes.LINE)),
            complaints_this_month=Count('pk', filter=Q(date__year=today.year, date__month=today.month)),
            resolved_this_month=Count('pk', filter=Q(
                status='Closed', closed_at__year=today.year, closed_at__month=today.month,
            )),
        )
        summary.update({
            'total_vehicles': YearRange.objects.count(),
            'total_skus': SKU.objects.count(),
            'total_settings': MasterSetting.objects.count(),
        })
        cache.set(summary_key, summary, settings.DASHBOARD_CACHE_TTL)
    unread_notifications_qs = Notification.objects.filter(
        recipient=request.user,
        is_read=False,
    ).select_related('complaint')
    unread_notification_count = unread_notifications_qs.count()
    unread_notifications = list(unread_notifications_qs[:4])
    current_profile = get_user_profile(request.user)
    is_approver = bool(current_profile and current_profile.role == WorkflowRoles.APPROVER)
    is_admin = bool(request.user.is_superuser or (current_profile and current_profile.role == WorkflowRoles.ADMIN))
    is_approver_or_admin = is_approver or is_admin

    active_approval_workflow_statuses = [
        WorkflowStatuses.AWAITING_APPROVAL,
        WorkflowStatuses.PARTIALLY_APPROVED,
        WorkflowStatuses.AWAITING_EXECUTION_VERIFICATION,
        WorkflowStatuses.EXECUTION_PARTIALLY_VERIFIED,
    ]

    pending_approvals_list = []
    pending_approvals_total = 0

    if is_approver:
        approvals_qs = ComplaintApproval.objects.filter(
            approver_user=request.user,
            status=DecisionStatuses.PENDING,
            complaint__workflow_status__in=active_approval_workflow_statuses,
        ).select_related(
            'complaint__brand',
            'complaint__model',
            'complaint__sub_model',
            'complaint__year',
            'complaint__person',
            'complaint__sku',
            'approver_user',
        ).order_by('-pk')
        pending_approvals_total = approvals_qs.count()
        pending_approval_count = pending_approvals_total
        pending_approvals_list = list(approvals_qs[:10])
    elif is_admin:
        approvals_qs = ComplaintApproval.objects.filter(
            status=DecisionStatuses.PENDING,
            complaint__workflow_status__in=active_approval_workflow_statuses,
        ).select_related(
            'complaint__brand',
            'complaint__model',
            'complaint__sub_model',
            'complaint__year',
            'complaint__person',
            'complaint__sku',
            'approver_user',
        ).order_by('-pk')
        pending_approvals_total = approvals_qs.count()
        pending_approval_count = pending_approvals_total
        pending_approvals_list = list(approvals_qs[:10])
    else:
        pending_approval_count = 0

    complaints_limit = 10 if is_approver_or_admin else 15

    context = {
        **summary,
        'dashboard_notifications': unread_notifications[:4],
        'unread_notification_count': unread_notification_count,
        'pending_approval_count': pending_approval_count,
        'is_approver_or_admin': is_approver_or_admin,
        'pending_approvals_list': pending_approvals_list,
        'pending_approvals_total': pending_approvals_total,
        'recent_complaints': visible_complaints.select_related(
            'brand', 'model', 'sub_model', 'year', 'person', 'sku'
        ).annotate(
            sort_weight=Case(
                When(status='Closed', then=Value(1)),
                When(workflow_status='closed', then=Value(1)),
                default=Value(0),
                output_field=IntegerField(),
            )
        ).order_by('sort_weight', '-date')[:complaints_limit],
    }
    request._fabro_badges = {'pending_approvals_count': pending_approval_count}
    return render(request, 'management/index.html', context)


@login_required
def car_details(request):
    search_query = request.GET.get('search', '').strip()
    search_column = (request.GET.get('search_by') or request.GET.get('column', 'all')).strip()
    show_duplicate_modal = False
    show_layout_code_error_modal = False
    conflicting_car = None
    form = CarDetailsForm()

    if request.method == "POST":
        if not _can_manage_catalog(request.user):
            raise PermissionDenied('Only staff users can add vehicles.')
        form = CarDetailsForm(request.POST, request.FILES)
        if form.is_valid():
            layout_code = form.cleaned_data["layout_code"]
            brand_name = form.cleaned_data["brand_name"]
            brand_logo = form.cleaned_data.get("brand_logo")
            model_name = form.cleaned_data["model_name"]
            sub_model_name = form.cleaned_data["sub_model_name"] or '-'
            year_start = form.cleaned_data["year_start"]
            year_end = form.cleaned_data["year_end"]
            number_of_seats = form.cleaned_data["number_of_seats"]
            number_of_doors = form.cleaned_data["number_of_doors"]

            brand, created = Brand.objects.get_or_create(name=brand_name)
            
            # Update brand logo if provided
            if brand_logo:
                brand.logo = brand_logo
                brand.save()
            
            model, model_created = Model.objects.get_or_create(brand=brand, name=model_name)
            sub_model, sub_model_created = SubModel.objects.get_or_create(model=model, name=sub_model_name)

            # ✅ Check for layout code duplication
            if YearRange.objects.filter(layout_code=layout_code).exists():
                show_layout_code_error_modal = True

            # ✅ Check for year range overlap
            elif YearRange.objects.filter(
                sub_model=sub_model,
                year_start__lte=year_end,
                year_end__gte=year_start
            ).exists():
                show_duplicate_modal = True
                conflicting = YearRange.objects.filter(
                    sub_model=sub_model,
                    year_start__lte=year_end,
                    year_end__gte=year_start
                ).first()
                conflicting_car = {
                    "layout_code": conflicting.layout_code,
                    "brand": brand.name,
                    "model": model.name,
                    "sub_model": sub_model.name,
                    "year_start": conflicting.year_start,
                    "year_end": conflicting.year_end,
                    "number_of_seats": conflicting.number_of_seats,
                    "number_of_doors": conflicting.number_of_doors
                }

            else:
                x_code_val = (form.cleaned_data.get("x_code") or "").strip()
                fitting_conf_val = (form.cleaned_data.get("fitting_confirmation") or "").strip()
                serial_num_val = (form.cleaned_data.get("serial_number") or "").strip()
                YearRange.objects.create(
                    sub_model=sub_model,
                    serial_number=serial_num_val,
                    year_start=year_start,
                    year_end=year_end,
                    number_of_seats=number_of_seats,
                    number_of_doors=number_of_doors,
                    layout_code=layout_code or None,
                    x_code=x_code_val,
                    fitting_confirmation=fitting_conf_val,
                    vehicle_country=form.cleaned_data.get("vehicle_country"),
                    measurement_country=form.cleaned_data.get("measurement_country")
                )
                ActivityLog.objects.create(
                    user=request.user,
                    action="created",
                    object_type="Car",
                    object_name=f"{brand_name} {model_name} {sub_model_name} ({year_start}-{year_end})"
                )
                messages.success(request, _('Pattern added successfully.'))
                return redirect('car_details')

    new_search_enabled = True
    scoped_search_enabled = True

    # Fetch car data (Optimized via select_related)
    yr_qs = YearRange.objects.select_related('sub_model__model__brand', 'vehicle_country', 'measurement_country').order_by('id')
    if search_query:
        if search_column in ('serial_number', 'serial_no', 'serial'):
            yr_qs = yr_qs.filter(serial_number__icontains=search_query)
        elif search_column == 'x_code':
            yr_qs = yr_qs.filter(Q(x_code__icontains=search_query) | Q(layout_code__icontains=search_query))
        elif search_column == 'fitting_confirmation':
            yr_qs = yr_qs.filter(fitting_confirmation__icontains=search_query)
        elif search_column == 'layout_code':
            yr_qs = yr_qs.filter(Q(layout_code__icontains=search_query) | Q(x_code__icontains=search_query))
        elif search_column == 'brand':
            yr_qs = yr_qs.filter(sub_model__model__brand__name__icontains=search_query)
        elif search_column == 'model':
            yr_qs = yr_qs.filter(sub_model__model__name__icontains=search_query)
        elif search_column == 'sub_model':
            yr_qs = yr_qs.filter(sub_model__name__icontains=search_query)
        elif search_column == 'vehicle_country':
            yr_qs = yr_qs.filter(vehicle_country__name__icontains=search_query)
        elif search_column == 'measurement_country':
            yr_qs = yr_qs.filter(measurement_country__name__icontains=search_query)
        else:
            yr_qs = yr_qs.filter(
                Q(serial_number__icontains=search_query) |
                Q(x_code__icontains=search_query) |
                Q(fitting_confirmation__icontains=search_query) |
                Q(layout_code__icontains=search_query) |
                Q(sub_model__model__brand__name__icontains=search_query) |
                Q(sub_model__model__name__icontains=search_query) |
                Q(sub_model__name__icontains=search_query) |
                Q(vehicle_country__name__icontains=search_query) |
                Q(measurement_country__name__icontains=search_query)
            )

    vehicle_paginator = Paginator(yr_qs, 50)
    vehicle_page = vehicle_paginator.get_page(request.GET.get('page'))
    car_data = []
    for yr in vehicle_page.object_list:
        car_data.append({
            "serial_number": yr.serial_number or '',
            "layout_code": yr.layout_code,
            "x_code": yr.x_code or yr.layout_code or '-',
            "raw_x_code": yr.x_code or '',
            "fitting_confirmation": yr.fitting_confirmation or '-',
            "raw_fitting_confirmation": yr.fitting_confirmation or '',
            "id": yr.id,
            "brand_id": yr.sub_model.model.brand.id if yr.sub_model and yr.sub_model.model and yr.sub_model.model.brand else None,
            "brand": yr.sub_model.model.brand.name if yr.sub_model and yr.sub_model.model and yr.sub_model.model.brand else '',
            "brand_logo": yr.sub_model.model.brand.logo if yr.sub_model and yr.sub_model.model and yr.sub_model.model.brand else None,
            "model_id": yr.sub_model.model.id if yr.sub_model and yr.sub_model.model else None,
            "model": yr.sub_model.model.name if yr.sub_model and yr.sub_model.model else '',
            "sub_model_id": yr.sub_model.id if yr.sub_model else None,
            "sub_model": yr.sub_model.name if yr.sub_model else '',
            "raw_sub_model": yr.sub_model.name if (yr.sub_model and yr.sub_model.name != '-') else '',
            "year_start": yr.year_start,
            "year_end": yr.year_end,
            "seats": yr.number_of_seats,
            "doors": yr.number_of_doors,
            "vehicle_country": yr.vehicle_country.name if yr.vehicle_country else '-',
            "vehicle_country_id": yr.vehicle_country.id if yr.vehicle_country else None,
            "measurement_country": yr.measurement_country.name if yr.measurement_country else '-',
            "measurement_country_id": yr.measurement_country.id if yr.measurement_country else None,
        })

    countries = MasterSetting.objects.filter(category='Country').order_by('name')

    can_manage_catalog = _can_manage_catalog(request.user)
    next_serial_number = get_next_pattern_serial()
    pagination_params = request.GET.copy()
    pagination_params.pop('page', None)

    return render(request, 'management/car_details.html', {
        'form': form,
        'car_data': car_data,
        'countries': countries,
        'next_serial_number': next_serial_number,
        'show_duplicate_modal': show_duplicate_modal,
        'show_layout_code_error_modal': show_layout_code_error_modal,
        'conflicting_car': conflicting_car,
        'search_query': search_query,
        'search_column': search_column,
        'search_by': search_column,
        'new_search_enabled': new_search_enabled,
        'scoped_search_enabled': scoped_search_enabled,
        'can_manage_catalog': can_manage_catalog,
        'page_obj': vehicle_page,
        'pagination_querystring': pagination_params.urlencode(),
    })


@login_required
def pattern_vehicle_list_api(request):
    """Small server-filtered catalogue response for progressive UI consumers."""
    search = request.GET.get('search', '').strip()[:100]
    queryset = YearRange.objects.select_related(
        'sub_model__model__brand', 'vehicle_country', 'measurement_country'
    ).order_by('id')
    if search:
        queryset = queryset.filter(
            Q(serial_number__icontains=search)
            | Q(layout_code__icontains=search)
            | Q(x_code__icontains=search)
            | Q(sub_model__model__brand__name__icontains=search)
            | Q(sub_model__model__name__icontains=search)
            | Q(sub_model__name__icontains=search)
        )
    page = Paginator(queryset, 50).get_page(request.GET.get('page'))
    results = [{
        'id': vehicle.pk,
        'serial_number': vehicle.serial_number,
        'layout_code': vehicle.layout_code,
        'brand': vehicle.sub_model.model.brand.name,
        'model': vehicle.sub_model.model.name,
        'sub_model': vehicle.sub_model.name,
        'year_start': vehicle.year_start,
        'year_end': vehicle.year_end,
    } for vehicle in page.object_list]
    return JsonResponse({
        'results': results,
        'count': page.paginator.count,
        'page': page.number,
        'pages': page.paginator.num_pages,
        'has_next': page.has_next(),
        'has_previous': page.has_previous(),
    })


@login_required
def pattern_vehicle_count_api(request):
    return JsonResponse({'count': YearRange.objects.count()})


@login_required
@require_POST
def delete_car_detail(request, year_range_id):
    if not _can_manage_catalog(request.user):
        raise PermissionDenied('Only staff users can delete vehicles.')
    year_range = get_object_or_404(YearRange, id=year_range_id)
    brand_name = year_range.sub_model.model.brand.name if year_range.sub_model else ''
    model_name = year_range.sub_model.model.name if year_range.sub_model else ''
    sub_model_name = year_range.sub_model.name if year_range.sub_model else ''
    year_start = year_range.year_start
    year_end = year_range.year_end

    year_range.delete()
    messages.success(request, _('Vehicle deleted successfully.'))
    ActivityLog.objects.create(
        user=request.user,
        action="deleted",
        object_type="Car",
        object_name=f"{brand_name} {model_name} {sub_model_name} ({year_start}-{year_end})"
    )
    return redirect('car_details')


@login_required
@require_POST
def update_fitting_confirmation_api(request, year_range_id):
    if not _can_manage_catalog(request.user):
        return JsonResponse({"success": False, "error": _("Permission denied.")}, status=403)
    
    year_range = get_object_or_404(YearRange, id=year_range_id)
    
    try:
        data = json.loads(request.body.decode('utf-8'))
    except Exception:
        data = request.POST

    fitting_val = (data.get("fitting_confirmation") or "").strip()
    
    # Allowed choices
    allowed_choices = ['Confirmed', 'Pending', 'Rework', 'Sampling', '']
    if fitting_val not in allowed_choices:
        return JsonResponse({"success": False, "error": _("Invalid fitting confirmation value.")}, status=400)
    
    year_range.fitting_confirmation = fitting_val
    year_range.save()
    
    brand_name = year_range.sub_model.model.brand.name if year_range.sub_model and year_range.sub_model.model and year_range.sub_model.model.brand else ''
    model_name = year_range.sub_model.model.name if year_range.sub_model and year_range.sub_model.model else ''
    
    ActivityLog.objects.create(
        user=request.user,
        action="updated",
        object_type="Fitting Confirmation",
        object_name=f"{brand_name} {model_name} -> {fitting_val or 'Cleared'}"
    )
    
    return JsonResponse({
        "success": True,
        "id": year_range.id,
        "fitting_confirmation": fitting_val,
        "message": _("Fitting confirmation updated successfully.")
    })


@login_required
def get_next_pattern_serial_api(request):
    country_id = request.GET.get('country_id')
    exclude_id = request.GET.get('exclude_id')
    country = None
    if country_id:
        try:
            country = MasterSetting.objects.filter(category='Country', id=country_id).first()
        except (ValueError, TypeError):
            pass
    try:
        exclude_id = int(exclude_id) if exclude_id else None
    except (ValueError, TypeError):
        exclude_id = None

    next_serial = get_next_pattern_serial(country=country, exclude_id=exclude_id)
    return JsonResponse({'success': True, 'next_serial': next_serial})


@login_required
def edit_car_detail(request, car_id):
    if not _can_manage_catalog(request.user):
        if request.headers.get('x-requested-with') == 'XMLHttpRequest' or request.POST.get('is_ajax') == '1':
            return JsonResponse({'success': False, 'error': _('Only staff users can edit vehicles.')}, status=403)
        raise PermissionDenied('Only staff users can edit vehicles.')
    year_range = get_object_or_404(YearRange, id=car_id)
    existing_logo = year_range.sub_model.model.brand.logo if (year_range.sub_model and year_range.sub_model.model and year_range.sub_model.model.brand) else None

    # Prepopulate form values
    initial_data = {
        'serial_number': year_range.serial_number,
        'layout_code': year_range.layout_code,
        'x_code': year_range.x_code,
        'fitting_confirmation': year_range.fitting_confirmation,
        'brand_name': year_range.sub_model.model.brand.name if year_range.sub_model else '',
        'model_name': year_range.sub_model.model.name if year_range.sub_model else '',
        'sub_model_name': year_range.sub_model.name if year_range.sub_model else '',
        'year_start': year_range.year_start,
        'year_end': year_range.year_end,
        'number_of_seats': year_range.number_of_seats,
        'number_of_doors': year_range.number_of_doors,
        'vehicle_country': year_range.vehicle_country,
        'measurement_country': year_range.measurement_country,
    }

    countries = MasterSetting.objects.filter(category='Country').order_by('name')

    if request.method == "POST":
        is_ajax = request.headers.get('x-requested-with') == 'XMLHttpRequest' or request.POST.get('is_ajax') == '1'
        form = CarDetailsForm(request.POST, request.FILES)
        if form.is_valid():
            layout_code = (form.cleaned_data.get("layout_code") or "").strip()
            x_code = (form.cleaned_data.get("x_code") or "").strip()
            fitting_confirmation = (form.cleaned_data.get("fitting_confirmation") or "").strip()
            brand_name = form.cleaned_data["brand_name"].strip()
            brand_logo = form.cleaned_data.get("brand_logo")
            model_name = form.cleaned_data["model_name"].strip()
            sub_model_name = (form.cleaned_data.get("sub_model_name") or "").strip() or '-'
            year_start = form.cleaned_data.get("year_start")
            year_end = form.cleaned_data.get("year_end")
            number_of_seats = form.cleaned_data.get("number_of_seats")
            number_of_doors = form.cleaned_data.get("number_of_doors")

            # Check for layout code duplication if layout_code provided
            if layout_code and YearRange.objects.filter(layout_code=layout_code).exclude(id=car_id).exists():
                err_msg = _('Layout code already exists. Please use a unique layout code.')
                if is_ajax:
                    return JsonResponse({'success': False, 'error': str(err_msg)}, status=400)
                messages.error(request, err_msg)
                return redirect('car_details')

            brand, brand_created = Brand.objects.get_or_create(name=brand_name)
            
            # Update brand logo if provided
            if brand_logo:
                brand.logo = brand_logo
                brand.save()
            
            model, model_created = Model.objects.get_or_create(brand=brand, name=model_name)

            sub_model = None
            if sub_model_name:
                sub_model, sub_model_created = SubModel.objects.get_or_create(model=model, name=sub_model_name)

            # Update the existing YearRange
            year_range.sub_model = sub_model
            year_range.year_start = year_start
            year_range.year_end = year_end
            year_range.number_of_seats = number_of_seats
            year_range.number_of_doors = number_of_doors
            if layout_code:
                year_range.layout_code = layout_code
            year_range.x_code = x_code
            year_range.fitting_confirmation = fitting_confirmation
            year_range.vehicle_country = form.cleaned_data.get("vehicle_country")
            year_range.measurement_country = form.cleaned_data.get("measurement_country")
            serial_number = (form.cleaned_data.get("serial_number") or "").strip()
            if serial_number:
                year_range.serial_number = serial_number
            year_range.save()

            ActivityLog.objects.create(
                user=request.user,
                action="updated",
                object_type="Car",
                object_name=f"{brand_name} {model_name} {sub_model_name} ({year_start or ''}-{year_end or ''})"
            )

            if is_ajax:
                return JsonResponse({
                    'success': True,
                    'message': _('Vehicle updated successfully.'),
                    'car': {
                        'id': year_range.id,
                        'serial_number': year_range.serial_number or '',
                        'brand': brand.name,
                        'brand_logo': brand.logo.url if brand.logo else '',
                        'model': model.name,
                        'sub_model': year_range.sub_model.name if year_range.sub_model else '',
                        'raw_sub_model': year_range.sub_model.name if (year_range.sub_model and year_range.sub_model.name != '-') else '',
                        'year_start': year_range.year_start,
                        'year_end': year_range.year_end,
                        'seats': year_range.number_of_seats,
                        'doors': year_range.number_of_doors,
                        'x_code': year_range.x_code or '',
                        'fitting_confirmation': year_range.fitting_confirmation or '',
                        'vehicle_country': year_range.vehicle_country.name if year_range.vehicle_country else '-',
                        'vehicle_country_id': year_range.vehicle_country.id if year_range.vehicle_country else None,
                        'measurement_country': year_range.measurement_country.name if year_range.measurement_country else '-',
                        'measurement_country_id': year_range.measurement_country.id if year_range.measurement_country else None,
                    }
                })

            messages.success(request, _('Vehicle updated successfully.'))
            return redirect('car_details')
        else:
            error_list = []
            for field, errs in form.errors.items():
                error_list.append(f"{field}: {', '.join(errs)}")
            err_msg = _('Failed to update vehicle: ') + '; '.join(error_list)
            if is_ajax:
                return JsonResponse({'success': False, 'error': err_msg}, status=400)
            messages.error(request, err_msg)
            return redirect('car_details')
    else:
        form = CarDetailsForm(initial=initial_data)

    return render(request, 'management/edit_car_detail.html', {
        'form': form,
        'car_id': car_id,
        'existing_logo': existing_logo,
        'countries': countries,
    })


@login_required
def get_design_folders_api(request):
    vehicle_id = request.GET.get('vehicle_id')
    vehicle_info = None
    direct_images_data = []
    if vehicle_id:
        try:
            yr = YearRange.objects.select_related('sub_model__model__brand').get(id=vehicle_id)
            brand_name = yr.sub_model.model.brand.name if yr.sub_model and yr.sub_model.model and yr.sub_model.model.brand else ''
            model_name = yr.sub_model.model.name if yr.sub_model and yr.sub_model.model else ''
            sub_name = yr.sub_model.name if yr.sub_model and yr.sub_model.name != '-' else ''
            years = f"{yr.year_start}-{yr.year_end}" if yr.year_start and yr.year_end else ''
            formatted_name = f"{brand_name} {model_name} {years} {sub_name}".strip()
            vehicle_info = {
                'id': yr.id,
                'name': formatted_name,
                'brand': brand_name,
                'model': model_name,
                'year_range': years,
                'sub_model': sub_name,
                'google_drive_url': yr.google_drive_url or '',
            }
            folders = PatternDesignFolder.objects.filter(vehicle=yr).annotate(image_total=Count('images'))
            direct_page = Paginator(
                PatternDesignImage.objects.filter(vehicle=yr, folder__isnull=True).order_by('-uploaded_at'),
                4,
            ).get_page(request.GET.get('image_page'))
            direct_imgs = direct_page.object_list
            for img in direct_imgs:
                if img.image:
                    direct_images_data.append({
                        'id': img.id,
                        'url': _ensure_pattern_thumbnail(img),
                        'original_url': reverse('pattern_design_image_download', args=[img.pk]),
                        'title': img.title or os.path.basename(img.image.name),
                        'file_size': img.file_size,
                        'uploaded_at': img.uploaded_at.strftime('%b %d, %Y %H:%M'),
                    })
        except YearRange.DoesNotExist:
            folders = PatternDesignFolder.objects.none()
            direct_page = Paginator(PatternDesignImage.objects.none(), 4).get_page(1)
    else:
        # Keep the legacy unscoped API response for integrations that do not yet
        # send a vehicle. The Pattern Master itself always supplies vehicle_id
        # and never calls this endpoint during its initial render.
        folders = PatternDesignFolder.objects.annotate(image_total=Count('images')).order_by('-created_at', '-pk')
        direct_page = Paginator(PatternDesignImage.objects.none(), 4).get_page(1)

    folder_page = Paginator(folders, 20).get_page(request.GET.get('folder_page'))
    data = []
    preview_rows = PatternDesignImage.objects.filter(
        folder_id__in=[folder.pk for folder in folder_page.object_list]
    ).order_by('folder_id', '-uploaded_at')
    previews_by_folder = {}
    for image in preview_rows:
        bucket = previews_by_folder.setdefault(image.folder_id, [])
        if len(bucket) < 4 and image.image:
            thumbnail_url = _ensure_pattern_thumbnail(image)
            if thumbnail_url:
                bucket.append(thumbnail_url)
    for f in folder_page.object_list:
        data.append({
            'id': f.id,
            'name': f.name,
            'description': f.description,
            'image_count': f.image_total,
            'created_at': f.created_at.strftime('%b %d, %Y'),
            'preview_images': previews_by_folder.get(f.pk, []),
            'vehicle_id': f.vehicle_id,
        })
    return JsonResponse({
        'status': 'success',
        'folders': data,
        'direct_images': direct_images_data,
        'vehicle': vehicle_info,
        'folder_pagination': {'page': folder_page.number, 'pages': folder_page.paginator.num_pages},
        'image_pagination': {'page': direct_page.number, 'pages': direct_page.paginator.num_pages},
    })


@login_required
@require_POST
def create_design_folder_api(request):
    if not _can_manage_catalog(request.user):
        return JsonResponse({'status': 'error', 'message': _('Permission denied.')}, status=403)
    name = (request.POST.get('name') or '').strip()
    if not name:
        return JsonResponse({'status': 'error', 'message': _('Folder name is required.')}, status=400)
    if len(name) > 150:
        return JsonResponse({'status': 'error', 'message': _('Folder name must be 150 characters or fewer.')}, status=400)

    vehicle_id = request.POST.get('vehicle_id')
    vehicle = None
    if vehicle_id:
        try:
            vehicle = YearRange.objects.get(id=vehicle_id)
        except YearRange.DoesNotExist:
            vehicle = None

    folder = PatternDesignFolder.objects.create(
        name=name,
        vehicle=vehicle,
        created_by=request.user
    )
    ActivityLog.objects.create(
        user=request.user,
        action='created',
        object_type='Design Folder',
        object_name=folder.name,
    )
    return JsonResponse({
        'status': 'success',
        'folder': {
            'id': folder.id,
            'name': folder.name,
            'description': folder.description,
            'image_count': 0,
            'created_at': folder.created_at.strftime('%b %d, %Y'),
            'preview_images': [],
            'vehicle_id': folder.vehicle_id,
        }
    })


@login_required
def get_design_folder_detail_api(request, folder_id):
    folder = get_object_or_404(PatternDesignFolder.objects.select_related('vehicle__sub_model__model__brand'), id=folder_id)
    image_page = Paginator(folder.images.all(), 4).get_page(request.GET.get('page'))
    image_list = []
    for img in image_page.object_list:
        if img.image:
            image_list.append({
                'id': img.id,
                'url': _ensure_pattern_thumbnail(img),
                'original_url': reverse('pattern_design_image_download', args=[img.pk]),
                'title': img.title or os.path.basename(img.image.name),
                'file_size': img.file_size,
                'uploaded_at': img.uploaded_at.strftime('%b %d, %Y %H:%M'),
            })

    vehicle_info = None
    if folder.vehicle:
        yr = folder.vehicle
        brand_name = yr.sub_model.model.brand.name if yr.sub_model and yr.sub_model.model and yr.sub_model.model.brand else ''
        model_name = yr.sub_model.model.name if yr.sub_model and yr.sub_model.model else ''
        sub_name = yr.sub_model.name if yr.sub_model and yr.sub_model.name != '-' else ''
        years = f"{yr.year_start}-{yr.year_end}" if yr.year_start and yr.year_end else ''
        formatted_name = f"{brand_name} {model_name} {years} {sub_name}".strip()
        vehicle_info = {
            'id': yr.id,
            'name': formatted_name,
        }

    return JsonResponse({
        'status': 'success',
        'folder': {
            'id': folder.id,
            'name': folder.name,
            'description': folder.description,
            'image_count': folder.images.count(),
            'created_at': folder.created_at.strftime('%b %d, %Y'),
            'vehicle_id': folder.vehicle_id,
            'vehicle': vehicle_info,
        },
        'images': image_list,
        'pagination': {'page': image_page.number, 'pages': image_page.paginator.num_pages},
    })


@login_required
@require_POST
def rename_design_folder_api(request, folder_id):
    if not _can_manage_catalog(request.user):
        return JsonResponse({'status': 'error', 'message': _('Permission denied.')}, status=403)
    folder = get_object_or_404(PatternDesignFolder, id=folder_id)
    name = (request.POST.get('name') or '').strip()
    if not name:
        return JsonResponse({'status': 'error', 'message': _('Folder name is required.')}, status=400)
    if len(name) > 150:
        return JsonResponse({'status': 'error', 'message': _('Folder name must be 150 characters or fewer.')}, status=400)
    folder.name = name
    folder.save(update_fields=['name', 'updated_at'])
    return JsonResponse({'status': 'success', 'name': folder.name})


@login_required
@require_POST
def delete_design_folder_api(request, folder_id):
    if not _can_manage_catalog(request.user):
        return JsonResponse({'status': 'error', 'message': _('Permission denied.')}, status=403)
    folder = get_object_or_404(PatternDesignFolder, id=folder_id)
    for img in folder.images.all():
        if img.image:
            try:
                default_storage.delete(img.image.name)
            except Exception:
                pass
        if img.thumbnail:
            try:
                default_storage.delete(img.thumbnail.name)
            except Exception:
                pass
    folder_name = folder.name
    folder.delete()
    ActivityLog.objects.create(
        user=request.user,
        action='deleted',
        object_type='Design Folder',
        object_name=folder_name,
    )
    return JsonResponse({'status': 'success'})


@login_required
@require_POST
def upload_design_images_api(request, folder_id):
    if not _can_manage_catalog(request.user):
        return JsonResponse({'status': 'error', 'message': _('Permission denied.')}, status=403)
    folder = get_object_or_404(PatternDesignFolder, id=folder_id)
    files = request.FILES.getlist('images')
    if not files:
        return JsonResponse({'status': 'error', 'message': _('No files uploaded.')}, status=400)

    allowed_exts = {'.jpg', '.jpeg', '.png', '.webp', '.gif'}
    max_size = 30 * 1024 * 1024  # 30MB
    created_images = []

    for file_obj in files:
        ext = os.path.splitext(file_obj.name)[1].lower()
        if ext not in allowed_exts:
            continue
        if file_obj.size > max_size:
            continue

        design_img = PatternDesignImage(
            folder=folder,
            image=file_obj,
            title=file_obj.name,
            file_size=file_obj.size,
            uploaded_by=request.user,
        )
        design_img.save()
        thumbnail_url = _ensure_pattern_thumbnail(design_img)
        created_images.append({
            'id': design_img.id,
            'url': thumbnail_url,
            'title': design_img.title,
            'file_size': design_img.file_size,
            'uploaded_at': design_img.uploaded_at.strftime('%b %d, %Y %H:%M'),
        })

    return JsonResponse({
        'status': 'success',
        'uploaded_count': len(created_images),
        'images': created_images,
        'total_count': folder.images.count(),
    })


@login_required
@require_POST
def upload_vehicle_design_images_api(request, vehicle_id):
    if not _can_manage_catalog(request.user):
        return JsonResponse({'status': 'error', 'message': _('Permission denied.')}, status=403)
    vehicle = get_object_or_404(YearRange, id=vehicle_id)
    files = request.FILES.getlist('images')
    if not files:
        return JsonResponse({'status': 'error', 'message': _('No files uploaded.')}, status=400)

    allowed_exts = {'.jpg', '.jpeg', '.png', '.webp', '.gif'}
    max_size = 30 * 1024 * 1024  # 30MB
    created_images = []

    for file_obj in files:
        ext = os.path.splitext(file_obj.name)[1].lower()
        if ext not in allowed_exts:
            continue
        if file_obj.size > max_size:
            continue

        design_img = PatternDesignImage(
            vehicle=vehicle,
            folder=None,
            image=file_obj,
            title=file_obj.name,
            file_size=file_obj.size,
            uploaded_by=request.user,
        )
        design_img.save()
        thumbnail_url = _ensure_pattern_thumbnail(design_img)
        created_images.append({
            'id': design_img.id,
            'url': thumbnail_url,
            'title': design_img.title,
            'file_size': design_img.file_size,
            'uploaded_at': design_img.uploaded_at.strftime('%b %d, %Y %H:%M'),
        })

    return JsonResponse({
        'status': 'success',
        'uploaded_count': len(created_images),
        'images': created_images,
        'total_count': PatternDesignImage.objects.filter(vehicle=vehicle, folder__isnull=True).count(),
    })


@login_required
@require_POST
def update_vehicle_google_drive_api(request, vehicle_id):
    if not _can_manage_catalog(request.user):
        return JsonResponse({'status': 'error', 'message': _('Permission denied.')}, status=403)
    vehicle = get_object_or_404(YearRange, id=vehicle_id)
    drive_url = (request.POST.get('google_drive_url') or '').strip()
    vehicle.google_drive_url = drive_url
    vehicle.save(update_fields=['google_drive_url'])
    return JsonResponse({
        'status': 'success',
        'google_drive_url': vehicle.google_drive_url
    })


@login_required
@require_POST
def delete_design_image_api(request, image_id):
    if not _can_manage_catalog(request.user):
        return JsonResponse({'status': 'error', 'message': _('Permission denied.')}, status=403)
    img = get_object_or_404(PatternDesignImage, id=image_id)
    folder_id = img.folder_id
    vehicle_id = img.vehicle_id
    if img.image:
        try:
            default_storage.delete(img.image.name)
        except Exception:
            pass
    if img.thumbnail:
        try:
            default_storage.delete(img.thumbnail.name)
        except Exception:
            pass
    img.delete()
    remaining = PatternDesignImage.objects.filter(folder_id=folder_id).count() if folder_id else PatternDesignImage.objects.filter(vehicle_id=vehicle_id, folder__isnull=True).count()
    return JsonResponse({
        'status': 'success',
        'remaining_count': remaining
    })


@login_required
def master_settings(request):
    if not is_workflow_admin(request.user):
        messages.error(request, _("This page is restricted to administrators only."))
        return redirect('index')
    
    if request.method == "POST":
        form = MasterSettingForm(request.POST)
        if form.is_valid():
            mas=form.save()
            ActivityLog.objects.create(
                user=request.user,
                action="created",
                object_type="Master Setting",
                object_name=mas.category + " - " + mas.name
            )
            return redirect('master_settings')
    else:
        form = MasterSettingForm()

    # Fetch existing master settings, grouped by category
    master_settings = {}
    for category, category_label in MasterSetting.CATEGORY_CHOICES:
        if category in {'Country', 'Reported By'}:
            continue
        master_settings[category] = MasterSetting.objects.filter(category=category)

    return render(request, 'management/master_settings.html', {
        'form': form,
        'master_settings': master_settings
    })

@login_required
@require_POST
def edit_master_setting(request, setting_id):
    if not is_workflow_admin(request.user):
        raise PermissionDenied('Only administrators can edit master settings.')
    setting = get_object_or_404(MasterSetting, id=setting_id)

    if request.method == 'POST':
        form = MasterSettingForm(request.POST, instance=setting)
        if form.is_valid():
            form.save()
            ActivityLog.objects.create(
                user=request.user,
                action="updated",
                object_type="Master Setting",
                object_name=setting.category + " - " + setting.name
            )
            return redirect('master_settings')
    else:
        form = MasterSettingForm(instance=setting)

    return render(request, 'management/edit_master_setting.html', {
        'form': form,
        'setting': setting
    })

@login_required
@require_POST
def delete_master_setting(request, setting_id):
    if not is_workflow_admin(request.user):
        raise PermissionDenied('Only administrators can delete master settings.')
    setting = get_object_or_404(MasterSetting, id=setting_id)
    ActivityLog.objects.create(
        user=request.user,
        action="deleted",
        object_type="Master Setting",
        object_name=setting.category + " - " + setting.name
    )
    setting.delete()
    return redirect('master_settings')


@login_required
def add_complaint(request):
    if not can_user_create_complaint(request.user):
        raise PermissionDenied('Your role can view complaints but cannot create them.')
    allowed_complaint_types = allowed_complaint_types_for_user(request.user)
    default_complaint_type = allowed_complaint_types[0]
    selected_complaint_type = request.POST.get('complaint_type', default_complaint_type)
    if request.method == 'POST' and not can_user_create_complaint_type(
        request.user,
        selected_complaint_type,
    ):
        raise PermissionDenied('Your role cannot create the selected complaint type.')
    if selected_complaint_type not in allowed_complaint_types:
        selected_complaint_type = default_complaint_type
    template_context = {
        'selected_complaint_type': selected_complaint_type,
        'allowed_complaint_types': allowed_complaint_types,
        'complaint_type_dock_width': {1: 280, 3: 760, 4: 980}.get(
            len(allowed_complaint_types),
            980,
        ),
        'direct_media_uploads': settings.USE_S3_STORAGE,
        'media_upload_batch': None,
    }
    if request.method == 'POST':
        form = ComplaintForm(request.POST, complaint_type=selected_complaint_type)
        _configure_complaint_form(form, request.user)
        uploaded_files = request.FILES.getlist('media_files')
        upload_ids = request.POST.getlist('media_upload_ids')
        upload_batch_id = request.POST.get('media_upload_batch')
        if settings.USE_S3_STORAGE and uploaded_files:
            form.add_error(None, _('Complaint media must be uploaded directly to object storage.'))
        try:
            if not settings.USE_S3_STORAGE:
                _validate_complaint_media_files(uploaded_files)
        except ValidationError as exc:
            form.add_error(None, exc)
            if upload_ids:
                discard_uploads(request.user, upload_ids)
            template_context.update(_media_upload_template_context(request.user))
            return render(request, 'management/add_complaint.html', {'form': form, **template_context})
        if form.is_valid():
            complaint = form.save(commit=False)
            complaint.complaint_type = selected_complaint_type
            try:
                prepare_complaint_for_create(complaint, request.user)
            except (PermissionError, ValueError) as exc:
                messages.error(request, str(exc))
                if upload_ids:
                    discard_uploads(request.user, upload_ids)
                template_context.update(_media_upload_template_context(request.user))
                return render(request, 'management/add_complaint.html', {'form': form, **template_context})
            stored_names = []
            try:
                with transaction.atomic():
                    complaint.save()
                    initialize_created_complaint(complaint, request.user)
                    if settings.USE_S3_STORAGE:
                        batch = get_owned_batch(request.user, upload_batch_id, for_update=True)
                        verified_uploads = verify_pending_uploads(
                            request.user,
                            batch,
                            upload_ids,
                        )
                        attach_verified_uploads(complaint, verified_uploads)
                    else:
                        stored_names = _save_complaint_media_files(complaint, uploaded_files)
                    ActivityLog.objects.create(
                        user=request.user,
                        action='created',
                        object_type='complaint',
                        object_name=complaint.complaint_id,
                    )
            except ValidationError as exc:
                if upload_ids:
                    discard_uploads(request.user, upload_ids)
                form.add_error(None, exc)
                template_context.update(_media_upload_template_context(request.user))
                return render(request, 'management/add_complaint.html', {'form': form, **template_context})
            except Exception:
                for stored_name in stored_names:
                    default_storage.delete(stored_name)
                if upload_ids:
                    discard_uploads(request.user, upload_ids)
                logger.exception('Unable to create complaint for user %s', request.user.pk)
                form.add_error(None, _('The complaint could not be saved. Please try again.'))
                template_context.update(_media_upload_template_context(request.user))
                return render(request, 'management/add_complaint.html', {'form': form, **template_context})
            return redirect('complaint_list')
        if upload_ids:
            discard_uploads(request.user, upload_ids)
        template_context.update(_media_upload_template_context(request.user))
    else:
        initial = {}
        brand_id = request.GET.get('brand')
        model_id = request.GET.get('model')
        sub_model_id = request.GET.get('sub_model')
        year_id = request.GET.get('year')
        if brand_id:
            initial['brand'] = brand_id
        if model_id:
            initial['model'] = model_id
        if sub_model_id:
            initial['sub_model'] = sub_model_id
        if year_id:
            initial['year'] = year_id
            
        form = ComplaintForm(initial=initial, complaint_type=selected_complaint_type)
        _configure_complaint_form(form, request.user)
        template_context.update(_media_upload_template_context(request.user))
    return render(request, 'management/add_complaint.html', {'form': form, **template_context})

@login_required
def get_brands(request):
    brands = Brand.objects.all().values('id', 'name')
    return JsonResponse(list(brands), safe=False)

@login_required
def get_models(request, brand_id):
    models = Model.objects.filter(brand_id=brand_id).values('id', 'name')
    return JsonResponse(list(models), safe=False)

@login_required
def get_sub_models(request, model_id):
    sub_models = SubModel.objects.filter(model_id=model_id).values('id', 'name')
    return JsonResponse(list(sub_models), safe=False)

@login_required
def get_year_ranges(request, sub_model_id):
    year_ranges = YearRange.objects.filter(sub_model_id=sub_model_id).order_by(
        'year_start', 'year_end'
    ).values('id', 'year_start', 'year_end')
    return JsonResponse([{'id': yr['id'], 'range': f"{yr['year_start'] % 100}-{yr['year_end'] % 100}"} for yr in year_ranges], safe=False)


@login_required
def get_complaint_type_options(request, complaint_type):
    if not can_user_create_complaint_type(request.user, complaint_type):
        raise PermissionDenied('Your role cannot create the selected complaint type.')
    category = complaint_type_master_category(complaint_type)
    if not category:
        return JsonResponse({'error': 'Unknown complaint type.'}, status=400)
    options = MasterSetting.objects.filter(category=category).order_by('name').values('id', 'name')
    return JsonResponse(list(options), safe=False)

@login_required
def get_filtered_skus(request):
    skus = SKU.objects.select_related('region').all().order_by('code')
    search = request.GET.get('q', '').strip()[:100]

    country_id = request.GET.get('country')
    region_id = request.GET.get('region')
    region_filter = None

    if region_id:
        region_filter = Q(region_id=region_id)
    else:
        selected_country = None
        if country_id:
            selected_country = MasterSetting.objects.filter(
                pk=country_id,
                category='Country',
            ).first()
        if selected_country is None:
            try:
                selected_country = reporting_country_for_user(request.user)
            except PermissionError:
                selected_country = None
        if selected_country:
            region_filter = Q(region__name__iexact=selected_country.name)

    if region_filter is not None and skus.filter(region_filter).exists():
        skus = skus.filter(region_filter)

    vehicle_lookups = (
        (Brand, request.GET.get('brand')),
        (Model, request.GET.get('model')),
        (SubModel, request.GET.get('sub_model')),
    )
    has_vehicle_filter = any(object_id for model_class, object_id in vehicle_lookups) or bool(request.GET.get('year'))
    if search:
        if len(search) < 2:
            return JsonResponse([], safe=False)
        skus = skus.filter(Q(code__icontains=search) | Q(description__icontains=search))
    elif not has_vehicle_filter:
        return JsonResponse([], safe=False)

    for model_class, object_id in vehicle_lookups:
        if not object_id:
            continue
        term = model_class.objects.filter(pk=object_id).values_list('name', flat=True).first()
        if not term:
            continue
        skus = skus.filter(Q(code__icontains=term) | Q(description__icontains=term))

    year_id = request.GET.get('year')
    if year_id:
        selected_year = YearRange.objects.filter(pk=year_id).values(
            'year_start', 'year_end'
        ).first()
        if selected_year:
            year_start = selected_year['year_start']
            year_end = selected_year['year_end']
            short_range = f'{year_start % 100:02d}-{year_end % 100:02d}'
            full_range = f'{year_start}-{year_end}'
            compact_range = f'{year_start % 100:02d}{year_end % 100:02d}'
            skus = skus.filter(
                Q(code__icontains=short_range)
                | Q(description__icontains=short_range)
                | Q(code__icontains=full_range)
                | Q(description__icontains=full_range)
                | Q(code__icontains=compact_range)
                | Q(description__icontains=compact_range)
            )

    data = [
        {
            'id': sku.id,
            'name': f"{sku.code} - {sku.description}" if sku.description else sku.code,
        }
        for sku in skus[:50]
    ]
    return JsonResponse(data, safe=False)

@login_required
def complaint_list(request):
    authorized_complaints = visible_complaints_for_user(request.user, Complaint.objects.select_related(
        'channel', 'country', 'person', 'case_sub_category',
        'series', 'material', 'sku', 'brand', 'model', 'sub_model', 'year',
        'created_by', 'assigned_factory_executive', 'closed_by',
    ).prefetch_related(
        'media_files',
        'approvals__approver_user',
        'timeline_events__user',
    ).all().annotate(
        media_count=Count('media_files', distinct=True),
        approval_count=Count('approvals', distinct=True),
        sort_weight=Case(
            When(status='Closed', then=Value(1)),
            When(workflow_status='closed', then=Value(1)),
            default=Value(0),
            output_field=IntegerField(),
        )
    ).order_by('sort_weight', '-complaint_id'))
    filter_scope = authorized_complaints
    complaints = authorized_complaints
    search_query = request.GET.get('search', '')[:200]
    allowed_search_fields = {
        'complaint_id': 'complaint_id',
        'batch_order': 'batch_order',
        'complaint_description': 'complaint_description',
        'justification_from_factory': 'justification_from_factory',
        'action_from_factory': 'action_from_factory',
        'complaint_type': 'complaint_type',
        'channel': 'channel__name',
        'country': 'country__name',
        'case_sub_category': 'case_sub_category__name',
        'series': 'series__name',
        'material': 'material__name',
        'description': 'complaint_description',
        'brand': 'brand__name',
        'model': 'model__name',
    }
    search_by = request.GET.get('search_by', 'complaint_id')
    if search_by not in {*allowed_search_fields, 'reported_by'}:
        search_by = 'complaint_id'
    search_field = allowed_search_fields.get(search_by, 'complaint_id')

    def scoped_ids(field_name):
        return {
            str(value) for value in filter_scope.order_by().values_list(field_name, flat=True).distinct()
            if value is not None
        }

    permitted_brand_ids = scoped_ids('brand_id')
    permitted_country_ids = scoped_ids('country_id')
    permitted_channel_ids = scoped_ids('channel_id')
    permitted_person_ids = scoped_ids('created_by_id')
    selected_brand = request.GET.get('brand', '')
    selected_brand = selected_brand if selected_brand in permitted_brand_ids else ''
    selected_country = request.GET.get('country', '')
    selected_country = selected_country if selected_country in permitted_country_ids else ''
    selected_channel = request.GET.get('channel', '')
    selected_channel = selected_channel if selected_channel in permitted_channel_ids else ''
    selected_person = request.GET.get('person', '')
    selected_person = selected_person if selected_person in permitted_person_ids else ''
    selected_status = request.GET.get('status', '')
    selected_status = selected_status if selected_status in {'Open', 'Closed', 'On Hold'} else ''
    selected_priority = request.GET.get('priority', '')
    selected_priority = selected_priority if selected_priority in {'High', 'Medium', 'Low'} else ''
    selected_complaint_type = request.GET.get('complaint_type', '')
    complaint_type_values = {value for value, label in ComplaintTypes.CHOICES}
    selected_complaint_type = selected_complaint_type if selected_complaint_type in complaint_type_values else ''

    from_date = request.GET.get('from_date', '')
    to_date = request.GET.get('to_date', '')
    parsed_from_date = parse_date(from_date)
    parsed_to_date = parse_date(to_date)
    from_date = from_date if parsed_from_date else ''
    to_date = to_date if parsed_to_date else ''

    if search_query:
        trimmed_search_query = search_query
        if search_by == 'reported_by':
            complaints = complaints.filter(
                Q(created_by__username__icontains=trimmed_search_query)
                | Q(created_by__first_name__icontains=trimmed_search_query)
                | Q(created_by__last_name__icontains=trimmed_search_query)
                | Q(person__name__icontains=trimmed_search_query)
            )
        elif search_by == 'complaint_type':
            matching_type_values = [
                value
                for value, label in ComplaintTypes.CHOICES
                if trimmed_search_query.lower() in value.lower()
                or trimmed_search_query.lower() in str(label).lower()
                or any(trimmed_search_query.lower() in p.lower() for p in ComplaintTypes.get_prefixes(value))
            ]
            complaints = complaints.filter(
                Q(complaint_type__icontains=trimmed_search_query)
                | Q(complaint_type__in=matching_type_values)
            )
        else:
            filter_kwargs = {f'{search_field}__icontains': trimmed_search_query}
            complaints = complaints.filter(**filter_kwargs)
    if selected_status:
        complaints = complaints.filter(status=selected_status)
    if selected_priority:
        complaints = complaints.filter(priority=selected_priority)
    if selected_channel:
        complaints = complaints.filter(channel=selected_channel)
    if selected_person:
        complaints = complaints.filter(created_by_id=selected_person)

    if selected_brand:
        complaints = complaints.filter(brand_id=selected_brand)

    if selected_country:
        complaints = complaints.filter(country=selected_country)

    if from_date:
        complaints = complaints.filter(date__gte=parsed_from_date)

    if to_date:
        complaints = complaints.filter(date__lte=parsed_to_date)

    if selected_complaint_type:
        complaints = complaints.filter(complaint_type=selected_complaint_type)

    # Column-menu values always come from the complete role-authorized queryset,
    # never from the current page or from complaints hidden from this user.
    id_options = [
        {'value': value, 'label': value}
        for value in filter_scope.order_by().values_list('complaint_id', flat=True).distinct()
    ]
    vehicle_options = []
    vehicle_filters = {}
    for brand_id, brand_name, model_id, model_name in filter_scope.order_by().values_list(
        'brand_id', 'brand__name', 'model_id', 'model__name'
    ).distinct():
        value = f'{brand_id or 0}:{model_id or 0}'
        label = f'{brand_name or ""} {model_name or ""}'.strip() or '-'
        vehicle_options.append({'value': value, 'label': label})
        vehicle_filters[value] = Q(brand_id=brand_id, model_id=model_id)
    vehicle_options.sort(key=lambda option: option['label'].casefold())

    category_options = []
    category_filters = {}
    for category_id, category_name in filter_scope.order_by().values_list(
        'case_sub_category_id', 'case_sub_category__name'
    ).distinct():
        value = str(category_id or 0)
        category_options.append({'value': value, 'label': category_name or '-'})
        category_filters[value] = Q(case_sub_category_id=category_id)
    category_options.sort(key=lambda option: option['label'].casefold())

    reporter_options = []
    reporter_filters = {}
    reporter_rows = filter_scope.order_by().values_list(
        'created_by_id', 'created_by__username', 'person_id', 'person__name'
    ).distinct()
    for user_id, username, person_id, person_name in reporter_rows:
        if user_id:
            value, label, condition = f'u:{user_id}', username, Q(created_by_id=user_id)
        elif person_id:
            value, label, condition = f'p:{person_id}', person_name, Q(created_by__isnull=True, person_id=person_id)
        else:
            value, label, condition = 'none', '-', Q(created_by__isnull=True, person__isnull=True)
        if value not in reporter_filters:
            reporter_options.append({'value': value, 'label': label or '-'})
            reporter_filters[value] = condition
    reporter_options.sort(key=lambda option: option['label'].casefold())

    present_priorities = set(filter_scope.order_by().values_list('priority', flat=True).distinct())
    priority_options = [
        {'value': value, 'label': label}
        for value, label in Complaint._meta.get_field('priority').choices
        if value in present_priorities
    ]
    present_workflow_statuses = set(
        filter_scope.order_by().values_list('workflow_status', flat=True).distinct()
    )
    workflow_options = [
        {'value': value, 'label': label}
        for value, label in WorkflowStatuses.CHOICES
        if value in present_workflow_statuses
    ]

    column_definitions = [
        ('cf_complaint', id_options, None),
        ('cf_vehicle', vehicle_options, vehicle_filters),
        ('cf_category', category_options, category_filters),
        ('cf_reporter', reporter_options, reporter_filters),
        ('cf_priority', priority_options, None),
        ('cf_workflow_status', workflow_options, None),
    ]
    column_filter_config = []
    active_column_filter_pairs = []
    for param, options, custom_filters in column_definitions:
        valid_values = {option['value'] for option in options}
        selected = []
        for value in request.GET.getlist(param)[:100]:
            if value in valid_values and value not in selected:
                selected.append(value)
        column_filter_config.append({
            'param': param,
            'options': options,
            'selected': selected,
        })
        active_column_filter_pairs.extend((param, value) for value in selected)
        if not selected:
            continue
        if param == 'cf_complaint':
            complaints = complaints.filter(complaint_id__in=selected)
        elif param == 'cf_priority':
            complaints = complaints.filter(priority__in=selected)
        elif param == 'cf_workflow_status':
            complaints = complaints.filter(workflow_status__in=selected)
        else:
            combined = Q()
            for value in selected:
                combined |= custom_filters[value]
            complaints = complaints.filter(combined)

    brands = Brand.objects.filter(id__in=permitted_brand_ids).order_by('name')
    countries = MasterSetting.objects.filter(id__in=permitted_country_ids, category='Country').order_by('name')
    channels = MasterSetting.objects.filter(id__in=permitted_channel_ids, category='Channel').order_by('name')
    persons = User.objects.filter(
        id__in=permitted_person_ids,
    ).distinct().order_by('username')
    statuses = ['Open', 'Closed', 'On Hold']
    priorities = ['High', 'Medium', 'Low']
    sku = SKU.objects.values_list('code', flat=True).distinct()[:100]

    # Status Pie Data
    status_qs = complaints.values('status').annotate(count=Count('status'))
    status_labels = [entry['status'] for entry in status_qs]
    status_data = [entry['count'] for entry in status_qs]

    # Country Pie Data
    country_qs = complaints.values('country__name').annotate(count=Count('country'))
    country_labels = [entry['country__name'] for entry in country_qs]
    country_data = [entry['count'] for entry in country_qs]

    # Paginate complaints to prevent multi-second DOM rendering and per-row N+1 overhead
    paginator = Paginator(complaints, 25)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    pagination_query = QueryDict('', mutable=True)
    normalized_values = {
        'search': search_query,
        'search_by': search_by,
        'complaint_type': selected_complaint_type,
        'brand': selected_brand,
        'country': selected_country,
        'channel': selected_channel,
        'person': selected_person,
        'status': selected_status,
        'priority': selected_priority,
        'from_date': from_date,
        'to_date': to_date,
    }
    for key, value in normalized_values.items():
        if value:
            pagination_query[key] = value
    for key, value in active_column_filter_pairs:
        pagination_query.appendlist(key, value)
    pagination_querystring = pagination_query.urlencode()
    clear_all_query = pagination_query.copy()
    for param, field_name, relation_path in column_definitions:
        clear_all_query.pop(param, None)
    clear_all_column_filters_querystring = clear_all_query.urlencode()

    for complaint in page_obj.object_list:
        complaint.can_edit = can_user_edit_report_step(request.user, complaint)
        complaint.can_delete = is_workflow_admin(request.user)
        complaint.can_factory_review = (
            can_user_review_factory_step(request.user, complaint)
            and can_start_factory_review(complaint)
        )
        complaint.current_approval = get_user_current_approval(request.user, complaint)
        complaint.can_approve = can_user_decide_approval(request.user, complaint.current_approval)
        complaint.can_execute = can_user_execute_action(request.user, complaint)
        complaint.approval_summary = approval_progress(complaint)
        complaint.journey_steps = complaint_journey_steps(complaint)
    
    team_users = User.objects.filter(is_active=True).exclude(id=request.user.id).select_related('workflow_profile', 'workflow_profile__country').order_by('username')
    team_members_data = []
    for u in team_users:
        p = getattr(u, 'workflow_profile', None)
        role_code = p.role if p else 'default'
        role_label = p.get_role_display() if p and p.role else ('Workflow Admin' if u.is_superuser else 'Team Member')
        flag_url = p.country_flag_url if p else None
        team_members_data.append({
            'id': u.id,
            'username': u.username,
            'role_code': role_code,
            'role_label': role_label,
            'country_flag_url': flag_url,
        })

    return render(request, 'management/complaint_list.html', {
        'complaints': page_obj.object_list,
        'page_obj': page_obj,
        'pagination_querystring': pagination_querystring,
        'clear_all_column_filters_querystring': clear_all_column_filters_querystring,
        'column_filter_config': column_filter_config,
        'active_column_filter_pairs': active_column_filter_pairs,
        'status_labels': status_labels,
        'status_data': status_data,
        'country_labels': country_labels,
        'country_data': country_data,
        'search_query': search_query,
        'search_by': search_by,
        'selected_complaint_type': selected_complaint_type,
        'complaint_type_choices': ComplaintTypes.CHOICES,
        'selected_brand': selected_brand,
        'selected_country': selected_country,
        'selected_channel': selected_channel,
        'selected_person': selected_person,
        'selected_status': selected_status,
        'selected_priority': selected_priority,
        'from_date': from_date,
        'to_date': to_date,
        'brands': brands,
        'countries': countries,
        'channels': channels,
        'persons': persons,
        'statuses': statuses,
        'priorities': priorities,
        'sku': sku,
        'team_members_data': team_members_data,
    })


def logout_success(request):
    return render(request, 'management/logout_success.html')


@login_required
@require_POST
def set_portal_language(request):
    language = (request.POST.get('language') or 'en').strip().lower()
    if language not in {'en', 'ar', 'hi'}:
        language = 'en'

    profile = get_user_profile(request.user)
    if profile.preferred_language != language:
        profile.preferred_language = language
        profile.save(update_fields=['preferred_language'])
    request.session[settings.LANGUAGE_COOKIE_NAME] = language
    request.session['_language'] = language
    translation.activate(language)

    next_url = request.POST.get('next') or reverse('index')
    if not url_has_allowed_host_and_scheme(
        next_url,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        next_url = reverse('index')
    response = redirect(next_url)
    response.set_cookie(
        settings.LANGUAGE_COOKIE_NAME,
        language,
        max_age=31536000,
        secure=settings.SESSION_COOKIE_SECURE,
        httponly=False,
        samesite='Lax',
    )
    return response


@login_required
def edit_complaint(request, complaint_id):
    complaint = get_object_or_404(
        visible_complaints_for_user(request.user, Complaint.objects.all()),
        complaint_id=complaint_id
    )

    if not can_user_edit_report_step(request.user, complaint):
        messages.error(request, _('This complaint can no longer be edited from the report step.'))
        return redirect('complaint_list')

    if request.method == 'POST':
        tracked_fields = {
            field_name: getattr(complaint, field_name)
            for field_name in REPORT_EDITABLE_FIELDS
        }
        form = ComplaintForm(
            request.POST,
            instance=complaint,
            complaint_type=complaint.complaint_type,
        )
        _configure_complaint_form(form, request.user)
        uploaded_files = request.FILES.getlist('media_files')
        upload_ids = request.POST.getlist('media_upload_ids')
        upload_batch_id = request.POST.get('media_upload_batch')
        media_to_delete = request.POST.getlist('delete_media')
        remaining_media_count = complaint.media_files.exclude(id__in=media_to_delete).count()
        if settings.USE_S3_STORAGE and uploaded_files:
            form.add_error(None, _('Complaint media must be uploaded directly to object storage.'))
        try:
            if not settings.USE_S3_STORAGE:
                _validate_complaint_media_files(uploaded_files, existing_count=remaining_media_count)
        except ValidationError as exc:
            form.add_error(None, exc)
            if upload_ids:
                discard_uploads(request.user, upload_ids)
            return render(request, 'management/edit_complaint.html', {
                'form': form,
                'complaint': complaint,
                'media_files': complaint.media_files.all(),
                **_media_upload_template_context(request.user, complaint),
            })
        if form.is_valid():
            try:
                with transaction.atomic():
                    complaint = form.save()
                    changes = {
                        field_name: (old_value, getattr(complaint, field_name))
                        for field_name, old_value in tracked_fields.items()
                        if field_name in form.changed_data
                    }
                    removed_media = list(ComplaintMedia.objects.filter(
                        id__in=media_to_delete,
                        complaint=complaint,
                    ))
                    removed_media_count = len(removed_media)

                    if settings.USE_S3_STORAGE:
                        batch = get_owned_batch(
                            request.user,
                            upload_batch_id,
                            complaint=complaint,
                            for_update=True,
                        )
                        verified_uploads = verify_pending_uploads(
                            request.user,
                            batch,
                            upload_ids,
                            complaint=complaint,
                            existing_count=remaining_media_count,
                        )
                    else:
                        verified_uploads = []

                    for media in removed_media:
                        _delete_complaint_media_record(media)

                    if settings.USE_S3_STORAGE:
                        attach_verified_uploads(complaint, verified_uploads)
                    else:
                        _save_complaint_media_files(
                            complaint,
                            uploaded_files,
                            existing_count=remaining_media_count,
                        )
                    record_report_edit(
                        complaint,
                        request.user,
                        changes=changes,
                        media_added=len(upload_ids) if settings.USE_S3_STORAGE else len(uploaded_files),
                        media_removed=removed_media_count,
                    )
                    ActivityLog.objects.create(
                        user=request.user,
                        action='updated',
                        object_type='complaint',
                        object_name=complaint_id,
                    )
            except ValidationError as exc:
                if upload_ids:
                    discard_uploads(request.user, upload_ids)
                form.add_error(None, exc)
            except Exception:
                if upload_ids:
                    discard_uploads(request.user, upload_ids)
                logger.exception('Unable to update complaint %s.', complaint_id)
                form.add_error(None, _('The complaint could not be updated. Please try again.'))
            else:
                return redirect('complaint_list')
        elif upload_ids:
            discard_uploads(request.user, upload_ids)
    else:
        form = ComplaintForm(instance=complaint, complaint_type=complaint.complaint_type)
        _configure_complaint_form(form, request.user)

    media_files = complaint.media_files.all()

    return render(request, 'management/edit_complaint.html', {
        'form': form,
        'complaint': complaint,
        'media_files': media_files,
        **_media_upload_template_context(request.user, complaint),
    })
@login_required
def factory_review_complaint(request, complaint_id):
    complaint = get_object_or_404(
        visible_complaints_for_user(request.user, Complaint.objects.select_related(
            'channel', 'country', 'person', 'case_sub_category',
            'series', 'material', 'sku', 'brand', 'model', 'sub_model', 'year',
            'created_by', 'assigned_factory_executive'
        )),
        complaint_id=complaint_id
    )

    if not can_user_review_factory_step(request.user, complaint):
        messages.error(request, _('You are not allowed to review this complaint.'))
        return redirect('complaint_list')

    if not can_start_factory_review(complaint):
        messages.error(request, _('This complaint is not ready for factory review.'))
        return redirect('complaint_list')

    if request.method == 'POST':
        form = FactoryReviewForm(request.POST, instance=complaint)
        if form.is_valid():
            try:
                submit_factory_review(
                    complaint,
                    request.user,
                    form.cleaned_data['factory_reason'],
                    form.cleaned_data['factory_action_plan'],
                    form.cleaned_data['factory_priority'],
                )
            except (PermissionError, ValueError) as exc:
                messages.error(request, str(exc))
            else:
                ActivityLog.objects.create(
                    user=request.user,
                    action="submitted factory review",
                    object_type="complaint",
                    object_name=complaint_id
                )
                messages.success(request, _('Factory review submitted for approval.'))
                return redirect('complaint_list')
    else:
        form = FactoryReviewForm(instance=complaint)

    return render(request, 'management/factory_review_complaint.html', {
        'form': form,
        'complaint': complaint,
        'media_files': complaint.media_files.all(),
        'approval_summary': approval_progress(complaint),
    })


@login_required
def approvals_list_view(request):
    if not can_user_view_approvals(request.user):
        raise PermissionDenied('Only Country Executives, Approvers, Factory Executives, and Admins can view the Approvals workspace.')

    profile = get_user_profile(request.user)
    user_role = getattr(profile, 'role', '')
    workspace_stage = request.GET.get('stage', 'plan').strip().lower()
    if workspace_stage not in {'plan', 'verification'}:
        workspace_stage = 'plan'
    stage_filters = (
        [ApprovalStages.EXECUTION_VERIFICATION]
        if workspace_stage == 'verification'
        else [ApprovalStages.INITIAL, ApprovalStages.RECONSIDERATION]
    )
    active_statuses = (
        [
            WorkflowStatuses.AWAITING_EXECUTION_VERIFICATION,
            WorkflowStatuses.EXECUTION_PARTIALLY_VERIFIED,
        ]
        if workspace_stage == 'verification'
        else [WorkflowStatuses.AWAITING_APPROVAL, WorkflowStatuses.PARTIALLY_APPROVED]
    )
    
    # Base queryset scoped to user visibility
    base_qs = visible_complaints_for_user(
        request.user,
        Complaint.objects.select_related(
            'channel', 'country', 'person', 'case_sub_category',
            'series', 'material', 'sku', 'brand', 'model', 'sub_model', 'year',
            'created_by__workflow_profile__country', 'assigned_factory_executive', 'closed_by',
        ).prefetch_related(
            'approvals__approver_user__workflow_profile__country',
            'approvals__trigger_approval__approver_user__workflow_profile__country',
        )
    )

    # Filter parameters
    status_filter = request.GET.get('status', 'active')
    search_query = request.GET.get('search', '').strip()
    search_by = request.GET.get('search_by', 'all').strip()
    selected_priority = request.GET.get('priority', '').strip()
    selected_type = request.GET.get('type', '').strip()
    selected_country = request.GET.get('country', '').strip()

    # KPI counts calculated across all visible complaints
    staged_base_qs = (
        base_qs.filter(approvals__review_stage__in=stage_filters).distinct()
        if workspace_stage == 'verification'
        else base_qs
    )
    active_complaints_all = staged_base_qs.filter(workflow_status__in=active_statuses)
    total_active_count = active_complaints_all.count()

    my_pending_count = 0
    if profile and profile.role == WorkflowRoles.APPROVER:
        my_pending_count = ComplaintApproval.objects.filter(
            approver_user=request.user,
            status=DecisionStatuses.PENDING,
            review_stage__in=stage_filters,
            complaint__workflow_status__in=active_statuses,
        ).count()

    partial_status = (
        WorkflowStatuses.EXECUTION_PARTIALLY_VERIFIED
        if workspace_stage == 'verification'
        else WorkflowStatuses.PARTIALLY_APPROVED
    )
    partially_approved_count = staged_base_qs.filter(workflow_status=partial_status).count()
    
    reconsideration_count = active_complaints_all.filter(
        approvals__review_stage=ApprovalStages.RECONSIDERATION,
        approvals__status=DecisionStatuses.PENDING,
    ).distinct().count()

    top_priority_count = active_complaints_all.filter(
        Q(factory_priority='top') | Q(priority='High')
    ).distinct().count()

    # Filter applied to list
    complaints = staged_base_qs
    if status_filter == 'active':
        complaints = complaints.filter(workflow_status__in=active_statuses)
    elif status_filter == 'my_pending':
        if profile and profile.role == WorkflowRoles.APPROVER:
            complaints = complaints.filter(
                workflow_status__in=active_statuses,
                approvals__approver_user=request.user,
                approvals__status=DecisionStatuses.PENDING,
                approvals__review_stage__in=stage_filters,
            ).distinct()
        else:
            complaints = complaints.filter(workflow_status__in=active_statuses)
    elif status_filter == 'partially_approved':
        complaints = complaints.filter(workflow_status=partial_status)
    elif status_filter == 'reconsideration':
        complaints = complaints.none() if workspace_stage == 'verification' else complaints.filter(
            approvals__review_stage=ApprovalStages.RECONSIDERATION,
            workflow_status__in=[
                WorkflowStatuses.AWAITING_APPROVAL,
                WorkflowStatuses.PARTIALLY_APPROVED,
                WorkflowStatuses.REWORK_REQUIRED,
            ]
        ).distinct()
    elif status_filter == 'rework':
        complaints = complaints.filter(workflow_status=WorkflowStatuses.REWORK_REQUIRED)
    elif status_filter == 'approved':
        approved_statuses = (
            [WorkflowStatuses.PENDING_FINAL_UPDATE, WorkflowStatuses.CLOSED]
            if workspace_stage == 'verification'
            else [
                WorkflowStatuses.APPROVED,
                WorkflowStatuses.ACTION_IN_PROGRESS,
                WorkflowStatuses.AWAITING_EXECUTION_VERIFICATION,
                WorkflowStatuses.EXECUTION_PARTIALLY_VERIFIED,
                WorkflowStatuses.PENDING_FINAL_UPDATE,
                WorkflowStatuses.CLOSED,
            ]
        )
        complaints = complaints.filter(workflow_status__in=approved_statuses)
    elif status_filter == 'all':
        complaints = complaints.filter(approvals__isnull=False).distinct()

    # Search filter
    if search_query:
        if search_by == 'complaint_id':
            complaints = complaints.filter(complaint_id__icontains=search_query)
        elif search_by == 'complaint_type':
            matching_type_values = [
                value
                for value, label in ComplaintTypes.CHOICES
                if search_query.lower() in value.lower()
                or search_query.lower() in str(label).lower()
                or any(search_query.lower() in p.lower() for p in ComplaintTypes.get_prefixes(value))
            ]
            complaints = complaints.filter(
                Q(complaint_type__icontains=search_query)
                | Q(complaint_type__in=matching_type_values)
            )
        elif search_by == 'priority':
            complaints = complaints.filter(
                Q(factory_priority__icontains=search_query) | Q(priority__icontains=search_query)
            )
        elif search_by == 'country':
            complaints = complaints.filter(country__name__icontains=search_query)
        elif search_by == 'channel':
            complaints = complaints.filter(channel__name__icontains=search_query)
        elif search_by == 'vehicle':
            complaints = complaints.filter(
                Q(brand__name__icontains=search_query) | Q(model__name__icontains=search_query)
            )
        elif search_by == 'factory_reason':
            complaints = complaints.filter(factory_reason__icontains=search_query)
        elif search_by == 'factory_action_plan':
            complaints = complaints.filter(factory_action_plan__icontains=search_query)
        else:
            matching_type_values = [
                value
                for value, label in ComplaintTypes.CHOICES
                if search_query.lower() in value.lower()
                or search_query.lower() in str(label).lower()
                or any(search_query.lower() in p.lower() for p in ComplaintTypes.get_prefixes(value))
            ]
            complaints = complaints.filter(
                Q(complaint_id__icontains=search_query)
                | Q(complaint_type__in=matching_type_values)
                | Q(brand__name__icontains=search_query)
                | Q(model__name__icontains=search_query)
                | Q(sku__code__icontains=search_query)
                | Q(country__name__icontains=search_query)
                | Q(channel__name__icontains=search_query)
                | Q(factory_reason__icontains=search_query)
                | Q(factory_action_plan__icontains=search_query)
                | Q(batch_no__icontains=search_query)
                | Q(serial_no__icontains=search_query)
                | Q(shipment_order_no__icontains=search_query)
            )

    # Priority filter
    if selected_priority:
        complaints = complaints.filter(
            Q(factory_priority=selected_priority.lower()) | Q(priority__iexact=selected_priority)
        )

    # Type filter
    if selected_type:
        complaints = complaints.filter(complaint_type=selected_type.lower())

    # Country filter
    if selected_country:
        complaints = complaints.filter(country__id=selected_country)

    complaints = complaints.annotate(
        media_total=Count('media_files', distinct=True),
    ).order_by('-date', '-complaint_id')
    approval_page = Paginator(complaints, 20).get_page(request.GET.get('page'))
    pagination_params = request.GET.copy()
    pagination_params.pop('page', None)

    # Build enriched approval item list
    approval_items = []
    for complaint in approval_page.object_list:
        prog = approval_progress(complaint, stage_filters)
        my_appr = get_user_current_approval(request.user, complaint, stage_filters)
        can_decide = can_user_decide_approval(request.user, my_appr) if my_appr else False
        
        progress_pct = int((prog['decided'] / prog['total'] * 100)) if prog['total'] > 0 else 0

        assigned_exec_name = "Unassigned"
        if complaint.assigned_factory_executive:
            assigned_exec_name = complaint.assigned_factory_executive.get_full_name() or complaint.assigned_factory_executive.username

        reporter_name = "-"
        if complaint.created_by:
            reporter_name = complaint.created_by.username
        elif complaint.person:
            reporter_name = complaint.person.name

        country_flag_url = None
        if complaint.created_by:
            cb_prof = get_user_profile(complaint.created_by)
            country_flag_url = getattr(cb_prof, 'country_flag_url', None)

        enhanced_approvals = []
        for app in prog['approvals']:
            app_prof = get_user_profile(app.approver_user) if app.approver_user else None
            app_name = "Unassigned"
            if app.approver_user:
                app_name = app.approver_user.get_full_name() or app.approver_user.username
            enhanced_approvals.append({
                'id': app.id,
                'role': app.approver_role,
                'user': app.approver_user,
                'user_name': app_name,
                'user_profile': app_prof,
                'status': app.status,
                'status_display': app.get_status_display(),
                'comment': app.comment,
                'decided_at': app.decided_at,
                'review_stage': app.review_stage,
                'is_my_approval': (app.approver_user_id == request.user.id),
                'can_decide': can_user_decide_approval(request.user, app),
            })

        approval_items.append({
            'complaint': complaint,
            'assigned_exec_name': assigned_exec_name,
            'reporter_name': reporter_name,
            'country_flag_url': country_flag_url,
            'progress': prog,
            'progress_percent': progress_pct,
            'approvals': enhanced_approvals,
            'my_approval': my_appr,
            'can_decide': can_decide,
            'media_count': complaint.media_total,
        })

    countries = MasterSetting.objects.filter(category='Country').order_by('name')

    # Recent decisions history
    recent_decisions = ComplaintApproval.objects.filter(
        status__in=[DecisionStatuses.APPROVED, DecisionStatuses.REJECTED],
        review_stage__in=stage_filters,
    ).select_related(
        'complaint',
        'complaint__country',
        'approver_user',
    ).order_by('-decided_at')[:15]

    return render(request, 'management/approvals_list.html', {
        'approval_items': approval_items,
        'status_filter': status_filter,
        'search_query': search_query,
        'search_by': search_by,
        'selected_priority': selected_priority,
        'selected_type': selected_type,
        'selected_country': selected_country,
        'total_active_count': total_active_count,
        'my_pending_count': my_pending_count,
        'partially_approved_count': partially_approved_count,
        'reconsideration_count': reconsideration_count,
        'top_priority_count': top_priority_count,
        'recent_decisions': recent_decisions,
        'countries': countries,
        'profile': profile,
        'user_role': user_role,
        'workspace_stage': workspace_stage,
        'page_obj': approval_page,
        'pagination_querystring': pagination_params.urlencode(),
    })


@login_required
def approval_inbox(request):
    """Backwards-compatible wrapper that renders the full approvals workspace."""
    if not can_user_view_approvals(request.user):
        raise PermissionDenied('Only authorized workflow roles can access the approvals workspace.')
    return approvals_list_view(request)


@login_required
@require_POST
def quick_approval_decision_api(request, approval_id):
    approval = get_object_or_404(
        ComplaintApproval.objects.select_related('complaint', 'approver_user'),
        pk=approval_id,
        approver_user=request.user,
    )
    if not can_user_decide_approval(request.user, approval):
        return JsonResponse({'success': False, 'error': 'You cannot submit a decision for this approval record.'}, status=403)

    decision = request.POST.get('decision', '').strip()
    comment = request.POST.get('comment', '').strip()

    if not decision:
        return JsonResponse({'success': False, 'error': 'Decision is required.'}, status=400)

    if decision == DecisionStatuses.REJECTED and not comment:
        return JsonResponse({'success': False, 'error': 'A comment is required when rejecting or requesting rework.'}, status=400)

    try:
        approval_record, outcome = record_approval_decision(
            approval.pk,
            request.user,
            decision,
            comment,
        )
    except Exception as exc:
        return JsonResponse({'success': False, 'error': str(exc)}, status=400)

    ActivityLog.objects.create(
        user=request.user,
        action=f"{decision} approval",
        object_type='complaint',
        object_name=approval.complaint.complaint_id,
    )
    Notification.objects.filter(
        recipient=request.user,
        complaint=approval.complaint,
        notification_type__in=['approval', 'approval_reconsideration', 'execution_verification'],
    ).update(is_read=True)

    return JsonResponse({
        'success': True,
        'outcome': outcome,
        'complaint_id': approval.complaint.complaint_id,
        'message': 'Decision successfully recorded.',
    })


@login_required
def approval_review(request, approval_id):
    approval = get_object_or_404(
        ComplaintApproval.objects.select_related(
            'complaint',
            'complaint__country',
            'complaint__person',
            'complaint__brand',
            'complaint__model',
            'complaint__assigned_factory_executive',
            'approver_user',
            'trigger_approval',
            'trigger_approval__approver_user',
        ).prefetch_related(
            'complaint__media_files',
            'complaint__timeline_events__user',
        ),
        pk=approval_id,
        approver_user=request.user,
    )
    complaint = approval.complaint

    initial = {}
    if approval.status != DecisionStatuses.PENDING:
        initial = {'decision': approval.status, 'comment': approval.comment}

    if request.method == 'POST':
        form = ApprovalDecisionForm(request.POST, approval_stage=approval.review_stage)
        if form.is_valid():
            try:
                approval_record, outcome = record_approval_decision(
                    approval.pk,
                    request.user,
                    form.cleaned_data['decision'],
                    form.cleaned_data['comment'],
                )
            except PermissionError as exc:
                raise PermissionDenied(str(exc)) from exc
            except ValueError as exc:
                form.add_error(None, str(exc))
            else:
                ActivityLog.objects.create(
                    user=request.user,
                    action=f"{form.cleaned_data['decision']} approval",
                    object_type='complaint',
                    object_name=complaint.complaint_id,
                )
                if outcome == 'approved':
                    messages.success(request, _('All required members approved. The executive has received the green light.'))
                elif outcome == 'execution_verified':
                    messages.success(request, _('Execution was verified unanimously. Final CAD and container updates are now unlocked.'))
                elif outcome == 'execution_rejected':
                    messages.warning(request, _('Execution correction was requested and the case returned to the Factory Executive.'))
                elif outcome == 'rejected':
                    messages.warning(request, _('All reconsideration reviews are complete. The complaint was returned for rework.'))
                elif outcome == 'reconsideration':
                    messages.warning(request, _('Your rejection was saved. Every other required approver was asked to reconsider the complaint.'))
                else:
                    messages.success(request, _('Your review was saved. The remaining member reviews are still pending.'))
                Notification.objects.filter(
                    recipient=request.user,
                    complaint=complaint,
                    notification_type__in=['approval', 'approval_reconsideration', 'execution_verification'],
                ).update(is_read=True)
                return redirect('approval_inbox')
    else:
        form = ApprovalDecisionForm(initial=initial, approval_stage=approval.review_stage)

    return render(request, 'management/approval_review.html', {
        'approval': approval,
        'complaint': complaint,
        'form': form,
        'can_decide': can_user_decide_approval(request.user, approval),
        'approval_summary': approval_progress(complaint, [approval.review_stage]),
        'media_files': complaint.media_files.all(),
    })


@login_required
def execute_complaint(request, complaint_id):
    complaint = get_object_or_404(
        visible_complaints_for_user(request.user, Complaint.objects.select_related(
            'country', 'person', 'brand', 'model', 'assigned_factory_executive', 'created_by',
        ).prefetch_related('media_files', 'approvals__approver_user', 'timeline_events__user')),
        complaint_id=complaint_id,
    )
    if not can_user_execute_action(request.user, complaint):
        raise PermissionDenied('Only the assigned factory executive can execute this approved action plan.')

    form = FinalComplaintUpdateForm(complaint=complaint, initial={
        'cad_date': complaint.cad_date,
        'production_updates_container': complaint.production_updates_container,
    })
    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'start':
            try:
                start_action_execution(complaint, request.user)
            except (PermissionError, ValueError) as exc:
                messages.error(request, str(exc))
            else:
                ActivityLog.objects.create(
                    user=request.user,
                    action='started approved action plan',
                    object_type='complaint',
                    object_name=complaint.complaint_id,
                )
                messages.success(request, _('Action plan started. Submit the execution for verification when implementation is complete.'))
            return redirect('execute_complaint', complaint_id=complaint.complaint_id)

        if action == 'submit_verification':
            try:
                submit_execution_for_verification(complaint, request.user)
            except (PermissionError, ValueError) as exc:
                messages.error(request, str(exc))
            else:
                ActivityLog.objects.create(
                    user=request.user,
                    action='submitted execution for verification',
                    object_type='complaint',
                    object_name=complaint.complaint_id,
                )
                messages.success(request, _('Execution submitted to the original approvers for verification.'))
            return redirect('execute_complaint', complaint_id=complaint.complaint_id)

        form = FinalComplaintUpdateForm(request.POST, complaint=complaint)
        if form.is_valid():
            try:
                close_complaint_after_execution(
                    complaint,
                    request.user,
                    form.cleaned_data['cad_date'],
                    form.cleaned_data.get('production_updates_container', ''),
                )
            except PermissionError as exc:
                raise PermissionDenied(str(exc)) from exc
            except ValueError as exc:
                form.add_error(None, str(exc))
            else:
                ActivityLog.objects.create(
                    user=request.user,
                    action='closed after final update',
                    object_type='complaint',
                    object_name=complaint.complaint_id,
                )
                messages.success(request, _('Final updates saved. The complaint is now closed.'))
                Notification.objects.filter(
                    recipient=request.user,
                    complaint=complaint,
                    notification_type='fully_approved',
                ).update(is_read=True)
                return redirect('complaint_list')

    return render(request, 'management/execute_complaint.html', {
        'complaint': complaint,
        'form': form,
        'approval_summary': approval_progress(complaint),
    })


@login_required
def notification_list(request):
    notifications = Notification.objects.filter(
        recipient=request.user,
    ).select_related('complaint')
    page = Paginator(notifications, 50).get_page(request.GET.get('page'))
    return render(request, 'management/notifications.html', {
        'notifications': page.object_list,
        'page_obj': page,
    })


@login_required
def open_notification(request, notification_id):
    notification = get_object_or_404(
        Notification.objects.select_related('complaint'),
        pk=notification_id,
        recipient=request.user,
    )
    if not notification.is_read:
        notification.is_read = True
        notification.save(update_fields=['is_read'])

    complaint = notification.complaint
    if not complaint:
        return redirect('notification_list')
    if notification.notification_type in ['approval', 'approval_reconsideration', 'execution_verification']:
        approval = get_user_current_approval(request.user, complaint)
        if approval:
            return redirect('approval_review', approval_id=approval.pk)
    if notification.notification_type in ['assignment', 'rework']:
        if can_user_review_factory_step(request.user, complaint) and can_start_factory_review(complaint):
            return redirect('factory_review_complaint', complaint_id=complaint.complaint_id)
    if notification.notification_type in [
        'fully_approved',
        'execution_verification_rejected',
        'execution_verified',
    ] and can_user_execute_action(request.user, complaint):
        return redirect('execute_complaint', complaint_id=complaint.complaint_id)
    return redirect(f"{reverse('complaint_list')}?search={complaint.complaint_id}&search_by=complaint_id")


@login_required
@require_POST
def mark_all_notifications_read(request):
    updated_count = Notification.objects.filter(recipient=request.user, is_read=False).update(is_read=True)
    is_ajax = request.headers.get('x-requested-with') == 'XMLHttpRequest' or 'application/json' in request.headers.get('accept', '')
    if is_ajax:
        return JsonResponse({
            'status': 'success',
            'message': 'All notifications marked as read.',
            'count': updated_count
        })
    messages.success(request, _('All notifications marked as read.'))
    return redirect('notification_list')

@login_required
@require_POST
def delete_complaint(request, complaint_id):
    if not is_workflow_admin(request.user):
        raise PermissionDenied('Only workflow administrators can delete complaints.')
    complaint = get_object_or_404(
        visible_complaints_for_user(request.user, Complaint.objects.all()),
        pk=complaint_id,
    )
    for media in complaint.media_files.all():
        _delete_complaint_media_record(media)
    complaint.delete()
    messages.success(request, _('Complaint deleted successfully.'))
    ActivityLog.objects.create(
        user=request.user,
        action="deleted",
        object_type="complaint",
        object_name=complaint_id,
    )
    return redirect('complaint_list')


def _csv_safe(value):
    text = '' if value is None else str(value)
    if text.startswith(('=', '+', '-', '@', '\t', '\r')):
        return f"'{text}"
    return text


@login_required
def export_complaints(request):
    complaints = visible_complaints_for_user(request.user, Complaint.objects.select_related(
        'channel', 'country', 'person', 'case_sub_category',
        'series', 'material', 'sku', 'brand', 'model', 'sub_model', 'year'
    ).all())

    # Apply filters like in your complaint list view
    if 'status' in request.GET:
        complaints = complaints.filter(status=request.GET['status'])
    if 'case_type' in request.GET:
        complaints = complaints.filter(case_sub_category__name=request.GET['case_type'])
    if 'from_date' in request.GET:
        from_date = request.GET['from_date']
        parsed_from_date = parse_date(from_date) if from_date else None
        if parsed_from_date:
            complaints = complaints.filter(date__gte=parsed_from_date)
    if 'to_date' in request.GET:
        to_date = request.GET['to_date']
        parsed_to_date = parse_date(to_date) if to_date else None
        if parsed_to_date:
            complaints = complaints.filter(date__lte=parsed_to_date)

    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="complaints.csv"'

    writer = csv.writer(response)
    writer.writerow(['ID', 'Vehicle', 'Status', 'Case Type', 'Created On', 'Brand', 'Model', 'Sub Model', 'Year Start', 'Year End', 'Number of Seats', 'Number of Doors', 'Layout Code', 'Description', 'Status', 'Date', 'Channel', 'Country', 'Person', 'Case Sub Category', 'Series', 'Material', 'SKU', 'CAD Date', 'Updated Order No'])

    for complaint in complaints:
        writer.writerow([_csv_safe(value) for value in [
            complaint.complaint_id,
            str(complaint.model) if complaint.model else '',
            complaint.status,
            complaint.case_sub_category.name if complaint.case_sub_category else '',
            complaint.date.strftime('%Y-%m-%d') if complaint.date else '',
            complaint.brand.name if complaint.brand else '',
            complaint.model.name if complaint.model else '',
            complaint.sub_model.name if complaint.sub_model else '',
            complaint.year.year_start if complaint.year else '',
            complaint.year.year_end if complaint.year else '',
            complaint.year.number_of_seats if complaint.year else '',
            complaint.year.number_of_doors if complaint.year else '',
            complaint.year.layout_code if complaint.year else '',
            complaint.complaint_description,
            complaint.status,
            complaint.date.strftime('%Y-%m-%d') if complaint.date else '',
            complaint.channel.name if complaint.channel else '',
            complaint.country.name if complaint.country else '',
            (
                complaint.created_by.username
                if complaint.created_by
                else complaint.person.name if complaint.person else ''
            ),
            complaint.case_sub_category.name if complaint.case_sub_category else '',
            complaint.series.name if complaint.series else '',
            complaint.material.name if complaint.material else '',
            complaint.sku.code if complaint.sku else '',
            complaint.cad_date.strftime('%Y-%m-%d') if complaint.cad_date else '',
            complaint.updated_order_no if complaint.updated_order_no else ''
        ]])
    return response


CAR_CSV_HEADER_MAP = {
    # Brand
    'brand': 'brand',
    'brand name': 'brand',
    'brandname': 'brand',
    'make': 'brand',
    # Model
    'model': 'model',
    'model name': 'model',
    'modelname': 'model',
    # Sub Model
    'sub model': 'sub_model',
    'sub_model': 'sub_model',
    'submodel': 'sub_model',
    'sub model name': 'sub_model',
    'submodel name': 'sub_model',
    'variant': 'sub_model',
    'trim': 'sub_model',
    # Year Start
    'year start': 'year_start',
    'year_start': 'year_start',
    'start year': 'year_start',
    'start_year': 'year_start',
    'year from': 'year_start',
    'from year': 'year_start',
    'from': 'year_start',
    # Year End
    'year end': 'year_end',
    'year_end': 'year_end',
    'end year': 'year_end',
    'end_year': 'year_end',
    'year to': 'year_end',
    'to year': 'year_end',
    'to': 'year_end',
    # Seats
    'seats': 'number_of_seats',
    'seat': 'number_of_seats',
    'number of seats': 'number_of_seats',
    'number_of_seats': 'number_of_seats',
    'no of seats': 'number_of_seats',
    'no. of seats': 'number_of_seats',
    'seat count': 'number_of_seats',
    # Doors
    'doors': 'number_of_doors',
    'door': 'number_of_doors',
    'number of doors': 'number_of_doors',
    'number_of_doors': 'number_of_doors',
    'no of doors': 'number_of_doors',
    'no. of doors': 'number_of_doors',
    'door count': 'number_of_doors',
    # X / X Code
    'x': 'x_code',
    'x code': 'x_code',
    'x_code': 'x_code',
    'xcode': 'x_code',
    'x codes': 'x_code',
    'x-code': 'x_code',
    'x-codes': 'x_code',
    'x no': 'x_code',
    'x number': 'x_code',
    # Fitting Confirm / Fitting Confirmation
    'fitting confirm': 'fitting_confirmation',
    'fitting confirmation': 'fitting_confirmation',
    'fitting_confirmation': 'fitting_confirmation',
    'fitting_confirm': 'fitting_confirmation',
    'fitting status': 'fitting_confirmation',
    'fitting': 'fitting_confirmation',
    # Layout Code
    'layout code': 'layout_code',
    'layout_code': 'layout_code',
    'layout': 'layout_code',
    'layoutcode': 'layout_code',
    # Serial Number / #
    '#': 'serial_number',
    'sl no': 'serial_number',
    'sl. no': 'serial_number',
    'sl no.': 'serial_number',
    'serial': 'serial_number',
    'serial no': 'serial_number',
    'serial no.': 'serial_number',
    'serial number': 'serial_number',
    's no': 'serial_number',
    's.no': 'serial_number',
}


@login_required
def upload_car_csv(request):
    if not _can_manage_catalog(request.user):
        raise PermissionDenied('Only staff users can upload vehicle data.')
    if request.method == "POST":
        form = UploadCSVForm(request.POST, request.FILES)
        if form.is_valid():
            uploaded_file = form.cleaned_data['csv_file']
            try:
                uploaded_file.seek(0)
                content_bytes = uploaded_file.read()
                decoded_text = None
                for encoding in ('utf-8-sig', 'utf-8', 'latin-1', 'cp1252'):
                    try:
                        decoded_text = content_bytes.decode(encoding)
                        break
                    except UnicodeDecodeError:
                        continue
                if decoded_text is None:
                    raise ValidationError(_('CSV must use UTF-8 or compatible text encoding.'))

                lines = [l for l in decoded_text.splitlines() if l.strip()]
                if not lines:
                    raise ValidationError(_('The uploaded CSV file is empty.'))

                reader = csv.reader(lines)
                try:
                    raw_headers = next(reader)
                except StopIteration:
                    raise ValidationError(_('The uploaded CSV file is empty.'))

                # Match headers case-insensitively and ignore extra spaces
                col_to_field = {}
                for idx, h in enumerate(raw_headers):
                    norm = re.sub(r'[\s_\-]+', ' ', (h or '').strip().lower())
                    target_field = CAR_CSV_HEADER_MAP.get(norm)
                    if target_field:
                        col_to_field[idx] = target_field

                total_rows = 0
                new_entries = []
                duplicates = []
                invalid_rows = []

                seen_batch_keys = set()
                seen_layout_codes = set(YearRange.objects.values_list('layout_code', flat=True))

                with transaction.atomic():
                    for row_idx, row in enumerate(reader, start=2):
                        if not row or not any(cell.strip() for cell in row):
                            continue

                        total_rows += 1
                        if total_rows > MAX_CSV_IMPORT_ROWS:
                            raise ValidationError(
                                _('CSV files may contain at most %(count)s data rows.') % {'count': MAX_CSV_IMPORT_ROWS}
                            )

                        row_data = {}
                        for col_idx, field_name in col_to_field.items():
                            if col_idx < len(row):
                                val = (row[col_idx] or '').strip()
                                if val.lower() in ('null', 'undefined'):
                                    val = ''
                                row_data[field_name] = val
                            else:
                                row_data[field_name] = ''

                        brand_name = row_data.get('brand', '')
                        model_name = row_data.get('model', '')
                        sub_model_name = row_data.get('sub_model', '')
                        if sub_model_name.lower() in ('undefined', 'null', 'none', 'n/a', '-'):
                            sub_model_name = ''
                        layout_code = row_data.get('layout_code', '')
                        x_code = row_data.get('x_code', '')
                        if x_code.lower() in ('undefined', 'null', 'none'):
                            x_code = ''
                        fitting_confirmation = row_data.get('fitting_confirmation', '')
                        if fitting_confirmation.lower() in ('undefined', 'null', 'none'):
                            fitting_confirmation = ''

                        # Mandatory validation (Brand & Model)
                        if not brand_name:
                            invalid_rows.append(f"Row {row_idx}: Brand is required.")
                            continue
                        if not model_name:
                            invalid_rows.append(f"Row {row_idx}: Model is required.")
                            continue
                        if len(brand_name) > 100:
                            invalid_rows.append(f"Row {row_idx}: Brand must be 100 characters or fewer.")
                            continue
                        if len(model_name) > 100:
                            invalid_rows.append(f"Row {row_idx}: Model must be 100 characters or fewer.")
                            continue
                        if len(sub_model_name) > 100:
                            invalid_rows.append(f"Row {row_idx}: Sub-Model must be 100 characters or fewer.")
                            continue
                        if len(layout_code) > 100:
                            invalid_rows.append(f"Row {row_idx}: Layout Code must be 100 characters or fewer.")
                            continue
                        if len(x_code) > 100:
                            invalid_rows.append(f"Row {row_idx}: X-Code must be 100 characters or fewer.")
                            continue
                        if len(fitting_confirmation) > 100:
                            invalid_rows.append(f"Row {row_idx}: Fitting Confirmation must be 100 characters or fewer.")
                            continue

                        # Convert years, seats and doors to numbers only when valid
                        year_start_raw = row_data.get('year_start', '')
                        year_start = None
                        if year_start_raw:
                            try:
                                year_start = int(year_start_raw)
                                if not (1900 <= year_start <= 2100):
                                    invalid_rows.append(f"Row {row_idx}: Year Start must be between 1900 and 2100.")
                                    continue
                            except (ValueError, TypeError):
                                invalid_rows.append(f"Row {row_idx}: Year Start must be a valid whole number.")
                                continue

                        year_end_raw = row_data.get('year_end', '')
                        year_end = None
                        if year_end_raw:
                            try:
                                year_end = int(year_end_raw)
                                if not (1900 <= year_end <= 2100):
                                    invalid_rows.append(f"Row {row_idx}: Year End must be between 1900 and 2100.")
                                    continue
                            except (ValueError, TypeError):
                                invalid_rows.append(f"Row {row_idx}: Year End must be a valid whole number.")
                                continue

                        if year_start is not None and year_end is not None and year_start > year_end:
                            invalid_rows.append(f"Row {row_idx}: Year End must be greater than or equal to Year Start.")
                            continue

                        seats_raw = row_data.get('number_of_seats', '')
                        seats = None
                        if seats_raw:
                            try:
                                seats = int(seats_raw)
                                if not (1 <= seats <= 100):
                                    invalid_rows.append(f"Row {row_idx}: Seats must be between 1 and 100.")
                                    continue
                            except (ValueError, TypeError):
                                invalid_rows.append(f"Row {row_idx}: Seats must be a valid whole number.")
                                continue

                        doors_raw = row_data.get('number_of_doors', '')
                        doors = None
                        if doors_raw:
                            try:
                                doors = int(doors_raw)
                                if not (1 <= doors <= 20):
                                    invalid_rows.append(f"Row {row_idx}: Doors must be between 1 and 20.")
                                    continue
                            except (ValueError, TypeError):
                                invalid_rows.append(f"Row {row_idx}: Doors must be a valid whole number.")
                                continue

                        # Prevent duplicate records if the same CSV is uploaded again
                        batch_key = (
                            brand_name.strip().casefold(),
                            model_name.strip().casefold(),
                            sub_model_name.strip().casefold(),
                            year_start,
                            year_end,
                            x_code.strip().casefold(),
                        )
                        if batch_key in seen_batch_keys:
                            duplicates.append(f"Row {row_idx}: Duplicate entry in file ({brand_name} {model_name} {sub_model_name})")
                            continue

                        if layout_code and layout_code in seen_layout_codes:
                            duplicates.append(f"Row {row_idx}: Layout code '{layout_code}' already exists")
                            continue

                        # Check if matches existing record in DB
                        existing_brand = Brand.objects.filter(name__iexact=brand_name).first()
                        existing_model = Model.objects.filter(brand=existing_brand, name__iexact=model_name).first() if existing_brand else None
                        existing_sub = SubModel.objects.filter(model=existing_model, name__iexact=sub_model_name).first() if existing_model else None

                        if existing_sub:
                            yr_qs = YearRange.objects.filter(
                                sub_model=existing_sub,
                                year_start=year_start,
                                year_end=year_end,
                            )
                            if x_code:
                                yr_exists = yr_qs.filter(Q(x_code__iexact=x_code) | Q(x_code='')).exists()
                            else:
                                yr_exists = yr_qs.exists()

                            if yr_exists:
                                yr_desc = f"{brand_name} {model_name} {sub_model_name}".strip()
                                if year_start or year_end:
                                    yr_desc += f" ({year_start or ''}-{year_end or ''})"
                                duplicates.append(f"Row {row_idx}: Vehicle record already exists ({yr_desc})")
                                seen_batch_keys.add(batch_key)
                                continue

                        # Resolve / create Brand, Model, SubModel (case-insensitive reuse)
                        brand = existing_brand or Brand.objects.create(name=brand_name)
                        model = existing_model or Model.objects.create(brand=brand, name=model_name)
                        sub_model = existing_sub or SubModel.objects.create(model=model, name=sub_model_name)

                        # Assign unique layout_code
                        if not layout_code:
                            base = x_code.strip()
                            if base and base not in seen_layout_codes and not YearRange.objects.filter(layout_code=base).exists():
                                layout_code = base
                            else:
                                layout_code = f"YR-{uuid.uuid4().hex[:8].upper()}"
                                while layout_code in seen_layout_codes or YearRange.objects.filter(layout_code=layout_code).exists():
                                    layout_code = f"YR-{uuid.uuid4().hex[:8].upper()}"

                        seen_layout_codes.add(layout_code)
                        seen_batch_keys.add(batch_key)

                        serial_number_raw = row_data.get('serial_number', '').strip()
                        serial_number = format_pattern_serial(serial_number_raw) if serial_number_raw else ''

                        new_entries.append(YearRange(
                            sub_model=sub_model,
                            serial_number=serial_number,
                            year_start=year_start,
                            year_end=year_end,
                            number_of_seats=seats,
                            number_of_doors=doors,
                            layout_code=layout_code,
                            x_code=x_code,
                            fitting_confirmation=fitting_confirmation,
                        ))

                    if new_entries:
                        YearRange.objects.bulk_create(new_entries)
                        ActivityLog.objects.create(
                            user=request.user,
                            action='uploaded',
                            object_type='Car CSV',
                            object_name=f'Uploaded {len(new_entries)} new car records via CSV file',
                        )

            except ValidationError as exc:
                err_msg = str(exc.message if hasattr(exc, 'message') else exc)
                messages.error(request, err_msg)
                return redirect('car_details')
            except IntegrityError:
                logger.exception('Vehicle CSV import conflict for user %s', request.user.pk)
                messages.error(request, _('The import conflicted with another database update. Please retry.'))
                return redirect('car_details')

            imported_count = len(new_entries)
            duplicates_count = len(duplicates)
            invalid_count = len(invalid_rows)

            summary_parts = [
                _("CSV Import Results:"),
                f"• Total CSV rows: {total_rows}",
                f"• Successfully imported: {imported_count}",
                f"• Duplicates skipped: {duplicates_count}",
                f"• Invalid rows skipped: {invalid_count}",
            ]
            summary_text = "\n".join(summary_parts)

            if imported_count > 0 and invalid_count == 0:
                messages.success(request, summary_text)
            elif imported_count > 0 and invalid_count > 0:
                messages.warning(request, summary_text)
            elif total_rows > 0 and duplicates_count == total_rows:
                messages.info(request, summary_text)
            else:
                messages.error(request, summary_text)

            if invalid_rows:
                error_header = _("Error reason for each failed row:\n")
                error_list = "\n".join([f"• {err}" for err in invalid_rows[:30]])
                if len(invalid_rows) > 30:
                    error_list += f"\n• ... and {len(invalid_rows) - 30} more failed rows."
                messages.error(request, error_header + error_list)

            return redirect('car_details')
    else:
        form = UploadCSVForm()

    return render(request, "management/upload_csv.html", {"form": form})


@login_required
def add_sku(request):
    form = SKUForm()
    search_query = request.GET.get('search', '').strip()
    search_column = (request.GET.get('search_by') or request.GET.get('column', 'all')).strip()
    new_search_enabled = True
    scoped_search_enabled = True
    skus_qs = SKU.objects.select_related('region').all().order_by('code')
    if search_query:
        if search_column == 'code':
            skus_qs = skus_qs.filter(code__icontains=search_query)
        elif search_column == 'description':
            skus_qs = skus_qs.filter(description__icontains=search_query)
        elif search_column == 'region':
            skus_qs = skus_qs.filter(region__name__icontains=search_query)
        else:
            skus_qs = skus_qs.filter(
                Q(code__icontains=search_query) |
                Q(description__icontains=search_query) |
                Q(region__name__icontains=search_query)
            )
    paginator = Paginator(skus_qs, 50)
    page_number = request.GET.get('page')
    page_skus = paginator.get_page(page_number)
    upload_feedback = ''
    upload_form = SKUUploadForm()

    if request.method == "POST":
        if not _can_manage_catalog(request.user):
            raise PermissionDenied('Only staff users can add or upload SKUs.')
        if "add_sku" in request.POST:
            form = SKUForm(request.POST)
            if form.is_valid():
                skus_obj=form.save()
                ActivityLog.objects.create(
                    user=request.user,
                    action="created",
                    object_type="SKU",
                    object_name=skus_obj.code
                )
                return redirect('add_sku')

        elif "upload_csv" in request.POST:
            upload_form = SKUUploadForm(request.POST, request.FILES)
            if upload_form.is_valid():
                pending_skus = []
                existing_codes = set(SKU.objects.values_list('code', flat=True))
                seen_codes = set()
                regions = {
                    setting.name.casefold(): setting
                    for setting in MasterSetting.objects.filter(category='Region')
                }
                skipped = 0
                invalid_rows = []
                try:
                    with transaction.atomic():
                        for row_number, row in _iter_csv_rows(
                            upload_form.cleaned_data['csv_file'],
                            {'code'},
                        ):
                            code = row.get('code', '')
                            description = row.get('description', '')
                            region_name = row.get('region', '')
                            if not code:
                                invalid_rows.append(f'row {row_number}: code is required')
                                continue
                            if len(code) > 100 or len(description) > 255:
                                invalid_rows.append(f'row {row_number}: code or description is too long')
                                continue
                            if code in existing_codes or code in seen_codes:
                                skipped += 1
                                continue
                            region = regions.get(region_name.casefold()) if region_name else None
                            if region_name and not region:
                                invalid_rows.append(f'row {row_number}: unknown region {region_name}')
                                continue
                            seen_codes.add(code)
                            pending_skus.append(SKU(
                                code=code,
                                description=description,
                                region=region,
                            ))

                        SKU.objects.bulk_create(pending_skus)
                        ActivityLog.objects.create(
                            user=request.user,
                            action='uploaded',
                            object_type='SKU CSV',
                            object_name=f'Uploaded {len(pending_skus)} new SKUs via CSV file',
                        )
                except ValidationError as exc:
                    upload_form.add_error('csv_file', exc)
                except IntegrityError:
                    logger.exception('SKU CSV import conflict for user %s', request.user.pk)
                    upload_form.add_error('csv_file', _('The import conflicted with another update. Please retry.'))
                else:
                    upload_feedback = (
                        f'{len(pending_skus)} SKUs added. {skipped} duplicates and '
                        f'{len(invalid_rows)} invalid rows skipped.'
                    )
                    if invalid_rows:
                        messages.warning(request, '; '.join(invalid_rows[:5]))

    return render(request, 'management/add_skus.html', {
        'form': form,
        'skus': page_skus.object_list,
        'page_obj': page_skus,
        'search_query': search_query,
        'search_column': search_column,
        'search_by': search_column,
        'new_search_enabled': new_search_enabled,
        'scoped_search_enabled': scoped_search_enabled,
        'upload_feedback': upload_feedback,
        'upload_form': upload_form,
    })


@login_required
@require_POST
def delete_sku(request, sku_id):
    if not _can_manage_catalog(request.user):
        raise PermissionDenied('Only staff users can delete SKUs.')
    sku = get_object_or_404(SKU, id=sku_id)
    ActivityLog.objects.create(
        user=request.user,
        action="deleted",
        object_type="SKU",
        object_name=sku.code
    )
    sku.delete()
    return redirect('add_sku')


@login_required
def edit_sku(request, sku_id):
    if not _can_manage_catalog(request.user):
        raise PermissionDenied('Only staff users can edit SKUs.')
    sku = get_object_or_404(SKU, id=sku_id)
    if request.method == 'POST':
        form = SKUForm(request.POST, instance=sku)
        if form.is_valid():
            form.save()
            ActivityLog.objects.create(
                user=request.user,
                action="updated",
                object_type="SKU",
                object_name=sku.code
            )
            return redirect('add_sku')
    else:
        form = SKUForm(instance=sku)

    return render(request, 'management/edit_sku.html', {
        'form': form,
        'sku': sku
    })


@user_passes_test(is_workflow_admin)
def admin_panel_view(request):
    user_form = UserCreationForm()
    if not request.user.is_superuser:
        user_form.fields.pop('is_staff', None)
        user_form.fields.pop('is_superuser', None)
    group_form = GroupCreationForm()
    assign_form = AssignUserToGroupForm()

    if request.method == "POST":
        if 'add_user' in request.POST:
            user_form = UserCreationForm(request.POST, request.FILES)
            if not request.user.is_superuser:
                user_form.fields.pop('is_staff', None)
                user_form.fields.pop('is_superuser', None)
            if user_form.is_valid():
                user = user_form.save(commit=False)
                if not request.user.is_superuser:
                    user.is_staff = False
                    user.is_superuser = False
                user.set_password(user_form.cleaned_data['password'])
                user.save()
                user_form.save_profile(user)
                ActivityLog.objects.create(
                    user=request.user,
                    action="created",
                    object_type="User",
                    object_name=user.username
                )
                messages.success(request, _('User %(username)s was created successfully.') % {'username': user.username})
            for errors in user_form.errors.values():
                for error in errors:
                    messages.error(request, error)

        elif 'add_group' in request.POST:
            group_form = GroupCreationForm(request.POST)
            if group_form.is_valid():
                group = group_form.save()
                ActivityLog.objects.create(
                    user=request.user,
                    action="created",
                    object_type="Group",
                    object_name=group.name
                )
                messages.success(request, _('Group %(group)s was created successfully.') % {'group': group.name})

        elif 'assign_group' in request.POST:
            assign_form = AssignUserToGroupForm(request.POST)
            if assign_form.is_valid():
                user = assign_form.cleaned_data['user']
                group = assign_form.cleaned_data['group']
                user.groups.add(group)
                ActivityLog.objects.create(
                    user=request.user,
                    action="assigned",
                    object_type="Group",
                    object_name=f"{user.username} → {group.name}"
                )
                messages.success(request, _('%(username)s was assigned to %(group)s.') % {'username': user.username, 'group': group.name})
        
    section = request.GET.get('section', 'dashboard').strip().lower()
    if section not in {'dashboard', 'users', 'skus', 'brands', 'master', 'sessions', 'logs'}:
        section = 'dashboard'

    active_users = get_active_users() if section in {'dashboard', 'users', 'sessions'} else []
    online_user_ids = {entry['user'].pk for entry in active_users}
    users_qs = User.objects.select_related('workflow_profile__country').order_by('username')
    users_page = Paginator(users_qs, 25).get_page(request.GET.get('section_page')) if section == 'users' else None
    users = list(users_page.object_list) if users_page else []
    for listed_user in users:
        listed_user.is_online = listed_user.pk in online_user_ids

    role_counts = {
        role: 0
        for role in (
            WorkflowRoles.COUNTRY_EXECUTIVE,
            WorkflowRoles.FACTORY_VIEWER,
            WorkflowRoles.FACTORY_EXECUTIVE,
            WorkflowRoles.FACTORY_COMPLAINT_REGISTRAR,
            WorkflowRoles.ADMIN,
            *[role for role, label in ApprovalRoles.CHOICES],
        )
    }
    if section == 'dashboard':
        for role, approval_role, count in UserProfile.objects.values_list('role', 'approval_role').annotate(count=Count('pk')):
            role_key = approval_role if role == WorkflowRoles.APPROVER else role
            role_counts[role_key] = role_counts.get(role_key, 0) + count

    countries = MasterSetting.objects.filter(category='Country').annotate(
        user_count=Count('workflow_users'),
    ).order_by('name')
    resolved_filter = Q(workflow_status=WorkflowStatuses.CLOSED) | Q(status__iexact='closed')

    complaint_stats = Complaint.objects.aggregate(
        total=Count('pk'),
        resolved=Count('pk', filter=resolved_filter),
        in_progress=Count('pk', filter=~resolved_filter),
    ) if section == 'dashboard' else {'total': 0, 'resolved': 0, 'in_progress': 0}
    logs_page = Paginator(
        ActivityLog.objects.select_related('user').order_by('-timestamp'), 50
    ).get_page(request.GET.get('section_page')) if section == 'logs' else None
    sku_page = Paginator(
        SKU.objects.select_related('region').order_by('code'), 50
    ).get_page(request.GET.get('section_page')) if section == 'skus' else None
    session_page = Paginator(active_users, 50).get_page(request.GET.get('section_page')) if section == 'sessions' else None
    vehicle_page = Paginator(Brand.objects.order_by('name'), 50).get_page(
        request.GET.get('section_page')
    ) if section == 'brands' else None

    return render(request, 'management/admin_panel.html', {
        'user_form': user_form,
        'group_form': group_form,
        'assign_form': assign_form,
        'active_users': active_users,
        'users': users,
        'groups': Group.objects.prefetch_related('permissions__content_type') if section == 'users' else [],
        'permissions': Permission.objects.select_related('content_type').all() if section == 'users' else [],
        'active_sessions': session_page.object_list if session_page else (active_users if section == 'dashboard' else []),
        'activity_logs': logs_page.object_list if logs_page else [],
        'total_users_count': User.objects.count() if section == 'dashboard' else users_qs.count(),
        'active_users_count': len(online_user_ids),
        'active_sessions_count': len(active_users),
        'total_complaints_count': complaint_stats['total'],
        'complaints_resolved_count': complaint_stats['resolved'],
        'complaints_in_progress_count': complaint_stats['in_progress'],
        'role_counts': role_counts,
        'skus': sku_page.object_list if sku_page else [],
        'brands': Brand.objects.filter(
            pk__in=[brand.pk for brand in vehicle_page.object_list]
        ).annotate(model_total=Count('models')).order_by('name') if vehicle_page else [],
        'master_settings': MasterSetting.objects.order_by('category', 'name') if section == 'master' else [],
        'workflow_role_choices': WorkflowRoles.CHOICES,
        'approval_role_choices': ApprovalRoles.CHOICES,
        'workflow_countries': countries,
        'edit_user_id': request.GET.get('edit_user', '').strip(),
        'active_tab': section,
        'section_page_obj': users_page or sku_page or session_page or vehicle_page or logs_page,
    })


@user_passes_test(is_workflow_admin)
def admin_brand_tree(request, brand_id):
    brand = get_object_or_404(
        Brand.objects.prefetch_related('models__submodels__year_ranges'),
        pk=brand_id,
    )
    return render(request, 'management/partials/admin_brand_tree.html', {'brand': brand})


@user_passes_test(is_workflow_admin)
@require_POST
def edit_group(request):
    if request.method == 'POST':
        group_id = request.POST.get('group_id')
        new_name = (request.POST.get('name') or '').strip()
        if not new_name:
            messages.error(request, _('Group name is required.'))
            return redirect('admin_panel')
        if len(new_name) > 150:
            messages.error(request, _('Group name must be 150 characters or fewer.'))
            return redirect('admin_panel')
        group = get_object_or_404(Group, id=group_id)
        if Group.objects.filter(name__iexact=new_name).exclude(pk=group.pk).exists():
            messages.error(request, _('A group with that name already exists.'))
            return redirect('admin_panel')
        group.name = new_name
        group.save()
        ActivityLog.objects.create(
            user=request.user,
            action="edited",
            object_type="Group",
            object_name=new_name
        )
    return redirect('admin_panel')


@user_passes_test(is_workflow_admin)
@require_POST
def delete_group(request):
    if request.method == 'POST':
        group_id = request.POST.get('group_id')
        group = get_object_or_404(Group, id=group_id)
        ActivityLog.objects.create(
            user=request.user,
            action="deleted",
            object_type="Group",
            object_name=group.name
        )
        group.delete()
    return redirect('admin_panel')


@user_passes_test(is_workflow_admin)
@require_POST
def edit_user(request):
    if request.method == 'POST':
        user_id = request.POST.get('user_id')
        edit_redirect = f"{reverse('admin_panel')}?edit_user={user_id}#users"

        def add_edit_feedback(level, text):
            messages.add_message(
                request,
                level,
                text,
                extra_tags='edit-user-feedback',
            )

        if 'reset_password' in request.POST:
            new_password = request.POST.get('new_password') or ''
            confirm_password = request.POST.get('confirm_password') or ''
            is_ajax_password_reset = (
                request.headers.get('x-requested-with') == 'XMLHttpRequest'
            )

            def password_reset_response(success, feedback, status=200):
                feedback = list(feedback)
                if is_ajax_password_reset:
                    return JsonResponse(
                        {'success': success, 'messages': feedback},
                        status=status,
                    )
                level = messages.SUCCESS if success else messages.ERROR
                for message in feedback:
                    add_edit_feedback(level, message)
                return redirect(edit_redirect)

            try:
                user = User.objects.get(id=user_id)
                if user.is_superuser and not request.user.is_superuser:
                    return password_reset_response(
                        False,
                        [_('Only a Django superuser can reset another superuser password.')],
                        status=403,
                    )
                if not new_password:
                    return password_reset_response(
                        False,
                        [_('Enter a new password.')],
                        status=400,
                    )
                if new_password != confirm_password:
                    return password_reset_response(
                        False,
                        [_('The two password fields did not match.')],
                        status=400,
                    )
                try:
                    validate_password(new_password, user=user)
                except ValidationError as exc:
                    return password_reset_response(
                        False,
                        exc.messages,
                        status=400,
                    )

                user.set_password(new_password)
                user.save(update_fields=['password'])
                _invalidate_user_authentication(user.id)
                ActivityLog.objects.create(
                    user=request.user,
                    action='reset password',
                    object_type='User',
                    object_name=user.username,
                )
                return password_reset_response(
                    True,
                    [_('Password reset successfully for %(username)s.') % {'username': user.username}],
                )
            except User.DoesNotExist:
                return password_reset_response(
                    False,
                    [_('User not found.')],
                    status=404,
                )

        username = (request.POST.get('username') or '').strip()
        email = (request.POST.get('email') or '').strip()
        first_name = (request.POST.get('first_name') or '').strip()
        last_name = (request.POST.get('last_name') or '').strip()

        try:
            if not username:
                add_edit_feedback(messages.ERROR, _('Username is required.'))
                return redirect(edit_redirect)
            if User.objects.filter(username=username).exclude(id=user_id).exists():
                add_edit_feedback(messages.ERROR, _('That username is already in use.'))
                return redirect(edit_redirect)
            if len(username) > 150:
                add_edit_feedback(messages.ERROR, _('Username must be 150 characters or fewer.'))
                return redirect(edit_redirect)
            if len(first_name) > 150 or len(last_name) > 150:
                add_edit_feedback(messages.ERROR, _('Names must be 150 characters or fewer.'))
                return redirect(edit_redirect)
            if email:
                try:
                    validate_email(email)
                except ValidationError:
                    add_edit_feedback(messages.ERROR, _('Enter a valid email address.'))
                    return redirect(edit_redirect)
            user = User.objects.select_related('workflow_profile').get(id=user_id)
            if user.is_superuser and not request.user.is_superuser:
                add_edit_feedback(messages.ERROR, _('Only a Django superuser can edit another superuser account.'))
                return redirect(edit_redirect)
            profile, profile_created = UserProfile.objects.get_or_create(user=user)
            profile_form = UserWorkflowProfileForm(request.POST, request.FILES, instance=profile)
            if not profile_form.is_valid():
                for errors in profile_form.errors.values():
                    for error in errors:
                        add_edit_feedback(messages.ERROR, error)
                return redirect(edit_redirect)

            new_is_staff = user.is_staff
            new_is_superuser = user.is_superuser
            if request.user.is_superuser:
                new_is_superuser = request.POST.get('is_superuser') == 'on'
                new_is_staff = request.POST.get('is_staff') == 'on' or new_is_superuser
                removing_final_superuser = (
                    user.is_superuser
                    and not new_is_superuser
                    and User.objects.filter(is_superuser=True, is_active=True).count() <= 1
                )
                if removing_final_superuser:
                    add_edit_feedback(messages.ERROR, _('The final active superuser cannot be demoted.'))
                    return redirect(edit_redirect)

            user.username = username
            user.email = email
            user.first_name = first_name
            user.last_name = last_name
            user.is_staff = new_is_staff
            user.is_superuser = new_is_superuser
            with transaction.atomic():
                user.save()
                updated_profile = profile_form.save(commit=False)
                updated_profile.save()
                ActivityLog.objects.create(
                    user=request.user,
                    action="edited",
                    object_type="User",
                    object_name=username
                )

            add_edit_feedback(
                messages.SUCCESS,
                _('User %(username)s and workflow access were updated.') % {'username': username},
            )
        except User.DoesNotExist:
            add_edit_feedback(messages.ERROR, _('User not found.'))

    return redirect(edit_redirect)


def _invalidate_user_authentication(user_id):
    """Remove only the reset account's server sessions and DRF token."""
    session_keys = []
    for session in Session.objects.filter(expire_date__gte=now()).iterator():
        try:
            if str(session.get_decoded().get('_auth_user_id')) == str(user_id):
                session_keys.append(session.session_key)
        except Exception:
            logger.warning('Unable to inspect a session while resetting user %s.', user_id)
    if session_keys:
        Session.objects.filter(session_key__in=session_keys).delete()
    Token.objects.filter(user_id=user_id).delete()


@user_passes_test(is_workflow_admin)
@require_POST
def delete_user_photo(request, user_id):
    """Remove a selected user's photo without submitting the profile editor."""
    user = get_object_or_404(User.objects.select_related('workflow_profile'), pk=user_id)
    if user.is_superuser and not request.user.is_superuser:
        return JsonResponse({'success': False, 'messages': [_('Only a Django superuser can edit another superuser account.')]}, status=403)
    try:
        profile = user.workflow_profile
    except UserProfile.DoesNotExist:
        return JsonResponse({'success': False, 'messages': [_('User profile not found.')]}, status=404)

    old_name = profile.photo.name if profile.photo else ''
    if not old_name:
        return JsonResponse({'success': True, 'messages': [_('This user has no profile photo to remove.')]})
    profile.photo = None
    profile.save(update_fields=['photo'])
    try:
        default_storage.delete(old_name)
    except Exception:
        logger.warning('Profile photo record removed but storage cleanup failed for user %s.', user.pk, exc_info=True)
    ActivityLog.objects.create(user=request.user, action='removed photo', object_type='User', object_name=user.username)
    return JsonResponse({'success': True, 'messages': [_('Profile photo removed successfully.')]})


@user_passes_test(is_workflow_admin)
@require_POST
def delete_user(request):
    if request.method == 'POST':
        user_id = request.POST.get('user_id')
        try:
            user = User.objects.get(id=user_id)
            if user == request.user:
                messages.error(request, _("You cannot delete your own signed-in account."))
                return redirect('admin_panel')
            if user.is_superuser and not request.user.is_superuser:
                messages.error(request, _('Only a Django superuser can delete another superuser account.'))
                return redirect('admin_panel')
            if user.is_superuser and User.objects.filter(is_superuser=True, is_active=True).count() <= 1:
                messages.error(request, _("The final active superuser cannot be deleted."))
                return redirect('admin_panel')
            ActivityLog.objects.create(
                user=request.user,
                action="deleted",
                object_type="User",
                object_name=user.username
            )
            user.delete()
        except User.DoesNotExist:
            messages.error(request, _("User not found."))

    return redirect('admin_panel')


def get_active_users():
    sessions = Session.objects.filter(expire_date__gte=now())
    active_users = []

    # Collect all unique user IDs from active sessions
    user_ids = set()
    session_data_list = []
    for session in sessions:
        data = session.get_decoded()
        user_id = data.get('_auth_user_id')
        if user_id:
            user_ids.add(user_id)
            session_data_list.append((user_id, data.get('login_time'), data.get('ip_address', 'N/A'), session.session_key))

    # Query all users in one database hit
    users_map = {str(u.id): u for u in User.objects.filter(id__in=user_ids)}

    for user_id, login_time, ip_address, session_key in session_data_list:
        user = users_map.get(str(user_id))
        if user:
            active_users.append({
                'user': user,
                'login_time': login_time or 'N/A',
                'ip': ip_address,
                'session_key': session_key
            })

    return active_users


@login_required
def profile_settings(request):
    user = request.user
    if request.method == 'POST':
        if 'update_profile' in request.POST:
            first_name = request.POST.get('first_name', '').strip()
            last_name = request.POST.get('last_name', '').strip()
            email = request.POST.get('email', '').strip()
            phone_number = request.POST.get('phone_number', '').strip()
            profile_photo = request.FILES.get('photo')
            if len(first_name) > 150 or len(last_name) > 150:
                messages.error(request, _('Names must be 150 characters or fewer.'))
                return redirect('profile_settings')
            if len(phone_number) > UserProfile._meta.get_field('phone_number').max_length:
                messages.error(request, _('Phone number must be 30 characters or fewer.'))
                return redirect('profile_settings')
            if email:
                try:
                    validate_email(email)
                except ValidationError:
                    messages.error(request, _('Enter a valid email address.'))
                    return redirect('profile_settings')

            if profile_photo:
                if profile_photo.size > 5 * 1024 * 1024:
                    messages.error(request, _('Profile photo must be 5 MB or smaller.'))
                    return redirect('profile_settings')
                try:
                    image = Image.open(profile_photo)
                    image.verify()
                    profile_photo.seek(0)
                except (UnidentifiedImageError, OSError, ValueError):
                    messages.error(request, _('Upload a valid image.'))
                    return redirect('profile_settings')

            with transaction.atomic():
                user.first_name = first_name
                user.last_name = last_name
                user.email = email
                user.save(update_fields=['first_name', 'last_name', 'email'])

                profile, profile_created = UserProfile.objects.get_or_create(user=user)
                profile.phone_number = phone_number
                profile_fields = ['phone_number']
                if request.POST.get('remove_photo') == '1':
                    profile.photo = None
                    profile_fields.append('photo')
                elif profile_photo:
                    profile.photo = profile_photo
                    profile_fields.append('photo')
                profile.save(update_fields=profile_fields)
            
            ActivityLog.objects.create(
                user=request.user,
                action="updated profile",
                object_type="User",
                object_name=user.username
            )
            
            messages.success(request, _("Your profile details have been updated successfully."))
            return redirect('profile_settings')
            
        elif 'change_password' in request.POST:
            password_form = PasswordChangeForm(user, request.POST)
            if password_form.is_valid():
                user = password_form.save()
                update_session_auth_hash(request, user)
                
                ActivityLog.objects.create(
                    user=request.user,
                    action="changed password",
                    object_type="User",
                    object_name=user.username
                )
                
                messages.success(request, _("Your password has been changed successfully."))
                return redirect('profile_settings')
            else:
                for field, errors in password_form.errors.items():
                    for error in errors:
                        messages.error(request, f"{field.capitalize()}: {error}")
    
    password_form = PasswordChangeForm(user)
    return render(request, 'management/profile_settings.html', {
        'password_form': password_form,
    })


@user_passes_test(is_workflow_admin)
@require_POST
def terminate_session_view(request, session_key):
    try:
        deleted_count, deleted_details = Session.objects.filter(session_key=session_key).delete()
        if deleted_count > 0:
            messages.success(request, _("Session terminated successfully."))
        else:
            messages.error(request, _("Session not found or already expired."))
    except Exception as e:
        messages.error(request, _("Error terminating session: %(error)s") % {'error': e})
    return redirect('admin_panel')


@user_passes_test(is_workflow_admin)
@require_POST
def terminate_all_sessions_view(request):
    try:
        current_key = request.session.session_key
        deleted_count, deleted_details = Session.objects.exclude(session_key=current_key).delete()
        messages.success(request, ngettext(
            'Terminated %(count)s active session. Only your current session remains active.',
            'Terminated %(count)s active sessions. Only your current session remains active.',
            deleted_count,
        ) % {'count': deleted_count})
    except Exception as e:
        messages.error(request, _("Error clearing sessions: %(error)s") % {'error': e})
    return redirect('admin_panel')


def get_sorted_chat_users(current_user):
    latest_message = ChatMessage.objects.filter(
        Q(sender_id=OuterRef('pk'), recipient=current_user)
        | Q(sender=current_user, recipient_id=OuterRef('pk'))
    ).order_by('-created_at', '-pk')
    user_list = list(
        User.objects.filter(is_active=True)
        .exclude(id=current_user.id)
        .select_related('workflow_profile__country')
        .annotate(
            chat_unread_count=Count(
                'sent_chat_messages',
                filter=Q(
                    sent_chat_messages__recipient=current_user,
                    sent_chat_messages__is_read=False,
                ),
            ),
            latest_unread_time=Max(
                'sent_chat_messages__created_at',
                filter=Q(
                    sent_chat_messages__recipient=current_user,
                    sent_chat_messages__is_read=False,
                ),
            ),
            latest_message_id=Subquery(latest_message.values('pk')[:1]),
            latest_message_time=Subquery(latest_message.values('created_at')[:1]),
        )
    )
    last_messages = {
        message.pk: message
        for message in ChatMessage.objects.filter(
            pk__in=[u.latest_message_id for u in user_list if u.latest_message_id]
        ).select_related('complaint')
    }
    raw_users = []
    
    for u in user_list:
        try:
            prof = u.workflow_profile
        except UserProfile.DoesNotExist:
            prof = None
        role_code = getattr(prof, 'role', '')
        role_label = dict(WorkflowRoles.CHOICES).get(role_code, 'User')
        
        unread_count = u.chat_unread_count
        last_msg = last_messages.get(u.latest_message_id)

        raw_users.append({
            'user': u,
            'role_code': role_code,
            'role_label': role_label,
            'country_flag_url': getattr(prof, 'country_flag_url', None),
            'unread_count': unread_count,
            'latest_unread_time': u.latest_unread_time,
            'last_message': last_msg,
            'last_message_time': u.latest_message_time,
        })

    # Tier 1: Users with unread messages (ordered by latest unread message timestamp descending)
    unread_users = [item for item in raw_users if item['unread_count'] > 0]
    unread_users.sort(key=lambda item: item['latest_unread_time'], reverse=True)

    # Tier 2: Users with conversation history but no unread messages (ordered by last message timestamp descending)
    history_users = [item for item in raw_users if item['unread_count'] == 0 and item['last_message'] is not None]
    history_users.sort(key=lambda item: item['last_message_time'], reverse=True)

    # Tier 3: Users without conversation history (alphabetical by username)
    no_msg_users = [item for item in raw_users if item['unread_count'] == 0 and item['last_message'] is None]
    no_msg_users.sort(key=lambda item: item['user'].username.lower())

    return unread_users + history_users + no_msg_users


@login_required
def chat_view(request):
    recipient_id = request.GET.get('user')
    complaint_id = request.GET.get('complaint')
    
    users_data = get_sorted_chat_users(request.user)

    selected_user = None
    if recipient_id and recipient_id.isdigit():
        selected_user = User.objects.filter(id=int(recipient_id), is_active=True).exclude(id=request.user.id).first()
    
    if not selected_user and users_data:
        selected_user = users_data[0]['user']

    selected_complaint = None
    if complaint_id:
        selected_complaint = Complaint.objects.filter(complaint_id=complaint_id).first()

    selected_user_profile = None
    chat_messages = []
    if selected_user:
        selected_user_profile = get_user_profile(selected_user)
        ChatMessage.objects.filter(sender=selected_user, recipient=request.user, is_read=False).update(is_read=True)
        latest_messages = ChatMessage.objects.filter(
            Q(sender=request.user, recipient=selected_user) | Q(sender=selected_user, recipient=request.user)
        ).select_related('sender', 'recipient', 'complaint').order_by('-created_at', '-pk')[:50]
        chat_messages = list(reversed(list(latest_messages)))
        
        # After marking read for selected user, update unread_count in users_data for clean initial render
        for ud in users_data:
            if ud['user'].id == selected_user.id:
                ud['unread_count'] = 0

    selected_role_label = ""
    if selected_user_profile:
        selected_role_label = dict(WorkflowRoles.CHOICES).get(getattr(selected_user_profile, 'role', ''), 'User')

    default_message = ""
    if selected_complaint:
        default_message = f"Regarding Complaint {selected_complaint.complaint_id} ({selected_complaint.get_complaint_type_display()} - {selected_complaint.brand} {selected_complaint.model}): "

    total_unread_chat_count = sum(ud['unread_count'] for ud in users_data)

    return render(request, 'management/chat.html', {
        'users_data': users_data,
        'selected_user': selected_user,
        'selected_user_profile': selected_user_profile,
        'selected_role_label': selected_role_label,
        'selected_complaint': selected_complaint,
        'chat_messages': chat_messages,
        'chat_has_older': len(chat_messages) == 50,
        'default_message': default_message,
        'total_unread_chat_count': total_unread_chat_count,
    })


@login_required
def chat_users_api(request):
    users_data = get_sorted_chat_users(request.user)
    data = []
    total_unread = 0
    for ud in users_data:
        last_msg_str = ""
        if ud['last_message']:
            last_msg_str = ud['last_message'].created_at.strftime('%b %d')
        total_unread += ud['unread_count']
        data.append({
            'user_id': ud['user'].id,
            'username': ud['user'].username,
            'role_label': ud['role_label'],
            'role_code': ud['role_code'] or 'default',
            'country_flag_url': ud['country_flag_url'] or '',
            'unread_count': ud['unread_count'],
            'last_message_date': last_msg_str,
        })
    return JsonResponse({'status': 'ok', 'users': data, 'total_unread': total_unread})


@login_required
def chat_messages_api(request, user_id):
    target_user = get_object_or_404(User.objects.filter(is_active=True).exclude(id=request.user.id), id=user_id)
    ChatMessage.objects.filter(sender=target_user, recipient=request.user, is_read=False).update(is_read=True)
    
    messages_qs = ChatMessage.objects.filter(
        Q(sender=request.user, recipient=target_user) | Q(sender=target_user, recipient=request.user)
    ).select_related('sender', 'complaint')

    after_id = request.GET.get('after_id', '').strip()
    before_id = request.GET.get('before_id', '').strip()
    if after_id.isdigit():
        messages_qs = messages_qs.filter(pk__gt=int(after_id)).order_by('pk')[:50]
        has_more = False
    else:
        if before_id.isdigit():
            messages_qs = messages_qs.filter(pk__lt=int(before_id))
        page = list(messages_qs.order_by('-pk')[:51])
        has_more = len(page) > 50
        messages_qs = list(reversed(page[:50]))
    
    data = []
    for m in messages_qs:
        data.append({
            'id': m.id,
            'sender': m.sender.username,
            'sender_id': m.sender.id,
            'is_self': m.sender_id == request.user.id,
            'message': m.message,
            'complaint_id': m.complaint.complaint_id if m.complaint else None,
            'created_at': m.created_at.strftime('%b %d, %H:%M'),
        })
    return JsonResponse({'status': 'ok', 'messages': data, 'has_more': has_more})


@login_required
@require_POST
def chat_send_api(request):
    recipient_id = request.POST.get('recipient_id')
    message_text = request.POST.get('message', '').strip()
    complaint_id = request.POST.get('complaint_id', '').strip()

    if not recipient_id or not message_text:
        return JsonResponse({'status': 'error', 'error': 'Recipient and message content are required.'}, status=400)
    if len(message_text) > 5000:
        return JsonResponse({'status': 'error', 'error': 'Messages must be 5000 characters or fewer.'}, status=400)

    recipient = get_object_or_404(User.objects.filter(is_active=True).exclude(id=request.user.id), id=recipient_id)
    complaint = None
    if complaint_id:
        complaint = get_object_or_404(
            visible_complaints_for_user(request.user),
            complaint_id=complaint_id,
        )

    chat_msg = ChatMessage.objects.create(
        sender=request.user,
        recipient=recipient,
        complaint=complaint,
        message=message_text,
    )

    notif_title = f"New message from {request.user.username}"
    notif_msg = message_text[:120]
    if complaint:
        notif_msg = f"[{complaint.complaint_id}] {notif_msg}"

    Notification.objects.create(
        recipient=recipient,
        complaint=complaint,
        title=notif_title,
        message=notif_msg,
        notification_type='chat'
    )

    return JsonResponse({
        'status': 'ok',
        'message': {
            'id': chat_msg.id,
            'sender': chat_msg.sender.username,
            'sender_id': chat_msg.sender.id,
            'is_self': True,
            'message': chat_msg.message,
            'complaint_id': chat_msg.complaint.complaint_id if chat_msg.complaint else None,
            'created_at': chat_msg.created_at.strftime('%b %d, %H:%M'),
        }
    })

