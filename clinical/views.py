from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from tenants.permissions import (
    CLINICAL_ALLOWED_ROLES,
    tenant_capability_required,
    tenant_role_required,
)

from .forms import (
    ClinicalDiagnosisForm,
    ClinicalDocumentForm,
    ClinicalEncounterForm,
    ClinicalOrderForm,
    PrescriptionForm,
)
from .models import ClinicalDocument, ClinicalEncounter, ClinicalOrder, ClinicalOrderStatus


def _save_with_audit(obj, request):
    if obj.pk:
        obj.updated_by = request.user
    else:
        obj.created_by = request.user
        obj.updated_by = request.user
    obj.save()


@login_required
@tenant_capability_required("clinical.basic")
@tenant_role_required(*CLINICAL_ALLOWED_ROLES)
def index(request):
    q = (request.GET.get("q") or "").strip()
    encounters = ClinicalEncounter.objects.select_related("patient", "provider", "appointment")
    if q:
        encounters = encounters.filter(
            Q(patient__first_name__icontains=q)
            | Q(patient__last_name__icontains=q)
            | Q(patient__mrn__icontains=q)
            | Q(chief_complaint__icontains=q)
        )

    today = timezone.localdate()
    context = {
        "q": q,
        "encounters": encounters.order_by("-encounter_date")[:100],
        "summary": {
            "encounters_today": ClinicalEncounter.objects.filter(encounter_date__date=today).count(),
            "open_orders": ClinicalOrder.objects.filter(
                status__in=[ClinicalOrderStatus.REQUESTED, ClinicalOrderStatus.SCHEDULED]
            ).count(),
            "documents": ClinicalDocument.objects.count(),
            "signed_notes": ClinicalEncounter.objects.filter(status="SIGNED").count(),
        },
        "pending_orders": ClinicalOrder.objects.select_related("encounter__patient").filter(
            status__in=[ClinicalOrderStatus.REQUESTED, ClinicalOrderStatus.SCHEDULED]
        )[:8],
    }
    return render(request, "clinical/index.html", context)


@login_required
@tenant_capability_required("clinical.basic")
@tenant_role_required(*CLINICAL_ALLOWED_ROLES)
def create(request):
    initial = {}
    patient_id = request.GET.get("patient")
    appointment_id = request.GET.get("appointment")
    provider_id = request.GET.get("provider")
    if patient_id:
        initial["patient"] = patient_id
    if appointment_id:
        initial["appointment"] = appointment_id
    if provider_id:
        initial["provider"] = provider_id
    if appointment_id and (not patient_id or not provider_id):
        from appointments.models import Appointment

        appointment = Appointment.objects.select_related("patient", "provider").filter(pk=appointment_id).first()
        if appointment:
            initial.setdefault("patient", appointment.patient_id)
            if appointment.provider_id:
                initial.setdefault("provider", appointment.provider_id)

    if request.method == "POST":
        form = ClinicalEncounterForm(request.POST, tenant=request.tenant)
        if form.is_valid():
            encounter = form.save(commit=False)
            _save_with_audit(encounter, request)
            messages.success(request, "Evolucion clinica creada correctamente.")
            return redirect("clinical:detail", pk=encounter.pk)
    else:
        form = ClinicalEncounterForm(tenant=request.tenant, initial=initial)

    return render(
        request,
        "clinical/encounter_form.html",
        {"form": form, "page_title": "Nueva evolucion clinica", "submit_label": "Guardar evolucion"},
    )


@login_required
@tenant_capability_required("clinical.basic")
@tenant_role_required(*CLINICAL_ALLOWED_ROLES)
def detail(request, pk):
    encounter = get_object_or_404(
        ClinicalEncounter.objects.select_related("patient", "appointment", "provider"),
        pk=pk,
    )
    context = {
        "encounter": encounter,
        "diagnoses": encounter.diagnoses.all(),
        "orders": encounter.orders.all(),
        "prescriptions": encounter.prescriptions.all(),
        "documents": encounter.documents.all(),
    }
    return render(request, "clinical/detail.html", context)


