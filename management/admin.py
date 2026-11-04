from django.contrib import admin
from .models import (
    ActivityLog,
    Brand,
    Complaint,
    ComplaintApproval,
    ComplaintEditLog,
    ComplaintMedia,
    ComplaintTimeline,
    MasterSetting,
    Model,
    Notification,
    SKU,
    SubModel,
    UserProfile,
    UserAccessAudit,
    YearRange,
)
from django.contrib.sessions.models import Session


admin.site.register(Session)
admin.site.register(MasterSetting)
admin.site.register(SKU)
class CatalogAssetAdmin(admin.ModelAdmin):
    def _protect(self, request, queryset):
        from management.services.activity_permissions import protect_vehicle_files
        paths = {Brand: 'sub_model__model__brand', Model: 'sub_model__model', SubModel: 'sub_model', YearRange: 'pk'}
        vehicles = YearRange.objects.filter(**{paths[self.model] + '__in': queryset.values('pk')})
        protect_vehicle_files(list(vehicles.values_list('pk', flat=True)), request.user)

    def delete_model(self, request, obj):
        self._protect(request, self.model.objects.filter(pk=obj.pk))
        super().delete_model(request, obj)

    def delete_queryset(self, request, queryset):
        self._protect(request, queryset)
        super().delete_queryset(request, queryset)

for catalog_model in (Brand, Model, SubModel, YearRange):
    admin.site.register(catalog_model, CatalogAssetAdmin)


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'role', 'country', 'department', 'approval_role', 'can_receive_factory_assignments')
    list_filter = ('role', 'approval_role', 'country', 'can_receive_factory_assignments')
    search_fields = ('user__username', 'user__email', 'department')
    readonly_fields = ('activity_permissions',)


@admin.register(Complaint)
class ComplaintAdmin(admin.ModelAdmin):
    list_display = (
        'complaint_id',
        'complaint_type',
        'workflow_status',
        'status',
        'country',
        'created_by',
        'assigned_factory_executive',
        'factory_priority',
        'date',
    )
    list_filter = ('complaint_type', 'workflow_status', 'status', 'factory_priority', 'country')
    search_fields = ('complaint_id', 'complaint_description', 'created_by__username', 'assigned_factory_executive__username')
    def get_readonly_fields(self, request, obj=None):
        return tuple(field.name for field in self.model._meta.fields)

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class WorkflowAuditAdmin(admin.ModelAdmin):
    """Keep workflow evidence visible while preventing out-of-band mutation."""

    def get_readonly_fields(self, request, obj=None):
        return tuple(field.name for field in self.model._meta.fields)

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(ComplaintMedia)
class ComplaintMediaAdmin(WorkflowAuditAdmin):
    list_display = ('complaint', 'file')
    search_fields = ('complaint__complaint_id', 'file')


@admin.register(ComplaintApproval)
class ComplaintApprovalAdmin(WorkflowAuditAdmin):
    list_display = ('complaint', 'approval_round', 'review_stage', 'approver_role', 'approver_user', 'required', 'status', 'decided_at')
    list_filter = ('review_stage', 'approver_role', 'status', 'required')
    search_fields = ('complaint__complaint_id', 'approver_user__username')


@admin.register(ComplaintTimeline)
class ComplaintTimelineAdmin(WorkflowAuditAdmin):
    list_display = ('complaint', 'action_type', 'title', 'user', 'created_at')
    list_filter = ('action_type',)
    search_fields = ('complaint__complaint_id', 'title', 'description', 'user__username')


@admin.register(Notification)
class NotificationAdmin(WorkflowAuditAdmin):
    list_display = ('recipient', 'complaint', 'title', 'notification_type', 'is_read', 'created_at')
    list_filter = ('notification_type', 'is_read')
    search_fields = ('recipient__username', 'complaint__complaint_id', 'title', 'message')


@admin.register(ComplaintEditLog)
class ComplaintEditLogAdmin(WorkflowAuditAdmin):
    list_display = ('complaint', 'edited_by', 'field_name', 'created_at')
    search_fields = ('complaint__complaint_id', 'edited_by__username', 'field_name')


@admin.register(ActivityLog)
class ActivityLogAdmin(WorkflowAuditAdmin):
    list_display = ('timestamp', 'user', 'action', 'object_type', 'object_name')
    list_filter = ('action', 'object_type')
    search_fields = ('user__username', 'object_name')


@admin.register(UserAccessAudit)
class UserAccessAuditAdmin(WorkflowAuditAdmin):
    list_display = ('timestamp', 'actor', 'target_username')
    search_fields = ('target_username', 'actor__username')
