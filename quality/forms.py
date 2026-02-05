# quality/forms.py

from __future__ import annotations

from django import forms
from django.forms import inlineformset_factory
from django.utils import timezone
from decimal import Decimal 

from .models import (
    QAParameterTemplate,
    QualityInspection,
    QAPlan,
    InspectionStage,
)
from inventory.models import Product, Lot, LotStatus
from core.models import Location, Warehouse, WarehouseType
from production.models import WorkCenter, ProductRouteStep, ProductionOperation


# --------------------------------------------------------------------
# 1) Form para parámetros de un Plan de QA
# --------------------------------------------------------------------
class QAParameterTemplateForm(forms.ModelForm):
    class Meta:
        model = QAParameterTemplate
        fields = [
            "code",
            "label",
            "unit",
            "data_type",
            "min_value",
            "max_value",
            "is_required",
            "order",
        ]
        widgets = {
            "code": forms.TextInput(attrs={"class": "w-full rounded-lg border px-3 py-2"}),
            "label": forms.TextInput(attrs={"class": "w-full rounded-lg border px-3 py-2"}),
            "unit": forms.TextInput(attrs={"class": "w-full rounded-lg border px-3 py-2"}),
            "data_type": forms.Select(attrs={"class": "w-full rounded-lg border px-3 py-2"}),
            "min_value": forms.NumberInput(attrs={"class": "w-full rounded-lg border px-3 py-2"}),
            "max_value": forms.NumberInput(attrs={"class": "w-full rounded-lg border px-3 py-2"}),
            "is_required": forms.CheckboxInput(attrs={"class": "rounded"}),
            "order": forms.NumberInput(attrs={"class": "w-full rounded-lg border px-3 py-2"}),
        }


# --------------------------------------------------------------------
# 2) Form para Inspección de Calidad (con checklist dinámico por plan)
# --------------------------------------------------------------------

