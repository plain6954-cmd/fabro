import csv
import logging
import os
import uuid
from io import TextIOWrapper

from django.contrib import messages
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth.forms import PasswordChangeForm
from django.contrib.auth.models import Group, Permission, User
from django.contrib.sessions.models import Session
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.storage import default_storage
from django.core.paginator import Paginator
from django.core.validators import validate_email
from django.db import IntegrityError, transaction
from django.db.models import Count, Q, Case, When, Value, IntegerField
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.dateparse import parse_date
from django.utils.text import get_valid_filename
from django.utils.timezone import now
from django.views.decorators.http import require_POST

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
    ComplaintTypes,
    DecisionStatuses,
    MasterSetting,
    Model,
    Notification,
    SKU,
    SubModel,
    UserProfile,
    WorkflowRoles,
    WorkflowStatuses,
    YearRange,
)
from .services.workflow import (
    REPORT_EDITABLE_FIELDS,
    approval_progress,
    can_start_factory_review,
    can_user_create_complaint,
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
    is_country_executive,
    prepare_complaint_for_create,
    record_approval_decision,
    record_report_edit,
    start_action_execution,
    submit_factory_review,
    is_workflow_admin,
    visible_complaints_for_user,
)


MAX_COMPLAINT_MEDIA_FILES = 10
MAX_COMPLAINT_MEDIA_SIZE = 10 * 1024 * 1024
MAX_CSV_IMPORT_ROWS = 5000
ALLOWED_COMPLAINT_MEDIA_EXTENSIONS = {
    '.jpg', '.jpeg', '.png', '.webp', '.gif',
    '.mp4', '.mov', '.webm', '.avi', '.mkv',
}
logger = logging.getLogger(__name__)


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
            raise ValidationError(f"Missing required CSV columns: {', '.join(missing)}.")
        for row_number, row in enumerate(reader, start=2):
            if row_number > MAX_CSV_IMPORT_ROWS + 1:
                raise ValidationError(f'CSV files may contain at most {MAX_CSV_IMPORT_ROWS} data rows.')
            yield row_number, {
                (key or '').strip().lower(): (value or '').strip()
                for key, value in row.items()
            }
    except UnicodeDecodeError as exc:
        raise ValidationError('CSV must use UTF-8 encoding.') from exc
    except csv.Error as exc:
        raise ValidationError(f'CSV could not be parsed: {exc}.') from exc
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
        for field_name in ('country', 'case_sub_category'):
            if field_name in form.fields:
                form.fields[field_name].disabled = True
    elif is_country_executive(user) and 'country' in form.fields:
        profile = get_user_profile(user)
        if profile and profile.country_id:
            form.fields['country'].initial = profile.country_id
            form.fields['country'].disabled = True


def _validate_complaint_media_files(uploaded_files, existing_count=0):
    if existing_count + len(uploaded_files) > MAX_COMPLAINT_MEDIA_FILES:
        raise ValidationError(f'Keep at most {MAX_COMPLAINT_MEDIA_FILES} media files on one complaint.')

    for uploaded_file in uploaded_files:
        extension = os.path.splitext(uploaded_file.name)[1].lower()
        content_type = (getattr(uploaded_file, 'content_type', '') or '').lower()
        if extension not in ALLOWED_COMPLAINT_MEDIA_EXTENSIONS:
            raise ValidationError(f'{uploaded_file.name}: unsupported file type.')
        if not (content_type.startswith('image/') or content_type.startswith('video/')):
            raise ValidationError(f'{uploaded_file.name}: only image and video files are allowed.')
        if uploaded_file.size > MAX_COMPLAINT_MEDIA_SIZE:
            raise ValidationError(f'{uploaded_file.name}: file size exceeds 10 MB.')


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
    storage_name = media.storage_name
    if storage_name:
        try:
            default_storage.delete(storage_name)
        except Exception:
            logger.warning('Unable to remove stored complaint media %s', storage_name, exc_info=True)
    media.delete()

