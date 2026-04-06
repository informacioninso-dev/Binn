from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render

from billing.models import CashTransaction
from tenants.permissions import tenant_capability_required, tenant_role_required

from .forms import PatientForm
from .models import Patient


def _save_patient(form, request, *, success_message: str):
    patient = form.save(commit=False)
    if patient.pk:
        patient.updated_by = request.user
    else:
        patient.created_by = request.user
        patient.updated_by = request.user
    patient.save()
    messages.success(request, success_message)
    return redirect("patients:detail", pk=patient.pk)


@login_required
@tenant_capability_required("patients.basic")
@tenant_role_required()
def index(request):
    q = (request.GET.get("q") or "").strip()
    status = (request.GET.get("status") or "").strip().lower()

    patients = Patient.objects.all()
    if q:
        patients = patients.filter(
            Q(last_name__icontains=q)
            | Q(first_name__icontains=q)
            | Q(mrn__icontains=q)
            | Q(document_number__icontains=q)
            | Q(phone__icontains=q)
            | Q(email__icontains=q)
        )
    if status == "active":
        patients = patients.filter(is_active=True)
    elif status == "inactive":
        patients = patients.filter(is_active=False)

    patients = patients.order_by("last_name", "first_name")[:100]

    context = {
        "patients": patients,
        "q": q,
        "status": status,
        "summary": {
            "total": Patient.objects.count(),
            "active": Patient.objects.filter(is_active=True).count(),
            "with_insurance": Patient.objects.exclude(insurance_provider="").count(),
            "marketing_opt_in": Patient.objects.filter(marketing_opt_in=True).count(),
        },
    }
    return render(request, "patients/index.html", context)


@login_required
@tenant_capability_required("patients.basic")
@tenant_role_required()
def detail(request, pk):
    from billing.models import CashTransaction, Invoice
    from clinical.models import ClinicalDocument, ClinicalEncounter

    patient = get_object_or_404(Patient, pk=pk)
    appointments = patient.appointments.select_related("provider").order_by("-scheduled_at")[:8]
    cash_transactions = CashTransaction.objects.filter(patient=patient).select_related("appointment", "invoice")[:8]
    invoices = Invoice.objects.filter(patient=patient).select_related("coverage_agreement")[:8]
    encounters = ClinicalEncounter.objects.filter(patient=patient).select_related("provider")[:8]
    clinical_documents = ClinicalDocument.objects.filter(patient=patient)[:8]
    return render(
        request,
        "patients/detail.html",
        {
            "patient": patient,
            "appointments": appointments,
            "cash_transactions": cash_transactions,
            "invoices": invoices,
            "encounters": encounters,
            "clinical_documents": clinical_documents,
        },
    )


@login_required
@tenant_capability_required("patients.basic")
@tenant_role_required()
def create(request):
    if request.method == "POST":
        form = PatientForm(request.POST)
        if form.is_valid():
            return _save_patient(form, request, success_message="Paciente creado correctamente.")
    else:
        form = PatientForm(initial={"is_active": True, "marketing_opt_in": True})

    return render(
        request,
        "patients/form.html",
        {"form": form, "page_title": "Nuevo paciente", "submit_label": "Guardar paciente"},
    )


@login_required
@tenant_capability_required("patients.basic")
@tenant_role_required()
def edit(request, pk):
    patient = get_object_or_404(Patient, pk=pk)
    if request.method == "POST":
        form = PatientForm(request.POST, instance=patient)
        if form.is_valid():
            return _save_patient(form, request, success_message="Paciente actualizado correctamente.")
    else:
        form = PatientForm(instance=patient)

    return render(
        request,
        "patients/form.html",
        {
            "form": form,
            "patient": patient,
            "page_title": f"Editar paciente: {patient.full_name}",
            "submit_label": "Guardar cambios",
        },
    )