@login_required
@tenant_capability_required("clinical.basic")
@tenant_role_required(*CLINICAL_ALLOWED_ROLES)
def edit(request, pk):
    encounter = get_object_or_404(ClinicalEncounter, pk=pk)
    if request.method == "POST":
        form = ClinicalEncounterForm(request.POST, instance=encounter, tenant=request.tenant)
        if form.is_valid():
            encounter = form.save(commit=False)
            _save_with_audit(encounter, request)
            messages.success(request, "Evolucion clinica actualizada.")
            return redirect("clinical:detail", pk=encounter.pk)
    else:
        form = ClinicalEncounterForm(instance=encounter, tenant=request.tenant)

    return render(
        request,
        "clinical/encounter_form.html",
        {
            "form": form,
            "encounter": encounter,
            "page_title": f"Editar evolucion: {encounter.patient.full_name}",
            "submit_label": "Guardar cambios",
        },
    )


def _related_form_response(request, form, *, page_title, submit_label, cancel_url):
    return render(
        request,
        "clinical/related_form.html",
        {
            "form": form,
            "page_title": page_title,
            "submit_label": submit_label,
            "cancel_url": cancel_url,
        },
    )


@login_required
@tenant_capability_required("clinical.basic")
@tenant_role_required(*CLINICAL_ALLOWED_ROLES)
def add_diagnosis(request, pk):
    encounter = get_object_or_404(ClinicalEncounter, pk=pk)
    if request.method == "POST":
        form = ClinicalDiagnosisForm(request.POST)
        if form.is_valid():
            diagnosis = form.save(commit=False)
            diagnosis.encounter = encounter
            _save_with_audit(diagnosis, request)
            messages.success(request, "Diagnostico agregado.")
            return redirect("clinical:detail", pk=encounter.pk)
    else:
        form = ClinicalDiagnosisForm()

    return _related_form_response(
        request,
        form,
        page_title=f"Agregar diagnostico a {encounter.patient.full_name}",
        submit_label="Guardar diagnostico",
        cancel_url=reverse("clinical:detail", kwargs={"pk": encounter.pk}),
    )


@login_required
@tenant_capability_required("clinical.basic")
@tenant_role_required(*CLINICAL_ALLOWED_ROLES)
def add_order(request, pk):
    encounter = get_object_or_404(ClinicalEncounter, pk=pk)
    if request.method == "POST":
        form = ClinicalOrderForm(request.POST)
        if form.is_valid():
            order = form.save(commit=False)
            order.encounter = encounter
            _save_with_audit(order, request)
            messages.success(request, "Orden clinica registrada.")
            return redirect("clinical:detail", pk=encounter.pk)
    else:
        form = ClinicalOrderForm()

    return _related_form_response(
        request,
        form,
        page_title=f"Agregar orden a {encounter.patient.full_name}",
        submit_label="Guardar orden",
        cancel_url=reverse("clinical:detail", kwargs={"pk": encounter.pk}),
    )


@login_required
@tenant_capability_required("clinical.basic")
@tenant_role_required(*CLINICAL_ALLOWED_ROLES)
def add_prescription(request, pk):
    encounter = get_object_or_404(ClinicalEncounter, pk=pk)
    if request.method == "POST":
        form = PrescriptionForm(request.POST)
        if form.is_valid():
            prescription = form.save(commit=False)
            prescription.encounter = encounter
            _save_with_audit(prescription, request)
            messages.success(request, "Receta registrada.")
            return redirect("clinical:detail", pk=encounter.pk)
    else:
        form = PrescriptionForm()

    return _related_form_response(
        request,
        form,
        page_title=f"Agregar receta a {encounter.patient.full_name}",
        submit_label="Guardar receta",
        cancel_url=reverse("clinical:detail", kwargs={"pk": encounter.pk}),
    )


@login_required
@tenant_capability_required("clinical.basic")
@tenant_role_required(*CLINICAL_ALLOWED_ROLES)
def add_document(request, pk):
    encounter = get_object_or_404(ClinicalEncounter.objects.select_related("patient"), pk=pk)
    if request.method == "POST":
        form = ClinicalDocumentForm(request.POST, request.FILES)
        if form.is_valid():
            document = form.save(commit=False)
            document.encounter = encounter
            if not document.patient_id:
                document.patient = encounter.patient
            _save_with_audit(document, request)
            messages.success(request, "Documento clinico agregado.")
            return redirect("clinical:detail", pk=encounter.pk)
    else:
        form = ClinicalDocumentForm(initial={"patient": encounter.patient})

    return _related_form_response(
        request,
        form,
        page_title=f"Agregar documento a {encounter.patient.full_name}",
        submit_label="Guardar documento",
        cancel_url=reverse("clinical:detail", kwargs={"pk": encounter.pk}),
    )
