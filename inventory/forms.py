from django import forms
from .models import Product

class ProductForm(forms.ModelForm):
    class Meta:
        model = Product
        fields = [
            "code", "code_2", "name", "unit_price", "tax_rate", "unit_cost",
            "provider", "category", "brand", "unit", "is_active"
        ]
        widgets = {
            "code": forms.TextInput(attrs={"class": "w-full rounded-lg border px-3 py-2"}),
            "name": forms.TextInput(attrs={"class": "w-full rounded-lg border px-3 py-2"}),
            "unit_price": forms.NumberInput(attrs={"class": "w-full rounded-lg border px-3 py-2"}),
            "tax_rate": forms.NumberInput(attrs={"class": "w-full rounded-lg border px-3 py-2"}),
            "unit_cost": forms.NumberInput(attrs={"class": "w-full rounded-lg border px-3 py-2"}),
            "provider": forms.TextInput(attrs={"class": "w-full rounded-lg border px-3 py-2"}),
            "category": forms.TextInput(attrs={"class": "w-full rounded-lg border px-3 py-2"}),
            "brand": forms.TextInput(attrs={"class": "w-full rounded-lg border px-3 py-2"}),
            "unit": forms.TextInput(attrs={"class": "w-full rounded-lg border px-3 py-2"}),
            "is_active": forms.CheckboxInput(attrs={"class": "rounded"}),
        }
