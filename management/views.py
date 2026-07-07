from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from .forms import ComplaintForm
from django.shortcuts import render, redirect, get_object_or_404
from .models import Brand, Model, SubModel, YearRange, ComplaintMedia, MasterSetting, SKU, Complaint
from .forms import CarDetailsForm, MasterSettingForm, UploadCSVForm
from django.contrib import messages
import os
from django.conf import settings
from django.utils.text import get_valid_filename
from django.db.models import Q
from django.utils.dateparse import parse_date
from collections import Counter
from django.db.models import Count
from datetime import datetime
from django.contrib.auth.decorators import user_passes_test
from django.contrib.auth.models import User, Group, Permission
from django.contrib.sessions.models import Session
from django.utils.timezone import now
from .forms import UserCreationForm, GroupCreationForm, AssignUserToGroupForm
from .models import ActivityLog
from fabro_leather.settings import AWS_S3_REGION_NAME, s3, AWS_STORAGE_BUCKET_NAME, s3_initialized


def _save_complaint_media_files(complaint, uploaded_files):
    for uploaded_file in uploaded_files:
        safe_name = get_valid_filename(uploaded_file.name)
        relative_path = f'complaint_media/complaint_{complaint.complaint_id}/{safe_name}'
        s3_key = f'media/{relative_path}'
        local_path = os.path.join(settings.MEDIA_ROOT, relative_path)
        os.makedirs(os.path.dirname(local_path), exist_ok=True)

        with open(local_path, 'wb') as destination:
            for chunk in uploaded_file.chunks():
                destination.write(chunk)

        file_url = f"/media/{relative_path}"

        if s3_initialized:
            try:
                with open(local_path, 'rb') as source_file:
                    s3.upload_fileobj(
                        source_file,
                        AWS_STORAGE_BUCKET_NAME,
                        s3_key,
                        ExtraArgs={'ACL': 'public-read'}
                    )
                file_url = f"https://{AWS_STORAGE_BUCKET_NAME}.s3.{AWS_S3_REGION_NAME}.amazonaws.com/{s3_key}"
            except Exception as exc:
                print(f"Warning: S3 upload failed for complaint {complaint.complaint_id}: {exc}")

        ComplaintMedia.objects.create(
            complaint=complaint,
            file=file_url
        )

@login_required
def index(request):
    # Get dashboard statistics
    complaint_status_counts = dict(
        Complaint.objects.values_list('status').annotate(count=Count('status'))
    )
    context = {
        'total_complaints': sum(complaint_status_counts.values()),
        'open_complaints': complaint_status_counts.get('Open', 0),
        'closed_complaints': complaint_status_counts.get('Closed', 0),
        'on_hold_complaints': complaint_status_counts.get('On Hold', 0),
        'total_vehicles': YearRange.objects.count(),
        'total_skus': SKU.objects.count(),
        'total_settings': MasterSetting.objects.count(),
    }
    return render(request, 'management/index.html', context)


from io import TextIOWrapper
@login_required
def add_car_details(request):
    show_duplicate_modal = False
    show_layout_code_error_modal = False
    conflicting_car = None

    if request.method == "POST":
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
                    layout_code=layout_code
                )
                ActivityLog.objects.create(
                user=request.user,
                action="created",
                object_type="Car",
                object_name= f"{brand_name} {model_name} {sub_model_name} ({year_start}-{year_end})"
                )
                messages.success(request, 'Vehicle added successfully!')
                return redirect('add_car_details')
    else:
        form = CarDetailsForm()

    # Fetch car data (Optimized via select_related)
    car_data = []
    for yr in YearRange.objects.select_related('sub_model__model__brand').all():
        car_data.append({
            "layout_code": yr.layout_code,
            "id": yr.id,
            "brand": yr.sub_model.model.brand.name if yr.sub_model and yr.sub_model.model and yr.sub_model.model.brand else '',
            "brand_logo": yr.sub_model.model.brand.logo if yr.sub_model and yr.sub_model.model and yr.sub_model.model.brand else None,
            "model": yr.sub_model.model.name if yr.sub_model and yr.sub_model.model else '',
            "sub_model": yr.sub_model.name if yr.sub_model else '',
            "year_start": yr.year_start,
            "year_end": yr.year_end,
            "seats": yr.number_of_seats,
            "doors": yr.number_of_doors
        })

    return render(request, 'management/add_car_details.html', {
        'form': form,
        'car_data': car_data,
        'show_duplicate_modal': show_duplicate_modal,
        'show_layout_code_error_modal': show_layout_code_error_modal,
        'conflicting_car': conflicting_car
    })


