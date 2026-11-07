"""Auditable route/action inventory shared by HTML middleware, DRF and template tags.

Existing views/services remain authoritative for object visibility and transitions.
Account access, language, login/logout, password self-service and push subscription
security are deliberately not feature-toggleable.
"""
import json
from django.db.models import Q
from django.utils.translation import gettext_lazy as _
from django.core.exceptions import PermissionDenied
from management.services.activity_permissions import granted, require, scoped, self_access_recovery

ROUTES = {}
def routes(names, read, write=None):
    for name in names.split():
        ROUTES[name] = (read, write or read)

routes('index api_dashboard', 'dashboard.view')
routes('car_details', 'pattern.view', 'vehicle.create')
routes('pattern_vehicle_list_api pattern_vehicle_count_api get_next_pattern_serial_api', 'pattern.view')
routes('edit_car_detail update_fitting_confirmation_api update_vehicle_country_api update_drive_api', 'pattern.edit')
routes('update_measurement_country_api', 'pattern.edit')
routes('delete_car_detail bulk_delete_patterns_api', 'pattern.delete')
routes('decide_pattern_alteration_api', 'pattern.decide')
routes('pattern_logs_api', 'reports.pattern_history')
routes('get_models get_sub_models get_year_ranges get_available_years', 'vehicle.view')
routes('get_filtered_skus', 'sku.view')
routes('get_complaint_type_options', 'complaint.view')
routes('upload_car_csv', 'vehicle.import')
routes('upload_vehicle_photo', 'vehicle.photo')
routes('create_color_api', 'color.create')
routes('master_colors_api', 'color.view')
routes('update_color_api', 'color.edit')
routes('delete_color_api', 'color.delete')
routes('save_color_selection_api', 'picked_colors.add')
routes('list_picked_colors picked_color_swatch edit_picked_color delete_picked_color', 'picked_colors.view')
routes('list_picked_color_photos upload_picked_color_photo remove_picked_color_photo cancel_picked_color_photo_upload picked_color_photo_file', 'picked_colors.view')
routes('color_selection_photo_file', 'color.history')
routes('get_color_selection_details_api', 'color.view')
routes('color_selection_file', 'color.view')
routes('submit_color_decision_api', 'color.view')
routes('get_design_folders_api get_design_folder_detail_api', 'folder.view')
routes('create_design_folder_api', 'folder.create')
routes('rename_design_folder_api', 'folder.rename')
routes('delete_design_folder_api', 'folder.view')
routes('upload_design_images_api upload_vehicle_design_images_api', None)
routes('vehicle_drive_links_api', 'pattern.drive_view', 'pattern.drive_add')
routes('update_vehicle_google_drive_api', 'pattern.drive_add')
routes('delete_vehicle_drive_link_api', 'pattern.drive_delete')
routes('pattern_design_image_download design_comparison_manifest design_comparison_file delete_design_image_api', None)
routes('approve_design_image_api', 'design_approval.approve')
routes('reject_design_image_api', 'design_approval.reject')
routes('resubmit_design_image_api', None)
routes('design_approval_detail design_approvals_list', 'design_approval.view')
routes('design_review_voice_audio', 'design_approval.history')
routes('get_measurement_files_api measurement_file_download delete_measurement_file_api', None)
routes('upload_measurement_files_api', 'measurement.upload')
routes('master_settings', 'master.view', 'master.create')
routes('get_material_variants', 'complaint.view')
routes('edit_master_setting', 'master.edit')
routes('delete_master_setting', 'master.delete')
routes('complaint_list', 'complaint.view')
routes('add_complaint', 'complaint.create')
routes('edit_complaint', 'complaint.view', 'complaint.edit')
routes('delete_complaint', 'complaint.delete')
routes('complaint_media_download', 'complaint.media_view')
routes('complaint_media_signed_upload', 'complaint.media_upload')
routes('complaint_media_discard_uploads', 'complaint.media_delete')
routes('export_complaints', 'complaint.export')
routes('factory_review_complaint api_factory_review', 'workflow.factory_review')
routes('approvals_list approval_inbox approval_review quick_approval_decision_api api_approval_inbox api_approval_decision', 'workflow.view')
routes('execute_complaint', 'complaint.view')
routes('api_start_action', 'workflow.start')
routes('api_submit_execution_verification', 'workflow.verify_submit')
routes('api_final_update', 'workflow.close')
routes('notification_list api_notifications', 'notification.view')
routes('open_notification mark_all_notifications_read api_notification_read', 'notification.read')
routes('chat_view chat_users_api chat_messages_api', 'chat.view')
routes('chat_send_api', 'chat.send')
routes('add_sku', 'sku.view', 'sku.create')
routes('edit_sku', 'sku.edit')
routes('delete_sku', 'sku.delete')
routes('admin_panel admin_panel_alias', 'erp.view')
routes('admin_control_tower', 'erp.control_tower')
routes('admin_brand_tree', 'vehicle.view')
routes('edit_user user_control_data user_control_save delete_user', 'users.manage')
routes('delete_user_photo', 'users.photo_delete')
routes('terminate_session terminate_all_sessions', 'erp.sessions_terminate')
routes('api_complaints_list_create', 'complaint.view', 'complaint.create')
routes('api_complaint_detail', 'complaint.view', 'complaint.edit')
routes('api_skus_list_create', 'sku.view', 'sku.create')
routes('api_sku_detail', 'sku.view', 'sku.edit')
routes('api_vehicles_list_create', 'vehicle.view', 'vehicle.create')
routes('api_vehicle_detail', 'vehicle.view', 'vehicle.edit')

