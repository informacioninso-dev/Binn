from django.conf import settings
from django.db import models
from django.utils import timezone

from appointments.models import Appointment
from core.models import AuditModel
from patients.models import Patient


class EncounterType(models.TextChoices):
    FIRST_VISIT = "FIRST_VISIT", "Primera consulta"
    FOLLOW_UP = "FOLLOW_UP", "Control"
    PROCEDURE = "PROCEDURE", "Procedimiento"
    URGENT = "URGENT", "Urgencia"
    TELEMEDICINE = "TELEMEDICINE", "Telemedicina"


class EncounterStatus(models.TextChoices):
    DRAFT = "DRAFT", "Borrador"
    SIGNED = "SIGNED", "Firmada"


class DiagnosisType(models.TextChoices):
    PRIMARY = "PRIMARY", "Principal"
    SECONDARY = "SECONDARY", "Secundario"
    WORKING = "WORKING", "Impresion diagnostica"


class ClinicalOrderType(models.TextChoices):
    LAB = "LAB", "Laboratorio"
    IMAGING = "IMAGING", "Imagen"
    PROCEDURE = "PROCEDURE", "Procedimiento"
    INTERCONSULT = "INTERCONSULT", "Interconsulta"
    OTHER = "OTHER", "Otro"


class ClinicalOrderStatus(models.TextChoices):
    REQUESTED = "REQUESTED", "Solicitada"
    SCHEDULED = "SCHEDULED", "Agendada"
    COMPLETED = "COMPLETED", "Completada"
    CANCELED = "CANCELED", "Cancelada"


class PrescriptionStatus(models.TextChoices):
    ACTIVE = "ACTIVE", "Activa"
    COMPLETED = "COMPLETED", "Completada"
    CANCELED = "CANCELED", "Cancelada"


class DocumentType(models.TextChoices):
    CONSENT = "CONSENT", "Consentimiento"
    RESULT = "RESULT", "Resultado"
    CERTIFICATE = "CERTIFICATE", "Certificado"
    NOTE = "NOTE", "Nota"
    OTHER = "OTHER", "Otro"


class ClinicalEncounter(AuditModel):
    patient = models.ForeignKey(Patient, on_delete=models.PROTECT, related_name="clinical_encounters")
    appointment = models.ForeignKey(
        Appointment,
        on_delete=models.SET_NULL,
        related_name="clinical_encounters",
        null=True,
        blank=True,
    )
    provider = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="clinical_encounters",
        null=True,
        blank=True,
    )
    encounter_date = models.DateTimeField("Fecha de atencion", default=timezone.now)
    encounter_type = models.CharField(
        "Tipo de atencion",
        max_length=20,
        choices=EncounterType.choices,
        default=EncounterType.FIRST_VISIT,
    )
    status = models.CharField(
        "Estado",
        max_length=20,
        choices=EncounterStatus.choices,
        default=EncounterStatus.DRAFT,
    )
    chief_complaint = models.CharField("Motivo de consulta", max_length=255)
    vitals_summary = models.CharField("Signos vitales", max_length=255, blank=True)
    subjective = models.TextField("Subjetivo", blank=True)
    objective = models.TextField("Objetivo", blank=True)
    assessment = models.TextField("Analisis", blank=True)
    plan = models.TextField("Plan terapeutico", blank=True)

    class Meta:
        ordering = ["-encounter_date", "-id"]

    def __str__(self):
        return f"{self.patient.full_name} - {self.encounter_date:%Y-%m-%d %H:%M}"


class ClinicalDiagnosis(AuditModel):
    encounter = models.ForeignKey(
        ClinicalEncounter,
        on_delete=models.CASCADE,
        related_name="diagnoses",
    )
    diagnosis_type = models.CharField(
        "Tipo",
        max_length=20,
        choices=DiagnosisType.choices,
        default=DiagnosisType.PRIMARY,
    )
    code = models.CharField("Codigo", max_length=20, blank=True)
    description = models.CharField("Descripcion", max_length=255)
    notes = models.TextField("Notas", blank=True)

    class Meta:
        ordering = ["id"]

    def __str__(self):
        return self.description


class ClinicalOrder(AuditModel):
    encounter = models.ForeignKey(
        ClinicalEncounter,
        on_delete=models.CASCADE,
        related_name="orders",
    )
    order_type = models.CharField(
        "Tipo",
        max_length=20,
        choices=ClinicalOrderType.choices,
        default=ClinicalOrderType.LAB,
    )
    status = models.CharField(
        "Estado",
        max_length=20,
        choices=ClinicalOrderStatus.choices,
        default=ClinicalOrderStatus.REQUESTED,
    )
    description = models.CharField("Descripcion", max_length=255)
    instructions = models.TextField("Indicaciones", blank=True)
    scheduled_for = models.DateTimeField("Programado para", null=True, blank=True)
    result_summary = models.TextField("Resultado resumido", blank=True)

    class Meta:
        ordering = ["status", "id"]

    def __str__(self):
        return f"{self.get_order_type_display()} - {self.description}"


class Prescription(AuditModel):
    encounter = models.ForeignKey(
        ClinicalEncounter,
        on_delete=models.CASCADE,
        related_name="prescriptions",
    )
    medication_name = models.CharField("Medicamento", max_length=160)
    presentation = models.CharField("Presentacion", max_length=120, blank=True)
    route = models.CharField("Via", max_length=80, blank=True)
    dosage = models.CharField("Dosis", max_length=120)
    frequency = models.CharField("Frecuencia", max_length=120)
    duration_days = models.PositiveSmallIntegerField("Duracion (dias)", default=1)
    instructions = models.TextField("Indicaciones", blank=True)
    status = models.CharField(
        "Estado",
        max_length=20,
        choices=PrescriptionStatus.choices,
        default=PrescriptionStatus.ACTIVE,
    )

    class Meta:
        ordering = ["id"]

    def __str__(self):
        return self.medication_name


class ClinicalDocument(AuditModel):
    patient = models.ForeignKey(Patient, on_delete=models.CASCADE, related_name="clinical_documents")
    encounter = models.ForeignKey(
        ClinicalEncounter,
        on_delete=models.SET_NULL,
        related_name="documents",
        null=True,
        blank=True,
    )
    title = models.CharField("Titulo", max_length=160)
    document_type = models.CharField(
        "Tipo de documento",
        max_length=20,
        choices=DocumentType.choices,
        default=DocumentType.OTHER,
    )
    notes = models.TextField("Notas", blank=True)
    file = models.FileField("Archivo", upload_to="clinical_documents/%Y/%m/", blank=True)

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self):
        return self.title
