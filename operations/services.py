from datetime import timedelta
from decimal import Decimal

from django.db.models import Count, F, Q, Sum
from django.utils import timezone

from appointments.models import Appointment, AppointmentStatus
from billing.models import CashTransaction, CashTransactionType, Invoice, InvoiceStatus
from crm.models import Lead, LeadStage
from inventory.models import InventoryItem
from tenants.models import TenantMembership

from .models import (
    AutomationRun,
    AutomationRunStatus,
    AutomationTrigger,
    CommissionRecord,
    CommissionRecordStatus,
    CommissionScheme,
    IntegrationConnection,
    Location,
)


def build_operations_dashboard(*, tenant):
    today = timezone.localdate()
    month_appointments = Appointment.objects.filter(
        scheduled_at__date__month=today.month,
        scheduled_at__date__year=today.year,
    )
    month_invoice_totals = (
        Invoice.objects.exclude(status=InvoiceStatus.CANCELED).aggregate(total=Sum("total_amount"))["total"] or Decimal("0.00")
    )
    month_paid_totals = (
        Invoice.objects.exclude(status=InvoiceStatus.CANCELED).aggregate(total=Sum("paid_amount"))["total"] or Decimal("0.00")
    )
    receivable = (
        Invoice.objects.exclude(status=InvoiceStatus.CANCELED).aggregate(total=Sum("total_amount"))["total"] or Decimal("0.00")
    ) - (Invoice.objects.exclude(status=InvoiceStatus.CANCELED).aggregate(total=Sum("paid_amount"))["total"] or Decimal("0.00"))
    if receivable < 0:
        receivable = Decimal("0.00")

    location_summary = (
        Location.objects.filter(is_active=True)
        .annotate(
            appointments=Count("appointments"),
            completed=Count("appointments", filter=Q(appointments__status=AppointmentStatus.COMPLETED)),
            revenue=Sum("invoices__paid_amount"),
        )
        .order_by("-appointments", "name")[:8]
    )
    stage_labels = dict(LeadStage.choices)
    pipeline_summary = [
        {"stage": stage_labels.get(row["stage"], row["stage"]), "total": row["total"]}
        for row in Lead.objects.values("stage").annotate(total=Count("id")).order_by("stage")
    ]
    completion_rate = _ratio(
        month_appointments.filter(status=AppointmentStatus.COMPLETED).count(),
        month_appointments.count(),
    )
    collection_rate = _ratio(month_paid_totals, month_invoice_totals)

    return {
        "summary": {
            "revenue_month": (
                CashTransaction.objects.filter(
                    transaction_type=CashTransactionType.PAYMENT,
                    posted_at__date__month=today.month,
                    posted_at__date__year=today.year,
                ).aggregate(total=Sum("amount"))["total"]
                or Decimal("0.00")
            ),
            "receivable": receivable,
            "lead_conversion": _lead_conversion_ratio(),
            "completion_rate": completion_rate,
            "collection_rate": collection_rate,
            "locations": Location.objects.filter(is_active=True).count(),
            "low_stock": InventoryItem.objects.filter(stock_on_hand__lte=F("reorder_point"), is_active=True).count(),
            "automations": AutomationRun.objects.count(),
            "overdue_invoices": Invoice.objects.filter(due_date__lt=today).exclude(
                status__in=[InvoiceStatus.PAID, InvoiceStatus.CANCELED]
            ).count(),
            "pending_commissions_total": (
                CommissionRecord.objects.filter(status=CommissionRecordStatus.PENDING).aggregate(total=Sum("commission_amount"))[
                    "total"
                ]
                or Decimal("0.00")
            ),
        },
        "location_summary": list(location_summary),
        "pipeline_summary": pipeline_summary,
        "commission_pending": CommissionRecord.objects.filter(status=CommissionRecordStatus.PENDING).select_related(
            "provider",
            "appointment__patient",
            "scheme",
        )[:8],
        "recent_automation_runs": AutomationRun.objects.select_related("rule").order_by("-executed_at", "-id")[:8],
        "integrations": IntegrationConnection.objects.order_by("name")[:8],
    }


def _lead_conversion_ratio():
    total = Lead.objects.count()
    if total == 0:
        return Decimal("0.0")
    won = Lead.objects.filter(stage=LeadStage.WON).count()
    return _ratio(won, total)


def _ratio(numerator, denominator):
    if not denominator:
        return Decimal("0.0")
    return round((Decimal(numerator) / Decimal(denominator)) * Decimal("100.0"), 1)


