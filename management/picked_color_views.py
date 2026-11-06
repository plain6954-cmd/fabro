"""Measurements Picked Colors endpoints; existing approval views stay separate."""
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import FileResponse, Http404, JsonResponse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_POST
from management.models import PickedColorSelection
from management.services.activity_permissions import require
from management.services import picked_colors


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
    rows = PickedColorSelection.objects.filter(vehicle=vehicle, deleted_at=None).select_related('source_selection')
    return JsonResponse({'status': 'success', 'selections': [picked_colors.serialize(row, request.user) for row in rows]})


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
    if not row or not row.source_selection or not row.source_selection.swatch_image:
        raise Http404
    try:
        response = FileResponse(row.source_selection.swatch_image.open('rb'))
    except FileNotFoundError:
        raise Http404
    response['Cache-Control'] = 'private, no-store'
    response['X-Content-Type-Options'] = 'nosniff'
    return response
