from rest_framework import serializers
from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from django.utils import timezone
from .models import (
    Brand,
    Complaint,
    ComplaintApproval,
    ComplaintEditLog,
    ComplaintMedia,
    ComplaintTimeline,
    MasterSetting,
    Model,
    Notification,
    DecisionStatuses,
    FactoryPriorities,
    SKU,
    SubModel,
    UserProfile,
    YearRange,
    complaint_type_master_category,
    complaint_type_from_master_setting,
)

class DashboardStatsSerializer(serializers.Serializer):
    total_complaints = serializers.IntegerField()
    open_complaints = serializers.IntegerField()
    closed_complaints = serializers.IntegerField()
    on_hold_complaints = serializers.IntegerField()
    total_vehicles = serializers.IntegerField()
    total_skus = serializers.IntegerField()
    total_settings = serializers.IntegerField()
    total_master_settings = serializers.IntegerField()

class UserSerializer(serializers.ModelSerializer):
    workflow_role = serializers.SerializerMethodField()
    approval_role = serializers.SerializerMethodField()
    country = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            'id', 'username', 'first_name', 'last_name', 'email', 'is_staff', 'is_superuser',
            'workflow_role', 'approval_role', 'country',
        ]
        read_only_fields = ['id', 'username', 'is_staff', 'is_superuser']

    def _profile(self, obj):
        try:
            return obj.workflow_profile
        except UserProfile.DoesNotExist:
            return None

    def get_workflow_role(self, obj):
        profile = self._profile(obj)
        return profile.role if profile else None

    def get_approval_role(self, obj):
        profile = self._profile(obj)
        return profile.approval_role if profile else None

    def get_country(self, obj):
        profile = self._profile(obj)
        return profile.country.name if profile and profile.country_id else None


class WorkflowUserProfileSerializer(serializers.ModelSerializer):
    username = serializers.CharField(source='user.username', read_only=True)
    country_name = serializers.CharField(source='country.name', read_only=True)

    class Meta:
        model = UserProfile
        fields = '__all__'

class RegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(
        write_only=True,
        style={'input_type': 'password'},
        validators=[validate_password],
    )

    class Meta:
        model = User
        fields = ['username', 'email', 'password']

    def create(self, validated_data):
        user = User.objects.create_user(
            username=validated_data['username'],
            email=validated_data.get('email', ''),
            password=validated_data['password']
        )
        return user

class UserProfileUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ['first_name', 'last_name', 'email']

class BrandSerializer(serializers.ModelSerializer):
    class Meta:
        model = Brand
        fields = '__all__'

class ModelSerializer(serializers.ModelSerializer):
    brand_name = serializers.CharField(source='brand.name', read_only=True)
    class Meta:
        model = Model
        fields = '__all__'

class SubModelSerializer(serializers.ModelSerializer):
    model_name = serializers.CharField(source='model.name', read_only=True)
    class Meta:
        model = SubModel
        fields = '__all__'

class YearRangeSerializer(serializers.ModelSerializer):
    sub_model_name = serializers.CharField(source='sub_model.name', read_only=True)
    class Meta:
        model = YearRange
        fields = '__all__'

class MasterSettingSerializer(serializers.ModelSerializer):
    class Meta:
        model = MasterSetting
        fields = '__all__'

class SKUSerializer(serializers.ModelSerializer):
    region_name = serializers.CharField(source='region.name', read_only=True)
    class Meta:
        model = SKU
        fields = '__all__'

class ComplaintMediaSerializer(serializers.ModelSerializer):
    url = serializers.CharField(read_only=True)
    is_available = serializers.BooleanField(read_only=True)

    class Meta:
        model = ComplaintMedia
        fields = '__all__'


class ComplaintApprovalSerializer(serializers.ModelSerializer):
    approver_username = serializers.CharField(source='approver_user.username', read_only=True)

    class Meta:
        model = ComplaintApproval
        fields = '__all__'


class ComplaintTimelineSerializer(serializers.ModelSerializer):
    username = serializers.CharField(source='user.username', read_only=True)

    class Meta:
        model = ComplaintTimeline
        fields = '__all__'