def generate_commission_records(*, tenant, period_start, period_end, actor=None):
    appointments = Appointment.objects.select_related("provider").filter(
        scheduled_at__date__gte=period_start,
        scheduled_at__date__lte=period_end,
        status=AppointmentStatus.COMPLETED,
        provider__isnull=False,
    )
    created_or_updated = 0

    for appointment in appointments:
        membership = TenantMembership.objects.filter(
            tenant=tenant,
            user=appointment.provider,
            is_active=True,
        ).first()
        if membership is None:
            continue

        applicable_scheme = (
            CommissionScheme.objects.filter(
                is_active=True,
            )
            .filter(Q(applies_to_role="") | Q(applies_to_role=membership.role))
            .order_by("-percentage", "-flat_amount", "id")
            .first()
        )
        if applicable_scheme is None:
            continue

        payments_total = (
            appointment.cash_transactions.filter(transaction_type=CashTransactionType.PAYMENT).aggregate(total=Sum("amount"))["total"]
            or Decimal("0.00")
        ) - (
            appointment.cash_transactions.filter(transaction_type=CashTransactionType.REFUND).aggregate(total=Sum("amount"))["total"]
            or Decimal("0.00")
        )
        invoice = appointment.invoices.order_by("-issued_at", "-id").first()
        invoice_total = invoice.total_amount if invoice is not None else Decimal("0.00")
        base_amount = payments_total if applicable_scheme.basis == "COLLECTION" else invoice_total
        if base_amount <= Decimal("0.00"):
            continue

        commission_amount = (base_amount * applicable_scheme.percentage / Decimal("100.00")) + applicable_scheme.flat_amount
        record, created = CommissionRecord.objects.update_or_create(
            provider=appointment.provider,
            appointment=appointment,
            defaults={
                "scheme": applicable_scheme,
                "source_invoice": invoice,
                "period_start": period_start,
                "period_end": period_end,
                "base_amount": base_amount,
                "commission_amount": commission_amount,
                "status": CommissionRecordStatus.PENDING,
                "updated_by": actor,
            },
        )
        if created and actor and record.created_by_id is None:
            record.created_by = actor
            record.save(update_fields=["created_by"])
        created_or_updated += 1

    return created_or_updated


def execute_automation_rule(rule, *, actor=None):
    today = timezone.localdate()
    payload = {}
    status = AutomationRunStatus.SUCCESS
    summary = "Ejecucion completada."

    if rule.trigger == AutomationTrigger.APPOINTMENT_REMINDER:
        count = Appointment.objects.filter(
            scheduled_at__date=today,
            status__in=[AppointmentStatus.SCHEDULED, AppointmentStatus.CONFIRMED],
        ).count()
        payload = {"appointments_to_notify": count, "channel": rule.channel}
        summary = f"{count} citas listas para recordatorio."
    elif rule.trigger == AutomationTrigger.FOLLOW_UP:
        count = Appointment.objects.filter(
            status=AppointmentStatus.COMPLETED,
            checked_out_at__date__gte=today - timedelta(days=7),
        ).count()
        payload = {"completed_appointments_last_7_days": count}
        summary = f"{count} atenciones elegibles para seguimiento."
    elif rule.trigger == AutomationTrigger.INVOICE_OVERDUE:
        count = Invoice.objects.filter(due_date__lt=today).exclude(status__in=[InvoiceStatus.PAID, InvoiceStatus.CANCELED]).count()
        payload = {"overdue_invoices": count}
        summary = f"{count} facturas vencidas detectadas."
        status = AutomationRunStatus.WARNING if count else AutomationRunStatus.SUCCESS
    elif rule.trigger == AutomationTrigger.LOW_STOCK_ALERT:
        count = InventoryItem.objects.filter(stock_on_hand__lte=F("reorder_point"), is_active=True).count()
        payload = {"low_stock_items": count}
        summary = f"{count} items con stock critico."
        status = AutomationRunStatus.WARNING if count else AutomationRunStatus.SUCCESS
    else:
        payload = {"message": "Trigger no reconocido."}
        summary = "No se pudo ejecutar la regla."
        status = AutomationRunStatus.ERROR

    run = AutomationRun.objects.create(
        rule=rule,
        status=status,
        summary=summary,
        payload=payload,
        created_by=actor,
        updated_by=actor,
    )
    rule.last_run_at = run.executed_at
    rule.save(update_fields=["last_run_at"])
    return run
