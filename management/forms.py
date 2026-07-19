from django import forms
from .models import (
    ApprovalStages,
    ApprovalRoles,
    Brand,
    Complaint,
    ComplaintMedia,
    ComplaintTypes,
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

MAX_CSV_UPLOAD_SIZE = 5 * 1024 * 1024
MAX_BRAND_LOGO_SIZE = 2 * 1024 * 1024


def validate_csv_upload(csv_file):
    if not csv_file.name.lower().endswith('.csv'):
        raise forms.ValidationError('File must be a CSV.')
    if csv_file.size > MAX_CSV_UPLOAD_SIZE:
        raise forms.ValidationError('CSV file must be 5 MB or smaller.')
    return csv_file

class CarDetailsForm(forms.Form):
    layout_code = forms.CharField(label="Layout Code", max_length=100)
    brand_name = forms.CharField(label="Brand Name", max_length=100)
    brand_logo = forms.ImageField(label="Brand Logo", required=False)
    model_name = forms.CharField(label="Model Name", max_length=100)
    sub_model_name = forms.CharField(label="Sub-Model Name", max_length=100, required=False,)
    year_start = forms.IntegerField(label="Year Start", min_value=1900, max_value=2100)
    year_end = forms.IntegerField(label="Year End", min_value=1900, max_value=2100)
    number_of_seats = forms.IntegerField(label="Number of Seats", min_value=1, max_value=100)
    number_of_doors = forms.IntegerField(label="Number of Doors", min_value=1, max_value=20)
    
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
    }

    def clean(self):
        cleaned_data = super().clean()
        for field in ['brand_name', 'model_name', 'sub_model_name', 'layout_code']:
            if field in cleaned_data and isinstance(cleaned_data[field], str):
                cleaned_data[field] = cleaned_data[field].strip()
        year_start = cleaned_data.get("year_start")
        year_end = cleaned_data.get("year_end")
        
        if year_start and year_end and year_start > year_end:
            self.add_error("year_end", "Year End must be greater than or equal to Year Start.")
        
        return cleaned_data

    def clean_brand_logo(self):
        logo = self.cleaned_data.get('brand_logo')
        if not logo:
            return logo
        if logo.size > MAX_BRAND_LOGO_SIZE:
            raise forms.ValidationError('Brand logo must be 2 MB or smaller.')
        content_type = (getattr(logo, 'content_type', '') or '').lower()
        if content_type not in {'image/jpeg', 'image/png', 'image/webp', 'image/gif'}:
            raise forms.ValidationError('Brand logo must be a JPG, PNG, WEBP, or GIF image.')
        return logo

class MasterSettingForm(forms.ModelForm):
    class Meta:
        model = MasterSetting
        fields = ['category', 'name']
        widgets = {
            'category': forms.Select(attrs={'class': 'form-select'}),
            'name': forms.TextInput(attrs={'class': 'form-input'}),
            }