@login_required
def index(request):
    # Get dashboard statistics
    visible_complaints = visible_complaints_for_user(request.user, Complaint.objects.all())
    today = now().date()
    complaint_status_counts = dict(
        visible_complaints.values_list('status').annotate(count=Count('status'))
    )
    complaint_type_counts = dict(
        visible_complaints.values_list('complaint_type').annotate(count=Count('complaint_type'))
    )
    complaints_this_month = visible_complaints.filter(
        date__year=today.year,
        date__month=today.month,
    ).count()
    resolved_this_month = visible_complaints.filter(
        status='Closed',
        closed_at__year=today.year,
        closed_at__month=today.month,
    ).count()
    unread_notifications = list(Notification.objects.filter(
        recipient=request.user,
        is_read=False,
    ).select_related('complaint'))
    current_profile = get_user_profile(request.user)
    pending_approval_count = 0
    if current_profile and current_profile.role == WorkflowRoles.APPROVER:
        pending_approval_count = ComplaintApproval.objects.filter(
            approver_user=request.user,
            status=DecisionStatuses.PENDING,
            complaint__workflow_status__in=[
                WorkflowStatuses.AWAITING_APPROVAL,
                WorkflowStatuses.PARTIALLY_APPROVED,
            ],
        ).count()

    context = {
        'total_complaints': sum(complaint_status_counts.values()),
        'open_complaints': complaint_status_counts.get('Open', 0),
        'closed_complaints': complaint_status_counts.get('Closed', 0),
        'on_hold_complaints': complaint_status_counts.get('On Hold', 0),
        'pattern_complaints': complaint_type_counts.get(ComplaintTypes.PATTERN, 0),
        'production_complaints': complaint_type_counts.get(ComplaintTypes.PRODUCTION, 0),
        'line_complaints': complaint_type_counts.get(ComplaintTypes.LINE, 0),
        'complaints_this_month': complaints_this_month,
        'resolved_this_month': resolved_this_month,
        'total_vehicles': YearRange.objects.count(),
        'total_skus': SKU.objects.count(),
        'total_settings': MasterSetting.objects.count(),
        'dashboard_notifications': unread_notifications[:4],
        'unread_notification_count': len(unread_notifications),
        'pending_approval_count': pending_approval_count,
        'recent_complaints': visible_complaints.select_related(
            'brand', 'model', 'sub_model', 'year', 'person', 'sku'
        ).annotate(
            sort_weight=Case(
                When(status='Closed', then=Value(1)),
                When(workflow_status='closed', then=Value(1)),
                default=Value(0),
                output_field=IntegerField(),
            )
        ).order_by('sort_weight', '-date')[:15],
    }
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
            
            model, _ = Model.objects.get_or_create(brand=brand, name=model_name)
            sub_model, _ = SubModel.objects.get_or_create(model=model, name=sub_model_name)

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
                YearRange.objects.create(
                    sub_model=sub_model,
                    year_start=year_start,
                    year_end=year_end,
                    number_of_seats=number_of_seats,
                    number_of_doors=number_of_doors,
                    layout_code=layout_code,
                    vehicle_country=form.cleaned_data.get("vehicle_country"),
                    measurement_country=form.cleaned_data.get("measurement_country")
                )
                ActivityLog.objects.create(
                    user=request.user,
                    action="created",
                    object_type="Car",
                    object_name=f"{brand_name} {model_name} {sub_model_name} ({year_start}-{year_end})"
                )
                messages.success(request, 'Vehicle added successfully!')
                return redirect('car_details')

    new_search_enabled = True
    scoped_search_enabled = True

    # Fetch car data (Optimized via select_related)
    yr_qs = YearRange.objects.select_related('sub_model__model__brand', 'vehicle_country', 'measurement_country').all()
    if search_query:
        if search_column == 'layout_code':
            yr_qs = yr_qs.filter(layout_code__icontains=search_query)
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
                Q(layout_code__icontains=search_query) |
                Q(sub_model__model__brand__name__icontains=search_query) |
                Q(sub_model__model__name__icontains=search_query) |
                Q(sub_model__name__icontains=search_query) |
                Q(vehicle_country__name__icontains=search_query) |
                Q(measurement_country__name__icontains=search_query)
            )

    car_data = []
    for yr in yr_qs:
        car_data.append({
            "layout_code": yr.layout_code,
            "id": yr.id,
            "brand_id": yr.sub_model.model.brand.id if yr.sub_model and yr.sub_model.model and yr.sub_model.model.brand else None,
            "brand": yr.sub_model.model.brand.name if yr.sub_model and yr.sub_model.model and yr.sub_model.model.brand else '',
            "brand_logo": yr.sub_model.model.brand.logo if yr.sub_model and yr.sub_model.model and yr.sub_model.model.brand else None,
            "model_id": yr.sub_model.model.id if yr.sub_model and yr.sub_model.model else None,
            "model": yr.sub_model.model.name if yr.sub_model and yr.sub_model.model else '',
            "sub_model_id": yr.sub_model.id if yr.sub_model else None,
            "sub_model": yr.sub_model.name if yr.sub_model else '',
            "year_start": yr.year_start,
            "year_end": yr.year_end,
            "seats": yr.number_of_seats,
            "doors": yr.number_of_doors,
            "vehicle_country": yr.vehicle_country.name if yr.vehicle_country else '-',
            "measurement_country": yr.measurement_country.name if yr.measurement_country else '-'
        })

    countries = MasterSetting.objects.filter(category='Country').order_by('name')

    return render(request, 'management/car_details.html', {
        'form': form,
        'car_data': car_data,
        'countries': countries,
        'show_duplicate_modal': show_duplicate_modal,
        'show_layout_code_error_modal': show_layout_code_error_modal,
        'conflicting_car': conflicting_car,
        'search_query': search_query,
        'search_column': search_column,
        'search_by': search_column,
        'new_search_enabled': new_search_enabled,
        'scoped_search_enabled': scoped_search_enabled,
    })


@login_required
@require_POST
def delete_car_detail(request, year_range_id):
    if not _can_manage_catalog(request.user):
        raise PermissionDenied('Only staff users can delete vehicles.')
    year_range = get_object_or_404(YearRange, id=year_range_id)
    messages.success(request, 'Vehicle deleted successfully!')
    ActivityLog.objects.create(
        user=request.user,
        action="deleted",
        object_type="Car",
        object_name=f"{year_range.sub_model.model.brand.name} {year_range.sub_model.model.name} {year_range.sub_model.name} ({year_range.year_start}-{year_range.year_end})"
    )
    year_range.delete()
    return redirect('car_details')

