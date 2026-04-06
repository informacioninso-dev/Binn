from django.contrib.auth.decorators import login_required
from django.db import models
from django.db.models import Sum
from django.shortcuts import render
from django.utils import timezone


@login_required
def dashboard(request):
    tenant = getattr(request, "tenant", None)
    context = {
        "tenant_name": getattr(tenant, "name", ""),
        "tenant_schema": getattr(tenant, "schema_name", ""),
    }

    if tenant and tenant.schema_name != "public":
        from appointments.models import Appointment, AppointmentStatus
        from billing.models import CashTransaction, CashTransactionType, Invoice, InvoiceStatus
        from crm.models import Lead, LeadStage
        from clinical.models import ClinicalEncounter, ClinicalOrder, ClinicalOrderStatus
        from inventory.models import InventoryItem, PurchaseOrder, PurchaseOrderStatus
        from operations.models import AutomationRun, CommissionRecord, CommissionRecordStatus
        from patients.models import Patient

        today = timezone.localdate()
        receivable_total = (
            Invoice.objects.exclude(status=InvoiceStatus.CANCELED).aggregate(total=Sum("total_amount"))["total"] or 0
        ) - (Invoice.objects.exclude(status=InvoiceStatus.CANCELED).aggregate(total=Sum("paid_amount"))["total"] or 0)
        if receivable_total < 0:
            receivable_total = 0

        context.update(
            {
                "summary": {
                    "patients": Patient.objects.filter(is_active=True).count(),
                    "appointments_today": Appointment.objects.filter(scheduled_at__date=today).count(),
                    "leads_open": Lead.objects.filter(is_active=True).exclude(stage=LeadStage.WON).count(),
                    "cash_today": CashTransaction.objects.filter(
                        transaction_type=CashTransactionType.PAYMENT,
                        posted_at__date=today,
                    ).aggregate(total=Sum("amount"))["total"]
                    or 0,
                    "encounters_today": ClinicalEncounter.objects.filter(encounter_date__date=today).count(),
                    "receivable": receivable_total,
                    "low_stock": InventoryItem.objects.filter(stock_on_hand__lte=models.F("reorder_point"), is_active=True).count(),
                    "pending_commissions": CommissionRecord.objects.filter(status=CommissionRecordStatus.PENDING).count(),
                    "automation_runs": AutomationRun.objects.count(),
                },
                "appointments_today": Appointment.objects.select_related("patient", "provider").filter(
                    scheduled_at__date=today
                ).order_by("scheduled_at")[:6],
                "recent_invoices": Invoice.objects.select_related("patient").order_by("-issued_at", "-id")[:5],
                "recent_leads": Lead.objects.select_related("assigned_to").filter(is_active=True).order_by(
                    "-created_at"
                )[:5],
                "recent_encounters": ClinicalEncounter.objects.select_related("patient", "provider").order_by(
                    "-encounter_date"
                )[:5],
                "recent_purchase_orders": PurchaseOrder.objects.select_related("supplier").order_by("-ordered_at", "-id")[:5],
                "recent_automation_runs": AutomationRun.objects.select_related("rule").order_by("-executed_at", "-id")[:5],
                "alerts": {
                    "pending_appointments": Appointment.objects.filter(
                        status=AppointmentStatus.SCHEDULED
                    ).count(),
                    "checked_in": Appointment.objects.filter(
                        status=AppointmentStatus.CHECKED_IN
                    ).count(),
                    "no_show": Appointment.objects.filter(status=AppointmentStatus.NO_SHOW).count(),
                    "open_orders": ClinicalOrder.objects.filter(
                        status__in=[ClinicalOrderStatus.REQUESTED, ClinicalOrderStatus.SCHEDULED]
                    ).count(),
                    "open_invoices": Invoice.objects.exclude(
                        status__in=[InvoiceStatus.PAID, InvoiceStatus.CANCELED]
                    ).count(),
                    "open_purchase_orders": PurchaseOrder.objects.filter(status=PurchaseOrderStatus.OPEN).count(),
                    "pending_commissions": CommissionRecord.objects.filter(status=CommissionRecordStatus.PENDING).count(),
                },
            }
        )

    return render(request, "pages/dashboard.html", context)
