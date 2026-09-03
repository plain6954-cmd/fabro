from django import forms
from django.db.models import Q
from .models import (
    ApprovalStages,
    ApprovalRoles,
    Brand,
    Complaint,
    ComplaintMedia,
    ComplaintTypes,
    complaint_type_master_category,
    DecisionStatuses,
    FactoryPriorities,
    MasterSetting,
    Model,
    SKU,
    SubModel,
    UserProfile,
    WorkflowRoles,
    YearRange,
)
from datetime import date
from django.contrib.auth.password_validation import validate_password
from django.utils.translation import gettext_lazy as _

MAX_CSV_UPLOAD_SIZE = 5 * 1024 * 1024
MAX_BRAND_LOGO_SIZE = 2 * 1024 * 1024
MAX_PROFILE_PHOTO_SIZE = 5 * 1024 * 1024
ALLOWED_IMAGE_CONTENT_TYPES = {'image/jpeg', 'image/png', 'image/webp', 'image/gif'}


def validate_profile_photo(photo):
    if not photo:
        return photo
    if photo.size > MAX_PROFILE_PHOTO_SIZE:
        raise forms.ValidationError(_('Profile photo must be 5 MB or smaller.'))
    content_type = (getattr(photo, 'content_type', '') or '').lower()
    if content_type not in ALLOWED_IMAGE_CONTENT_TYPES:
        raise forms.ValidationError(_('Profile photo must be a JPG, PNG, WEBP, or GIF image.'))
    # ImageField asks Pillow to verify the bytes, not only the filename or MIME header.
    return forms.ImageField().clean(photo)


def validate_csv_upload(csv_file):
    if not csv_file.name.lower().endswith('.csv'):
        raise forms.ValidationError(_('File must be a CSV.'))
    if csv_file.size > MAX_CSV_UPLOAD_SIZE:
        raise forms.ValidationError(_('CSV file must be 5 MB or smaller.'))
    return csv_file

