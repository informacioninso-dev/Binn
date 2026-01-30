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
    ProductRouteStep,
    WorkCenter,
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
        self.fields["product_finished"].label = "Producto terminado"
        self.fields["revision"].label = "Revisión"
        self.fields["description"].label = "Descripción"
        self.fields["is_active"].label = "Activo"


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
        # Componentes: solo materia prima (RAW) y semielaborados (SEMI)
        self.fields["component"].queryset = Product.objects.filter(
            product_type__in=[ProductType.RAW, ProductType.SEMI],
            is_active=True,
        ).order_by("name")
        # Mostrar solo el nombre (el código se identifica aparte)
        self.fields["component"].label_from_instance = lambda obj: f"{obj.code} - {obj.name}"
        # Labels en español
        self.fields["component"].label = "Componente"
        self.fields["quantity"].label = "Cant. por unidad PT"
        self.fields["scrap_rate"].label = "Merma estimada (%)"
        self.fields["sequence"].label = "Secuencia"


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
                format="%Y-%m-%d",
                attrs={"class": "w-full rounded-lg border px-3 py-2", "type": "date"}
            ),
            "end_date": forms.DateInput(
                format="%Y-%m-%d",
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

        # Ruta obligatoria, filtrada por producto seleccionado
        self.fields["route"].required = True
        product = self.initial.get("product") or (self.instance.product_id if self.instance.pk else None)
        if product:
            pid = product.pk if hasattr(product, "pk") else product
            self.fields["route"].queryset = ProductRoute.objects.filter(
                product_id=pid, is_active=True
            ).order_by("name")
        else:
            self.fields["route"].queryset = ProductRoute.objects.none()

        # Solo BOM activos
        self.fields["bom"].queryset = BillOfMaterial.objects.filter(
            is_active=True
        ).select_related("product_finished").order_by("product_finished__name", "revision")

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
            "operator",
            "started_at",
            "finished_at",
            "quantity_input",
            "quantity_output",
            "notes",
        ]
        labels = {
            "status": "Estado de la operación",
            "operator": "Operario responsable",
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
            "operator": forms.Select(
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

        self.fields["status"].choices = ProductionOperationStatus.choices

        from django.contrib.auth import get_user_model
        User = get_user_model()
        self.fields["operator"].queryset = User.objects.filter(is_active=True).order_by("first_name", "username")
        self.fields["operator"].required = False


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


# ─── Estaciones de trabajo ────────────────────────────────────

class WorkCenterForm(forms.ModelForm):
    class Meta:
        model = WorkCenter
        fields = [
            "code", "name", "description", "default_warehouse",
            "capacity_per_hour", "num_machines", "num_operators",
            "efficiency_factor", "setup_time_min",
            "hours_per_shift", "shifts_per_day",
            "is_active",
        ]
        labels = {
            "code": "Código",
            "name": "Nombre",
            "description": "Descripción",
            "default_warehouse": "Almacén por defecto",
            "capacity_per_hour": "Capacidad por hora (unid/h)",
            "num_machines": "Máquinas / puestos",
            "num_operators": "Operarios disponibles",
            "efficiency_factor": "Factor de eficiencia",
            "setup_time_min": "Tiempo de setup (min)",
            "hours_per_shift": "Horas por turno",
            "shifts_per_day": "Turnos por día",
            "is_active": "Activo",
        }
        _input = "w-full rounded-lg border px-3 py-2"
        widgets = {
            "code": forms.TextInput(attrs={"class": _input}),
            "name": forms.TextInput(attrs={"class": _input}),
            "description": forms.TextInput(attrs={"class": _input}),
            "default_warehouse": forms.Select(attrs={"class": _input}),
            "capacity_per_hour": forms.NumberInput(attrs={"class": _input, "step": "0.01"}),
            "num_machines": forms.NumberInput(attrs={"class": _input, "min": "1"}),
            "num_operators": forms.NumberInput(attrs={"class": _input, "min": "1"}),
            "efficiency_factor": forms.NumberInput(attrs={"class": _input, "step": "0.01", "min": "0", "max": "1"}),
            "setup_time_min": forms.NumberInput(attrs={"class": _input, "min": "0"}),
            "hours_per_shift": forms.NumberInput(attrs={"class": _input, "step": "0.5", "min": "0.5"}),
            "shifts_per_day": forms.NumberInput(attrs={"class": _input, "min": "1"}),
            "is_active": forms.CheckboxInput(attrs={"class": "rounded"}),
        }


# ─── Rutas de producción ──────────────────────────────────────

class ProductRouteForm(forms.ModelForm):
    class Meta:
        model = ProductRoute
        fields = ["product", "name", "is_active", "notes"]
        labels = {
            "product": "Producto",
            "name": "Nombre de la ruta",
            "is_active": "Activa",
            "notes": "Notas",
        }
        widgets = {
            "product": forms.Select(attrs={"class": "w-full rounded-lg border px-3 py-2"}),
            "name": forms.TextInput(attrs={"class": "w-full rounded-lg border px-3 py-2"}),
            "is_active": forms.CheckboxInput(attrs={"class": "rounded"}),
            "notes": forms.Textarea(attrs={"class": "w-full rounded-lg border px-3 py-2", "rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["product"].queryset = Product.objects.filter(
            product_type=ProductType.FG, is_active=True
        ).order_by("name")


class ProductRouteStepForm(forms.ModelForm):
    class Meta:
        model = ProductRouteStep
        fields = ["sequence", "work_center", "name", "description", "expected_duration_min", "setup_time_min", "requires_qa"]
        labels = {
            "sequence": "Secuencia",
            "work_center": "Estación de trabajo",
            "name": "Nombre del paso",
            "description": "Descripción",
            "expected_duration_min": "Dur. x unid (min)",
            "setup_time_min": "Setup (min)",
            "requires_qa": "Requiere QA",
        }
        _input = "w-full rounded-lg border px-3 py-2"
        widgets = {
            "sequence": forms.NumberInput(attrs={"class": _input}),
            "work_center": forms.Select(attrs={"class": _input}),
            "name": forms.TextInput(attrs={"class": _input}),
            "description": forms.TextInput(attrs={"class": _input}),
            "expected_duration_min": forms.NumberInput(attrs={"class": _input}),
            "setup_time_min": forms.NumberInput(attrs={"class": _input, "min": "0"}),
            "requires_qa": forms.CheckboxInput(attrs={"class": "rounded"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["work_center"].queryset = WorkCenter.objects.filter(is_active=True).order_by("name")


class MaterialTransferConfirmForm(forms.Form):
    quantity_confirmed = forms.DecimalField(
        label="Cantidad confirmada",
        min_value=0,
        widget=forms.NumberInput(attrs={"class": "w-full rounded-lg border px-3 py-2", "step": "0.0001"}),
    )
    notes = forms.CharField(
        label="Notas de desviación (opcional)",
        required=False,
        widget=forms.Textarea(attrs={"class": "w-full rounded-lg border px-3 py-2", "rows": 2}),
    )


ProductRouteStepFormSet = inlineformset_factory(
    ProductRoute,
    ProductRouteStep,
    form=ProductRouteStepForm,
    extra=1,
    can_delete=True,
)