@login_required
def car_details(request):
    car_data = []
    for yr in YearRange.objects.select_related('sub_model__model__brand').all():
        car_data.append({
            "layout_code": yr.layout_code,
            "id": yr.id,
            "brand": yr.sub_model.model.brand.name if yr.sub_model and yr.sub_model.model and yr.sub_model.model.brand else '',
            "brand_logo": yr.sub_model.model.brand.logo if yr.sub_model and yr.sub_model.model and yr.sub_model.model.brand else None,
            "model": yr.sub_model.model.name if yr.sub_model and yr.sub_model.model else '',
            "sub_model": yr.sub_model.name if yr.sub_model else '',
            "year_start": yr.year_start,
            "year_end": yr.year_end,
            "seats": yr.number_of_seats,
            "doors": yr.number_of_doors
        })
    return render(request, 'management/car_details.html', {
        'car_data': car_data
    })


@login_required
def delete_car_detail(request, year_range_id):
    year_range = get_object_or_404(YearRange, id=year_range_id)
    messages.success(request, 'Vehicle deleted successfully!')
    ActivityLog.objects.create(
        user=request.user,
        action="deleted",
        object_type="Car",
        object_name=f"{year_range.sub_model.model.brand.name} {year_range.sub_model.model.name} {year_range.sub_model.name} ({year_range.year_start}-{year_range.year_end})"
    )
    year_range.delete()
    return redirect('add_car_details')

@login_required
def edit_car_detail(request, car_id):
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
    }

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
    })


@login_required
def master_settings(request):
    if not request.user.is_superuser:
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
def edit_master_setting(request, setting_id):
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
def delete_master_setting(request, setting_id):
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
    if request.method == 'POST':
        form = ComplaintForm(request.POST)
        if form.is_valid():
            complaint = form.save()

            _save_complaint_media_files(complaint, request.FILES.getlist('media_files'))
                
            ActivityLog.objects.create(
                user=request.user,
                action="created",
                object_type="complaint",
                object_name= complaint.complaint_id)
            return redirect('complaint_list')
    else:
        form = ComplaintForm()
    return render(request, 'management/add_complaint.html', {'form': form})

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
def complaint_list(request):
    complaints = Complaint.objects.select_related(
        'channel', 'country', 'person', 'case_sub_category',
        'series', 'material', 'sku', 'brand', 'model', 'sub_model', 'year'
    ).all()
    search_query = request.GET.get('search', '')
    search_by = request.GET.get('search_by', 'complaint_id')
    selected_brand = request.GET.get('brand')
    selected_country = request.GET.get('country')
    selected_status = request.GET.get('status')
    selected_priority = request.GET.get('priority')
    selected_channel = request.GET.get('channel')
    selected_person = request.GET.get('person')
    selected_case_sub_category = request.GET.get('case_sub_category')

    from_date = request.GET.get('from_date')
    to_date = request.GET.get('to_date')

    if search_query:
        filter_kwargs = {f'{search_by}__icontains': search_query}
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
        complaints = complaints.filter(date__gte=parse_date(from_date))

    if to_date:
        complaints = complaints.filter(date__lte=parse_date(to_date))

    if selected_case_sub_category:
        complaints = complaints.filter(case_sub_category=selected_case_sub_category)

    brands = Brand.objects.all()
    countries = MasterSetting.objects.filter(id__in=Complaint.objects.values_list('country', flat=True).distinct())
    channels = MasterSetting.objects.filter(id__in=Complaint.objects.values_list('channel', flat=True).distinct())
    case_sub_categories = MasterSetting.objects.filter(id__in=Complaint.objects.values_list('case_sub_category', flat=True).distinct())
    persons = MasterSetting.objects.filter(id__in=Complaint.objects.values_list('person', flat=True).distinct())
    statuses = Complaint.objects.values_list('status', flat=True).distinct()
    priorities = Complaint.objects.values_list('priority', flat=True).distinct()
    sku = Complaint.objects.values_list('sku__code', flat=True).distinct()

    # Status Pie Data
    status_qs = complaints.values('status').annotate(count=Count('status'))
    status_labels = [entry['status'] for entry in status_qs]
    status_data = [entry['count'] for entry in status_qs]

    # Country Pie Data
    country_qs = complaints.values('country__name').annotate(count=Count('country'))
    country_labels = [entry['country__name'] for entry in country_qs]
    country_data = [entry['count'] for entry in country_qs]
    
    return render(request, 'management/complaint_list.html', {
        'complaints': complaints,
        'status_labels': status_labels,
        'status_data': status_data,
        'country_labels': country_labels,
        'country_data': country_data,
        'search_query': search_query,
        'search_by': search_by,
        'selected_case_sub_category': selected_case_sub_category,
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
        'case_sub_categories': case_sub_categories,
        'persons': persons,
        'statuses': statuses,
        'priorities': priorities,
        'sku': sku
    })


