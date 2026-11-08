import json
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.http import JsonResponse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_POST
from management.models import ActivityRole
from management.services import roles


@login_required
@never_cache
@require_GET
def role_control_data(request):
    roles.authorize(request.user)
    identifier = request.GET.get('id')
    if identifier and (not identifier.isdecimal() or len(identifier)>19 or not 0<int(identifier)<=2**63-1):
        return JsonResponse({'success':False,'message':'Role not found.'},status=404)
    try:
        role = ActivityRole.objects.get(pk=identifier) if identifier else ActivityRole.objects.order_by('pk').first()
    except (ActivityRole.DoesNotExist,ValueError,TypeError):
        return JsonResponse({'success':False,'message':'Role not found.'},status=404)
    return JsonResponse(roles.control_data(request.user,role))


@login_required
@never_cache
@require_POST
def role_control_save(request):
    try:
        data = json.loads(request.body)
        role = roles.save_role(request.user,data)
        return JsonResponse(dict(roles.control_data(request.user,role),success=True))
    except ActivityRole.DoesNotExist:
        return JsonResponse({'success':False,'message':'Role not found.'},status=404)
    except (ValidationError,IntegrityError,ValueError,TypeError) as error:
        return JsonResponse({'success':False,'message':' '.join(getattr(error,'messages',['Unable to save this role. Check the fields and try again.']))},status=400)


@login_required
@never_cache
@require_POST
def role_control_delete(request):
    try:
        data = json.loads(request.body)
        if not isinstance(data,dict) or set(data)-{'id','revision'}:
            raise ValidationError('Invalid role submission.')
        roles.delete_role(request.user,data.get('id'),data.get('revision'))
        return JsonResponse(dict(roles.control_data(request.user),success=True))
    except ActivityRole.DoesNotExist:
        return JsonResponse({'success':False,'message':'Role not found.'},status=404)
    except (ValidationError,ValueError,TypeError) as error:
        return JsonResponse({'success':False,'message':' '.join(getattr(error,'messages',['Unable to delete this role.']))},status=400)
