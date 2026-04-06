from decimal import Decimal

from django.db import models
from django.utils import timezone

from appointments.models import Appointment
from core.models import AuditModel
from patients.models import Patient


class CashTransactionType(models.TextChoices):
    PAYMENT = "PAYMENT", "Cobro"
    REFUND = "REFUND", "Reembolso"
    EXPENSE = "EXPENSE", "Egreso"


class PaymentMethod(models.TextChoices):
    CASH = "CASH", "Efectivo"
    CARD = "CARD", "Tarjeta"
    TRANSFER = "TRANSFER", "Transferencia"
    LINK = "LINK", "Link de pago"
    OTHER = "OTHER", "Otro"


class CoveragePayerType(models.TextChoices):
    INSURER = "INSURER", "Aseguradora"
    CORPORATE = "CORPORATE", "Convenio corporativo"
    MEMBERSHIP = "MEMBERSHIP", "Membresia"
    OTHER = "OTHER", "Otro"


class InvoiceStatus(models.TextChoices):
    DRAFT = "DRAFT", "Borrador"
    ISSUED = "ISSUED", "Emitida"
    PARTIAL = "PARTIAL", "Abono parcial"
    PAID = "PAID", "Pagada"
    OVERDUE = "OVERDUE", "Vencida"
    CANCELED = "CANCELED", "Anulada"


class CoverageAgreement(AuditModel):
    code = models.CharField("Codigo", max_length=30, unique=True)
    name = models.CharField("Nombre", max_length=160)
    payer_type = models.CharField(
        "Tipo de pagador",
        max_length=20,
        choices=CoveragePayerType.choices,
        default=CoveragePayerType.INSURER,
    )
    contact_name = models.CharField("Contacto", max_length=120, blank=True)
    phone = models.CharField("Telefono", max_length=30, blank=True)
    email = models.EmailField("Correo", blank=True)
    default_discount_percent = models.DecimalField(
        "Descuento por defecto",
        max_digits=5,
        decimal_places=2,
        default=Decimal("0.00"),
    )
    default_credit_days = models.PositiveSmallIntegerField("Dias de credito", default=0)
    notes = models.TextField("Notas", blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class Invoice(AuditModel):
    patient = models.ForeignKey(
        Patient,
        on_delete=models.PROTECT,
        related_name="invoices",
    )
    location = models.ForeignKey(
        "operations.Location",
        on_delete=models.SET_NULL,
        related_name="invoices",
        null=True,
        blank=True,
    )
    appointment = models.ForeignKey(
        Appointment,
        on_delete=models.SET_NULL,
        related_name="invoices",
        null=True,
        blank=True,
    )
    coverage_agreement = models.ForeignKey(
        CoverageAgreement,
        on_delete=models.SET_NULL,
        related_name="invoices",
        null=True,
        blank=True,
    )
    invoice_number = models.CharField("Numero de factura", max_length=40, unique=True)
    issued_at = models.DateTimeField("Fecha de emision", default=timezone.now)
    due_date = models.DateField("Vence", null=True, blank=True)
    status = models.CharField(
        "Estado",
        max_length=20,
        choices=InvoiceStatus.choices,
        default=InvoiceStatus.DRAFT,
    )
    subtotal = models.DecimalField("Subtotal", max_digits=10, decimal_places=2, default=Decimal("0.00"))
    discount_amount = models.DecimalField("Descuento", max_digits=10, decimal_places=2, default=Decimal("0.00"))
    total_amount = models.DecimalField("Total", max_digits=10, decimal_places=2, default=Decimal("0.00"))
    paid_amount = models.DecimalField("Pagado", max_digits=10, decimal_places=2, default=Decimal("0.00"))
    notes = models.TextField("Notas", blank=True)

    class Meta:
        ordering = ["-issued_at", "-id"]

    def __str__(self):
        return f"{self.invoice_number} - {self.patient.full_name}"

    @property
    def balance_amount(self):
        balance = self.total_amount - self.paid_amount
        return balance if balance > Decimal("0.00") else Decimal("0.00")

    @property
    def is_overdue(self):
        return bool(
            self.due_date
            and self.balance_amount > Decimal("0.00")
            and self.due_date < timezone.localdate()
            and self.status != InvoiceStatus.CANCELED
        )

    def save(self, *args, **kwargs):
        computed_total = self.subtotal - self.discount_amount
        self.total_amount = computed_total if computed_total > Decimal("0.00") else Decimal("0.00")
        if self.paid_amount > self.total_amount:
            self.paid_amount = self.total_amount
        super().save(*args, **kwargs)

    def refresh_payment_snapshot(self, *, save=True):
        payments = (
            self.cash_transactions.filter(transaction_type=CashTransactionType.PAYMENT).aggregate(total=models.Sum("amount"))[
                "total"
            ]
            or Decimal("0.00")
        )
        refunds = (
            self.cash_transactions.filter(transaction_type=CashTransactionType.REFUND).aggregate(total=models.Sum("amount"))[
                "total"
            ]
            or Decimal("0.00")
        )
        self.paid_amount = payments - refunds
        if self.paid_amount < Decimal("0.00"):
            self.paid_amount = Decimal("0.00")

        if self.status != InvoiceStatus.CANCELED:
            if self.total_amount <= Decimal("0.00"):
                self.status = InvoiceStatus.DRAFT
            elif self.balance_amount == Decimal("0.00"):
                self.status = InvoiceStatus.PAID
            elif self.paid_amount > Decimal("0.00"):
                self.status = InvoiceStatus.PARTIAL
            elif self.is_overdue:
                self.status = InvoiceStatus.OVERDUE
            else:
                self.status = InvoiceStatus.ISSUED

        if save:
            self.save(update_fields=["paid_amount", "status", "total_amount"])
        return self


class CashTransaction(AuditModel):
    posted_at = models.DateTimeField("Fecha", default=timezone.now)
    transaction_type = models.CharField(
        "Tipo",
        max_length=20,
        choices=CashTransactionType.choices,
        default=CashTransactionType.PAYMENT,
    )
    payment_method = models.CharField(
        "Metodo de pago",
        max_length=20,
        choices=PaymentMethod.choices,
        default=PaymentMethod.CASH,
    )
    patient = models.ForeignKey(
        Patient,
        on_delete=models.SET_NULL,
        related_name="cash_transactions",
        null=True,
        blank=True,
    )
    appointment = models.ForeignKey(
        Appointment,
        on_delete=models.SET_NULL,
        related_name="cash_transactions",
        null=True,
        blank=True,
    )
    invoice = models.ForeignKey(
        Invoice,
        on_delete=models.SET_NULL,
        related_name="cash_transactions",
        null=True,
        blank=True,
    )
    amount = models.DecimalField("Monto", max_digits=10, decimal_places=2, default=Decimal("0.00"))
    concept = models.CharField("Concepto", max_length=160)
    reference = models.CharField("Referencia", max_length=80, blank=True)
    notes = models.TextField("Notas", blank=True)

    class Meta:
        ordering = ["-posted_at", "-id"]

    def __str__(self):
        return f"{self.get_transaction_type_display()} {self.amount} - {self.concept}"