def logout_success(request):
    return render(request, 'management/logout_success.html')


@login_required
def edit_complaint(request, complaint_id):
    complaint = get_object_or_404(Complaint, complaint_id=complaint_id)

    if request.method == 'POST':
        form = ComplaintForm(request.POST, instance=complaint)
        if form.is_valid():
            form.save()

            # Delete selected media
            media_to_delete = request.POST.getlist('delete_media')
            for media_id in media_to_delete:
                media = ComplaintMedia.objects.get(id=media_id)
                media.delete()

            _save_complaint_media_files(complaint, request.FILES.getlist('media_files'))

            ActivityLog.objects.create(
                user=request.user,
                action="updated",
                object_type="complaint",
                object_name=complaint_id)

            return redirect('complaint_list')
    else:
        form = ComplaintForm(instance=complaint)

    media_files = complaint.media_files.all()

    return render(request, 'management/edit_complaint.html', {
        'form': form,
        'complaint': complaint,
        'media_files': media_files,
    })

@login_required
def delete_complaint(request, complaint_id):
    complaint = get_object_or_404(Complaint, pk=complaint_id)
    if request.method == 'POST':
        complaint.delete()
        messages.success(request, 'Complaint deleted successfully!')
        ActivityLog.objects.create(
                    user=request.user,
                    action="deleted",
                    object_type="complaint",
                    object_name=complaint_id)
    else:
        messages.error(request, 'Use the delete button to remove a complaint.')
    return redirect('complaint_list')


@login_required
def delete_media(request, pk):
    media = get_object_or_404(ComplaintMedia, pk=pk)
    complaint_id = media.complaint.complaint_id
    media.delete()
    return redirect('edit_complaint', complaint_id=complaint_id)

import csv
from django.http import HttpResponse

@login_required
def export_complaints(request):
    format = request.GET.get('format', 'csv')

    complaints = Complaint.objects.select_related(
        'channel', 'country', 'person', 'case_sub_category',
        'series', 'material', 'sku', 'brand', 'model', 'sub_model', 'year'
    ).all()

    # Apply filters like in your complaint list view
    if 'status' in request.GET:
        complaints = complaints.filter(status=request.GET['status'])
    if 'case_type' in request.GET:
        complaints = complaints.filter(case_sub_category__name=request.GET['case_type'])
    if 'from_date' in request.GET:
        from_date = request.GET['from_date']
        if from_date:
            complaints = complaints.filter(date__gte=parse_date(from_date))
    if 'to_date' in request.GET:
        to_date = request.GET['to_date']
        if to_date:
            complaints = complaints.filter(date__lte=parse_date(to_date))

    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="complaints.csv"'

    writer = csv.writer(response)
    writer.writerow(['ID', 'Vehicle', 'Status', 'Case Type', 'Created On', 'Brand', 'Model', 'Sub Model', 'Year Start', 'Year End', 'Number of Seats', 'Number of Doors', 'Layout Code', 'Description', 'Status', 'Date', 'Channel', 'Country', 'Person', 'Case Sub Category', 'Series', 'Material', 'SKU', 'CAD Date', 'Updated Order No'])

    for complaint in complaints:
        writer.writerow([
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
        ])
    return response


@login_required
def upload_car_csv(request):
    if request.method == "POST":
        form = UploadCSVForm(request.POST, request.FILES)
        if form.is_valid():
            csv_file = TextIOWrapper(request.FILES["csv_file"].file, encoding="utf-8")
            reader = csv.DictReader(csv_file)

            new_entries = []
            duplicates = []
            for row in reader:
                brand_name = row.get("brand", "").strip()
                model_name = row.get("model", "").strip()
                sub_model_name = row.get("sub_model", "").strip() or "-"
                year_start = int(row.get("year_start", 0))
                year_end = int(row.get("year_end", 0))
                seats = int(row.get("number_of_seats", 0))
                doors = int(row.get("number_of_doors", 0))
                layout_code = row.get("layout_code", "").strip()

                brand, _ = Brand.objects.get_or_create(name=brand_name)
                model, _ = Model.objects.get_or_create(brand=brand, name=model_name)
                sub_model, _ = SubModel.objects.get_or_create(model=model, name=sub_model_name)

                if YearRange.objects.filter(layout_code=layout_code).exists():
                    duplicates.append(layout_code)
                    continue

                new_entries.append(YearRange(
                    sub_model=sub_model,
                    year_start=year_start,
                    year_end=year_end,
                    number_of_seats=seats,
                    number_of_doors=doors,
                    layout_code=layout_code
                ))

            YearRange.objects.bulk_create(new_entries)

            if duplicates:
                messages.warning(request, f"Skipped {len(duplicates)} duplicate layout codes: {', '.join(duplicates)}")
            messages.success(request, f"Successfully added {len(new_entries)} records.")

            ActivityLog.objects.create(
                user=request.user,
                action="uploaded",
                object_type="Car CSV",
                object_name=f"Uploaded {len(new_entries)} new car records via CSV file"
            )
            return redirect("upload_car_csv")
    else:
        form = UploadCSVForm()

    return render(request, "management/upload_csv.html", {"form": form})


