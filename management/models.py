import os
import uuid
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.contrib.auth.models import User
from django.core.files.storage import default_storage
from django.db import IntegrityError, models, transaction
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext_lazy as _


class WorkflowRoles:
    COUNTRY_EXECUTIVE = 'country_executive'
    FACTORY_VIEWER = 'factory_viewer'
    FACTORY_EXECUTIVE = 'factory_executive'
    FACTORY_COMPLAINT_REGISTRAR = 'factory_complaint_registrar'
    APPROVER = 'approver'
    ADMIN = 'admin'

    CHOICES = [
        (COUNTRY_EXECUTIVE, _('Country Executive')),
        (FACTORY_VIEWER, _('Factory Viewer')),
        (FACTORY_EXECUTIVE, _('Factory Executive')),
        (FACTORY_COMPLAINT_REGISTRAR, _('Factory Complaint Registrar')),
        (APPROVER, _('Approver')),
        (ADMIN, _('Admin')),
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
    QUALITY = 'quality'
    LINE = 'line'

    CHOICES = [
        (PATTERN, _('Pattern Complaint')),
        (PRODUCTION, _('Production Complaint')),
        (QUALITY, _('Quality Complaint')),
        (LINE, _('Factory Complaint')),
    ]

    PREFIXES = {
        PATTERN: 'PAT',
        PRODUCTION: 'PRO',
        QUALITY: 'QUA',
        LINE: 'LIN',
    }


COMPLAINT_TYPE_MASTER_CATEGORIES = {
    ComplaintTypes.PATTERN: 'Pattern Complaint Type',
    ComplaintTypes.PRODUCTION: 'Production Complaint Type',
    ComplaintTypes.QUALITY: 'Quality Complaint Type',
    ComplaintTypes.LINE: 'Factory Complaint Type',
}


def complaint_type_master_category(complaint_type):
    return COMPLAINT_TYPE_MASTER_CATEGORIES.get(complaint_type)


def complaint_type_from_master_setting(setting):
    if not setting:
        return None
    category_to_type = {
        category: complaint_type
        for complaint_type, category in COMPLAINT_TYPE_MASTER_CATEGORIES.items()
    }
    return category_to_type.get(setting.category)


class WorkflowStatuses:
    SUBMITTED = 'submitted'
    ASSIGNED_TO_FACTORY = 'assigned_to_factory'
    FACTORY_REVIEW = 'factory_review'
    AWAITING_APPROVAL = 'awaiting_approval'
    PARTIALLY_APPROVED = 'partially_approved'
    REWORK_REQUIRED = 'rework_required'
    APPROVED = 'approved'
    ACTION_IN_PROGRESS = 'action_in_progress'
    AWAITING_EXECUTION_VERIFICATION = 'awaiting_execution_verification'
    EXECUTION_PARTIALLY_VERIFIED = 'execution_partially_verified'
    PENDING_FINAL_UPDATE = 'pending_final_update'
    CLOSED = 'closed'
    ON_HOLD = 'on_hold'

    CHOICES = [
        (SUBMITTED, _('Submitted')),
        (ASSIGNED_TO_FACTORY, _('Assigned to Factory')),
        (FACTORY_REVIEW, _('Factory Review')),
        (AWAITING_APPROVAL, _('Awaiting Approval')),
        (PARTIALLY_APPROVED, _('Partially Approved')),
        (REWORK_REQUIRED, _('Rework Required')),
        (APPROVED, _('Approved')),
        (ACTION_IN_PROGRESS, _('Action In Progress')),
        (AWAITING_EXECUTION_VERIFICATION, _('Awaiting Execution Verification')),
        (EXECUTION_PARTIALLY_VERIFIED, _('Execution Partially Verified')),
        (PENDING_FINAL_UPDATE, _('Pending Final Update')),
        (CLOSED, _('Closed')),
        (ON_HOLD, _('On Hold')),
    ]


class FactoryPriorities:
    LOW = 'low'
    MEDIUM = 'medium'
    TOP = 'top'

    CHOICES = [
        (LOW, _('Low')),
        (MEDIUM, _('Medium')),
        (TOP, _('Top')),
    ]


class DecisionStatuses:
    PENDING = 'pending'
    APPROVED = 'approved'
    REJECTED = 'rejected'
    SUPERSEDED = 'superseded'

    CHOICES = [
        (PENDING, _('Pending')),
        (APPROVED, _('Approved')),
        (REJECTED, _('Rejected')),
        (SUPERSEDED, _('Superseded')),
    ]


class ApprovalStages:
    INITIAL = 'initial'
    RECONSIDERATION = 'reconsideration'
    EXECUTION_VERIFICATION = 'execution_verification'

    CHOICES = [
        (INITIAL, _('Initial approval')),
        (RECONSIDERATION, _('Rejection reconsideration')),
        (EXECUTION_VERIFICATION, _('Execution verification')),
    ]


def infer_complaint_type(type_name):
    value = (type_name or '').strip().lower()
    if 'line' in value or 'factory' in value:
        return ComplaintTypes.LINE
    if 'quality' in value:
        return ComplaintTypes.QUALITY
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
    vehicle_country = models.ForeignKey('MasterSetting', on_delete=models.SET_NULL, null=True, blank=True, related_name='year_ranges_by_vehicle_country')
    measurement_country = models.ForeignKey('MasterSetting', on_delete=models.SET_NULL, null=True, blank=True, related_name='year_ranges_by_measurement_country')

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
        ('Channel', _('Channel')),
        ('Country', _('Country')),
        ('Reported By', _('Reported By')),
        ('Pattern Complaint Type', _('Pattern Complaint Types')),
        ('Production Complaint Type', _('Production Complaint Types')),
        ('Quality Complaint Type', _('Quality Complaint Types')),
        ('Factory Complaint Type', _('Factory Complaint Types')),
        ('Series', _('Series')),
        ('Material', _('Material')),
        ('Region', _('Region')),
    ]

    category = models.CharField(max_length=50, choices=CATEGORY_CHOICES)
    name = models.CharField(max_length=100)
    class Meta:
        unique_together = ('category', 'name')

    def __str__(self):
        return self.name


