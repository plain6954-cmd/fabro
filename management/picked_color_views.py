"""Measurements Picked Colors endpoints; existing approval views stay separate."""
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.http import FileResponse, Http404, JsonResponse
import logging
from pathlib import PurePosixPath
from types import SimpleNamespace
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_POST
from management.models import PatternColorSelection, PickedColorSelection
from management.services.activity_permissions import require
from management.services import picked_colors, swatch_photos

logger = logging.getLogger(__name__)


def failure(error):
    return JsonResponse({'status': 'error', 'message': '; '.join(error.messages)}, status=400)


@login_required
@never_cache
@require_GET
def list_picked_colors(request):
    require(request.user, 'picked_colors.view')
    try:
        vehicle = picked_colors.vehicle_for_user(request.user, request.GET.get('vehicle_id'))
    except ValidationError as error:
        return failure(error)
    rows = PickedColorSelection.objects.filter(vehicle=vehicle, deleted_at=None).select_related('source_selection').prefetch_related('swatch_photos')
    selections = [picked_colors.serialize(row, request.user) for row in rows]
    counts = {key: sum(row['category'] == key for row in selections) for key, _ in PickedColorSelection.CATEGORY_CHOICES}
    return JsonResponse({'status': 'success', 'selections': selections, 'counts': counts})


@login_required
@require_POST
def edit_picked_color(request, selection_id):
    try:
        row, changed = picked_colors.save(request.user, request.POST.get('vehicle_id'), request.POST,
            row_id=selection_id, swatch_file=request.FILES.get('swatch_image'))
    except ValidationError as error:
        return failure(error)
    return JsonResponse({'status': 'success', 'changed': changed, 'selection': picked_colors.serialize(row, request.user)})


@login_required
@require_POST
def delete_picked_color(request, selection_id):
    try:
        picked_colors.delete(request.user, request.POST.get('vehicle_id'), selection_id)
    except ValidationError as error:
        return failure(error)
    return JsonResponse({'status': 'success'})


@login_required
@never_cache
@require_GET
def picked_color_swatch(request, selection_id):
    require(request.user, 'picked_colors.view')
    try:
        vehicle = picked_colors.vehicle_for_user(request.user, request.GET.get('vehicle_id'))
    except ValidationError as error:
        return failure(error)
    row = PickedColorSelection.objects.select_related('source_selection').filter(pk=selection_id, vehicle=vehicle, deleted_at=None).first()
    if not row:
        raise Http404
    legacy = swatch_photos.unimported_legacy(row)
    if legacy:
        return deliver_photo(SimpleNamespace(image=legacy, filename=PurePosixPath(legacy.name).name,
            uploaded_at=row.source_selection.created_at, pk=f'legacy-{row.pk}'))
    photo = row.swatch_photos.filter(removed_at=None, uploaded_at__isnull=False).exclude(image='').first()
    if not photo:
        raise Http404
    return deliver_photo(photo)


def deliver_photo(photo):
    if not photo.image or not photo.uploaded_at:
        raise Http404
    try:
        content_type = swatch_photos.TYPES.get(PurePosixPath(photo.filename).suffix.lower(), 'application/octet-stream')
        response = FileResponse(photo.image.open('rb'), content_type=content_type,
            as_attachment=content_type == 'application/octet-stream', filename=photo.filename)
    except FileNotFoundError:
        raise Http404
    except Exception:
        logger.exception('Private swatch photo delivery unavailable for photo %s', photo.pk)
        return JsonResponse({'status': 'error', 'message': 'Photo temporarily unavailable.'}, status=503)
    response['Cache-Control'] = 'private, no-store'
    response['X-Content-Type-Options'] = 'nosniff'
    return response


def visible_row(request, selection_id):
    require(request.user, 'picked_colors.view')
    vehicle = picked_colors.vehicle_for_user(request.user, request.GET.get('vehicle_id'))
    try:
        return PickedColorSelection.objects.get(pk=selection_id, vehicle=vehicle, deleted_at=None)
    except PickedColorSelection.DoesNotExist:
        raise Http404


@login_required
@never_cache
@require_GET
def list_picked_color_photos(request, selection_id):
    try:
        row = visible_row(request, selection_id)
    except ValidationError as error:
        return failure(error)
    return JsonResponse({'status': 'success', 'photos': swatch_photos.gallery(row, request.user),
                         'can_upload': picked_colors.permitted(request.user, row, 'edit')})


@transaction.non_atomic_requests
@login_required
@require_POST
def upload_picked_color_photo(request, selection_id):
    if len(request.FILES) != 1 or len(request.FILES.getlist('photo')) != 1:
        return failure(ValidationError('Send one photo per upload request.'))
    try:
        row, photo, created = swatch_photos.upload(request.user, request.POST.get('vehicle_id'), selection_id,
            request.POST.get('upload_key'), request.FILES.get('photo'))
    except ValidationError as error:
        return failure(error)
    except (PermissionDenied, Http404):
        raise
    except Exception:
        logger.exception('Unable to save a private matching swatch photo')
        return JsonResponse({'status': 'error', 'message': 'Photo could not be saved. Retry this upload.'}, status=503)
    return JsonResponse({'status': 'success', 'created': created,
                         'photo': swatch_photos.photo_data(photo, row, request.user)})


@login_required
@require_POST
def remove_picked_color_photo(request, selection_id, photo_id):
    try:
        row = swatch_photos.remove(request.user, request.POST.get('vehicle_id'), selection_id, photo_id=photo_id)
    except ValidationError as error:
        return failure(error)
    return JsonResponse({'status': 'success', 'photos': swatch_photos.gallery(row, request.user)})


@login_required
@require_POST
def cancel_picked_color_photo_upload(request, selection_id):
    try:
        row = swatch_photos.remove(request.user, request.POST.get('vehicle_id'), selection_id,
                                   raw_key=request.POST.get('upload_key'))
    except ValidationError as error:
        return failure(error)
    return JsonResponse({'status': 'success', 'photos': swatch_photos.gallery(row, request.user)})


@login_required
@never_cache
@require_GET
def picked_color_photo_file(request, selection_id, photo_id):
    try:
        row = visible_row(request, selection_id)
    except ValidationError as error:
        return failure(error)
    photo = row.swatch_photos.filter(pk=photo_id, removed_at=None).first()
    if not photo:
        raise Http404
    return deliver_photo(photo)


@login_required
@never_cache
@require_GET
def color_selection_photo_file(request, selection_id, photo_id):
    require(request.user, 'picked_colors.view', 'color.view', 'color.history')
    try:
        selection = PatternColorSelection.objects.get(pk=selection_id)
        picked_colors.vehicle_for_user(request.user, selection.vehicle_id)
    except PatternColorSelection.DoesNotExist:
        raise Http404
    photo = selection.swatch_photos.filter(pk=photo_id).first()
    if not photo:
        raise Http404
    return deliver_photo(photo)