ESSENTIAL_ROUTES = frozenset(('login', 'logout', 'logout_success', 'api_login', 'api_logout', 'api_register',
    'profile_settings', 'api_profile', 'user_activity_state', 'set_portal_language', 'push_subscribe', 'push_unsubscribe', 'push_status', 'service_worker'))

def payload(request):
    if hasattr(request, 'data'):
        return request.data
    if request.content_type == 'application/json':
        try:
            data = json.loads(request.body)
            return data if isinstance(data, dict) else {}
        except (ValueError, UnicodeError):
            return {}
    return request.POST

def request_keys(request, name=None):
    name = name or request.resolver_match.url_name
    # Keep a narrow self-service recovery path for active Django superusers.
    if self_access_recovery(request.user):
        if name in ('admin_panel', 'admin_panel_alias') and request.method == 'GET' and request.GET.get('section') == 'users':
            return []
        if name == 'user_control_data' and request.method == 'GET' and request.GET.get('user_id') == str(request.user.pk):
            return []
        if name == 'user_control_save' and request.method == 'POST' and request.POST.get('user_id') == str(request.user.pk):
            return []
    if request.resolver_match.namespace == 'admin':
        parts = name.split('_')
        model = parts[1] if len(parts) > 2 else ''
        action = parts[-1]
        mutation = request.method not in ('GET', 'HEAD', 'OPTIONS')
        categories = {'user': 'users.manage', 'userprofile': 'users.permissions', 'group': 'users.groups',
            'session': 'erp.sessions_terminate' if mutation else 'erp.sessions_view',
            'activitylog': 'reports.activity', 'useraccessaudit': 'reports.activity',
            'mastersetting': 'master.edit' if mutation else 'master.view', 'sku': 'sku.edit' if mutation else 'sku.view',
            'yearrange': 'vehicle.edit' if mutation else 'vehicle.view', 'brand': 'vehicle.edit' if mutation else 'vehicle.view',
            'model': 'vehicle.edit' if mutation else 'vehicle.view', 'submodel': 'vehicle.edit' if mutation else 'vehicle.view',
            'complaint': 'complaint.view', 'complaintmedia': 'complaint.media_view', 'complaintapproval': 'workflow.view',
            'complainttimeline': 'complaint.view', 'complainteditlog': 'complaint.view', 'notification': 'notification.view'}
        if model in ('sku', 'yearrange', 'brand', 'model', 'submodel'):
            category = 'sku' if model == 'sku' else 'vehicle'
            verb = 'delete' if action == 'delete' or mutation and payload(request).get('action') == 'delete_selected' else 'create' if action == 'add' else 'edit' if mutation else 'view'
            return [category + '.' + verb]
        return [categories[model]] if model in categories else []
    if name not in ROUTES:
        return []
    read, write = ROUTES[name]
    mutation = request.method not in ('GET', 'HEAD', 'OPTIONS')
    keys = [write if mutation else read]
    data = payload(request) if mutation else {}
    if request.method == 'DELETE' and name.startswith('api_'):
        keys = [{'api_complaint_detail': 'complaint.delete', 'api_sku_detail': 'sku.delete', 'api_vehicle_detail': 'vehicle.delete'}.get(name, write)]
    if name in ('admin_panel', 'admin_panel_alias'):
        sections = {'users': 'users.manage', 'sessions': 'erp.sessions_view', 'logs': 'reports.activity',
                    'dashboard': 'erp.control_tower', 'brands': 'vehicle.view', 'skus': 'sku.view', 'master': 'master.view'}
        keys.append(sections.get(request.GET.get('section', 'dashboard'), 'erp.control_tower'))
        if mutation:
            keys.append('users.create' if 'add_user' in data else 'users.groups')
    if name == 'user_control_save' and mutation and not data.get('user_id'):
        keys.append('users.create')
    if name == 'edit_user' and mutation and 'reset_password' in data:
        keys.append('users.password')
    if name == 'approvals_list':
        from management.services.activity_permissions import profile
        stage = request.GET.get('stage', 'designer' if getattr(profile(request.user), 'role', '') == 'freelance_3d_designer' else 'plan')
        keys = ['design_approval.view' if stage == 'designer' else 'color.history' if stage == 'colors' else 'workflow.view']
    if name in ('upload_design_images_api', 'upload_vehicle_design_images_api'):
        keys = ['reference.upload' if str(data.get('is_reference', '')).lower() in ('1', 'true', 'yes', 'on') or data.get('upload_category') == 'reference' else 'design.upload']
    if mutation and name in ('approve_design_image_api', 'reject_design_image_api', 'design_approval_detail'):
        if name == 'design_approval_detail':
            if data.get('action') == 'resubmit':
                keys.append('design.resubmit_own')
            else:
                keys.append('design_approval.approve' if data.get('decision') in ('approve', 'approved') else 'design_approval.reject')
        if data.get('comment') or data.get('remarks'):
            keys.append('design_approval.comment')
        if request.FILES.get('voice_note'):
            keys.append('design_approval.voice')
    if mutation and name in ('approval_review', 'quick_approval_decision_api', 'api_approval_decision'):
        keys.append('workflow.approve' if data.get('decision') in ('approve', 'approved') else 'workflow.reject')
    if name == 'design_review_voice_audio':
        keys.append('design.history')
    if name == 'bulk_delete_patterns_api':
        keys.append('pattern.alter')
    if name == 'execute_complaint' and mutation:
        action = data.get('action', '')
        keys.append({'start': 'workflow.start', 'submit_verification': 'workflow.verify_submit'}.get(action, 'workflow.close'))
    if name == 'submit_color_decision_api':
        keys.append('color.approve' if data.get('decision') in ('approve', 'approved') else 'color.reject')
    if mutation and name in ('edit_complaint', 'add_complaint', 'api_complaint_detail', 'api_complaints_list_create'):
        if request.FILES:
            keys.append('complaint.media_upload')
        if data.get('delete_media') or data.get('remove_media') or data.get('delete_media_ids'):
            keys.append('complaint.media_delete')
    if name == 'open_notification':
        from management.models import Notification
        if Notification.objects.filter(pk=request.resolver_match.kwargs.get('notification_id'), recipient=request.user, notification_type='access_change').exists():
            return []
    return [key for key in keys if key]

