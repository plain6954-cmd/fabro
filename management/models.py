import os
from pathlib import Path

from django.conf import settings
from django.contrib.auth.models import User
from django.core.files.storage import default_storage
from django.db import IntegrityError, models, transaction
from django.utils import timezone


class WorkflowRoles:
    COUNTRY_EXECUTIVE = 'country_executive'
    FACTORY_VIEWER = 'factory_viewer'
    FACTORY_EXECUTIVE = 'factory_executive'
    APPROVER = 'approver'
    ADMIN = 'admin'

    CHOICES = [
        (COUNTRY_EXECUTIVE, 'Country Executive'),
        (FACTORY_VIEWER, 'Factory Viewer'),
        (FACTORY_EXECUTIVE, 'Factory Executive'),
        (APPROVER, 'Approver'),
        (ADMIN, 'Admin'),
    ]


class ApprovalRoles:
    PM = 'PM'
    OM = 'OM'
    CAD = 'CAD'
    ED = 'ED'
    MD = 'MD'

    CHOICES = [
        (PM, 'PM'),
        (OM, 'OM'),
        (CAD, 'CAD'),
        (ED, 'ED'),
        (MD, 'MD'),
    ]


class ComplaintTypes:
    PATTERN = 'pattern'
    PRODUCTION = 'production'
    LINE = 'line'

    CHOICES = [
        (PATTERN, 'Pattern Complaint'),
        (PRODUCTION, 'Production Complaint'),
        (LINE, 'Line Complaint'),
    ]

    PREFIXES = {
        PATTERN: 'PAT',
        PRODUCTION: 'PRO',
        LINE: 'LIN',
    }


class WorkflowStatuses:
    SUBMITTED = 'submitted'
    ASSIGNED_TO_FACTORY = 'assigned_to_factory'
    FACTORY_REVIEW = 'factory_review'
    AWAITING_APPROVAL = 'awaiting_approval'
    PARTIALLY_APPROVED = 'partially_approved'
    REWORK_REQUIRED = 'rework_required'
    APPROVED = 'approved'
    ACTION_IN_PROGRESS = 'action_in_progress'
    PENDING_FINAL_UPDATE = 'pending_final_update'
    CLOSED = 'closed'
    ON_HOLD = 'on_hold'

    CHOICES = [
        (SUBMITTED, 'Submitted'),
        (ASSIGNED_TO_FACTORY, 'Assigned to Factory'),
        (FACTORY_REVIEW, 'Factory Review'),
        (AWAITING_APPROVAL, 'Awaiting Approval'),
        (PARTIALLY_APPROVED, 'Partially Approved'),
        (REWORK_REQUIRED, 'Rework Required'),
        (APPROVED, 'Approved'),
        (ACTION_IN_PROGRESS, 'Action In Progress'),
        (PENDING_FINAL_UPDATE, 'Pending Final Update'),
        (CLOSED, 'Closed'),
        (ON_HOLD, 'On Hold'),
    ]


class FactoryPriorities:
    LOW = 'low'
    MEDIUM = 'medium'
    TOP = 'top'

    CHOICES = [
        (LOW, 'Low'),
        (MEDIUM, 'Medium'),
        (TOP, 'Top'),
    ]


class DecisionStatuses:
    PENDING = 'pending'
    APPROVED = 'approved'
    REJECTED = 'rejected'
    SUPERSEDED = 'superseded'

    CHOICES = [
        (PENDING, 'Pending'),
        (APPROVED, 'Approved'),
        (REJECTED, 'Rejected'),
        (SUPERSEDED, 'Superseded'),
    ]


class ApprovalStages:
    INITIAL = 'initial'
    RECONSIDERATION = 'reconsideration'

    CHOICES = [
        (INITIAL, 'Initial approval'),
        (RECONSIDERATION, 'Rejection reconsideration'),
    ]


def infer_complaint_type(type_name):
    value = (type_name or '').strip().lower()
    if 'line' in value:
        return ComplaintTypes.LINE
    if 'production' in value:
        return ComplaintTypes.PRODUCTION
    return ComplaintTypes.PATTERN

