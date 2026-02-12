from django import forms
from .models import SaleOrder, SaleOrderLine
from inventory.models import Product, ProductType
from partners.models import Partner

FIELD_CSS = "w-full rounded-lg border px-3 py-2 text-sm"


class SaleOrderForm(forms.ModelForm):
    class Meta:
        model = SaleOrder
        fields = [
            "client", "delivery_date", "payment_method",
            "delivery_address", "delivery_city", "delivery_phone", "delivery_email",
            "notes"
        ]
        labels = {
            "client": "Cliente",
            "delivery_date": "Fecha de entrega",
            "payment_method": "Método de pago",
            "delivery_address": "Dirección de entrega",
            "delivery_city": "Ciudad",
            "delivery_phone": "Teléfono",
            "delivery_email": "Email",
            "notes": "Notas",
        }
        widgets = {
            "client": forms.Select(attrs={"class": FIELD_CSS}),
            "delivery_date": forms.DateInput(
                attrs={"class": FIELD_CSS, "type": "date"},
            ),
            "payment_method": forms.TextInput(attrs={
                "class": FIELD_CSS,
                "placeholder": "Ej: Transferencia, Efectivo, Crédito 30 días",
            }),
            "delivery_address": forms.TextInput(attrs={"class": FIELD_CSS}),
            "delivery_city": forms.TextInput(attrs={"class": FIELD_CSS}),
            "delivery_phone": forms.TextInput(attrs={"class": FIELD_CSS}),
            "delivery_email": forms.EmailInput(attrs={"class": FIELD_CSS}),
            "notes": forms.Textarea(attrs={"class": FIELD_CSS, "rows": 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["client"].queryset = Partner.objects.filter(
            is_customer=True, is_active=True,
        )


class SaleOrderLineForm(forms.ModelForm):
    class Meta:
        model = SaleOrderLine
        fields = ["product", "quantity", "unit_price"]
        labels = {
            "product": "Producto",
            "quantity": "Cantidad",
            "unit_price": "Precio unitario",
        }
        widgets = {
            "product": forms.Select(attrs={"class": FIELD_CSS}),
            "quantity": forms.NumberInput(attrs={
                "class": "w-full rounded-lg border px-3 py-2 text-sm text-right",
                "step": "0.01", "min": "0.01",
            }),
            "unit_price": forms.NumberInput(attrs={
                "class": "w-full rounded-lg border px-3 py-2 text-sm text-right",
                "step": "0.01", "min": "0",
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["product"].queryset = Product.objects.filter(
            is_active=True, product_type=ProductType.FG,
        )