class UserProfile(models.Model):
    LANGUAGE_CHOICES = [
        ('en', 'English'),
        ('ar', 'العربية'),
        ('hi', 'हिन्दी'),
    ]

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
    phone_number = models.CharField(max_length=30, blank=True)
    approval_role = models.CharField(max_length=10, choices=ApprovalRoles.CHOICES, blank=True)
    can_receive_factory_assignments = models.BooleanField(default=False)
    photo = models.ImageField(upload_to='profile_photos/', null=True, blank=True)
    preferred_language = models.CharField(
        max_length=5,
        choices=LANGUAGE_CHOICES,
        default='en',
    )

    @property
    def avatar_url(self):
        if self.photo:
            try:
                return self.photo.url
            except Exception:
                return None
        return None

    @property
    def country_flag_url(self):
        # Country executives are scoped to their configured country. Every other
        # role reports for India, regardless of any legacy profile-country value.
        if self.role == WorkflowRoles.COUNTRY_EXECUTIVE:
            country = self.country
        else:
            country = None

        if self.role == WorkflowRoles.COUNTRY_EXECUTIVE and not country:
            return None
        country_name = country.name.strip().lower() if country else 'india'
        mapping = {
            'ksa': 'sa',
            'saudi arabia': 'sa',
            'india': 'in',
            'usa': 'us',
            'united states': 'us',
            'united states of america': 'us',
            'uae': 'ae',
            'united arab emirates': 'ae',
            'thailand': 'th',
            'malaysia': 'my',
            'germany': 'de',
            'united kingdom': 'gb',
            'uk': 'gb',
        }
        code = mapping.get(country_name)
        if not code:
            code = country_name[:2]
        return f"https://flagcdn.com/w40/{code}.png"

    class Meta:
        ordering = ['user__username']

    def __str__(self):
        return f"{self.user.username} - {self.get_role_display()}"


