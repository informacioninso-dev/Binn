from django.conf import settings
from django.db import models

from core.models import AuditModel
from patients.models import Patient


class LeadSource(models.TextChoices):
    WEBSITE = "WEBSITE", "Web"
    WHATSAPP = "WHATSAPP", "WhatsApp"
    PHONE = "PHONE", "Telefono"
    WALK_IN = "WALK_IN", "Presencial"
    REFERRAL = "REFERRAL", "Referido"
    CAMPAIGN = "CAMPAIGN", "Campana"
    INSURER = "INSURER", "Aseguradora"
    OTHER = "OTHER", "Otro"


class LeadStage(models.TextChoices):
    NEW = "NEW", "Nuevo"
    CONTACTED = "CONTACTED", "Contactado"
    QUALIFIED = "QUALIFIED", "Calificado"
    APPOINTMENT = "APPOINTMENT", "Cita agendada"
    WON = "WON", "Ganado"
    LOST = "LOST", "Perdido"


class Lead(AuditModel):
    full_name = models.CharField("Nombre", max_length=160)
    phone = models.CharField("Telefono", max_length=30, blank=True)
    email = models.EmailField("Correo", blank=True)
    source = models.CharField("Origen", max_length=20, choices=LeadSource.choices, default=LeadSource.WHATSAPP)
    stage = models.CharField("Etapa", max_length=20, choices=LeadStage.choices, default=LeadStage.NEW)
    interested_service = models.CharField("Servicio de interes", max_length=160, blank=True)
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="crm_leads",
        null=True,
        blank=True,
    )
    next_contact_at = models.DateTimeField("Proximo contacto", null=True, blank=True)
    converted_patient = models.ForeignKey(
        Patient,
        on_delete=models.SET_NULL,
        related_name="source_leads",
        null=True,
        blank=True,
    )
    notes = models.TextField("Notas", blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["stage", "full_name"]

    def __str__(self):
        return f"{self.full_name} ({self.get_stage_display()})"

