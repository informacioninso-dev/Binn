from django import forms
from .models import TaxScheme, Location, Warehouse, WarehouseType, Unit, UnitCategory


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