class Brand(models.Model):
    name = models.CharField(max_length=100, unique=True)
    logo = models.ImageField(upload_to='brand_logos/', blank=True, null=True)

    def __str__(self):
        return self.name

class Model(models.Model):
    brand = models.ForeignKey(Brand, on_delete=models.CASCADE, related_name="models")
    name = models.CharField(max_length=100)

    class Meta:
        unique_together = ('brand', 'name')  # Ensure models are unique within each brand

    def __str__(self):
        return self.name

class SubModel(models.Model):
    model = models.ForeignKey(Model, on_delete=models.CASCADE, related_name="submodels", null=True, blank=True)
    name = models.CharField(max_length=100)

    class Meta:
        unique_together = ('model', 'name')

    def __str__(self):
        return self.name

class YearRange(models.Model):
    sub_model = models.ForeignKey(SubModel, on_delete=models.CASCADE, related_name="year_ranges")
    year_start = models.PositiveSmallIntegerField()
    year_end = models.PositiveSmallIntegerField()
    number_of_seats = models.PositiveSmallIntegerField(null=True, blank=True)
    number_of_doors = models.PositiveSmallIntegerField(null=True, blank=True)
    layout_code = models.CharField(max_length=100, unique=True)

    class Meta:
        unique_together = ('sub_model', 'year_start', 'year_end')

    def __str__(self):
        return f" {self.year_start} - {self.year_end}"
    
class SKU(models.Model):
    code = models.CharField(max_length=100, unique=True)
    description = models.CharField(max_length=255, blank=True, null=True)
    region = models.ForeignKey('MasterSetting', on_delete=models.SET_NULL, null=True, blank=True, related_name='skus_by_region')

    def __str__(self):
        return self.code


class MasterSetting(models.Model):
    CATEGORY_CHOICES = [
        ('Channel', 'Channel'),
        ('Country', 'Country'),
        ('Reported By', 'Reported By'),
        ('Type', 'Type'),
        ('Series', 'Series'),
        ('Material', 'Material'),
        ('Region', 'Region'),
    ]

    category = models.CharField(max_length=50, choices=CATEGORY_CHOICES)
    name = models.CharField(max_length=100, unique=True)
    class Meta:
        unique_together = ('category', 'name')

    def __str__(self):
        return self.name


class UserProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='workflow_profile')
    role = models.CharField(max_length=30, choices=WorkflowRoles.CHOICES, default=WorkflowRoles.FACTORY_VIEWER)
    country = models.ForeignKey(
        MasterSetting,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        limit_choices_to={'category': 'Country'},
        related_name='workflow_users'
    )
    department = models.CharField(max_length=100, blank=True)
    approval_role = models.CharField(max_length=10, choices=ApprovalRoles.CHOICES, blank=True)
    can_receive_factory_assignments = models.BooleanField(default=False)

    class Meta:
        ordering = ['user__username']

    def __str__(self):
        return f"{self.user.username} - {self.get_role_display()}"