@login_required
def edit_car_detail(request, car_id):
    if not _can_manage_catalog(request.user):
        raise PermissionDenied('Only staff users can edit vehicles.')
    year_range = get_object_or_404(YearRange, id=car_id)
    existing_logo = year_range.sub_model.model.brand.logo

    # Prepopulate form values
    initial_data = {
        'layout_code': year_range.layout_code,
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
        form = CarDetailsForm(request.POST, request.FILES)
        if form.is_valid():
            layout_code = form.cleaned_data["layout_code"].strip()
            brand_name = form.cleaned_data["brand_name"].strip()
            brand_logo = form.cleaned_data.get("brand_logo")
            model_name = form.cleaned_data["model_name"].strip()
            sub_model_name = form.cleaned_data["sub_model_name"].strip() or '-'
            year_start = form.cleaned_data["year_start"]
            year_end = form.cleaned_data["year_end"]
            number_of_seats = form.cleaned_data["number_of_seats"]
            number_of_doors = form.cleaned_data["number_of_doors"]

            # Check for layout code duplication (excluding current record)
            if YearRange.objects.filter(layout_code=layout_code).exclude(id=car_id).exists():
                messages.error(request, 'Layout code already exists. Please use a unique layout code.')
                return render(request, 'management/edit_car_detail.html', {
                    'form': form,
                    'car_id': car_id,
                    'existing_logo': existing_logo,
                    'countries': countries,
                })

            brand, _ = Brand.objects.get_or_create(name=brand_name)
            
            # Update brand logo if provided
            if brand_logo:
                brand.logo = brand_logo
                brand.save()
            
            model, _ = Model.objects.get_or_create(brand=brand, name=model_name)

            sub_model = None
            if sub_model_name:
                sub_model, _ = SubModel.objects.get_or_create(model=model, name=sub_model_name)

            # Update the existing YearRange
            year_range.sub_model = sub_model
            year_range.year_start = year_start
            year_range.year_end = year_end
            year_range.number_of_seats = number_of_seats
            year_range.number_of_doors = number_of_doors
            year_range.layout_code = layout_code
            year_range.vehicle_country = form.cleaned_data.get("vehicle_country")
            year_range.measurement_country = form.cleaned_data.get("measurement_country")
            year_range.save()

            messages.success(request, 'Vehicle updated successfully!')
            ActivityLog.objects.create(
                user=request.user,
                action="updated",
                object_type="Car",
                object_name=f"{brand_name} {model_name} {sub_model_name} ({year_start}-{year_end})"
            )
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
def master_settings(request):
    if not is_workflow_admin(request.user):
        messages.error(request, "This page is restricted to administrators only.")
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
    for category, _ in MasterSetting.CATEGORY_CHOICES:
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
    valid_complaint_types = {value for value, _ in ComplaintTypes.CHOICES}
    selected_complaint_type = request.POST.get('complaint_type', ComplaintTypes.PATTERN)
    if selected_complaint_type not in valid_complaint_types:
        selected_complaint_type = ComplaintTypes.PATTERN
    template_context = {
        'selected_complaint_type': selected_complaint_type,
        'can_create_line': not is_country_executive(request.user),
    }
    if request.method == 'POST':
        form = ComplaintForm(request.POST)
        _configure_complaint_form(form, request.user)
        uploaded_files = request.FILES.getlist('media_files')
        try:
            _validate_complaint_media_files(uploaded_files)
        except ValidationError as exc:
            form.add_error(None, exc)
            return render(request, 'management/add_complaint.html', {'form': form, **template_context})
        if form.is_valid():
            complaint = form.save(commit=False)
            complaint.complaint_type = selected_complaint_type
            try:
                prepare_complaint_for_create(complaint, request.user)
            except PermissionError as exc:
                messages.error(request, str(exc))
                return render(request, 'management/add_complaint.html', {'form': form, **template_context})
            stored_names = []
            try:
                with transaction.atomic():
                    complaint.save()
                    initialize_created_complaint(complaint, request.user)
                    stored_names = _save_complaint_media_files(complaint, uploaded_files)
                    ActivityLog.objects.create(
                        user=request.user,
                        action='created',
                        object_type='complaint',
                        object_name=complaint.complaint_id,
                    )
            except Exception:
                for stored_name in stored_names:
                    default_storage.delete(stored_name)
                logger.exception('Unable to create complaint for user %s', request.user.pk)
                form.add_error(None, 'The complaint could not be saved. Please try again.')
                return render(request, 'management/add_complaint.html', {'form': form, **template_context})
            return redirect('complaint_list')
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
            
        form = ComplaintForm(initial=initial)
        _configure_complaint_form(form, request.user)
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
    year_ranges = YearRange.objects.filter(sub_model_id=sub_model_id).values('id', 'year_start', 'year_end')
    return JsonResponse([{'id': yr['id'], 'range': f"{yr['year_start'] % 100}-{yr['year_end'] % 100}"} for yr in year_ranges], safe=False)

@login_required
def get_filtered_skus(request):
    skus = SKU.objects.select_related('region').all().order_by('code')

    country_id = request.GET.get('country')
    region_id = request.GET.get('region')
    region_filter = None

    if region_id:
        region_filter = Q(region_id=region_id)
    elif country_id:
        selected_country = MasterSetting.objects.filter(pk=country_id).first()
        if selected_country:
            region_filter = Q(region__name__iexact=selected_country.name)

    if region_filter is not None and skus.filter(region_filter).exists():
        skus = skus.filter(region_filter)

    vehicle_lookups = (
        (Brand, request.GET.get('brand')),
        (Model, request.GET.get('model')),
        (SubModel, request.GET.get('sub_model')),
    )

    for model_class, object_id in vehicle_lookups:
        if not object_id:
            continue
        term = model_class.objects.filter(pk=object_id).values_list('name', flat=True).first()
        if not term:
            continue
        skus = skus.filter(Q(code__icontains=term) | Q(description__icontains=term))

    data = [
        {
            'id': sku.id,
            'name': f"{sku.code} - {sku.description}" if sku.description else sku.code,
        }
        for sku in skus[:200]
    ]
    return JsonResponse(data, safe=False)

@login_required
def complaint_list(request):
    complaints = visible_complaints_for_user(request.user, Complaint.objects.select_related(
        'channel', 'country', 'person', 'case_sub_category',
        'series', 'material', 'sku', 'brand', 'model', 'sub_model', 'year',
        'created_by', 'assigned_factory_executive', 'closed_by',
    ).prefetch_related(
        'media_files',
        'approvals__approver_user',
        'timeline_events__user',
    ).all().annotate(
        sort_weight=Case(
            When(status='Closed', then=Value(1)),
            When(workflow_status='closed', then=Value(1)),
            default=Value(0),
            output_field=IntegerField(),
        )
    ).order_by('sort_weight', '-complaint_id'))
    filter_scope = complaints
    search_query = request.GET.get('search', '')
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
        'reported_by': 'person__name',
    }
    search_by = request.GET.get('search_by', 'complaint_id')
    search_field = allowed_search_fields.get(search_by, 'complaint_id')
    selected_brand = request.GET.get('brand', '')
    selected_country = request.GET.get('country', '')
    selected_status = request.GET.get('status', '')
    selected_priority = request.GET.get('priority', '')
    selected_channel = request.GET.get('channel', '')
    selected_person = request.GET.get('person', '')
    selected_complaint_type = request.GET.get('complaint_type', '')

    from_date = request.GET.get('from_date', '')
    to_date = request.GET.get('to_date', '')

    if search_query:
        trimmed_search_query = search_query[:200]
        if search_by == 'complaint_type':
            matching_type_values = [
                value
                for value, label in ComplaintTypes.CHOICES
                if trimmed_search_query.lower() in value.lower()
                or trimmed_search_query.lower() in label.lower()
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
        complaints = complaints.filter(person=selected_person) 

    if selected_brand:
        complaints = complaints.filter(brand_id=selected_brand)

    if selected_country:
        complaints = complaints.filter(country=selected_country)

    if from_date:
        parsed_from_date = parse_date(from_date)
        if parsed_from_date:
            complaints = complaints.filter(date__gte=parsed_from_date)

    if to_date:
        parsed_to_date = parse_date(to_date)
        if parsed_to_date:
            complaints = complaints.filter(date__lte=parsed_to_date)

    if selected_complaint_type in {value for value, _ in ComplaintTypes.CHOICES}:
        complaints = complaints.filter(complaint_type=selected_complaint_type)

    brands = Brand.objects.all().order_by('name')
    countries = MasterSetting.objects.filter(category='Country').order_by('name')
    channels = MasterSetting.objects.filter(category='Channel').order_by('name')
    persons = MasterSetting.objects.filter(category='Reported By').order_by('name')
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
    pagination_query = request.GET.copy()
    pagination_query.pop('page', None)
    pagination_querystring = pagination_query.urlencode()

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
def edit_complaint(request, complaint_id):
    complaint = get_object_or_404(
        visible_complaints_for_user(request.user, Complaint.objects.all()),
        complaint_id=complaint_id
    )

    if not can_user_edit_report_step(request.user, complaint):
        messages.error(request, 'This complaint can no longer be edited from the report step.')
        return redirect('complaint_list')

    if request.method == 'POST':
        tracked_fields = {
            field_name: getattr(complaint, field_name)
            for field_name in REPORT_EDITABLE_FIELDS
        }
        form = ComplaintForm(request.POST, instance=complaint)
        _configure_complaint_form(form, request.user)
        uploaded_files = request.FILES.getlist('media_files')
        media_to_delete = request.POST.getlist('delete_media')
        remaining_media_count = complaint.media_files.exclude(id__in=media_to_delete).count()
        try:
            _validate_complaint_media_files(uploaded_files, existing_count=remaining_media_count)
        except ValidationError as exc:
            form.add_error(None, exc)
            return render(request, 'management/edit_complaint.html', {
                'form': form,
                'complaint': complaint,
                'media_files': complaint.media_files.all(),
            })
        if form.is_valid():
            complaint = form.save()
            changes = {
                field_name: (old_value, getattr(complaint, field_name))
                for field_name, old_value in tracked_fields.items()
                if field_name in form.changed_data
            }

            # Delete selected media
            removed_media = list(ComplaintMedia.objects.filter(
                id__in=media_to_delete,
                complaint=complaint,
            ))
            removed_media_count = len(removed_media)
            for media in removed_media:
                _delete_complaint_media_record(media)

            _save_complaint_media_files(
                complaint,
                uploaded_files,
                existing_count=remaining_media_count,
            )
            record_report_edit(
                complaint,
                request.user,
                changes=changes,
                media_added=len(uploaded_files),
                media_removed=removed_media_count,
            )

            ActivityLog.objects.create(
                user=request.user,
                action="updated",
                object_type="complaint",
                object_name=complaint_id)

            return redirect('complaint_list')
    else:
        form = ComplaintForm(instance=complaint)
        _configure_complaint_form(form, request.user)

    media_files = complaint.media_files.all()

    return render(request, 'management/edit_complaint.html', {
        'form': form,
        'complaint': complaint,
        'media_files': media_files,
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
        messages.error(request, 'You are not allowed to review this complaint.')
        return redirect('complaint_list')

    if not can_start_factory_review(complaint):
        messages.error(request, 'This complaint is not ready for factory review.')
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
                messages.success(request, 'Factory review submitted for approval.')
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
    
    # Base queryset scoped to user visibility
    base_qs = visible_complaints_for_user(
        request.user,
        Complaint.objects.select_related(
            'channel', 'country', 'person', 'case_sub_category',
            'series', 'material', 'sku', 'brand', 'model', 'sub_model', 'year',
            'created_by', 'assigned_factory_executive', 'closed_by',
        ).prefetch_related(
            'media_files',
            'approvals__approver_user',
            'approvals__trigger_approval__approver_user',
            'timeline_events__user',
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
    active_complaints_all = base_qs.filter(
        workflow_status__in=[
            WorkflowStatuses.AWAITING_APPROVAL,
            WorkflowStatuses.PARTIALLY_APPROVED,
        ]
    )
    total_active_count = active_complaints_all.count()

    my_pending_count = 0
    if profile and profile.role == WorkflowRoles.APPROVER:
        my_pending_count = ComplaintApproval.objects.filter(
            approver_user=request.user,
            status=DecisionStatuses.PENDING,
            complaint__workflow_status__in=[
                WorkflowStatuses.AWAITING_APPROVAL,
                WorkflowStatuses.PARTIALLY_APPROVED,
            ],
        ).count()

    partially_approved_count = base_qs.filter(workflow_status=WorkflowStatuses.PARTIALLY_APPROVED).count()
    
    reconsideration_count = active_complaints_all.filter(
        approvals__review_stage=ApprovalStages.RECONSIDERATION,
        approvals__status=DecisionStatuses.PENDING,
    ).distinct().count()

    top_priority_count = active_complaints_all.filter(
        Q(factory_priority='top') | Q(priority='High')
    ).distinct().count()

    # Filter applied to list
    complaints = base_qs
    if status_filter == 'active':
        complaints = complaints.filter(
            workflow_status__in=[
                WorkflowStatuses.AWAITING_APPROVAL,
                WorkflowStatuses.PARTIALLY_APPROVED,
            ]
        )
    elif status_filter == 'my_pending':
        if profile and profile.role == WorkflowRoles.APPROVER:
            complaints = complaints.filter(
                workflow_status__in=[
                    WorkflowStatuses.AWAITING_APPROVAL,
                    WorkflowStatuses.PARTIALLY_APPROVED,
                ],
                approvals__approver_user=request.user,
                approvals__status=DecisionStatuses.PENDING,
            ).distinct()
        else:
            complaints = complaints.filter(
                workflow_status__in=[
                    WorkflowStatuses.AWAITING_APPROVAL,
                    WorkflowStatuses.PARTIALLY_APPROVED,
                ]
            )
    elif status_filter == 'partially_approved':
        complaints = complaints.filter(workflow_status=WorkflowStatuses.PARTIALLY_APPROVED)
    elif status_filter == 'reconsideration':
        complaints = complaints.filter(
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
        complaints = complaints.filter(
            workflow_status__in=[
                WorkflowStatuses.APPROVED,
                WorkflowStatuses.ACTION_IN_PROGRESS,
                WorkflowStatuses.PENDING_FINAL_UPDATE,
                WorkflowStatuses.CLOSED,
            ]
        )
    elif status_filter == 'all':
        complaints = complaints.filter(approvals__isnull=False).distinct()

    # Search filter
    if search_query:
        if search_by == 'complaint_id':
            complaints = complaints.filter(complaint_id__icontains=search_query)
        elif search_by == 'complaint_type':
            complaints = complaints.filter(complaint_type__icontains=search_query)
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
            complaints = complaints.filter(
                Q(complaint_id__icontains=search_query)
                | Q(brand__name__icontains=search_query)
                | Q(model__name__icontains=search_query)
                | Q(sku__code__icontains=search_query)
                | Q(country__name__icontains=search_query)
                | Q(channel__name__icontains=search_query)
                | Q(factory_reason__icontains=search_query)
                | Q(factory_action_plan__icontains=search_query)
                | Q(batch_order__icontains=search_query)
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

    complaints = complaints.order_by('-date', '-complaint_id')

    # Build enriched approval item list
    approval_items = []
    for complaint in complaints:
        prog = approval_progress(complaint)
        my_appr = get_user_current_approval(request.user, complaint)
        can_decide = can_user_decide_approval(request.user, my_appr) if my_appr else False
        
        progress_pct = int((prog['decided'] / prog['total'] * 100)) if prog['total'] > 0 else 0

        assigned_exec_name = "Unassigned"
        if complaint.assigned_factory_executive:
            assigned_exec_name = complaint.assigned_factory_executive.get_full_name() or complaint.assigned_factory_executive.username

        reporter_name = "-"
        if complaint.person:
            reporter_name = complaint.person.name
        elif complaint.created_by:
            reporter_name = complaint.created_by.get_full_name() or complaint.created_by.username

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
            'media_count': complaint.media_files.count(),
        })

    countries = MasterSetting.objects.filter(category='Country').order_by('name')

    # Recent decisions history
    recent_decisions = ComplaintApproval.objects.filter(
        status__in=[DecisionStatuses.APPROVED, DecisionStatuses.REJECTED],
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
        _, outcome = record_approval_decision(
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
        notification_type='approval',
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
                _, outcome = record_approval_decision(
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
                    messages.success(request, 'All required members approved. The executive has received the green light.')
                elif outcome == 'rejected':
                    messages.warning(request, 'All reconsideration reviews are complete. The complaint was returned for rework.')
                elif outcome == 'reconsideration':
                    messages.warning(request, 'Your rejection was saved. Every other required approver was asked to reconsider the complaint.')
                else:
                    messages.success(request, 'Your review was saved. The remaining member reviews are still pending.')
                Notification.objects.filter(
                    recipient=request.user,
                    complaint=complaint,
                    notification_type='approval',
                ).update(is_read=True)
                return redirect('approval_inbox')
    else:
        form = ApprovalDecisionForm(initial=initial, approval_stage=approval.review_stage)

    return render(request, 'management/approval_review.html', {
        'approval': approval,
        'complaint': complaint,
        'form': form,
        'can_decide': can_user_decide_approval(request.user, approval),
        'approval_summary': approval_progress(complaint),
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
                messages.success(request, 'Action plan started. Submit the final production updates when execution is complete.')
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
                messages.success(request, 'Final updates saved. The complaint is now closed.')
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
    ).select_related('complaint')[:100]
    return render(request, 'management/notifications.html', {'notifications': notifications})


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
    if notification.notification_type == 'approval':
        approval = get_user_current_approval(request.user, complaint)
        if approval:
            return redirect('approval_review', approval_id=approval.pk)
    if notification.notification_type in ['assignment', 'rework']:
        if can_user_review_factory_step(request.user, complaint) and can_start_factory_review(complaint):
            return redirect('factory_review_complaint', complaint_id=complaint.complaint_id)
    if notification.notification_type == 'fully_approved' and can_user_execute_action(request.user, complaint):
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
    messages.success(request, 'All notifications marked as read.')
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
    messages.success(request, 'Complaint deleted successfully!')
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
            complaint.person.name if complaint.person else '',
            complaint.case_sub_category.name if complaint.case_sub_category else '',
            complaint.series.name if complaint.series else '',
            complaint.material.name if complaint.material else '',
            complaint.sku.code if complaint.sku else '',
            complaint.cad_date.strftime('%Y-%m-%d') if complaint.cad_date else '',
            complaint.updated_order_no if complaint.updated_order_no else ''
        ]])
    return response


@login_required
def upload_car_csv(request):
    if not _can_manage_catalog(request.user):
        raise PermissionDenied('Only staff users can upload vehicle data.')
    if request.method == "POST":
        form = UploadCSVForm(request.POST, request.FILES)
        if form.is_valid():
            required_headers = {
                'brand', 'model', 'year_start', 'year_end',
                'number_of_seats', 'number_of_doors', 'layout_code',
            }
            new_entries = []
            duplicates = []
            invalid_rows = []
            seen_layout_codes = set()
            try:
                with transaction.atomic():
                    for row_number, row in _iter_csv_rows(
                        form.cleaned_data['csv_file'],
                        required_headers,
                    ):
                        try:
                            brand_name = row.get('brand', '')
                            model_name = row.get('model', '')
                            sub_model_name = row.get('sub_model', '') or '-'
                            layout_code = row.get('layout_code', '')
                            if not all([brand_name, model_name, layout_code]):
                                raise ValueError('brand, model, and layout_code are required')
                            if any(len(value) > 100 for value in [brand_name, model_name, sub_model_name, layout_code]):
                                raise ValueError('text values must be 100 characters or fewer')
                            year_start = _parse_csv_int(row.get('year_start'), 'year_start', 1900, 2100)
                            year_end = _parse_csv_int(row.get('year_end'), 'year_end', 1900, 2100)
                            seats = _parse_csv_int(row.get('number_of_seats'), 'number_of_seats', 1, 100)
                            doors = _parse_csv_int(row.get('number_of_doors'), 'number_of_doors', 1, 20)
                            if year_start > year_end:
                                raise ValueError('year_end must be greater than or equal to year_start')
                        except ValueError as exc:
                            invalid_rows.append(f'row {row_number}: {exc}')
                            continue

                        if layout_code in seen_layout_codes or YearRange.objects.filter(layout_code=layout_code).exists():
                            duplicates.append(layout_code)
                            continue
                        seen_layout_codes.add(layout_code)

                        brand, _ = Brand.objects.get_or_create(name=brand_name)
                        model, _ = Model.objects.get_or_create(brand=brand, name=model_name)
                        sub_model, _ = SubModel.objects.get_or_create(model=model, name=sub_model_name)
                        has_overlap = YearRange.objects.filter(
                            sub_model=sub_model,
                            year_start__lte=year_end,
                            year_end__gte=year_start,
                        ).exists() or any(
                            pending.sub_model_id == sub_model.id
                            and pending.year_start <= year_end
                            and pending.year_end >= year_start
                            for pending in new_entries
                        )
                        if has_overlap:
                            invalid_rows.append(f'row {row_number}: year range overlaps an existing row')
                            continue

                        new_entries.append(YearRange(
                            sub_model=sub_model,
                            year_start=year_start,
                            year_end=year_end,
                            number_of_seats=seats,
                            number_of_doors=doors,
                            layout_code=layout_code,
                        ))

                    YearRange.objects.bulk_create(new_entries)
                    ActivityLog.objects.create(
                        user=request.user,
                        action='uploaded',
                        object_type='Car CSV',
                        object_name=f'Uploaded {len(new_entries)} new car records via CSV file',
                    )
            except ValidationError as exc:
                form.add_error('csv_file', exc)
            except IntegrityError:
                logger.exception('Vehicle CSV import conflict for user %s', request.user.pk)
                form.add_error('csv_file', 'The import conflicted with another update. Please retry.')
            else:
                if duplicates:
                    preview = ', '.join(duplicates[:10])
                    messages.warning(request, f'Skipped {len(duplicates)} duplicate layout codes: {preview}')
                if invalid_rows:
                    preview = '; '.join(invalid_rows[:5])
                    messages.warning(request, f'Skipped {len(invalid_rows)} invalid rows. {preview}')
                messages.success(request, f'Successfully added {len(new_entries)} records.')
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
                    upload_form.add_error('csv_file', 'The import conflicted with another update. Please retry.')
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
            user_form = UserCreationForm(request.POST)
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
        
    users = User.objects.select_related('workflow_profile__country').all()
    groups = Group.objects.prefetch_related('permissions__content_type')
    permissions = Permission.objects.select_related('content_type').all()
    active_users = get_active_users()

    logs = ActivityLog.objects.select_related('user').order_by('-timestamp')[:20]

    return render(request, 'management/admin_panel.html', {
        'user_form': user_form,
        'group_form': group_form,
        'assign_form': assign_form,
        'active_users': active_users,
        'users': users,
        'groups': groups,
        'permissions': permissions,
        'active_sessions': active_users,
        'activity_logs': logs,
        'workflow_role_choices': WorkflowRoles.CHOICES,
        'approval_role_choices': ApprovalRoles.CHOICES,
        'workflow_countries': MasterSetting.objects.filter(category='Country').order_by('name'),
    })


@user_passes_test(is_workflow_admin)
@require_POST
def edit_group(request):
    if request.method == 'POST':
        group_id = request.POST.get('group_id')
        new_name = (request.POST.get('name') or '').strip()
        if not new_name:
            messages.error(request, 'Group name is required.')
            return redirect('admin_panel')
        if len(new_name) > 150:
            messages.error(request, 'Group name must be 150 characters or fewer.')
            return redirect('admin_panel')
        group = get_object_or_404(Group, id=group_id)
        if Group.objects.filter(name__iexact=new_name).exclude(pk=group.pk).exists():
            messages.error(request, 'A group with that name already exists.')
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
        username = (request.POST.get('username') or '').strip()
        email = (request.POST.get('email') or '').strip()

        try:
            if not username:
                messages.error(request, "Username is required.")
                return redirect('admin_panel')
            if User.objects.filter(username=username).exclude(id=user_id).exists():
                messages.error(request, "That username is already in use.")
                return redirect('admin_panel')
            if len(username) > 150:
                messages.error(request, 'Username must be 150 characters or fewer.')
                return redirect('admin_panel')
            if email:
                try:
                    validate_email(email)
                except ValidationError:
                    messages.error(request, 'Enter a valid email address.')
                    return redirect('admin_panel')
            user = User.objects.select_related('workflow_profile').get(id=user_id)
            if user.is_superuser and not request.user.is_superuser:
                messages.error(request, 'Only a Django superuser can edit another superuser account.')
                return redirect('admin_panel')
            profile, _ = UserProfile.objects.get_or_create(user=user)
            profile_form = UserWorkflowProfileForm(request.POST, instance=profile)
            if not profile_form.is_valid():
                for errors in profile_form.errors.values():
                    for error in errors:
                        messages.error(request, error)
                return redirect('admin_panel')
            user.username = username
            user.email = email
            with transaction.atomic():
                user.save()
                profile_form.save()
            ActivityLog.objects.create(
                user=request.user,
                action="edited",
                object_type="User",
                object_name=username
            )
            messages.success(request, f'User {username} and workflow access were updated.')
        except User.DoesNotExist:
            messages.error(request, "User not found.")

    return redirect('admin_panel')


@user_passes_test(is_workflow_admin)
@require_POST
def delete_user(request):
    if request.method == 'POST':
        user_id = request.POST.get('user_id')
        try:
            user = User.objects.get(id=user_id)
            if user == request.user:
                messages.error(request, "You cannot delete your own signed-in account.")
                return redirect('admin_panel')
            if user.is_superuser and not request.user.is_superuser:
                messages.error(request, 'Only a Django superuser can delete another superuser account.')
                return redirect('admin_panel')
            if user.is_superuser and User.objects.filter(is_superuser=True, is_active=True).count() <= 1:
                messages.error(request, "The final active superuser cannot be deleted.")
                return redirect('admin_panel')
            ActivityLog.objects.create(
                user=request.user,
                action="deleted",
                object_type="User",
                object_name=user.username
            )
            user.delete()
        except User.DoesNotExist:
            messages.error(request, "User not found.")

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
            if len(first_name) > 150 or len(last_name) > 150:
                messages.error(request, 'Names must be 150 characters or fewer.')
                return redirect('profile_settings')
            if email:
                try:
                    validate_email(email)
                except ValidationError:
                    messages.error(request, 'Enter a valid email address.')
                    return redirect('profile_settings')

            user.first_name = first_name
            user.last_name = last_name
            user.email = email
            user.save()
            
            ActivityLog.objects.create(
                user=request.user,
                action="updated profile",
                object_type="User",
                object_name=user.username
            )
            
            messages.success(request, "Your profile details have been updated successfully.")
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
                
                messages.success(request, "Your password has been changed successfully.")
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
        deleted_count, _ = Session.objects.filter(session_key=session_key).delete()
        if deleted_count > 0:
            messages.success(request, "Session terminated successfully.")
        else:
            messages.error(request, "Session not found or already expired.")
    except Exception as e:
        messages.error(request, f"Error terminating session: {e}")
    return redirect('admin_panel')


@user_passes_test(is_workflow_admin)
@require_POST
def terminate_all_sessions_view(request):
    try:
        current_key = request.session.session_key
        deleted_count, _ = Session.objects.exclude(session_key=current_key).delete()
        messages.success(request, f"Terminated {deleted_count} active session(s). Only your current session remains active.")
    except Exception as e:
        messages.error(request, f"Error clearing sessions: {e}")
    return redirect('admin_panel')


def get_sorted_chat_users(current_user):
    user_list = User.objects.filter(is_active=True).exclude(id=current_user.id)
    raw_users = []
    
    for u in user_list:
        prof = get_user_profile(u)
        role_code = getattr(prof, 'role', '')
        role_label = dict(WorkflowRoles.CHOICES).get(role_code, 'User')
        
        unread_qs = ChatMessage.objects.filter(sender=u, recipient=current_user, is_read=False)
        unread_count = unread_qs.count()
        latest_unread_msg = unread_qs.order_by('-created_at').first()
        
        last_msg = ChatMessage.objects.filter(
            Q(sender=current_user, recipient=u) | Q(sender=u, recipient=current_user)
        ).order_by('-created_at').first()

        raw_users.append({
            'user': u,
            'role_code': role_code,
            'role_label': role_label,
            'country_flag_url': getattr(prof, 'country_flag_url', None),
            'unread_count': unread_count,
            'latest_unread_time': latest_unread_msg.created_at if latest_unread_msg else None,
            'last_message': last_msg,
            'last_message_time': last_msg.created_at if last_msg else None,
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
        chat_messages = ChatMessage.objects.filter(
            Q(sender=request.user, recipient=selected_user) | Q(sender=selected_user, recipient=request.user)
        ).select_related('sender', 'recipient', 'complaint').order_by('created_at')
        
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
    target_user = get_object_or_404(User, id=user_id)
    ChatMessage.objects.filter(sender=target_user, recipient=request.user, is_read=False).update(is_read=True)
    
    messages_qs = ChatMessage.objects.filter(
        Q(sender=request.user, recipient=target_user) | Q(sender=target_user, recipient=request.user)
    ).select_related('sender', 'complaint').order_by('created_at')
    
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
    return JsonResponse({'status': 'ok', 'messages': data})


@login_required
@require_POST
def chat_send_api(request):
    recipient_id = request.POST.get('recipient_id')
    message_text = request.POST.get('message', '').strip()
    complaint_id = request.POST.get('complaint_id', '').strip()

    if not recipient_id or not message_text:
        return JsonResponse({'status': 'error', 'error': 'Recipient and message content are required.'}, status=400)

    recipient = get_object_or_404(User, id=recipient_id)
    complaint = None
    if complaint_id:
        complaint = Complaint.objects.filter(complaint_id=complaint_id).first()

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