class Complaint(models.Model):
    complaint_id = models.CharField(primary_key=True, max_length=20, unique=True, editable=False)
    complaint_type = models.CharField(max_length=20, choices=ComplaintTypes.CHOICES, default=ComplaintTypes.PATTERN, db_index=True)
    workflow_status = models.CharField(max_length=40, choices=WorkflowStatuses.CHOICES, default=WorkflowStatuses.SUBMITTED, db_index=True)
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
        limit_choices_to={'category__in': list(COMPLAINT_TYPE_MASTER_CATEGORIES.values())},
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
    status = models.CharField(max_length=10, choices=[('Open', _('Open')), ('Closed', _('Closed')), ('On Hold', _('On Hold'))], default='Open', db_index=True)
    priority = models.CharField(max_length=10, choices=[('High', _('High')), ('Medium', _('Medium')), ('Low', _('Low'))], default='Medium', db_index=True)
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
        target_date = self.date or timezone.now().date()
        if isinstance(target_date, str):
            from django.utils.dateparse import parse_date
            parsed = parse_date(target_date)
            if parsed:
                target_date = parsed
            else:
                target_date = timezone.now().date()
        date_str = target_date.strftime('%d%m%Y')
        type_prefix = ComplaintTypes.PREFIXES.get(
            self.complaint_type,
            ComplaintTypes.PREFIXES[ComplaintTypes.PATTERN],
        )
        base_seq = Complaint.objects.filter(
            complaint_type=self.complaint_type,
            date=target_date
        ).count() + 1
        seq = base_seq
        while True:
            candidate = f"{type_prefix}-{seq}{date_str}"
            if not Complaint.objects.filter(pk=candidate).exists():
                return candidate
            seq += 1

    def save(self, *args, **kwargs):
        if self.case_sub_category_id and not self.complaint_type:
            self.complaint_type = infer_complaint_type(self.case_sub_category.name)

        if not self.date:
            self.date = timezone.now().date()

        if self.complaint_id:
            return super().save(*args, **kwargs)

        # Concurrent submissions can calculate the same daily sequence. Retry
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
        if settings.USE_SUPABASE_STORAGE and self.pk:
            return reverse('complaint_media_download', args=[self.pk])
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

        if settings.USE_SUPABASE_STORAGE:
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


def complaint_media_upload_expiry():
    return timezone.now() + timedelta(seconds=settings.SUPABASE_SIGNED_UPLOAD_TTL_SECONDS)


class ComplaintMediaUploadBatch(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='complaint_media_upload_batches')
    complaint = models.ForeignKey(
        Complaint,
        on_delete=models.CASCADE,
        related_name='media_upload_batches',
        null=True,
        blank=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(default=complaint_media_upload_expiry)

    class Meta:
        indexes = [models.Index(fields=['user', 'expires_at'])]


class ComplaintMediaUpload(models.Model):
    class Status(models.TextChoices):
        PENDING = 'pending', 'Pending'
        ATTACHED = 'attached', 'Attached'
        REJECTED = 'rejected', 'Rejected'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    batch = models.ForeignKey(
        ComplaintMediaUploadBatch,
        on_delete=models.CASCADE,
        related_name='uploads',
    )
    complaint = models.ForeignKey(
        Complaint,
        on_delete=models.SET_NULL,
        related_name='verified_media_uploads',
        null=True,
        blank=True,
    )
    storage_path = models.CharField(max_length=500, unique=True)
    original_name = models.CharField(max_length=255)
    expected_size = models.PositiveBigIntegerField()
    expected_content_type = models.CharField(max_length=100)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    created_at = models.DateTimeField(auto_now_add=True)
    attached_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [models.Index(fields=['status', 'created_at'])]


class ComplaintApproval(models.Model):
    complaint = models.ForeignKey(Complaint, on_delete=models.CASCADE, related_name='approvals')
    approval_round = models.PositiveIntegerField(default=1)
    review_stage = models.CharField(
        max_length=30,
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


class ChatMessage(models.Model):
    sender = models.ForeignKey(User, on_delete=models.CASCADE, related_name='sent_chat_messages')
    recipient = models.ForeignKey(User, on_delete=models.CASCADE, related_name='received_chat_messages')
    complaint = models.ForeignKey(Complaint, on_delete=models.SET_NULL, null=True, blank=True, related_name='chat_messages')
    message = models.TextField()
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']
        indexes = [
            models.Index(fields=['sender', 'recipient', 'created_at'], name='idx_chat_participants_time'),
            models.Index(fields=['recipient', 'is_read'], name='idx_chat_recipient_read'),
        ]

    def __str__(self):
        return f"Chat from {self.sender.username} to {self.recipient.username} at {self.created_at}"
