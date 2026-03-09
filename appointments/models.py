from django.db import models

from core.models import AuditModel
from patients.models import Patient


class AppointmentStatus(models.TextChoices):
    SCHEDULED = "SCHEDULED", "Programada"
    CONFIRMED = "CONFIRMED", "Confirmada"
    IN_PROGRESS = "IN_PROGRESS", "En atencion"
    COMPLETED = "COMPLETED", "Completada"
    CANCELED = "CANCELED", "Cancelada"
    NO_SHOW = "NO_SHOW", "No asistio"


class Appointment(AuditModel):
    patient = models.ForeignKey(Patient, on_delete=models.PROTECT, related_name="appointments")
    scheduled_at = models.DateTimeField("Fecha y hora")
    duration_minutes = models.PositiveSmallIntegerField("Duracion (min)", default=30)
    reason = models.CharField("Motivo", max_length=255, blank=True)
    notes = models.TextField("Notas", blank=True)
    status = models.CharField(max_length=20, choices=AppointmentStatus.choices, default=AppointmentStatus.SCHEDULED)

    class Meta:
        ordering = ["-scheduled_at"]

    def __str__(self):
        return f"Cita {self.patient} - {self.scheduled_at:%Y-%m-%d %H:%M}"
