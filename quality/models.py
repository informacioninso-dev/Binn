from django.db import models
from django.conf import settings
from django.utils import timezone
from core.models import AuditModel
from django.db.models import Q, Case, When, Value, IntegerField
from inventory.models import LotStatus


# ─── Retiro de Mercado ──────────────────────────────────────────


class RecallOriginType(models.TextChoices):
    NON_CONFORMITY = "NON_CONFORMITY", "Producto no conforme"
    HEALTH_RISK = "HEALTH_RISK", "Riesgo para la salud"
    REGULATORY = "REGULATORY", "Notificación de ente regulador"
    QUALITY_ISSUE = "QUALITY_ISSUE", "Problema de calidad detectado"
    OTHER = "OTHER", "Otro"


class RecallOrigin(AuditModel):
    """Motivos/orígenes configurables para retiro de mercado."""
    code = models.CharField("Código", max_length=20, unique=True)
    name = models.CharField("Nombre", max_length=200)
    origin_type = models.CharField(
        "Tipo", max_length=20,
        choices=RecallOriginType.choices,
        default=RecallOriginType.OTHER,
    )
    description = models.TextField("Descripción", blank=True)
    is_active = models.BooleanField("Activo", default=True)

    class Meta:
        verbose_name = "Origen de retiro"
        verbose_name_plural = "Orígenes de retiro"
        ordering = ["origin_type", "name"]

    def __str__(self):
        return f"{self.name} ({self.get_origin_type_display()})"


class RecallStatus(models.TextChoices):
    DRAFT = "DRAFT", "Borrador"
    ACTIVE = "ACTIVE", "Activo"
    NOTIFYING = "NOTIFYING", "Notificando clientes"
    RECOVERING = "RECOVERING", "Recuperando producto"
    COMPLETED = "COMPLETED", "Completado"
    CANCELED = "CANCELED", "Cancelado"


class RecallSeverity(models.TextChoices):
    LOW = "LOW", "Baja"
    MEDIUM = "MEDIUM", "Media"
    HIGH = "HIGH", "Alta"
    CRITICAL = "CRITICAL", "Crítica"


class ProductRecall(AuditModel):
    """Retiro de mercado gestionado por Calidad."""
    code = models.CharField("Código", max_length=50, unique=True, blank=True)
    origin = models.ForeignKey(
        RecallOrigin, on_delete=models.PROTECT,
        related_name="recalls", verbose_name="Origen",
        null=True, blank=True,
    )
    product = models.ForeignKey(
        "inventory.Product", on_delete=models.PROTECT,
        related_name="recalls", verbose_name="Producto",
    )
    status = models.CharField(
        "Estado", max_length=20,
        choices=RecallStatus.choices,
        default=RecallStatus.DRAFT,
    )
    severity = models.CharField(
        "Severidad", max_length=20,
        choices=RecallSeverity.choices,
        default=RecallSeverity.MEDIUM,
    )
    recall_date = models.DateTimeField("Fecha de retiro", auto_now_add=True)
    completion_date = models.DateTimeField("Fecha de finalización", null=True, blank=True)
    reason = models.TextField("Motivo detallado")
    description = models.TextField("Descripción del problema", blank=True)
    corrective_action = models.TextField("Acción correctiva", blank=True)
    notes = models.TextField("Notas internas", blank=True)

    class Meta:
        verbose_name = "Retiro de mercado"
        verbose_name_plural = "Retiros de mercado"
        ordering = ["-recall_date"]

    def _generate_code(self):
        year = timezone.now().year
        prefix = f"RET-{year}-"
        last = (
            ProductRecall.objects.filter(code__startswith=prefix)
            .order_by("-code").values_list("code", flat=True).first()
        )
        seq = int(last.split("-")[-1]) + 1 if last else 1
        return f"{prefix}{seq:04d}"

    def save(self, *args, **kwargs):
        if not self.code:
            self.code = self._generate_code()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.code} – {self.product.name}"

    @property
    def total_affected(self):
        return sum(lot.quantity_affected for lot in self.lots.all())

    @property
    def total_recovered(self):
        return sum(lot.quantity_recovered for lot in self.lots.all())


class RecallLot(AuditModel):
    """Lote afectado por un retiro de mercado."""
    recall = models.ForeignKey(
        ProductRecall, on_delete=models.CASCADE,
        related_name="lots", verbose_name="Retiro",
    )
    lot = models.ForeignKey(
        "inventory.Lot", on_delete=models.PROTECT,
        related_name="recall_records", verbose_name="Lote",
    )
    quantity_affected = models.DecimalField("Cantidad afectada", max_digits=12, decimal_places=4)
    quantity_in_warehouse = models.DecimalField("En bodega", max_digits=12, decimal_places=4, default=0)
    quantity_with_clients = models.DecimalField("Con clientes", max_digits=12, decimal_places=4, default=0)
    quantity_recovered = models.DecimalField("Cantidad recuperada", max_digits=12, decimal_places=4, default=0)
    notes = models.TextField("Notas", blank=True)

    class Meta:
        verbose_name = "Lote afectado"
        verbose_name_plural = "Lotes afectados"
        unique_together = ("recall", "lot")

    def __str__(self):
        return f"{self.lot.internal_lot} – {self.quantity_affected}"


class RecallAffectedClient(AuditModel):
    """Cliente afectado por un retiro de mercado (recibió producto del lote)."""
    recall = models.ForeignKey(
        ProductRecall, on_delete=models.CASCADE,
        related_name="affected_clients", verbose_name="Retiro",
    )
    recall_lot = models.ForeignKey(
        RecallLot, on_delete=models.CASCADE,
        related_name="clients", verbose_name="Lote afectado",
    )
    client = models.ForeignKey(
        "partners.Partner", on_delete=models.PROTECT,
        related_name="recall_notifications", verbose_name="Cliente",
    )
    # Snapshot de dirección al momento del retiro
    client_name = models.CharField("Nombre", max_length=300)
    client_address = models.CharField("Dirección", max_length=300, blank=True)
    client_city = models.CharField("Ciudad", max_length=100, blank=True)
    client_phone = models.CharField("Teléfono", max_length=50, blank=True)
    client_email = models.EmailField("Email", blank=True)
    # Despacho original
    dispatch_code = models.CharField("Código despacho", max_length=50, blank=True)
    dispatch_date = models.DateField("Fecha despacho", null=True, blank=True)
    quantity_dispatched = models.DecimalField("Cantidad despachada", max_digits=12, decimal_places=4)
    # Seguimiento de notificación
    notified = models.BooleanField("Notificado", default=False)
    notified_date = models.DateTimeField("Fecha notificación", null=True, blank=True)
    notification_method = models.CharField("Método", max_length=100, blank=True)
    # Seguimiento de recuperación
    recovered = models.BooleanField("Producto recuperado", default=False)
    quantity_recovered = models.DecimalField("Cantidad recuperada", max_digits=12, decimal_places=4, default=0)
    recovery_date = models.DateTimeField("Fecha recuperación", null=True, blank=True)
    recovery_notes = models.TextField("Notas de recuperación", blank=True)

    class Meta:
        verbose_name = "Cliente afectado"
        verbose_name_plural = "Clientes afectados"

    def __str__(self):
        return f"{self.client_name} – {self.quantity_dispatched}"


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