def enforce_request(request):
    require(request.user, *request_keys(request))
    if request.resolver_match.namespace == 'admin' and request.method not in ('GET', 'HEAD', 'OPTIONS'):
        from management.services.activity_permissions import protected_admin, protected_files
        from management.models import PatternDesignImage
        if any(part in request.resolver_match.url_name for part in ('_user_', '_userprofile_', '_group_')) and not protected_admin(request.user):
            raise PermissionDenied('Only Admin may assign security authority.')
        if 'delete' in request.resolver_match.url_name or payload(request).get('action') == 'delete_selected':
            model = request.resolver_match.url_name.split('_')[1]
            ids = [request.resolver_match.kwargs.get('object_id')] if request.resolver_match.kwargs.get('object_id') else payload(request).getlist('_selected_action')
            paths = {'yearrange': 'vehicle_id', 'submodel': 'vehicle__sub_model_id', 'model': 'vehicle__sub_model__model_id', 'brand': 'vehicle__sub_model__model__brand_id'}
            if model in paths:
                path = paths[model]
                criteria = Q(**{path + '__in': ids}) | Q(**{'folder__' + path + '__in': ids})
                if protected_files(PatternDesignImage.objects.filter(criteria)).exists():
                    raise PermissionDenied('Reviewed assets cannot be deleted through catalog ancestors.')
    name = request.resolver_match.url_name
    kwargs = request.resolver_match.kwargs
    if name in ('pattern_design_image_download', 'design_comparison_file', 'design_comparison_manifest', 'delete_design_image_api', 'design_approval_detail', 'resubmit_design_image_api'):
        from management.models import PatternDesignImage
        image = PatternDesignImage.objects.filter(pk=kwargs.get('image_id')).first()
        if image:
            resource = 'reference' if image.is_reference else 'design'
            if name == 'resubmit_design_image_api' or name == 'design_approval_detail' and payload(request).get('action') == 'resubmit':
                require(request.user, 'design.resubmit_own' if image.uploaded_by_id == request.user.pk else 'design.resubmit_all')
            action = 'delete' if name == 'delete_design_image_api' else 'download' if request.GET.get('download') == '1' else 'view'
            if not scoped(request.user, resource, action, image.uploaded_by_id):
                raise PermissionDenied(_('File scope is not permitted.'))
    if name == 'design_review_voice_audio':
        from management.models import DesignReviewVoiceNote
        note = DesignReviewVoiceNote.objects.select_related('approval__design_image').filter(pk=kwargs.get('voice_id')).first()
        if note and not scoped(request.user, 'design', 'view', note.approval.design_image.uploaded_by_id):
            raise PermissionDenied('Design history scope is not permitted.')
    if name in ('measurement_file_download', 'delete_measurement_file_api'):
        from management.models import PatternMeasurementFile
        item = PatternMeasurementFile.objects.filter(pk=kwargs.get('file_id')).first()
        if item and not scoped(request.user, 'measurement', 'delete' if name.startswith('delete') else 'download' if request.GET.get('download') == '1' else 'view', item.uploaded_by_id):
            raise PermissionDenied('File scope is not permitted.')
    if request.method not in ('GET', 'HEAD', 'OPTIONS'):
        from management.models import PatternDesignImage, PatternDesignFolder, PatternAlteration
        from management.services.activity_permissions import protected_files
        images = PatternDesignImage.objects.none()
        if name == 'delete_design_image_api':
            if granted(request.user, 'design.delete_uploaded'):
                images = PatternDesignImage.objects.filter(pk=kwargs.get('image_id'), is_reference=True)
            else:
                images = PatternDesignImage.objects.filter(pk=kwargs.get('image_id'))
        elif name == 'delete_design_folder_api':
            folder = PatternDesignFolder.objects.filter(pk=kwargs.get('folder_id')).first()
            if folder and not scoped(request.user, 'folder', 'delete', folder.created_by_id):
                raise PermissionDenied('Folder deletion is disabled.')
            images = PatternDesignImage.objects.filter(folder_id=kwargs.get('folder_id'))
        elif name in ('delete_car_detail', 'api_vehicle_detail') and (name == 'delete_car_detail' or request.method == 'DELETE'):
            vehicle_id = kwargs.get('year_range_id', kwargs.get('pk'))
            images = PatternDesignImage.objects.filter(Q(vehicle_id=vehicle_id) | Q(folder__vehicle_id=vehicle_id))
        elif name == 'decide_pattern_alteration_api' and (payload(request).get('decision') or payload(request).get('action')) == 'approve':
            alteration = PatternAlteration.objects.filter(pk=kwargs.get('alteration_id')).first()
            if alteration and alteration.action_type in ('delete', 'bulk_delete'):
                images = PatternDesignImage.objects.filter(Q(vehicle_id__in=alteration.pattern_ids) | Q(folder__vehicle_id__in=alteration.pattern_ids))
        if protected_files(images).exists():
            raise PermissionDenied('Submitted, reviewed or approved files cannot be deleted, including through a parent record.')
    if name == 'get_measurement_files_api' and not any(granted(request.user, 'measurement.' + key) for key in ('view_own', 'view_all')):
        raise PermissionDenied('Measurement access is disabled.')
