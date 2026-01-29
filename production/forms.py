# production/forms.py
from django import forms
from django.forms import inlineformset_factory
from django.utils import timezone
from inventory.models import Lot as RawLot

from .models import (
    BillOfMaterial,
    BillOfMaterialLine,
    ProductionOrder,
    ProductRoute,
    ProductionOperation,        
    ProductionOperationStatus,
    ProductionPlanRawLot,  
    ProductionPlan, 
)
from inventory.models import Product, ProductType
from .models import ProductionOperation, ProductionOperationStatus

class BillOfMaterialForm(forms.ModelForm):
    class Meta:
        model = BillOfMaterial
        fields = ["product_finished", "revision", "description", "is_active"]
        widgets = {
            "product_finished": forms.Select(attrs={"class": "w-full rounded-lg border px-3 py-2"}),
            "revision": forms.TextInput(attrs={"class": "w-full rounded-lg border px-3 py-2"}),
            "description": forms.Textarea(attrs={"class": "w-full rounded-lg border px-3 py-2", "rows": 3}),
            "is_active": forms.CheckboxInput(attrs={"class": "rounded"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Solo productos terminados activos
        self.fields["product_finished"].queryset = Product.objects.filter(
            product_type=ProductType.FG,
            is_active=True
        ).order_by("name")


class BillOfMaterialLineForm(forms.ModelForm):
    class Meta:
        model = BillOfMaterialLine
        fields = ["component", "quantity", "scrap_rate", "sequence"]
        widgets = {
            "component": forms.Select(attrs={"class": "w-full rounded-lg border px-3 py-2"}),
            "quantity": forms.NumberInput(attrs={"class": "w-full rounded-lg border px-3 py-2"}),
            "scrap_rate": forms.NumberInput(attrs={"class": "w-full rounded-lg border px-3 py-2"}),
            "sequence": forms.NumberInput(attrs={"class": "w-full rounded-lg border px-3 py-2"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Componentes: normalmente RAW, PACK, SEMI (excluimos SERVICE)
        self.fields["component"].queryset = Product.objects.filter(
            is_active=True
        ).exclude(product_type=ProductType.SERVICE).order_by("name")


BillOfMaterialLineFormSet = inlineformset_factory(
    BillOfMaterial,
    BillOfMaterialLine,
    form=BillOfMaterialLineForm,
    extra=0,
    can_delete=True,
)


class ProductionOrderForm(forms.ModelForm):
    class Meta:
        model = ProductionOrder
        # No exponemos code, quantity_produced, finished_lot, status
        fields = [
            "product",
            "quantity_planned",
            "route",
            "bom",
            "start_date",
            "end_date",
            "notes",
        ]
        labels = {
            "product": "Producto a fabricar",
            "quantity_planned": "Cantidad planificada",
            "route": "Ruta de producción",
            "bom": "Plano de fabricación (BOM)",
            "start_date": "Fecha de inicio",
            "end_date": "Fecha de fin",
            "notes": "Notas / comentarios",
        }
        widgets = {
            "product": forms.Select(
                attrs={"class": "w-full rounded-lg border px-3 py-2"}
            ),
            "quantity_planned": forms.NumberInput(
                attrs={"class": "w-full rounded-lg border px-3 py-2", "step": "0.01"}
            ),
            "route": forms.Select(
                attrs={"class": "w-full rounded-lg border px-3 py-2"}
            ),
            "bom": forms.Select(
                attrs={"class": "w-full rounded-lg border px-3 py-2"}
            ),
            "start_date": forms.DateInput(
                attrs={"class": "w-full rounded-lg border px-3 py-2", "type": "date"}
            ),
            "end_date": forms.DateInput(
                attrs={"class": "w-full rounded-lg border px-3 py-2", "type": "date"}
            ),
            "notes": forms.Textarea(
                attrs={"class": "w-full rounded-lg border px-3 py-2", "rows": 3}
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Solo productos terminados activos
        self.fields["product"].queryset = Product.objects.filter(
            product_type=ProductType.FG,
            is_active=True,
        ).order_by("name")

        # Solo rutas activas
        self.fields["route"].queryset = ProductRoute.objects.filter(
            is_active=True
        ).order_by("product__name", "name")

        # Solo BOM activos
        self.fields["bom"].queryset = BillOfMaterial.objects.filter(
            is_active=True
        ).select_related("product_finished").order_by("product_finished__name", "revision")

        # Si quieres permitir crear en borrador sin ruta/BOM al inicio:
        # self.fields["route"].required = False
        # self.fields["bom"].required = False

        # Default start_date = hoy si está vacío
        if not self.instance.pk and not self.initial.get("start_date"):
            self.initial["start_date"] = timezone.localdate()

    def save(self, commit=True) -> ProductionOrder:
        """
        Genera el código de la OP si no existe:
        OP-2026-0001, OP-2026-0002, ...
        """
        obj: ProductionOrder = super().save(commit=False)

        if not obj.code:
            year = timezone.localdate().year
            prefix = f"OP-{year}-"

            last = (
                ProductionOrder.objects
                .filter(code__startswith=prefix)
                .order_by("-code")
                .first()
            )
            last_seq = 0
            if last:
                try:
                    last_seq = int(last.code.split("-")[-1])
                except (ValueError, IndexError):
                    last_seq = 0

            obj.code = f"{prefix}{last_seq + 1:04d}"

        if commit:
            obj.save()
        return obj


class ProductionOperationForm(forms.ModelForm):
    class Meta:
        model = ProductionOperation
        fields = [
            "status",
            "started_at",
            "finished_at",
            "quantity_input",
            "quantity_output",
            "notes",
        ]
        labels = {
            "status": "Estado de la operación",
            "started_at": "Fecha/hora de inicio",
            "finished_at": "Fecha/hora de fin",
            "quantity_input": "Cantidad de entrada",
            "quantity_output": "Cantidad de salida",
            "notes": "Notas / comentarios",
        }
        widgets = {
            "status": forms.Select(
                attrs={"class": "w-full rounded-lg border px-3 py-2"}
            ),
            "started_at": forms.DateTimeInput(
                attrs={
                    "class": "w-full rounded-lg border px-3 py-2",
                    "type": "datetime-local",
                }
            ),
            "finished_at": forms.DateTimeInput(
                attrs={
                    "class": "w-full rounded-lg border px-3 py-2",
                    "type": "datetime-local",
                }
            ),
            "quantity_input": forms.NumberInput(
                attrs={"class": "w-full rounded-lg border px-3 py-2"}
            ),
            "quantity_output": forms.NumberInput(
                attrs={"class": "w-full rounded-lg border px-3 py-2"}
            ),
            "notes": forms.Textarea(
                attrs={"class": "w-full rounded-lg border px-3 py-2", "rows": 3}
            ),
        }


    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Estados válidos directamente desde el modelo
        self.fields["status"].choices = ProductionOperationStatus.choices


class ProductionPlanRawLotForm(forms.ModelForm):
    class Meta:
        model = ProductionPlanRawLot
        fields = ["lot", "quantity_planned"]
        widgets = {
            "lot": forms.Select(
                attrs={"class": "w-full rounded-lg border px-3 py-2"}
            ),
            "quantity_planned": forms.NumberInput(
                attrs={"class": "w-full rounded-lg border px-3 py-2"}
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        from inventory.models import Lot, ProductType

        self.fields["lot"].queryset = (
            Lot.objects
            .filter(
                product__product_type=ProductType.RAW,
                quantity_current__gt=0,
            )
            .order_by("expiration_date", "internal_lot")  # 👈 FEFO
        )
class ProductionPlanForm(forms.ModelForm):
    class Meta:
        model = ProductionPlan
        fields = [
            "product",
            "lot_code",
            "manufacturing_date",
            "quantity_planned",
            "status",
            "notes",
        ]
        labels = {
            "product": "Producto (SKU)",
            "lot_code": "Código de lote de producción",
            "manufacturing_date": "Fecha de fabricación",
            "quantity_planned": "Cantidad total planificada",
            "status": "Estado del plan",
            "notes": "Notas / comentarios",
        }
        widgets = {
            "product": forms.Select(
                attrs={"class": "w-full rounded-lg border px-3 py-2"}
            ),
            "lot_code": forms.TextInput(
                attrs={"class": "w-full rounded-lg border px-3 py-2"}
            ),
            "manufacturing_date": forms.DateInput(
                attrs={
                    "class": "w-full rounded-lg border px-3 py-2",
                    "type": "date",
                }
            ),
            "quantity_planned": forms.NumberInput(
                attrs={"class": "w-full rounded-lg border px-3 py-2"}
            ),
            "status": forms.Select(
                attrs={"class": "w-full rounded-lg border px-3 py-2"}
            ),
            "notes": forms.Textarea(
                attrs={"class": "w-full rounded-lg border px-3 py-2", "rows": 3}
            ),
        }



    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Solo productos FG activos
        self.fields["product"].queryset = Product.objects.filter(
            product_type=ProductType.FG,
            is_active=True,
        ).order_by("name")

    def clean(self):
        """
        Si el usuario deja el lot_code vacío pero tenemos:
        - product con prefijo
        - manufacturing_date
        → sugerimos lote = prefijo + MMYYYY
        """
        cleaned = super().clean()
        lot_code = cleaned.get("lot_code")
        product = cleaned.get("product")
        mfg_date = cleaned.get("manufacturing_date")

        if not lot_code and product and mfg_date:
            # Ajusta el nombre del campo si no se llama lot_prefix
            prefix = getattr(product, "lot_prefix", "") or ""
            if prefix:
                # Ejemplo: CAP + 01 + 2026 → CAP012026
                auto_code = f"{prefix}{mfg_date.strftime('%m%Y')}"
                cleaned["lot_code"] = auto_code

        return cleaned