from .forms import SKUForm, SKUUploadForm

@login_required
def add_sku(request):
    form = SKUForm()
    skus = SKU.objects.all().order_by('code')
    upload_feedback = ''

    if request.method == "POST":
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
                csv_file = upload_form.cleaned_data["csv_file"]
                decoded_file = TextIOWrapper(csv_file.file, encoding='utf-8')
                reader = csv.DictReader(decoded_file)

                added = 0
                skipped = 0

                for row in reader:
                    code = row.get('code', '').strip()
                    description = row.get('description', '').strip()
                    region_name = row.get('region', '').strip() if 'region' in row else ''

                    if not code:
                        continue

                    if SKU.objects.filter(code=code).exists():
                        skipped += 1
                        continue

                    region = None
                    if region_name:
                        region = MasterSetting.objects.filter(name=region_name, category='Region').first()

                    SKU.objects.create(
                        code=code,
                        description=description,
                        region=region
                    )
                    added += 1
                ActivityLog.objects.create(
                    user=request.user,
                    action="uploaded",
                    object_type="SKU CSV",
                    object_name=f"Uploaded {added} new SKUs via CSV file"
                )

                upload_feedback = f"{added} SKUs added. {skipped} duplicates skipped."

    return render(request, 'management/add_skus.html', {
        'form': form,
        'skus': skus,
        'upload_feedback': upload_feedback,
        'upload_form': SKUUploadForm(),
    })


@login_required
def delete_sku(request, sku_id):
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


@user_passes_test(lambda u: u.is_superuser)
def admin_panel_view(request):
    user_form = UserCreationForm()
    group_form = GroupCreationForm()
    assign_form = AssignUserToGroupForm()

    if request.method == "POST":
        if 'add_user' in request.POST:
            user_form = UserCreationForm(request.POST)
            if user_form.is_valid():
                user = user_form.save(commit=False)
                user.set_password(user_form.cleaned_data['password'])
                user.save()
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
        
    users = User.objects.all()
    groups = Group.objects.prefetch_related('permissions')
    permissions = Permission.objects.all()
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
    })


@user_passes_test(lambda u: u.is_superuser)
def edit_group(request):
    if request.method == 'POST':
        group_id = request.POST.get('group_id')
        new_name = request.POST.get('name')
        group = get_object_or_404(Group, id=group_id)
        group.name = new_name
        group.save()
        ActivityLog.objects.create(
            user=request.user,
            action="edited",
            object_type="Group",
            object_name=new_name
        )
    return redirect('admin_panel')


@user_passes_test(lambda u: u.is_superuser)
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


@user_passes_test(lambda u: u.is_superuser)
def edit_user(request):
    if request.method == 'POST':
        user_id = request.POST.get('user_id')
        username = request.POST.get('username')
        email = request.POST.get('email')

        try:
            user = User.objects.get(id=user_id)
            user.username = username
            user.email = email
            user.save()
            ActivityLog.objects.create(
                user=request.user,
                action="edited",
                object_type="User",
                object_name=username
            )
        except User.DoesNotExist:
            messages.error(request, "User not found.")

    return redirect('admin_panel')


@user_passes_test(lambda u: u.is_superuser)
def delete_user(request):
    if request.method == 'POST':
        user_id = request.POST.get('user_id')
        try:
            user = User.objects.get(id=user_id)
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
            session_data_list.append((user_id, data.get('login_time'), data.get('ip_address', 'N/A')))

    # Query all users in one database hit
    users_map = {str(u.id): u for u in User.objects.filter(id__in=user_ids)}

    for user_id, login_time, ip_address in session_data_list:
        user = users_map.get(str(user_id))
        if user:
            active_users.append({
                'user': user,
                'login_time': login_time or 'N/A',
                'ip': ip_address
            })

    return active_users


from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.forms import PasswordChangeForm

@login_required
def profile_settings(request):
    user = request.user
    if request.method == 'POST':
        if 'update_profile' in request.POST:
            first_name = request.POST.get('first_name', '').strip()
            last_name = request.POST.get('last_name', '').strip()
            email = request.POST.get('email', '').strip()
            
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
