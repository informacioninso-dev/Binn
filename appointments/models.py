from django.db import models
from django.conf import settings

from core.models import AuditModel
from patients.models import Patient


class AppointmentStatus(models.TextChoices):
    SCHEDULED = "SCHEDULED", "Programada"
    CONFIRMED = "CONFIRMED", "Confirmada"
    CHECKED_IN = "CHECKED_IN", "Check-in"
    IN_PROGRESS = "IN_PROGRESS", "En atencion"
    COMPLETED = "COMPLETED", "Completada"
    CANCELED = "CANCELED", "Cancelada"
    NO_SHOW = "NO_SHOW", "No asistio"


class AppointmentChannel(models.TextChoices):
    PHONE = "PHONE", "Telefono"
    WHATSAPP = "WHATSAPP", "WhatsApp"
    WEB = "WEB", "Web"
    WALK_IN = "WALK_IN", "Presencial"
    REFERRAL = "REFERRAL", "Referido"


class AppointmentType(models.TextChoices):
    FIRST_VISIT = "FIRST_VISIT", "Primera vez"
    FOLLOW_UP = "FOLLOW_UP", "Control"
    PROCEDURE = "PROCEDURE", "Procedimiento"
    EXAM = "EXAM", "Examen"
    OTHER = "OTHER", "Otro"


class Appointment(AuditModel):
    patient = models.ForeignKey(Patient, on_delete=models.PROTECT, related_name="appointments")
    location = models.ForeignKey(
        "operations.Location",
        on_delete=models.SET_NULL,
        related_name="appointments",
        null=True,
        blank=True,
    )
    provider = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="assigned_appointments",
        null=True,
        blank=True,
    )
    scheduled_at = models.DateTimeField("Fecha y hora")
    duration_minutes = models.PositiveSmallIntegerField("Duracion (min)", default=30)
    appointment_type = models.CharField(
        "Tipo de cita",
        max_length=20,
        choices=AppointmentType.choices,
        default=AppointmentType.FIRST_VISIT,
    )
    channel = models.CharField(
        "Canal",
        max_length=20,
        choices=AppointmentChannel.choices,
        default=AppointmentChannel.PHONE,
    )
    reason = models.CharField("Motivo", max_length=255, blank=True)
    notes = models.TextField("Notas", blank=True)
    front_desk_notes = models.TextField("Notas de recepcion", blank=True)
    checked_in_at = models.DateTimeField("Check-in", null=True, blank=True)
    checked_out_at = models.DateTimeField("Salida", null=True, blank=True)
    status = models.CharField(max_length=20, choices=AppointmentStatus.choices, default=AppointmentStatus.SCHEDULED)

    class Meta:
        ordering = ["-scheduled_at"]

    def __str__(self):
        return f"Cita {self.patient} - {self.scheduled_at:%Y-%m-%d %H:%M}"

    @property
    def front_desk_status(self):
        if self.status == AppointmentStatus.CANCELED:
            return "Cancelada"
        if self.status == AppointmentStatus.NO_SHOW:
            return "No asistio"
        if self.checked_out_at:
            return "Finalizada en recepcion"
        if self.checked_in_at:
            return "En sala de espera"
        if self.status == AppointmentStatus.CONFIRMED:
            return "Confirmada"
        return "Pendiente"