class QualityInspectionForm(forms.ModelForm):
    """
    Formulario de inspección de calidad.

    - Recibe un `plan` (QAPlan) desde la vista.
    - Genera campos dinámicos `param_<id>` según los parámetros del plan.
    - Construye un JSON estructurado en `checklist` al hacer clean/save.
    """

    destination_location = forms.ModelChoiceField(
        queryset=Location.objects.none(),
        label="Ubicación destino (bodega MP)",
        required=False,
        widget=forms.Select(attrs={"class": "w-full rounded-lg border px-3 py-2"}),
        help_text="Opcional. Al aprobar, el lote se ubicará aquí dentro de la bodega de MP.",
    )

    class Meta:
        model = QualityInspection
        # Ojo: plan NO se expone como campo editable; se asocia desde la vista.
        fields = [
            "lot",
            "stage",
            "operation",
            "inspected_at",
            "inspected_by",
            "result",
            "notes",
        ]
        labels = {
            "lot": "Lote",
            "stage": "Etapa",
            "operation": "Operación",
            "inspected_at": "Fecha y hora de inspección",
            "inspected_by": "Inspector",
            "result": "Resultado",
            "notes": "Observaciones",
        }
        widgets = {
            "lot": forms.Select(
                attrs={"class": "w-full rounded-lg border px-3 py-2"}
            ),
            "stage": forms.Select(
                attrs={"class": "w-full rounded-lg border px-3 py-2"}
            ),
            "operation": forms.Select(
                attrs={"class": "w-full rounded-lg border px-3 py-2"}
            ),
            "inspected_at": forms.DateTimeInput(
                attrs={
                    "class": "w-full rounded-lg border px-3 py-2",
                    "type": "datetime-local",
                }
            ),
            "inspected_by": forms.Select(
                attrs={"class": "w-full rounded-lg border px-3 py-2"}
            ),
            "result": forms.Select(
                attrs={"class": "w-full rounded-lg border px-3 py-2"}
            ),
            "notes": forms.Textarea(
                attrs={"class": "w-full rounded-lg border px-3 py-2", "rows": 3}
            ),
        }

    def __init__(self, *args, plan: QAPlan | None = None, **kwargs):
        """
        plan: instancia de QAPlan resuelta en la vista (puede ser None).
        """
        self.plan: QAPlan | None = kwargs.pop("plan", plan)
        super().__init__(*args, **kwargs)

        # Si estamos editando y no nos pasaron plan, usamos el de la instancia.
        if not self.plan and self.instance and self.instance.pk:
            self.plan = self.instance.plan

        # ═══ CAMPOS AUTOMÁTICOS PARA TRAZABILIDAD ═══
        # inspected_at e inspected_by NO deben ser editables por el usuario
        # Se asignan automáticamente al crear la inspección

        # Fecha/hora de inspección: siempre automática
        if not self.instance.pk:
            self.initial["inspected_at"] = timezone.now()

        # Hacer inspected_at de solo lectura (no editable)
        if "inspected_at" in self.fields:
            self.fields["inspected_at"].disabled = True
            self.fields["inspected_at"].help_text = "Se registra automáticamente al crear la inspección"

        # Hacer inspected_by de solo lectura (no editable)
        if "inspected_by" in self.fields:
            self.fields["inspected_by"].disabled = True
            self.fields["inspected_by"].help_text = "Se asigna automáticamente al usuario actual"

        # Etiquetas en español
        self.fields["lot"].label = "Lote"
        self.fields["stage"].label = "Etapa"
        self.fields["operation"].label = "Operación"
        self.fields["inspected_at"].label = "Fecha y hora de inspección"
        self.fields["inspected_by"].label = "Inspector"
        self.fields["result"].label = "Resultado"
        self.fields["notes"].label = "Observaciones"

        # Placeholders en español
        if hasattr(self.fields["operation"], "empty_label"):
            self.fields["operation"].empty_label = "Sin operación (no aplica)"

        # Resultado: opciones disponibles
        self.fields["result"].choices = [
            (LotStatus.PENDING.value, LotStatus.PENDING.label),
            (LotStatus.APPROVED.value, LotStatus.APPROVED.label),
            (LotStatus.REJECTED.value, LotStatus.REJECTED.label),
            (LotStatus.QUARANTINE.value, LotStatus.QUARANTINE.label),
        ]
        if not self.instance.pk:
            self.initial["result"] = LotStatus.PENDING.value

        # Poblar ubicaciones de bodegas de MP para ubicación destino
        raw_wh = Warehouse.objects.filter(type=WarehouseType.RAW, is_active=True).first()
        if raw_wh:
            self.fields["destination_location"].queryset = (
                Location.objects.filter(warehouse=raw_wh, is_active=True).order_by("code")
            )
            self.fields["destination_location"].label = f"Ubicación destino ({raw_wh.name})"

        # Ajustar querysets (si usas Lot / ProductionOperation)
        # Asegúrate de tener importados Lot y ProductionOperation arriba.
        self.fields["lot"].queryset = Lot.objects.all().order_by("-created_at")
        self.fields["operation"].queryset = (
            ProductionOperation.objects
            .select_related("order", "step", "step__work_center")
            .all()
            .order_by("-id")
        )

        # Diccionario donde guardaremos el checklist estructurado
        self._checklist_data: dict = {}

        # Si hay plan, generamos campos dinámicos según sus parámetros
        if self.plan:
            existing_values = self.instance.checklist or {}

            for param in self.plan.parameters.all():
                field_name = f"param_{param.id}"

                # Elegir tipo de campo según data_type
                if param.data_type == QAParameterTemplate.DataType.BOOL:
                    field = forms.BooleanField(
                        label=param.label,
                        required=param.is_required,
                        widget=forms.CheckboxInput(attrs={"class": "rounded"}),
                    )
                elif param.data_type == QAParameterTemplate.DataType.NUMBER:
                    field = forms.DecimalField(
                        label=param.label,
                        required=param.is_required,
                        decimal_places=4,
                        max_digits=10,
                        widget=forms.NumberInput(
                            attrs={"class": "w-full rounded-lg border px-3 py-2"}
                        ),
                    )
                else:  # TEXT
                    field = forms.CharField(
                        label=param.label,
                        required=param.is_required,
                        widget=forms.TextInput(
                            attrs={"class": "w-full rounded-lg border px-3 py-2"}
                        ),
                    )

                # 👉 guardamos el objeto parámetro en el campo para usarlo en el template
                field.param = param

                # Inicializar con valores existentes si estamos editando
                if existing_values:
                    # guardamos por código en el JSON: checklist["ANCHO"]["value"]
                    param_data = existing_values.get(param.code)
                    if param_data is not None:
                        field.initial = param_data.get("value")

                self.fields[field_name] = field

    @property
    def parameter_fields(self):
        """
        Devuelve solo los campos dinámicos de parámetros (por si quieres
        usarlos en el template como form.parameter_fields).
        """
        return [
            self[name]        # BoundField → esto sí se renderiza como input HTML
            for name in self.fields.keys()
            if name.startswith("param_")
        ]

    def clean(self):
        cleaned_data = super().clean()

        # Si hay plan, construimos un diccionario estructurado para checklist
        if self.plan:
            checklist = {}

            for param in self.plan.parameters.all():
                field_name = f"param_{param.id}"
                value = cleaned_data.get(field_name)
                if isinstance(value, Decimal):
                    value = float(value)

                checklist[param.code] = {
                    "label": param.label,
                    "unit": param.unit,
                    "value": value,
                    # Más adelante puedes agregar "within_limits" aquí
                }

            self._checklist_data = checklist

        return cleaned_data

    def save(self, commit: bool = True) -> QualityInspection:
        """
        - Asigna plan y checklist en la instancia.
        - `inspected_by` se rellena en la vista con request.user.
        """
        obj: QualityInspection = super().save(commit=False)

        if self.plan:
            obj.plan = self.plan
            obj.checklist = self._checklist_data

        if commit:
            obj.save()
        return obj


