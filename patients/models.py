from django.db import models

from core.models import AuditModel


class DocumentType(models.TextChoices):
    NATIONAL_ID = "NATIONAL_ID", "Cedula"
    PASSPORT = "PASSPORT", "Pasaporte"
    RUC = "RUC", "RUC"
    OTHER = "OTHER", "Otro"


class SexType(models.TextChoices):
    FEMALE = "F", "Femenino"
    MALE = "M", "Masculino"
    OTHER = "O", "Otro"
    UNDISCLOSED = "U", "No especificado"


class PatientOrigin(models.TextChoices):
    ORGANIC = "ORGANIC", "Organico"
    REFERRAL = "REFERRAL", "Referido"
    WHATSAPP = "WHATSAPP", "WhatsApp"
    CAMPAIGN = "CAMPAIGN", "Campana"
    WALK_IN = "WALK_IN", "Espontaneo"
    INSURER = "INSURER", "Aseguradora"
    OTHER = "OTHER", "Otro"


class Patient(AuditModel):
    mrn = models.CharField("Historia clinica", max_length=32, unique=True)
    document_type = models.CharField("Tipo de documento", max_length=20, choices=DocumentType.choices)
    document_number = models.CharField("Numero de documento", max_length=30, db_index=True)
    first_name = models.CharField("Nombres", max_length=120)
    last_name = models.CharField("Apellidos", max_length=120)
    birth_date = models.DateField("Fecha de nacimiento", null=True, blank=True)
    sex = models.CharField("Sexo", max_length=1, choices=SexType.choices, default=SexType.UNDISCLOSED)
    source = models.CharField("Origen", max_length=20, choices=PatientOrigin.choices, default=PatientOrigin.ORGANIC)
    phone = models.CharField("Telefono", max_length=30, blank=True)
    email = models.EmailField("Correo", blank=True)
    address = models.CharField("Direccion", max_length=255, blank=True)
    responsible_party_name = models.CharField("Responsable", max_length=120, blank=True)
    responsible_party_phone = models.CharField("Telefono responsable", max_length=30, blank=True)
    emergency_contact_name = models.CharField("Contacto de emergencia", max_length=120, blank=True)
    emergency_contact_phone = models.CharField("Telefono de emergencia", max_length=30, blank=True)
    insurance_provider = models.CharField("Aseguradora", max_length=120, blank=True)
    insurance_plan = models.CharField("Plan/Convenio", max_length=120, blank=True)
    notes = models.TextField("Notas administrativas", blank=True)
    marketing_opt_in = models.BooleanField("Acepta recordatorios y promociones", default=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["last_name", "first_name"]
        constraints = [
            models.UniqueConstraint(
                fields=["document_type", "document_number"],
                name="patients_unique_document",
            )
        ]

    def __str__(self):
        return f"{self.last_name}, {self.first_name} ({self.mrn})"

    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}".strip()
