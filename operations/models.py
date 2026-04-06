from decimal import Decimal

from django.conf import settings
from django.db import models
from django.utils import timezone

from core.models import AuditModel


class Location(AuditModel):
    code = models.CharField("Codigo", max_length=30, unique=True)
    name = models.CharField("Nombre", max_length=160)
    address = models.CharField("Direccion", max_length=255, blank=True)
    phone = models.CharField("Telefono", max_length=30, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class CommissionBasis(models.TextChoices):
    COLLECTION = "COLLECTION", "Cobros"
    INVOICE = "INVOICE", "Facturacion"


class CommissionRecordStatus(models.TextChoices):
    PENDING = "PENDING", "Pendiente"
    APPROVED = "APPROVED", "Aprobada"
    PAID = "PAID", "Pagada"
    VOID = "VOID", "Anulada"


class CommissionScheme(AuditModel):
    name = models.CharField("Nombre", max_length=160)
    applies_to_role = models.CharField("Rol aplicable", max_length=30, blank=True)
    basis = models.CharField("Base", max_length=20, choices=CommissionBasis.choices, default=CommissionBasis.COLLECTION)
    percentage = models.DecimalField("Porcentaje", max_digits=5, decimal_places=2, default=Decimal("0.00"))
    flat_amount = models.DecimalField("Fijo por evento", max_digits=10, decimal_places=2, default=Decimal("0.00"))
    is_active = models.BooleanField(default=True)
    notes = models.TextField("Notas", blank=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class CommissionRecord(AuditModel):
    provider = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="commission_records",
    )
    appointment = models.ForeignKey(
        "appointments.Appointment",
        on_delete=models.CASCADE,
        related_name="commission_records",
    )
    source_invoice = models.ForeignKey(
        "billing.Invoice",
        on_delete=models.SET_NULL,
        related_name="commission_records",
        null=True,
        blank=True,
    )
    scheme = models.ForeignKey(
        CommissionScheme,
        on_delete=models.SET_NULL,
        related_name="records",
        null=True,
        blank=True,
    )
    period_start = models.DateField("Periodo desde")
    period_end = models.DateField("Periodo hasta")
    base_amount = models.DecimalField("Base", max_digits=10, decimal_places=2, default=Decimal("0.00"))
    commission_amount = models.DecimalField("Comision", max_digits=10, decimal_places=2, default=Decimal("0.00"))
    status = models.CharField(
        "Estado",
        max_length=20,
        choices=CommissionRecordStatus.choices,
        default=CommissionRecordStatus.PENDING,
    )
    notes = models.TextField("Notas", blank=True)

    class Meta:
        ordering = ["-period_end", "-commission_amount", "-id"]
        constraints = [
            models.UniqueConstraint(fields=["provider", "appointment"], name="operations_unique_provider_appointment_commission")
        ]

    def __str__(self):
        return f"{self.provider} - {self.commission_amount}"


class AutomationTrigger(models.TextChoices):
    APPOINTMENT_REMINDER = "APPOINTMENT_REMINDER", "Recordatorio de cita"
    FOLLOW_UP = "FOLLOW_UP", "Seguimiento post consulta"
    INVOICE_OVERDUE = "INVOICE_OVERDUE", "Factura vencida"
    LOW_STOCK_ALERT = "LOW_STOCK_ALERT", "Alerta de inventario"


class AutomationChannel(models.TextChoices):
    INTERNAL = "INTERNAL", "Interno"
    EMAIL = "EMAIL", "Email"
    WHATSAPP = "WHATSAPP", "WhatsApp"
    TASK = "TASK", "Tarea"


class AutomationRunStatus(models.TextChoices):
    SUCCESS = "SUCCESS", "Exitosa"
    WARNING = "WARNING", "Con alertas"
    ERROR = "ERROR", "Error"


class AutomationRule(AuditModel):
    name = models.CharField("Nombre", max_length=160)
    trigger = models.CharField("Disparador", max_length=30, choices=AutomationTrigger.choices)
    channel = models.CharField("Canal", max_length=20, choices=AutomationChannel.choices, default=AutomationChannel.INTERNAL)
    target_role = models.CharField("Rol destino", max_length=30, blank=True)
    offset_minutes = models.IntegerField("Offset minutos", default=0)
    template_text = models.TextField("Plantilla", blank=True)
    is_active = models.BooleanField(default=True)
    last_run_at = models.DateTimeField("Ultima ejecucion", null=True, blank=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class AutomationRun(AuditModel):
    rule = models.ForeignKey(
        AutomationRule,
        on_delete=models.CASCADE,
        related_name="runs",
    )
    status = models.CharField("Estado", max_length=20, choices=AutomationRunStatus.choices, default=AutomationRunStatus.SUCCESS)
    summary = models.CharField("Resumen", max_length=255)
    payload = models.JSONField(default=dict, blank=True)
    executed_at = models.DateTimeField("Ejecutada en", default=timezone.now)

    class Meta:
        ordering = ["-executed_at", "-id"]

    def __str__(self):
        return self.summary


class IntegrationProvider(models.TextChoices):
    WHATSAPP = "WHATSAPP", "WhatsApp"
    EMAIL = "EMAIL", "Email"
    PAYMENTS = "PAYMENTS", "Pasarela de pago"
    LAB = "LAB", "Laboratorio"
    BI = "BI", "BI / Data"


class IntegrationStatus(models.TextChoices):
    CONFIGURED = "CONFIGURED", "Configurada"
    TESTING = "TESTING", "En pruebas"
    ERROR = "ERROR", "Error"
    DISABLED = "DISABLED", "Desactivada"


class IntegrationConnection(AuditModel):
    name = models.CharField("Nombre", max_length=160)
    provider = models.CharField("Proveedor", max_length=20, choices=IntegrationProvider.choices)
    status = models.CharField("Estado", max_length=20, choices=IntegrationStatus.choices, default=IntegrationStatus.TESTING)
    endpoint = models.CharField("Endpoint o URL", max_length=255, blank=True)
    secret_hint = models.CharField("Referencia de credencial", max_length=40, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    notes = models.TextField("Notas", blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name