# --------------------------------------------------------------------
# 3) Form para Plan de QA (configuración)
# --------------------------------------------------------------------
class QAPlanForm(forms.ModelForm):
    """
    Plan de QA configurable por:
      - producto (opcional)
      - etapa (RAW, WIP, FG)
      - centro de trabajo (opcional)
      - paso de ruta (opcional)
    """

    class Meta:
        model = QAPlan
        fields = ["name", "product", "stage", "work_center", "route_step", "is_active"]
        labels = {
            "name": "Nombre del plan",
            "product": "Producto",
            "stage": "Etapa de inspección",
            "work_center": "Centro de trabajo",
            "route_step": "Paso de ruta",
            "is_active": "Plan activo",
        }
        widgets = {
            "name": forms.TextInput(
                attrs={"class": "w-full rounded-lg border px-3 py-2"}
            ),
            "product": forms.Select(
                attrs={"class": "w-full rounded-lg border px-3 py-2"}
            ),
            "stage": forms.Select(
                attrs={"class": "w-full rounded-lg border px-3 py-2"}
            ),
            "work_center": forms.Select(
                attrs={"class": "w-full rounded-lg border px-3 py-2"}
            ),
            "route_step": forms.Select(
                attrs={"class": "w-full rounded-lg border px-3 py-2"}
            ),
            "is_active": forms.CheckboxInput(attrs={"class": "rounded"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Todos estos campos son opcionales por diseño (para poder tener planes genéricos)
        self.fields["product"].required = False
        self.fields["work_center"].required = False
        self.fields["route_step"].required = False

        # Solo productos activos, ordenados por nombre
        self.fields["product"].queryset = (
            Product.objects.filter(is_active=True).order_by("name")
        )

        # Centros de trabajo activos
        self.fields["work_center"].queryset = WorkCenter.objects.filter(is_active=True)

        # Pasos de ruta activos
        self.fields["route_step"].queryset = ProductRouteStep.objects.filter(
            is_active=True
        )

        # Placeholders / empty_label en español
        if hasattr(self.fields["product"], "empty_label"):
            self.fields["product"].empty_label = "— Plan genérico (sin producto) —"

        if hasattr(self.fields["work_center"], "empty_label"):
            self.fields["work_center"].empty_label = "— Sin centro específico —"

        if hasattr(self.fields["route_step"], "empty_label"):
            self.fields["route_step"].empty_label = "— Sin paso específico —"

        if hasattr(self.fields["stage"], "empty_label"):
            self.fields["stage"].empty_label = "— Selecciona la etapa —"



# --------------------------------------------------------------------
# 4) Formset inline de parámetros por Plan de QA
# --------------------------------------------------------------------
QAParameterTemplateFormSet = inlineformset_factory(
    QAPlan,
    QAParameterTemplate,
    form=QAParameterTemplateForm,
    extra=1,          # 1 fila nueva vacía por defecto
    can_delete=True,  # permite marcar para eliminar
)
