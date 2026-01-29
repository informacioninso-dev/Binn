from django import forms
from .models import SaleOrder, SaleOrderLine
from inventory.models import Product


class SaleOrderForm(forms.ModelForm):
    class Meta:
        model = SaleOrder
        fields = ["client", "delivery_date", "payment_method", "notes"]
        widgets = {
            "client": forms.Select(attrs={"class": "w-full rounded-lg border px-3 py-2"}),
            "delivery_date": forms.DateInput(attrs={"class": "w-full rounded-lg border px-3 py-2"}),
            "payment_method": forms.Select(attrs={"class": "w-full rounded-lg border px-3 py-2"}),
            "notes": forms.Textarea(attrs={"class": "w-full rounded-lg border px-3 py-2", "rows": 3}),
        }

class SaleOrderLineForm(forms.ModelForm):
    class Meta:
        model = SaleOrderLine
        fields = ['product', 'quantity', 'unit_price']
        widgets = {
            "product": forms.Select(attrs={"class": "w-full rounded-lg border px-3 py-2"}),
            "quantity": forms.NumberInput(attrs={"class": "w-full rounded-lg border px-3 py-2"}),
            "unit_price": forms.NumberInput(attrs={"class": "w-full rounded-lg border px-3 py-2"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["product"].queryset = Product.objects.all()