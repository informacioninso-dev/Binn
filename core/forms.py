from django import forms
from .models import TaxScheme, Location, Warehouse, WarehouseType, Unit, UnitCategory, CompanyConfig


class TaxSchemeForm(forms.ModelForm):
    class Meta:
        model = TaxScheme
        fields = ['code', 'name', 'rate', 'is_active', 'applies_sales', 'applies_purchases']
        widgets = {
            'code': forms.TextInput(attrs={'class': 'w-full rounded-lg border px-3 py-2'}),
            'name': forms.TextInput(attrs={'class': 'w-full rounded-lg border px-3 py-2'}),
            'rate': forms.NumberInput(attrs={'class': 'w-full rounded-lg border px-3 py-2'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'rounded'}),
            'applies_sales': forms.CheckboxInput(attrs={'class': 'rounded'}),
            'applies_purchases': forms.CheckboxInput(attrs={'class': 'rounded'})
        }


class UnitForm(forms.ModelForm):
    class Meta:
        model = Unit
        fields = ['code', 'name', 'category', 'factor_to_base', 'is_active']
        widgets = {
            'code': forms.TextInput(attrs={'class': 'w-full rounded-lg border px-3 py-2'}),
            'name': forms.TextInput(attrs={'class': 'w-full rounded-lg border px-3 py-2'}),
            'category': forms.Select(attrs={'class': 'w-full rounded-lg border px-3 py-2'}),
            'factor_to_base': forms.NumberInput(attrs={'class': 'w-full rounded-lg border px-3 py-2'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'rounded'})
        }


class WarehouseForm(forms.ModelForm):
    class Meta:
        model = Warehouse
        fields = ['code', 'name', 'type', 'is_active', 'is_default_quarantine', 'is_default_for_raw', 'is_default_fg_released']
        widgets = {
            'code': forms.TextInput(attrs={'class': 'w-full rounded-lg border px-3 py-2'}),
            'name': forms.TextInput(attrs={'class': 'w-full rounded-lg border px-3 py-2'}),
            'type': forms.Select(choices=WarehouseType.choices, attrs={'class': 'w-full rounded-lg border px-3 py-2'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'rounded'}),
            'is_default_quarantine': forms.CheckboxInput(attrs={'class': 'rounded'}),
            'is_default_for_raw': forms.CheckboxInput(attrs={'class': 'rounded'}),
            'is_default_fg_released': forms.CheckboxInput(attrs={'class': 'rounded'})
        }



class LocationForm(forms.ModelForm):
    class Meta:
        model = Location
        fields = ['warehouse', 'code', 'name', 'description', 'row', 'rack', 'level', 'is_active']
        widgets = {
            'warehouse': forms.Select(attrs={'class': 'w-full rounded-lg border px-3 py-2'}),
            'code': forms.TextInput(attrs={'class': 'w-full rounded-lg border px-3 py-2'}),
            'name': forms.TextInput(attrs={'class': 'w-full rounded-lg border px-3 py-2'}),
            'description': forms.TextInput(attrs={'class': 'w-full rounded-lg border px-3 py-2'}),
            'row': forms.TextInput(attrs={'class': 'w-full rounded-lg border px-3 py-2'}),
            'rack': forms.TextInput(attrs={'class': 'w-full rounded-lg border px-3 py-2'}),
            'level': forms.TextInput(attrs={'class': 'w-full rounded-lg border px-3 py-2'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'rounded'})
        }


_tw = 'w-full rounded-lg border px-3 py-2'


class CompanyConfigForm(forms.ModelForm):
    class Meta:
        model = CompanyConfig
        fields = [
            'ruc', 'legal_name', 'trade_name', 'address',
            'establishment_code', 'emission_point',
            'special_taxpayer', 'obligated_accounting',
            'environment', 'emission_type',
            'certificate_file', 'certificate_password',
            'logo',
        ]
        widgets = {
            'ruc': forms.TextInput(attrs={'class': _tw, 'placeholder': '1790012345001'}),
            'legal_name': forms.TextInput(attrs={'class': _tw}),
            'trade_name': forms.TextInput(attrs={'class': _tw}),
            'address': forms.TextInput(attrs={'class': _tw}),
            'establishment_code': forms.TextInput(attrs={'class': _tw, 'maxlength': 3}),
            'emission_point': forms.TextInput(attrs={'class': _tw, 'maxlength': 3}),
            'special_taxpayer': forms.TextInput(attrs={'class': _tw}),
            'obligated_accounting': forms.CheckboxInput(attrs={'class': 'rounded'}),
            'environment': forms.Select(attrs={'class': _tw}),
            'emission_type': forms.TextInput(attrs={'class': _tw, 'readonly': True}),
            'certificate_file': forms.ClearableFileInput(attrs={'class': _tw}),
            'certificate_password': forms.PasswordInput(attrs={'class': _tw, 'render_value': True}),
            'logo': forms.ClearableFileInput(attrs={'class': _tw}),
        }
