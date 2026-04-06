from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from tenants.models import TenantMembership
from tenants.permissions import tenant_capability_required, tenant_role_required

from .forms import AppointmentForm
from .models import Appointment, AppointmentStatus


APPOINTMENT_ALLOWED_ROLES = (
    TenantMembership.ROLE_RECEPTION,
    TenantMembership.ROLE_ASSISTANT,
    TenantMembership.ROLE_DOCTOR,
    TenantMembership.ROLE_CASHIER,
    TenantMembership.ROLE_CLINIC_ADMIN,
)


def _save_appointment(form, request, *, success_message: str):
    appointment = form.save(commit=False)
    if appointment.pk:
        appointment.updated_by = request.user
    else:
        appointment.created_by = request.user
        appointment.updated_by = request.user
    appointment.save()
    messages.success(request, success_message)
    return redirect("appointments:index")


@login_required
@tenant_capability_required("appointments.basic")
@tenant_role_required(*APPOINTMENT_ALLOWED_ROLES)
def index(request):
    q = (request.GET.get("q") or "").strip()
    status = (request.GET.get("status") or "").strip()

    appointments = Appointment.objects.select_related("patient", "provider", "location")
    if q:
        appointments = appointments.filter(
            Q(patient__first_name__icontains=q)
            | Q(patient__last_name__icontains=q)
            | Q(patient__mrn__icontains=q)
            | Q(reason__icontains=q)
        )
    if status:
        appointments = appointments.filter(status=status)

    today = timezone.localdate()
    context = {
        "appointments": appointments.order_by("scheduled_at")[:100],
        "q": q,
        "status": status,
        "status_choices": AppointmentStatus.choices,
        "summary": {
            "today": Appointment.objects.filter(scheduled_at__date=today).count(),
            "checked_in": Appointment.objects.filter(status=AppointmentStatus.CHECKED_IN).count(),
            "pending": Appointment.objects.filter(status=AppointmentStatus.SCHEDULED).count(),
            "confirmed": Appointment.objects.filter(status=AppointmentStatus.CONFIRMED).count(),
        },
    }
    return render(request, "appointments/index.html", context)


@login_required
@tenant_capability_required("appointments.basic")
@tenant_role_required(*APPOINTMENT_ALLOWED_ROLES)
def create(request):
    initial = {}
    patient_id = request.GET.get("patient")
    if patient_id:
        initial["patient"] = patient_id

    if request.method == "POST":
        form = AppointmentForm(request.POST, tenant=request.tenant)
        if form.is_valid():
            return _save_appointment(form, request, success_message="Cita creada correctamente.")
    else:
        form = AppointmentForm(tenant=request.tenant, initial=initial)

    return render(
        request,
        "appointments/form.html",
        {"form": form, "page_title": "Nueva cita", "submit_label": "Guardar cita"},
    )


@login_required
@tenant_capability_required("appointments.basic")
@tenant_role_required(*APPOINTMENT_ALLOWED_ROLES)
def edit(request, pk):
    appointment = get_object_or_404(Appointment, pk=pk)
    if request.method == "POST":
        form = AppointmentForm(request.POST, instance=appointment, tenant=request.tenant)
        if form.is_valid():
            return _save_appointment(form, request, success_message="Cita actualizada correctamente.")
    else:
        form = AppointmentForm(instance=appointment, tenant=request.tenant)

    return render(
        request,
        "appointments/form.html",
        {
            "form": form,
            "appointment": appointment,
            "page_title": f"Editar cita: {appointment.patient.full_name}",
            "submit_label": "Guardar cambios",
        },
    )


@login_required
@tenant_capability_required("appointments.basic")
@tenant_role_required(*APPOINTMENT_ALLOWED_ROLES)
def quick_action(request, pk, action):
    if request.method != "POST":
        return redirect("appointments:index")

    appointment = get_object_or_404(Appointment, pk=pk)
    now = timezone.now()

    if action == "confirm":
        appointment.status = AppointmentStatus.CONFIRMED
        message = "Cita confirmada."
    elif action == "check_in":
        appointment.status = AppointmentStatus.CHECKED_IN
        appointment.checked_in_at = appointment.checked_in_at or now
        message = "Paciente marcado en recepcion."
    elif action == "complete":
        appointment.status = AppointmentStatus.COMPLETED
        appointment.checked_in_at = appointment.checked_in_at or now
        appointment.checked_out_at = now
        message = "Cita finalizada."
    elif action == "cancel":
        appointment.status = AppointmentStatus.CANCELED
        message = "Cita cancelada."
    elif action == "no_show":
        appointment.status = AppointmentStatus.NO_SHOW
        message = "Cita marcada como no asistio."
    else:
        messages.error(request, "Accion de agenda no reconocida.")
        return redirect("appointments:index")

    appointment.updated_by = request.user
    appointment.save(
        update_fields=["status", "checked_in_at", "checked_out_at", "updated_by", "updated_at"]
    )
    messages.success(request, message)
    return redirect("appointments:index")