class Complaint(models.Model):
    complaint_id = models.CharField(primary_key=True, max_length=20, unique=True, editable=False)
    complaint_type = models.CharField(max_length=20, choices=ComplaintTypes.CHOICES, default=ComplaintTypes.PATTERN, db_index=True)
    workflow_status = models.CharField(max_length=30, choices=WorkflowStatuses.CHOICES, default=WorkflowStatuses.SUBMITTED, db_index=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='created_complaints')
    assigned_factory_executive = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='assigned_factory_complaints'
    )
    date = models.DateField(auto_now_add=False, db_index=True)
    channel = models.ForeignKey(
        'management.MasterSetting', 
        on_delete=models.SET_NULL, 
        null=True, 
        limit_choices_to={'category': 'Channel'}, 
        related_name="complaints_as_channel"
    )
    country = models.ForeignKey(
        'management.MasterSetting', 
        on_delete=models.SET_NULL, 
        null=True, 
        limit_choices_to={'category': 'Country'}, 
        related_name="complaints_as_country"
    )
    person = models.ForeignKey(
        'management.MasterSetting', 
        on_delete=models.SET_NULL, 
        null=True, 
        limit_choices_to={'category': 'Reported By'}, 
        related_name="complaints_as_person"
    )
    case_sub_category = models.ForeignKey(
        'management.MasterSetting',
        on_delete=models.SET_NULL,
        null=True,
        limit_choices_to={'category': 'Type'},
        related_name="complaints_as_case_sub_category"
    )
    series = models.ForeignKey(
        'management.MasterSetting', 
        on_delete=models.SET_NULL, 
        null=True, 
        limit_choices_to={'category': 'Series'}, 
        related_name="complaints_as_series"
    )
    material = models.ForeignKey(
        'management.MasterSetting', 
        on_delete=models.SET_NULL, 
        null=True, 
        limit_choices_to={'category': 'Material'}, 
        related_name="complaints_as_material"
    )
    sku = models.ForeignKey(SKU, on_delete=models.SET_NULL, null=True, blank=True, related_name="complaints")
    brand = models.ForeignKey('management.Brand', on_delete=models.SET_NULL, null=True)
    model = models.ForeignKey('management.Model', on_delete=models.SET_NULL, null=True)
    sub_model = models.ForeignKey('management.SubModel', on_delete=models.SET_NULL, null=True, blank=True)
    year = models.ForeignKey('management.YearRange', on_delete=models.SET_NULL, null=True)
    status = models.CharField(max_length=10, choices=[('Open', 'Open'), ('Closed', 'Closed'), ('On Hold', 'On Hold')], default='Open', db_index=True)
    priority = models.CharField(max_length=10, choices=[('High', 'High'), ('Medium', 'Medium'), ('Low', 'Low')], default='Medium', db_index=True)
    complaint_description = models.TextField(default="Not Provided")
    batch_order = models.CharField(max_length=100)
    justification_from_factory = models.TextField(blank=True, null=True, default="Not Provided")
    action_from_factory = models.TextField(blank=True, null=True,  default="Not Provided")
    cad_date = models.DateField(auto_now_add=False, null=True, blank=True)
    updated_order_no = models.CharField(max_length=100, blank=True, null=True)
    factory_reason = models.TextField(blank=True, null=True)
    factory_action_plan = models.TextField(blank=True, null=True)
    factory_priority = models.CharField(max_length=10, choices=FactoryPriorities.CHOICES, blank=True)
    execution_notes = models.TextField(blank=True, null=True)
    production_updates_container = models.TextField(blank=True, null=True)
    factory_review_started_at = models.DateTimeField(null=True, blank=True)
    last_submitted_for_approval_at = models.DateTimeField(null=True, blank=True)
    fully_approved_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True, db_index=True)
    closed_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='closed_complaints')

    def _build_next_complaint_id(self):
        today = timezone.now().date()
        year = today.year % 100
        month = today.month
        type_prefix = ComplaintTypes.PREFIXES.get(
            self.complaint_type,
            ComplaintTypes.PREFIXES[ComplaintTypes.PATTERN],
        )
        prefix = f"{type_prefix}-{year:02d}{month:02d}"
        latest = Complaint.objects.filter(
            complaint_id__startswith=prefix
        ).order_by('-complaint_id').first()
        next_seq = int(latest.complaint_id[-4:]) + 1 if latest else 1
        return f"{prefix}{next_seq:04d}"

    def save(self, *args, **kwargs):
        if self.case_sub_category_id and not self.complaint_type:
            self.complaint_type = infer_complaint_type(self.case_sub_category.name)

        if self.complaint_id:
            return super().save(*args, **kwargs)

        # Concurrent submissions can calculate the same monthly sequence. Retry
        # only when that generated primary key was the conflicting value.
        for _ in range(5):
            candidate = self._build_next_complaint_id()
            self.complaint_id = candidate
            try:
                with transaction.atomic():
                    return super().save(*args, **kwargs)
            except IntegrityError:
                if not Complaint.objects.filter(pk=candidate).exists():
                    raise
                self.complaint_id = ''
        raise IntegrityError('Unable to allocate a unique complaint ID after several retries.')

    def __str__(self):
        return self.complaint_id

