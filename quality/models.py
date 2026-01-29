from django.db import models
from django.conf import settings
from core.models import AuditModel
from django.db.models import Q, Case, When, Value, IntegerField
from inventory.models import LotStatus


class InspectionStage(models.TextChoices):
    RAW = "RAW", "Ingreso materia prima"
    WIP = "WIP", "En proceso"
    FG  = "FG",  "Producto terminado"




class QAPlan(AuditModel):
    name = models.CharField(max_length=100)

    product = models.ForeignKey(
        "inventory.Product",
        on_delete=models.PROTECT,
        related_name="qa_plans",
        null=True,
        blank=True,
        help_text="Si se deja vacío, puede aplicarse por tipo de producto o genérico.",
    )

    stage = models.CharField(
        max_length=10,
        choices=InspectionStage.choices,
    )

    work_center = models.ForeignKey(
        "production.WorkCenter",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="qa_plans",
    )

    route_step = models.ForeignKey(
        "production.ProductRouteStep",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="qa_plans",
    )

    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name = "Plan de QA"
        verbose_name_plural = "Planes de QA"

    def __str__(self):
        return f"{self.name} ({self.get_stage_display()})"

    # 👇 NUEVO: selector de plan más específico aplicable
    @classmethod
    def get_applicable_plan(cls, *, product, stage, work_center=None, route_step=None):
        """
        Devuelve el plan de QA más específico aplicable para:
          - un producto (puede ser None),
          - una etapa (RAW / WIP / FG),
          - opcionalmente un work_center y/o route_step.

        Prioridad aproximada:
          1) product + route_step
          2) product + work_center
          3) product solo
          4) genérico con route_step
          5) genérico con work_center
          6) genérico por etapa
        """

        qs = cls.objects.filter(is_active=True, stage=stage)

        # Filtramos por producto: aceptamos planes específicos y genéricos
        if product is not None:
            qs = qs.filter(Q(product=product) | Q(product__isnull=True))
        # Si product es None → dejamos solo los que no tienen product
        else:
            qs = qs.filter(product__isnull=True)

        # Filtrado por contexto de operación
        if route_step is not None:
            qs = qs.filter(
                Q(route_step=route_step) | Q(route_step__isnull=True)
            )
        elif work_center is not None:
            qs = qs.filter(
                Q(work_center=work_center) | Q(work_center__isnull=True)
            )

        # Anotamos "especificidad" para ordenar: mientras menor, más específico
        qs = qs.annotate(
            product_score=Case(
                When(product__isnull=False, then=Value(0)),
                default=Value(1),
                output_field=IntegerField(),
            ),
            route_step_score=Case(
                When(route_step__isnull=False, then=Value(0)),
                default=Value(1),
                output_field=IntegerField(),
            ),
            wc_score=Case(
                When(work_center__isnull=False, then=Value(0)),
                default=Value(1),
                output_field=IntegerField(),
            ),
        ).order_by(
            "product_score",      # primero los que tienen product
            "route_step_score",   # luego los que tienen route_step
            "wc_score",           # luego los que tienen work_center
            "name",
        )

        return qs.first()



class QAParameterTemplate(AuditModel):
    class DataType(models.TextChoices):
        BOOL   = "BOOL", "Si / No"
        NUMBER = "NUMBER", "Numérico"
        TEXT   = "TEXT", "Texto libre"

    plan = models.ForeignKey(
        QAPlan,
        on_delete=models.CASCADE,
        related_name="parameters",
    )

    code = models.CharField(max_length=50, help_text="ANCHO, PESO, COLOR, etc.")
    label = models.CharField(max_length=100, help_text="Etiqueta visible en el formulario")
    unit = models.CharField(max_length=20, blank=True, null=True, help_text="cm, kg, g/m2...")

    data_type = models.CharField(
        max_length=10,
        choices=DataType.choices,
        default=DataType.TEXT,
    )

    min_value = models.DecimalField(max_digits=10, decimal_places=4, null=True, blank=True)
    max_value = models.DecimalField(max_digits=10, decimal_places=4, null=True, blank=True)

    is_required = models.BooleanField(default=False)
    order = models.PositiveIntegerField(default=10)

    class Meta:
        ordering = ["plan", "order"]
        verbose_name = "Parámetro de QA"
        verbose_name_plural = "Parámetros de QA"

    def __str__(self):
        return f"{self.plan.name} – {self.code}"

class QualityInspection(AuditModel):
    lot = models.ForeignKey(
        "inventory.Lot",
        on_delete=models.CASCADE,
        related_name="inspections",
    )

    stage = models.CharField(
        max_length=10,
        choices=InspectionStage.choices,
        help_text="Etapa del proceso en la que se realiza la inspección.",
    )

    operation = models.ForeignKey(
        "production.ProductionOperation",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="inspections",
        help_text="Operación específica asociada a esta inspección (WIP).",
    )
    plan = models.ForeignKey(
        QAPlan,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="inspections",
        help_text="Plan de QA aplicado a esta inspección.",
    )

    inspected_at = models.DateTimeField(null=True, blank=True)

    inspected_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="qa_inspections",
    )

    checklist = models.JSONField(
        null=True,
        blank=True,
        help_text="Resultados detallados de parámetros (ancho, peso, etc.)",
    )

    result = models.CharField(
        max_length=20,
        choices=LotStatus.choices,
        null=True,
        blank=True,
        help_text="Resultado global de la inspección.",
    )

    notes = models.TextField(blank=True, null=True)

    class Meta:
        verbose_name = "Inspección de Calidad"
        verbose_name_plural = "Inspecciones de Calidad"

    def __str__(self):
        return f"Inspección {self.stage} – lote {self.lot.internal_lot}"

