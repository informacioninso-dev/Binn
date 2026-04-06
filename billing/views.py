from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Q, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from tenants.permissions import BILLING_ALLOWED_ROLES, tenant_capability_required, tenant_role_required

from .forms import CashTransactionForm, CoverageAgreementForm, InvoiceForm
from .models import CashTransaction, CashTransactionType, CoverageAgreement, Invoice, InvoiceStatus


def _sum_transactions(transaction_type):
    return (
        CashTransaction.objects.filter(transaction_type=transaction_type).aggregate(total=Sum("amount"))["total"]
        or 0
    )


def _sum_invoice_balance():
    total_invoiced = Invoice.objects.exclude(status=InvoiceStatus.CANCELED).aggregate(total=Sum("total_amount"))["total"] or 0
    total_paid = Invoice.objects.exclude(status=InvoiceStatus.CANCELED).aggregate(total=Sum("paid_amount"))["total"] or 0
    balance = total_invoiced - total_paid
    return balance if balance > 0 else 0


def _save_with_audit(instance, request):
    if instance.pk:
        instance.updated_by = request.user
    else:
        instance.created_by = request.user
        instance.updated_by = request.user
    instance.save()
    return instance


def _sync_invoice(invoice):
    if invoice is not None:
        invoice.refresh_payment_snapshot()


@login_required
@tenant_capability_required("billing.basic")
@tenant_role_required(*BILLING_ALLOWED_ROLES)
def index(request):
    q = (request.GET.get("q") or "").strip()
    transaction_type = (request.GET.get("transaction_type") or "").strip()

    transactions = CashTransaction.objects.select_related("patient", "appointment", "invoice", "invoice__location")
    if q:
        transactions = transactions.filter(
            Q(concept__icontains=q)
            | Q(reference__icontains=q)
            | Q(patient__first_name__icontains=q)
            | Q(patient__last_name__icontains=q)
            | Q(patient__mrn__icontains=q)
            | Q(invoice__invoice_number__icontains=q)
        )
    if transaction_type:
        transactions = transactions.filter(transaction_type=transaction_type)

    today = timezone.localdate()
    context = {
        "transactions": transactions.order_by("-posted_at", "-id")[:100],
        "recent_invoices": Invoice.objects.select_related("patient", "coverage_agreement", "location").order_by("-issued_at")[:8],
        "recent_agreements": CoverageAgreement.objects.order_by("name")[:8],
        "q": q,
        "transaction_type": transaction_type,
        "type_choices": CashTransactionType.choices,
        "summary": {
            "today_total": (
                CashTransaction.objects.filter(
                    transaction_type=CashTransactionType.PAYMENT,
                    posted_at__date=today,
                ).aggregate(total=Sum("amount"))["total"]
                or 0
            ),
            "payments": _sum_transactions(CashTransactionType.PAYMENT),
            "refunds": _sum_transactions(CashTransactionType.REFUND),
            "expenses": _sum_transactions(CashTransactionType.EXPENSE),
            "receivable": _sum_invoice_balance(),
            "open_invoices": Invoice.objects.exclude(status__in=[InvoiceStatus.PAID, InvoiceStatus.CANCELED]).count(),
        },
    }
    return render(request, "billing/index.html", context)


@login_required
@tenant_capability_required("billing.basic")
@tenant_role_required(*BILLING_ALLOWED_ROLES)
def create(request):
    initial = {}
    invoice_id = request.GET.get("invoice")
    patient_id = request.GET.get("patient")
    appointment_id = request.GET.get("appointment")
    if invoice_id:
        initial["invoice"] = invoice_id
    if patient_id:
        initial["patient"] = patient_id
    if appointment_id:
        initial["appointment"] = appointment_id

    if request.method == "POST":
        form = CashTransactionForm(request.POST, tenant=request.tenant)
        if form.is_valid():
            transaction = form.save(commit=False)
            _save_with_audit(transaction, request)
            _sync_invoice(transaction.invoice)
            messages.success(request, "Movimiento de caja registrado correctamente.")
            return redirect("billing:index")
    else:
        form = CashTransactionForm(tenant=request.tenant, initial=initial)

    return render(
        request,
        "billing/form.html",
        {"form": form, "page_title": "Nuevo movimiento de caja", "submit_label": "Guardar movimiento"},
    )


