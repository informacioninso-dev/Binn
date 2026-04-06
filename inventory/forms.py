from decimal import Decimal

from django import forms

from .models import InventoryItem, PurchaseOrder, StockMovement, Supplier


_INPUT = {"class": "w-full rounded-lg border px-3 py-2"}


class SupplierForm(forms.ModelForm):
    class Meta:
        model = Supplier
        fields = ["name", "contact_name", "phone", "email", "notes", "is_active"]
        widgets = {
            "name": forms.TextInput(attrs=_INPUT),
            "contact_name": forms.TextInput(attrs=_INPUT),
            "phone": forms.TextInput(attrs=_INPUT),
            "email": forms.EmailInput(attrs=_INPUT),
            "notes": forms.Textarea(attrs={**_INPUT, "rows": 3}),
            "is_active": forms.CheckboxInput(attrs={"class": "h-4 w-4 rounded border-gray-300"}),
        }


class InventoryItemForm(forms.ModelForm):
    class Meta:
        model = InventoryItem
        fields = [
            "sku",
            "name",
            "category",
            "unit",
            "supplier",
            "stock_on_hand",
            "reorder_point",
            "unit_cost",
            "sale_price",
            "is_active",
        ]
        widgets = {
            "sku": forms.TextInput(attrs=_INPUT),
            "name": forms.TextInput(attrs=_INPUT),
            "category": forms.TextInput(attrs=_INPUT),
            "unit": forms.TextInput(attrs=_INPUT),
            "supplier": forms.Select(attrs=_INPUT),
            "stock_on_hand": forms.NumberInput(attrs={**_INPUT, "step": "0.01"}),
            "reorder_point": forms.NumberInput(attrs={**_INPUT, "step": "0.01"}),
            "unit_cost": forms.NumberInput(attrs={**_INPUT, "step": "0.01"}),
            "sale_price": forms.NumberInput(attrs={**_INPUT, "step": "0.01"}),
            "is_active": forms.CheckboxInput(attrs={"class": "h-4 w-4 rounded border-gray-300"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["supplier"].required = False
        self.fields["supplier"].queryset = self.fields["supplier"].queryset.filter(is_active=True).order_by("name")


class PurchaseOrderForm(forms.ModelForm):
    class Meta:
        model = PurchaseOrder
        fields = ["supplier", "ordered_at", "expected_on", "status", "reference", "total_amount", "notes"]
        widgets = {
            "supplier": forms.Select(attrs=_INPUT),
            "ordered_at": forms.DateTimeInput(attrs={**_INPUT, "type": "datetime-local"}, format="%Y-%m-%dT%H:%M"),
            "expected_on": forms.DateInput(attrs={**_INPUT, "type": "date"}),
            "status": forms.Select(attrs=_INPUT),
            "reference": forms.TextInput(attrs=_INPUT),
            "total_amount": forms.NumberInput(attrs={**_INPUT, "step": "0.01"}),
            "notes": forms.Textarea(attrs={**_INPUT, "rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["ordered_at"].input_formats = ["%Y-%m-%dT%H:%M"]
        self.fields["supplier"].queryset = self.fields["supplier"].queryset.filter(is_active=True).order_by("name")


class StockMovementForm(forms.ModelForm):
    class Meta:
        model = StockMovement
        fields = ["item", "purchase_order", "movement_type", "moved_at", "quantity", "unit_cost", "reference", "notes"]
        widgets = {
            "item": forms.Select(attrs=_INPUT),
            "purchase_order": forms.Select(attrs=_INPUT),
            "movement_type": forms.Select(attrs=_INPUT),
            "moved_at": forms.DateTimeInput(attrs={**_INPUT, "type": "datetime-local"}, format="%Y-%m-%dT%H:%M"),
            "quantity": forms.NumberInput(attrs={**_INPUT, "step": "0.01"}),
            "unit_cost": forms.NumberInput(attrs={**_INPUT, "step": "0.01"}),
            "reference": forms.TextInput(attrs=_INPUT),
            "notes": forms.Textarea(attrs={**_INPUT, "rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["moved_at"].input_formats = ["%Y-%m-%dT%H:%M"]
        self.fields["purchase_order"].required = False
        self.fields["item"].queryset = self.fields["item"].queryset.filter(is_active=True).order_by("name")
        self.fields["purchase_order"].queryset = self.fields["purchase_order"].queryset.order_by("-ordered_at", "-id")

    def clean_quantity(self):
        quantity = self.cleaned_data["quantity"]
        if quantity <= Decimal("0.00"):
            raise forms.ValidationError("La cantidad debe ser mayor a cero.")
        return quantity