class ComplaintForm(forms.ModelForm):
    class Meta:
        model = Complaint
        fields = [
            'date', 'channel', 'country', 'person','case_sub_category', 'series', 'material', 
            'brand', 'model', 'sub_model', 'year', 'status','priority','sku', 'updated_order_no',
            'complaint_description', 'batch_order'
        ]
        widgets = {
            'date': forms.DateInput(attrs={'type': 'date'}),
            'channel': forms.Select(attrs={'class': 'form-select'}),
            'country': forms.Select(attrs={'class': 'form-select'}),
            'person': forms.Select(attrs={'class': 'form-select'}),
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

    def __init__(self, *args, **kwargs):
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
        self.fields['sku'].label_from_instance = lambda sku: f"{sku.code} - {sku.description}" if sku.description else sku.code

        optional_fields = [
            'channel', 'country', 'person', 'case_sub_category', 'series', 'material',
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
                'placeholder': 'Write the real reason behind the defect after reviewing photos/videos.'
            }),
            'factory_action_plan': forms.Textarea(attrs={
                'rows': 5,
                'class': 'form-textarea',
                'placeholder': 'Write the proposed action plan from the factory.'
            }),
            'factory_priority': forms.Select(attrs={'class': 'form-select'}),
        }
        labels = {
            'factory_reason': 'Real reason behind defect',
            'factory_action_plan': 'Factory action plan',
            'factory_priority': 'Factory priority',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['factory_priority'].choices = [('', 'Select Priority')] + list(FactoryPriorities.CHOICES)
        for field in self.fields.values():
            field.required = True


class ApprovalDecisionForm(forms.Form):
    decision = forms.ChoiceField(
        label='Your decision',
        choices=[
            (DecisionStatuses.APPROVED, 'Approve'),
            (DecisionStatuses.REJECTED, 'Reject'),
        ],
        widget=forms.RadioSelect(attrs={'class': 'decision-radio'}),
    )
    comment = forms.CharField(
        label='Review comment',
        required=False,
        max_length=2000,
        widget=forms.Textarea(attrs={
            'rows': 5,
            'class': 'form-textarea',
            'placeholder': 'Optional for approval. Required when rejecting.',
        }),
    )

    def __init__(self, *args, **kwargs):
        approval_stage = kwargs.pop('approval_stage', ApprovalStages.INITIAL)
        super().__init__(*args, **kwargs)
        if approval_stage == ApprovalStages.RECONSIDERATION:
            self.fields['decision'].label = 'Reconsideration decision'
            self.fields['decision'].choices = [
                (DecisionStatuses.APPROVED, 'Proceed with Action Plan'),
                (DecisionStatuses.REJECTED, 'Return to Factory Executive for Rework'),
            ]
            self.fields['comment'].widget.attrs['placeholder'] = (
                'Optional when proceeding. Required when returning for rework.'
            )

    def clean(self):
        cleaned_data = super().clean()
        decision = cleaned_data.get('decision')
        comment = (cleaned_data.get('comment') or '').strip()
        cleaned_data['comment'] = comment
        if decision == DecisionStatuses.REJECTED and not comment:
            self.add_error('comment', 'Explain what must be corrected when rejecting.')
        return cleaned_data


class FinalComplaintUpdateForm(forms.Form):
    cad_date = forms.DateField(
        label='CAD Updated Date',
        widget=forms.DateInput(attrs={'type': 'date', 'class': 'form-input'}),
    )
    production_updates_container = forms.CharField(
        label='New Production Container Number',
        max_length=100,
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-input',
            'placeholder': 'Enter the new production container number',
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
            raise forms.ValidationError('CAD Updated Date cannot be in the future.')
        return cad_date

# forms.py
class UploadCSVForm(forms.Form):
    csv_file = forms.FileField(label="Upload CSV File")

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
                raise forms.ValidationError("SKU code already exists.")
        else:
            # Creating new SKU
            if SKU.objects.filter(code__iexact=code).exists():
                raise forms.ValidationError("SKU code already exists.")
        return code

    def clean_description(self):
        description = self.cleaned_data.get('description')
        return description.strip() if description else description

class SKUUploadForm(forms.Form):
    csv_file = forms.FileField(label="Upload CSV File")
    def clean_csv_file(self):
        return validate_csv_upload(self.cleaned_data['csv_file'])
    widgets = {
        'csv_file': forms.ClearableFileInput(attrs={'class': 'file-input'}),
    }

from django import forms
from django.contrib.auth.models import User, Group, Permission

class UserCreationForm(forms.ModelForm):
    password = forms.CharField(widget=forms.PasswordInput, validators=[validate_password])
    role = forms.ChoiceField(choices=WorkflowRoles.CHOICES, initial=WorkflowRoles.FACTORY_VIEWER)
    country = forms.ModelChoiceField(
        queryset=MasterSetting.objects.filter(category='Country').order_by('name'),
        required=False,
    )
    department = forms.CharField(max_length=100, required=False)
    approval_role = forms.ChoiceField(
        choices=[('', 'Not an approver')] + list(ApprovalRoles.CHOICES),
        required=False,
    )
    can_receive_factory_assignments = forms.BooleanField(required=False)
    
    class Meta:
        model = User
        fields = ['username', 'email', 'password', 'is_staff', 'is_superuser']

    def clean(self):
        cleaned_data = super().clean()
        role = cleaned_data.get('role')
        approval_role = cleaned_data.get('approval_role')
        if role == WorkflowRoles.APPROVER and not approval_role:
            self.add_error('approval_role', 'Choose PM, OM, CAD, ED, or MD for an approver.')
        elif role == WorkflowRoles.APPROVER and UserProfile.objects.filter(
            role=WorkflowRoles.APPROVER,
            approval_role=approval_role,
            user__is_active=True,
        ).exists():
            self.add_error('approval_role', f'An active {approval_role} approver already exists.')
        if role == WorkflowRoles.COUNTRY_EXECUTIVE and not cleaned_data.get('country'):
            self.add_error('country', 'Country executives must be assigned to a country.')
        if role != WorkflowRoles.APPROVER:
            cleaned_data['approval_role'] = ''
        if role != WorkflowRoles.FACTORY_EXECUTIVE:
            cleaned_data['can_receive_factory_assignments'] = False
        return cleaned_data

    def save_profile(self, user):
        profile, _ = UserProfile.objects.get_or_create(user=user)
        profile.role = self.cleaned_data['role']
        profile.country = self.cleaned_data.get('country')
        profile.department = self.cleaned_data.get('department', '')
        profile.approval_role = self.cleaned_data.get('approval_role', '')
        profile.can_receive_factory_assignments = self.cleaned_data.get(
            'can_receive_factory_assignments',
            False,
        )
        profile.save()
        return profile


class UserWorkflowProfileForm(forms.ModelForm):
    approval_role = forms.ChoiceField(
        choices=[('', 'Not an approver')] + list(ApprovalRoles.CHOICES),
        required=False,
    )

    class Meta:
        model = UserProfile
        fields = ['role', 'country', 'department', 'approval_role', 'can_receive_factory_assignments']

    def clean(self):
        cleaned_data = super().clean()
        role = cleaned_data.get('role')
        approval_role = cleaned_data.get('approval_role')
        if role == WorkflowRoles.APPROVER and not approval_role:
            self.add_error('approval_role', 'Choose PM, OM, CAD, ED, or MD for an approver.')
        elif role == WorkflowRoles.APPROVER and UserProfile.objects.filter(
            role=WorkflowRoles.APPROVER,
            approval_role=approval_role,
            user__is_active=True,
        ).exclude(pk=self.instance.pk).exists():
            self.add_error('approval_role', f'An active {approval_role} approver already exists.')
        if role == WorkflowRoles.COUNTRY_EXECUTIVE and not cleaned_data.get('country'):
            self.add_error('country', 'Country executives must be assigned to a country.')
        if role != WorkflowRoles.APPROVER:
            cleaned_data['approval_role'] = ''
        if role != WorkflowRoles.FACTORY_EXECUTIVE:
            cleaned_data['can_receive_factory_assignments'] = False
        return cleaned_data

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