@login_required
@tenant_capability_required("billing.ar")
@tenant_role_required(*BILLING_ALLOWED_ROLES)
def invoice_list(request):
    q = (request.GET.get("q") or "").strip()
    status = (request.GET.get("status") or "").strip()
    invoices = Invoice.objects.select_related("patient", "coverage_agreement", "location")
    if q:
        invoices = invoices.filter(
            Q(invoice_number__icontains=q)
            | Q(patient__first_name__icontains=q)
            | Q(patient__last_name__icontains=q)
            | Q(patient__mrn__icontains=q)
            | Q(location__name__icontains=q)
        )
    if status:
        invoices = invoices.filter(status=status)

    return render(
        request,
        "billing/invoice_list.html",
        {
            "invoices": invoices.order_by("-issued_at", "-id")[:100],
            "q": q,
            "status": status,
            "status_choices": InvoiceStatus.choices,
            "summary": {
                "issued": Invoice.objects.filter(status=InvoiceStatus.ISSUED).count(),
                "partial": Invoice.objects.filter(status=InvoiceStatus.PARTIAL).count(),
                "overdue": Invoice.objects.filter(status=InvoiceStatus.OVERDUE).count(),
                "receivable": _sum_invoice_balance(),
            },
        },
    )


@login_required
@tenant_capability_required("billing.ar")
@tenant_role_required(*BILLING_ALLOWED_ROLES)
def invoice_create(request):
    initial = {}
    patient_id = request.GET.get("patient")
    appointment_id = request.GET.get("appointment")
    if patient_id:
        initial["patient"] = patient_id
    if appointment_id:
        initial["appointment"] = appointment_id

    if request.method == "POST":
        form = InvoiceForm(request.POST, tenant=request.tenant)
        if form.is_valid():
            invoice = form.save(commit=False)
            _save_with_audit(invoice, request)
            invoice.refresh_payment_snapshot()
            messages.success(request, "Factura registrada correctamente.")
            return redirect("billing:invoice_detail", pk=invoice.pk)
    else:
        form = InvoiceForm(tenant=request.tenant, initial=initial)

    return render(
        request,
        "billing/invoice_form.html",
        {"form": form, "page_title": "Nueva factura", "submit_label": "Guardar factura"},
    )


@login_required
@tenant_capability_required("billing.ar")
@tenant_role_required(*BILLING_ALLOWED_ROLES)
def invoice_detail(request, pk):
    invoice = get_object_or_404(
        Invoice.objects.select_related("patient", "appointment", "coverage_agreement", "location"),
        pk=pk,
    )
    invoice.refresh_payment_snapshot()
    return render(
        request,
        "billing/invoice_detail.html",
        {
            "invoice": invoice,
            "payments": invoice.cash_transactions.order_by("-posted_at", "-id"),
        },
    )


@login_required
@tenant_capability_required("billing.ar")
@tenant_role_required(*BILLING_ALLOWED_ROLES)
def agreement_list(request):
    q = (request.GET.get("q") or "").strip()
    agreements = CoverageAgreement.objects.all()
    if q:
        agreements = agreements.filter(Q(name__icontains=q) | Q(code__icontains=q) | Q(contact_name__icontains=q))

    return render(
        request,
        "billing/agreement_list.html",
        {
            "agreements": agreements.order_by("name")[:100],
            "q": q,
            "summary": {
                "active": CoverageAgreement.objects.filter(is_active=True).count(),
                "inactive": CoverageAgreement.objects.filter(is_active=False).count(),
                "with_credit": CoverageAgreement.objects.filter(default_credit_days__gt=0).count(),
            },
        },
    )


@login_required
@tenant_capability_required("billing.ar")
@tenant_role_required(*BILLING_ALLOWED_ROLES)
def agreement_create(request):
    if request.method == "POST":
        form = CoverageAgreementForm(request.POST)
        if form.is_valid():
            agreement = form.save(commit=False)
            _save_with_audit(agreement, request)
            messages.success(request, "Convenio registrado correctamente.")
            return redirect("billing:agreements")
    else:
        form = CoverageAgreementForm(initial={"is_active": True})

    return render(
        request,
        "billing/agreement_form.html",
        {"form": form, "page_title": "Nuevo convenio", "submit_label": "Guardar convenio"},
    )