class CarDetailsForm(forms.Form):
    layout_code = forms.CharField(label=_("Layout Code"), max_length=100)
    brand_name = forms.CharField(label=_("Brand Name"), max_length=100)
    brand_logo = forms.ImageField(label=_("Brand Logo"), required=False)
    model_name = forms.CharField(label=_("Model Name"), max_length=100)
    sub_model_name = forms.CharField(label=_("Sub-Model Name"), max_length=100, required=False,)
    year_start = forms.IntegerField(label=_("Year Start"), min_value=1900, max_value=2100)
    year_end = forms.IntegerField(label=_("Year End"), min_value=1900, max_value=2100)
    number_of_seats = forms.IntegerField(label=_("Number of Seats"), min_value=1, max_value=100)
    number_of_doors = forms.IntegerField(label=_("Number of Doors"), min_value=1, max_value=20)
    vehicle_country = forms.ModelChoiceField(
        label=_("Vehicle Country"),
        queryset=MasterSetting.objects.filter(category='Country'),
        required=False,
        empty_label=_("Select Country"),
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    measurement_country = forms.ModelChoiceField(
        label=_("Measurement Country"),
        queryset=MasterSetting.objects.filter(category='Country'),
        required=False,
        empty_label=_("Select Country"),
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    
    widgets = {
        'layout_code': forms.TextInput(attrs={'class': 'form-input'}),
        'brand_name': forms.TextInput(attrs={'class': 'form-input'}),
        'brand_logo': forms.ClearableFileInput(attrs={'class': 'form-input'}),
        'model_name': forms.TextInput(attrs={'class': 'form-input'}),
        'sub_model_name': forms.TextInput(attrs={'class': 'form-input'}),
        'year_start': forms.NumberInput(attrs={'class': 'form-input'}),
        'year_end': forms.NumberInput(attrs={'class': 'form-input'}),
        'number_of_seats': forms.NumberInput(attrs={'class': 'form-input'}),
        'number_of_doors': forms.NumberInput(attrs={'class': 'form-input'}),
        'vehicle_country': forms.Select(attrs={'class': 'form-select'}),
        'measurement_country': forms.Select(attrs={'class': 'form-select'}),
    }

    def clean(self):
        cleaned_data = super().clean()
        for field in ['brand_name', 'model_name', 'sub_model_name', 'layout_code']:
            if field in cleaned_data and isinstance(cleaned_data[field], str):
                cleaned_data[field] = cleaned_data[field].strip()
        year_start = cleaned_data.get("year_start")
        year_end = cleaned_data.get("year_end")
        
        if year_start and year_end and year_start > year_end:
            self.add_error("year_end", _("Year End must be greater than or equal to Year Start."))
        
        return cleaned_data

    def clean_brand_logo(self):
        logo = self.cleaned_data.get('brand_logo')
        if not logo:
            return logo
        if logo.size > MAX_BRAND_LOGO_SIZE:
            raise forms.ValidationError(_('Brand logo must be 2 MB or smaller.'))
        content_type = (getattr(logo, 'content_type', '') or '').lower()
        if content_type not in ALLOWED_IMAGE_CONTENT_TYPES:
            raise forms.ValidationError(_('Brand logo must be a JPG, PNG, WEBP, or GIF image.'))
        return logo

class MasterSettingForm(forms.ModelForm):
    class Meta:
        model = MasterSetting
        fields = ['category', 'name']
        widgets = {
            'category': forms.Select(attrs={'class': 'form-select'}),
            'name': forms.TextInput(attrs={'class': 'form-input'}),
            }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['category'].choices = [
            (value, label)
            for value, label in MasterSetting.CATEGORY_CHOICES
            if value not in {'Country', 'Reported By'}
        ]

class ComplaintForm(forms.ModelForm):
    class Meta:
        model = Complaint
        fields = [
            'date', 'channel', 'case_sub_category', 'series', 'material',
            'brand', 'model', 'sub_model', 'year', 'status','priority','sku', 'updated_order_no',
            'complaint_description', 'batch_order'
        ]
        widgets = {
            'date': forms.DateInput(attrs={'type': 'date'}),
            'channel': forms.Select(attrs={'class': 'form-select'}),
            'case_sub_category': forms.Select(attrs={'class': 'form-select'}),
            'series': forms.Select(attrs={'class': 'form-select'}),
            'material': forms.Select(attrs={'class': 'form-select'}),
            'brand': forms.Select(attrs={'class': 'form-select'}),
            'model': forms.Select(attrs={'class': 'form-select'}),
            'sub_model': forms.Select(attrs={'class': 'form-select'}),
            'year': forms.Select(attrs={'class': 'form-select'}),
            'status': forms.Select(attrs={'class': 'form-select'}),
            'priority': forms.Select(attrs={'class': 'form-select'}),
            'updated_order_no': forms.TextInput(attrs={'class': 'form-input'}),
            'sku': forms.Select(attrs={'class': 'form-select'}),
            'complaint_description': forms.Textarea(attrs={'rows': 3, 'class': 'form-textarea'}),
            'batch_order': forms.TextInput(attrs={'class': 'form-input'}),

        }

    def __init__(self, *args, complaint_type=None, **kwargs):
        super().__init__(*args, **kwargs)
        today = date.today()
        if not self.instance.pk:
            self.fields['date'].initial = today
        self.fields['date'].disabled = True
        if not self.instance.pk:
            self.fields['status'].initial = 'Open'
        self.fields['brand'].queryset = Brand.objects.all()
        self.fields['model'].queryset = Model.objects.none()
        self.fields['sub_model'].queryset = SubModel.objects.none()
        self.fields['year'].queryset = YearRange.objects.none()
        self.fields['sku'].queryset = SKU.objects.all()
        self.fields['sku'].empty_label = _('Select SKU')
        self.fields['sku'].label_from_instance = lambda sku: f"{sku.code} - {sku.description}" if sku.description else sku.code

        selected_complaint_type = complaint_type or getattr(self.instance, 'complaint_type', None)
        type_category = complaint_type_master_category(selected_complaint_type)
        type_queryset = MasterSetting.objects.none()
        if type_category:
            type_queryset = MasterSetting.objects.filter(category=type_category)
        if self.instance.pk and self.instance.case_sub_category_id:
            type_queryset = MasterSetting.objects.filter(
                Q(category=type_category)
                | Q(pk=self.instance.case_sub_category_id)
            )
        self.fields['case_sub_category'].queryset = type_queryset.order_by('name')
        self.fields['case_sub_category'].empty_label = _('Select Type')

        optional_fields = [
            'channel', 'case_sub_category', 'series', 'material',
            'brand', 'model', 'sub_model', 'year', 'sku', 'updated_order_no',
            'complaint_description', 'batch_order'
        ]
        for field_name in optional_fields:
            if field_name in self.fields:
                self.fields[field_name].required = False

        if 'brand' in self.data:
            try:
                brand_id = int(self.data.get('brand'))
                self.fields['model'].queryset = Model.objects.filter(brand_id=brand_id)
            except (ValueError, TypeError):
                pass
        elif self.instance.pk:
            self.fields['model'].queryset = Model.objects.filter(brand=self.instance.brand)
        if 'model' in self.data:
            try:
                model_id = int(self.data.get('model'))
                self.fields['sub_model'].queryset = SubModel.objects.filter(model_id=model_id)
            except (ValueError, TypeError):
                pass
        elif self.instance.pk:
            self.fields['sub_model'].queryset = SubModel.objects.filter(model=self.instance.model)
        if 'sub_model' in self.data:
            try:
                sub_model_id = int(self.data.get('sub_model'))
                self.fields['year'].queryset = YearRange.objects.filter(sub_model_id=sub_model_id)
            except (ValueError, TypeError):
                pass
        elif self.instance.pk:
            self.fields['year'].queryset = YearRange.objects.filter(sub_model=self.instance.sub_model)


class FactoryReviewForm(forms.ModelForm):
    class Meta:
        model = Complaint
        fields = ['factory_reason', 'factory_action_plan', 'factory_priority']
        widgets = {
            'factory_reason': forms.Textarea(attrs={
                'rows': 5,
                'class': 'form-textarea',
                'placeholder': _('Write the real reason behind the defect after reviewing photos/videos.')
            }),
            'factory_action_plan': forms.Textarea(attrs={
                'rows': 5,
                'class': 'form-textarea',
                'placeholder': _('Write the proposed action plan from the factory.')
            }),
            'factory_priority': forms.Select(attrs={'class': 'form-select'}),
        }
        labels = {
            'factory_reason': _('Real reason behind defect'),
            'factory_action_plan': _('Factory action plan'),
            'factory_priority': _('Factory priority'),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['factory_priority'].choices = [('', _('Select Priority'))] + list(FactoryPriorities.CHOICES)
        for field in self.fields.values():
            field.required = True


class ApprovalDecisionForm(forms.Form):
    decision = forms.ChoiceField(
        label=_('Your decision'),
        choices=[
            (DecisionStatuses.APPROVED, _('Approve')),
            (DecisionStatuses.REJECTED, _('Reject')),
        ],
        widget=forms.RadioSelect(attrs={'class': 'decision-radio'}),
    )
    comment = forms.CharField(
        label=_('Review comment'),
        required=False,
        max_length=2000,
        widget=forms.Textarea(attrs={
            'rows': 5,
            'class': 'form-textarea',
            'placeholder': _('Optional for approval. Required when rejecting.'),
        }),
    )

    def __init__(self, *args, **kwargs):
        approval_stage = kwargs.pop('approval_stage', ApprovalStages.INITIAL)
        super().__init__(*args, **kwargs)
        if approval_stage == ApprovalStages.RECONSIDERATION:
            self.fields['decision'].label = _('Reconsideration decision')
            self.fields['decision'].choices = [
                (DecisionStatuses.APPROVED, _('Proceed with Action Plan')),
                (DecisionStatuses.REJECTED, _('Return to Factory Executive for Rework')),
            ]
            self.fields['comment'].widget.attrs['placeholder'] = (
                _('Optional when proceeding. Required when returning for rework.')
            )
        elif approval_stage == ApprovalStages.EXECUTION_VERIFICATION:
            self.fields['decision'].label = _('Execution verification decision')
            self.fields['decision'].choices = [
                (DecisionStatuses.APPROVED, _('Execution Is Correct')),
                (DecisionStatuses.REJECTED, _('Execution Needs Correction')),
            ]
            self.fields['comment'].widget.attrs['placeholder'] = (
                _('Optional when verifying. Required when requesting an execution correction.')
            )

    def clean(self):
        cleaned_data = super().clean()
        decision = cleaned_data.get('decision')
        comment = (cleaned_data.get('comment') or '').strip()
        cleaned_data['comment'] = comment
        if decision == DecisionStatuses.REJECTED and not comment:
            self.add_error('comment', _('Explain what must be corrected when rejecting.'))
        return cleaned_data


class FinalComplaintUpdateForm(forms.Form):
    cad_date = forms.DateField(
        label=_('CAD Updated Date'),
        widget=forms.DateInput(attrs={'type': 'date', 'class': 'form-input'}),
    )
    production_updates_container = forms.CharField(
        label=_('New Production Container Number'),
        max_length=100,
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-input',
            'placeholder': _('Enter the new production container number'),
            'autocomplete': 'off',
        }),
    )

    def __init__(self, *args, complaint=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.complaint = complaint
        if complaint and complaint.complaint_type == ComplaintTypes.LINE:
            self.fields['production_updates_container'].widget = forms.HiddenInput()
        else:
            self.fields['production_updates_container'].required = True

    def clean_cad_date(self):
        cad_date = self.cleaned_data['cad_date']
        if cad_date > date.today():
            raise forms.ValidationError(_('CAD Updated Date cannot be in the future.'))
        return cad_date

# forms.py
class UploadCSVForm(forms.Form):
    csv_file = forms.FileField(label=_("Upload CSV File"))

    def clean_csv_file(self):
        return validate_csv_upload(self.cleaned_data['csv_file'])

class SKUForm(forms.ModelForm):
    class Meta:
        model = SKU
        fields = ['code', 'description', 'region']
        widgets = {
            'code': forms.TextInput(attrs={'class': 'form-input'}),
            'description': forms.Textarea(attrs={'class': 'form-textarea', 'rows': 3}),
            'region': forms.Select(attrs={'class': 'form-select'}),
        }
    def __init__(self, *args, **kwargs):
        super(SKUForm, self).__init__(*args, **kwargs)
        self.fields['region'].queryset = MasterSetting.objects.filter(category='Region')

    def clean_code(self):
        code = (self.cleaned_data.get('code') or '').strip()
        if self.instance.pk:
            # Editing existing SKU
            if SKU.objects.filter(code__iexact=code).exclude(pk=self.instance.pk).exists():
                raise forms.ValidationError(_("SKU code already exists."))
        else:
            # Creating new SKU
            if SKU.objects.filter(code__iexact=code).exists():
                raise forms.ValidationError(_("SKU code already exists."))
        return code

    def clean_description(self):
        description = self.cleaned_data.get('description')
        return description.strip() if description else description

class SKUUploadForm(forms.Form):
    csv_file = forms.FileField(label=_("Upload CSV File"))
    def clean_csv_file(self):
        return validate_csv_upload(self.cleaned_data['csv_file'])
    widgets = {
        'csv_file': forms.ClearableFileInput(attrs={'class': 'file-input'}),
    }

from django import forms
from django.contrib.auth.models import User, Group, Permission

class UnifiedWorkflowRoles:
    CHOICES = [
        (WorkflowRoles.COUNTRY_EXECUTIVE, _('Country Executive')),
        (WorkflowRoles.FACTORY_VIEWER, _('Factory Viewer')),
        (WorkflowRoles.FACTORY_EXECUTIVE, _('Factory Executive')),
        (WorkflowRoles.FACTORY_COMPLAINT_REGISTRAR, _('Factory Complaint Registrar')),
        ('PM', 'PM'),
        ('OM', 'OM'),
        ('CAD', 'CAD'),
        ('ED', 'ED'),
        ('MD', 'MD'),
        (WorkflowRoles.ADMIN, _('Admin')),
    ]

    ALL_CHOICES = CHOICES + [
        (WorkflowRoles.APPROVER, _('Approver')),
        ('approver_PM', 'PM'),
        ('approver_OM', 'OM'),
        ('approver_CAD', 'CAD'),
        ('approver_ED', 'ED'),
        ('approver_MD', 'MD'),
    ]


class PermissiveRoleChoiceField(forms.ChoiceField):
    def valid_value(self, value):
        text_value = str(value)
        valid_keys = [str(k) for k, _ in UnifiedWorkflowRoles.ALL_CHOICES]
        if text_value in valid_keys:
            return True
        return super().valid_value(value)


class UserCreationForm(forms.ModelForm):
    password = forms.CharField(widget=forms.PasswordInput, validators=[validate_password])
    first_name = forms.CharField(max_length=150, required=False)
    last_name = forms.CharField(max_length=150, required=False)
    phone_number = forms.CharField(max_length=30, required=False)
    photo = forms.ImageField(required=False)
    role = PermissiveRoleChoiceField(choices=UnifiedWorkflowRoles.CHOICES, initial=WorkflowRoles.FACTORY_VIEWER)
    country = forms.ModelChoiceField(
        queryset=MasterSetting.objects.filter(category='Country').order_by('name'),
        required=False,
    )
    department = forms.CharField(max_length=100, required=False)
    approval_role = forms.CharField(required=False, widget=forms.HiddenInput())
    can_receive_factory_assignments = forms.BooleanField(required=False)
    
    class Meta:
        model = User
        fields = ['username', 'email', 'first_name', 'last_name', 'password', 'is_staff', 'is_superuser']

    def clean(self):
        cleaned_data = super().clean()
        role = cleaned_data.get('role', '')
        approval_role = cleaned_data.get('approval_role', '')

        if role.startswith('approver_'):
            mapped_role = WorkflowRoles.APPROVER
            mapped_approval = role.split('_', 1)[1]
        elif role == WorkflowRoles.APPROVER:
            mapped_role = WorkflowRoles.APPROVER
            mapped_approval = approval_role or ''
        elif role in [r[0] for r in ApprovalRoles.CHOICES]:
            mapped_role = WorkflowRoles.APPROVER
            mapped_approval = role
        else:
            mapped_role = role
            mapped_approval = ''

        if mapped_role == WorkflowRoles.APPROVER and not mapped_approval:
            self.add_error('role', _('Choose PM, OM, CAD, ED, or MD for an approver.'))
        elif mapped_role == WorkflowRoles.APPROVER and UserProfile.objects.filter(
            role=WorkflowRoles.APPROVER,
            approval_role=mapped_approval,
            user__is_active=True,
        ).exists():
            self.add_error('role', _('An active %(role)s approver already exists.') % {'role': mapped_approval})

        if mapped_role == WorkflowRoles.COUNTRY_EXECUTIVE and not cleaned_data.get('country'):
            self.add_error('country', _('Country executives must be assigned to a country.'))

        if mapped_role != WorkflowRoles.FACTORY_EXECUTIVE:
            cleaned_data['can_receive_factory_assignments'] = False

        cleaned_data['mapped_role'] = mapped_role
        cleaned_data['mapped_approval_role'] = mapped_approval
        return cleaned_data

    def clean_photo(self):
        return validate_profile_photo(self.cleaned_data.get('photo'))

    def save_profile(self, user):
        profile, _ = UserProfile.objects.get_or_create(user=user)
        profile.role = self.cleaned_data.get('mapped_role', WorkflowRoles.FACTORY_VIEWER)
        profile.approval_role = self.cleaned_data.get('mapped_approval_role', '')
        profile.country = self.cleaned_data.get('country')
        profile.department = self.cleaned_data.get('department', '')
        if self.cleaned_data.get('phone_number'):
            profile.phone_number = self.cleaned_data.get('phone_number')
        if self.cleaned_data.get('photo'):
            profile.photo = self.cleaned_data.get('photo')
        profile.can_receive_factory_assignments = self.cleaned_data.get(
            'can_receive_factory_assignments',
            False,
        )
        profile.save()
        return profile


class UserWorkflowProfileForm(forms.ModelForm):
    role = PermissiveRoleChoiceField(choices=UnifiedWorkflowRoles.CHOICES, initial=WorkflowRoles.FACTORY_VIEWER)
    approval_role = forms.CharField(required=False, widget=forms.HiddenInput())

    class Meta:
        model = UserProfile
        fields = ['role', 'country', 'department', 'phone_number', 'photo', 'approval_role', 'can_receive_factory_assignments']

    def clean(self):
        cleaned_data = super().clean()
        role = cleaned_data.get('role', '')
        approval_role = cleaned_data.get('approval_role', '')

        if role.startswith('approver_'):
            mapped_role = WorkflowRoles.APPROVER
            mapped_approval = role.split('_', 1)[1]
        elif role == WorkflowRoles.APPROVER:
            mapped_role = WorkflowRoles.APPROVER
            mapped_approval = approval_role or ''
        elif role in [r[0] for r in ApprovalRoles.CHOICES]:
            mapped_role = WorkflowRoles.APPROVER
            mapped_approval = role
        else:
            mapped_role = role
            mapped_approval = ''

        if mapped_role == WorkflowRoles.APPROVER and not mapped_approval:
            self.add_error('role', _('Choose PM, OM, CAD, ED, or MD for an approver.'))
        elif mapped_role == WorkflowRoles.APPROVER and UserProfile.objects.filter(
            role=WorkflowRoles.APPROVER,
            approval_role=mapped_approval,
            user__is_active=True,
        ).exclude(pk=self.instance.pk).exists():
            self.add_error('role', _('An active %(role)s approver already exists.') % {'role': mapped_approval})

        if mapped_role == WorkflowRoles.COUNTRY_EXECUTIVE and not cleaned_data.get('country'):
            self.add_error('country', _('Country executives must be assigned to a country.'))

        if mapped_role != WorkflowRoles.FACTORY_EXECUTIVE:
            cleaned_data['can_receive_factory_assignments'] = False

        cleaned_data['mapped_role'] = mapped_role
        cleaned_data['mapped_approval_role'] = mapped_approval
        return cleaned_data

    def clean_photo(self):
        return validate_profile_photo(self.cleaned_data.get('photo'))

    def save(self, commit=True):
        instance = super().save(commit=False)
        instance.role = self.cleaned_data.get('mapped_role', instance.role)
        instance.approval_role = self.cleaned_data.get('mapped_approval_role', '')
        if commit:
            instance.save()
        return instance

class GroupCreationForm(forms.ModelForm):
    class Meta:
        model = Group
        fields = ['name', 'permissions']
        widgets = {
            'permissions': forms.CheckboxSelectMultiple(attrs={'class': 'permissions-checkbox-list'}),
        }

class AssignUserToGroupForm(forms.Form):
    user = forms.ModelChoiceField(queryset=User.objects.all())
    group = forms.ModelChoiceField(queryset=Group.objects.all())