class NotificationSerializer(serializers.ModelSerializer):
    complaint_id = serializers.CharField(source='complaint.complaint_id', read_only=True)

    class Meta:
        model = Notification
        fields = '__all__'


class ComplaintEditLogSerializer(serializers.ModelSerializer):
    edited_by_username = serializers.CharField(source='edited_by.username', read_only=True)

    class Meta:
        model = ComplaintEditLog
        fields = '__all__'


class FactoryReviewInputSerializer(serializers.Serializer):
    factory_reason = serializers.CharField(max_length=5000, allow_blank=False, trim_whitespace=True)
    factory_action_plan = serializers.CharField(max_length=5000, allow_blank=False, trim_whitespace=True)
    factory_priority = serializers.ChoiceField(choices=FactoryPriorities.CHOICES)


class ApprovalDecisionInputSerializer(serializers.Serializer):
    decision = serializers.ChoiceField(choices=[
        DecisionStatuses.APPROVED,
        DecisionStatuses.REJECTED,
    ])
    comment = serializers.CharField(max_length=2000, required=False, allow_blank=True, trim_whitespace=True)

    def validate(self, attrs):
        if attrs.get('decision') == DecisionStatuses.REJECTED and not attrs.get('comment'):
            raise serializers.ValidationError({
                'comment': 'Explain what must be corrected when rejecting.'
            })
        return attrs


class FinalComplaintUpdateSerializer(serializers.Serializer):
    cad_date = serializers.DateField()
    production_updates_container = serializers.CharField(
        max_length=100,
        required=False,
        allow_blank=True,
        trim_whitespace=True,
    )

    def validate_cad_date(self, value):
        if value > timezone.localdate():
            raise serializers.ValidationError('CAD Updated Date cannot be in the future.')
        return value

class ComplaintSerializer(serializers.ModelSerializer):
    brand_name = serializers.CharField(source='brand.name', read_only=True)
    model_name = serializers.CharField(source='model.name', read_only=True)
    sub_model_name = serializers.CharField(source='sub_model.name', read_only=True)
    year_range = serializers.CharField(source='year.__str__', read_only=True)
    sku_code = serializers.CharField(source='sku.code', read_only=True)
    channel_name = serializers.CharField(source='channel.name', read_only=True)
    country_name = serializers.CharField(source='country.name', read_only=True)
    reported_by_name = serializers.SerializerMethodField()
    case_type_name = serializers.CharField(source='case_sub_category.name', read_only=True)
    series_name = serializers.CharField(source='series.name', read_only=True)
    material_name = serializers.CharField(source='material.name', read_only=True)
    media = ComplaintMediaSerializer(source='media_files', many=True, read_only=True)
    approvals = ComplaintApprovalSerializer(many=True, read_only=True)
    timeline_events = ComplaintTimelineSerializer(many=True, read_only=True)

    def get_reported_by_name(self, obj):
        if obj.created_by:
            return obj.created_by.username
        return obj.person.name if obj.person else ''

    def validate(self, attrs):
        case_type = attrs.get(
            'case_sub_category',
            getattr(self.instance, 'case_sub_category', None),
        )
        complaint_type = attrs.get(
            'complaint_type',
            getattr(self.instance, 'complaint_type', None),
        )
        if self.instance is None and 'complaint_type' not in self.initial_data:
            complaint_type = complaint_type_from_master_setting(case_type) or complaint_type
        if case_type and complaint_type:
            expected_category = complaint_type_master_category(complaint_type)
            if case_type.category != expected_category:
                raise serializers.ValidationError({
                    'case_sub_category': 'Select a Type from the selected complaint category.'
                })
        return attrs

    class Meta:
        model = Complaint
        fields = '__all__'
        read_only_fields = [
            'complaint_id',
            'date',
            'workflow_status',
            'created_by',
            'person',
            'country',
            'assigned_factory_executive',
            'status',
            'justification_from_factory',
            'action_from_factory',
            'factory_reason',
            'factory_action_plan',
            'factory_priority',
            'execution_notes',
            'production_updates_container',
            'factory_review_started_at',
            'last_submitted_for_approval_at',
            'fully_approved_at',
            'closed_at',
            'closed_by',
        ]
