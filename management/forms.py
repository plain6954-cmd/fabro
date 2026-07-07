from django import forms
from .models import Complaint, ComplaintMedia, MasterSetting, Brand, Model, SubModel, YearRange, SKU
from datetime import date

class CarDetailsForm(forms.Form):
    layout_code = forms.CharField(label="Layout Code", max_length=100)
    brand_name = forms.CharField(label="Brand Name", max_length=100)
    brand_logo = forms.ImageField(label="Brand Logo", required=False)
    model_name = forms.CharField(label="Model Name", max_length=100)
    sub_model_name = forms.CharField(label="Sub-Model Name", max_length=100, required=False,)
    year_start = forms.IntegerField(label="Year Start", min_value=1900, max_value=2100)
    year_end = forms.IntegerField(label="Year End", min_value=1900, max_value=2100)
    number_of_seats = forms.IntegerField(label="Number of Seats", min_value=1)
    number_of_doors = forms.IntegerField(label="Number of Doors", min_value=1)
    
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
            'brand', 'model', 'sub_model', 'year', 'status','priority','sku', 'cad_date', 'updated_order_no',
            'complaint_description', 'batch_order', 
            'justification_from_factory', 'action_from_factory'
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
            'cad_date': forms.DateInput(attrs={'type': 'date'}),
            'updated_order_no': forms.TextInput(attrs={'class': 'form-input'}),
            'sku': forms.Select(attrs={'class': 'form-select'}),
            'complaint_description': forms.Textarea(attrs={'rows': 3, 'class': 'form-textarea'}),
            'batch_order': forms.TextInput(attrs={'class': 'form-input'}),
            'justification_from_factory': forms.Textarea(attrs={'rows': 3, 'class': 'form-textarea'}),
            'action_from_factory': forms.Textarea(attrs={'rows': 3, 'class': 'form-textarea'}),

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
            'brand', 'model', 'sub_model', 'year', 'sku', 'cad_date', 'updated_order_no',
            'complaint_description', 'batch_order', 'justification_from_factory',
            'action_from_factory'
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

# forms.py
class UploadCSVForm(forms.Form):
    csv_file = forms.FileField(label="Upload CSV File")

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
        code = self.cleaned_data.get('code')
        if self.instance.pk:
            # Editing existing SKU
            if SKU.objects.filter(code=code).exclude(pk=self.instance.pk).exists():
                raise forms.ValidationError("SKU code already exists.")
        else:
            # Creating new SKU
            if SKU.objects.filter(code=code).exists():
                raise forms.ValidationError("SKU code already exists.")
        return code

    def clean_description(self):
        description = self.cleaned_data.get('description')
        if description:
            if self.instance.pk:
                # Editing existing SKU
                if SKU.objects.filter(description=description).exclude(pk=self.instance.pk).exists():
                    raise forms.ValidationError("SKU description already exists.")
            else:
                # Creating new SKU
                if SKU.objects.filter(description=description).exists():
                    raise forms.ValidationError("SKU description already exists.")
        return description

class SKUUploadForm(forms.Form):
    csv_file = forms.FileField(label="Upload CSV File")
    def clean_csv_file(self):
        csv_file = self.cleaned_data.get('csv_file')
        if not csv_file.name.endswith('.csv'):
            raise forms.ValidationError("File must be a CSV.")
        return csv_file
    widgets = {
        'csv_file': forms.ClearableFileInput(attrs={'class': 'file-input'}),
    }

from django import forms
from django.contrib.auth.models import User, Group, Permission

class UserCreationForm(forms.ModelForm):
    password = forms.CharField(widget=forms.PasswordInput)
    
    class Meta:
        model = User
        fields = ['username', 'email', 'password', 'is_staff', 'is_superuser']

class GroupCreationForm(forms.ModelForm):
    class Meta:
        model = Group
        fields = ['name', 'permissions']

class AssignUserToGroupForm(forms.Form):
    user = forms.ModelChoiceField(queryset=User.objects.all())
    group = forms.ModelChoiceField(queryset=Group.objects.all())