def media_upload_path(instance, filename):
    return f'complaint_media/complaint_{instance.complaint.complaint_id}/{filename}'

class ComplaintMedia(models.Model):
    complaint = models.ForeignKey(Complaint, on_delete=models.CASCADE, related_name='media_files')
    file = models.CharField()

    @property
    def storage_name(self):
        value = (self.file or '').strip()
        if not value or value.startswith(('https://', 'http://')):
            return ''
        media_prefix = settings.MEDIA_URL.rstrip('/') + '/'
        return value[len(media_prefix):] if value.startswith(media_prefix) else value.lstrip('/')

    @property
    def url(self):
        value = (self.file or '').strip()
        if not value:
            return ''
        if value.startswith(('https://', 'http://')):
            return value
        try:
            return default_storage.url(self.storage_name)
        except (NotImplementedError, ValueError):
            return ''

    @property
    def is_available(self):
        value = (self.file or '').strip()
        if not value:
            return False
        if value.startswith(('https://', 'http://')):
            return True

        if settings.USE_S3:
            return True
        media_root = Path(settings.MEDIA_ROOT).resolve()
        candidate = (media_root / self.storage_name).resolve()
        try:
            candidate.relative_to(media_root)
        except ValueError:
            return False
        return candidate.is_file()

    def __str__(self):
        return os.path.basename(self.file)


class ComplaintApproval(models.Model):
    complaint = models.ForeignKey(Complaint, on_delete=models.CASCADE, related_name='approvals')
    approval_round = models.PositiveIntegerField(default=1)
    review_stage = models.CharField(
        max_length=20,
        choices=ApprovalStages.CHOICES,
        default=ApprovalStages.INITIAL,
    )
    trigger_approval = models.ForeignKey(
        'self',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='reconsideration_approvals',
    )
    approver_role = models.CharField(max_length=10, choices=ApprovalRoles.CHOICES)
    approver_user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='complaint_approvals')
    required = models.BooleanField(default=True)
    status = models.CharField(max_length=10, choices=DecisionStatuses.CHOICES, default=DecisionStatuses.PENDING)
    comment = models.TextField(blank=True)
    decided_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('complaint', 'approval_round', 'approver_role')
        ordering = ['complaint_id', 'approval_round', 'approver_role']
        indexes = [
            models.Index(fields=['approver_user', 'status'], name='idx_approval_user_status'),
        ]

    def __str__(self):
        return f"{self.complaint_id} - {self.approver_role} - {self.status}"


class ComplaintTimeline(models.Model):
    complaint = models.ForeignKey(Complaint, on_delete=models.CASCADE, related_name='timeline_events')
    action_type = models.CharField(max_length=50)
    title = models.CharField(max_length=150)
    description = models.TextField(blank=True)
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='complaint_timeline_events')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']

    def __str__(self):
        return f"{self.complaint_id} - {self.title}"


class Notification(models.Model):
    recipient = models.ForeignKey(User, on_delete=models.CASCADE, related_name='workflow_notifications')
    complaint = models.ForeignKey(Complaint, on_delete=models.CASCADE, null=True, blank=True, related_name='notifications')
    title = models.CharField(max_length=150)
    message = models.TextField(blank=True)
    notification_type = models.CharField(max_length=50, default='workflow')
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['recipient', 'is_read'], name='idx_notif_recipient_read'),
            models.Index(fields=['recipient', '-created_at'], name='idx_notif_recipient_created'),
        ]

    def __str__(self):
        return f"{self.recipient.username} - {self.title}"


class ComplaintEditLog(models.Model):
    complaint = models.ForeignKey(Complaint, on_delete=models.CASCADE, related_name='edit_logs')
    edited_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='complaint_edits')
    field_name = models.CharField(max_length=100)
    old_value = models.TextField(blank=True)
    new_value = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.complaint_id} - {self.field_name}"

# Activity Log Model

class ActivityLog(models.Model):
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    action = models.CharField(max_length=100)
    object_type = models.CharField(max_length=100)
    object_name = models.CharField(max_length=255)
    timestamp = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.timestamp} - {self.user} - {self.action} {self.object_type} {self.object_name}"
