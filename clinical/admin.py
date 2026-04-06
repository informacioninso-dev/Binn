from django.contrib import admin

from .models import (
    ClinicalDiagnosis,
    ClinicalDocument,
    ClinicalEncounter,
    ClinicalOrder,
    Prescription,
)


@admin.register(ClinicalEncounter)
class ClinicalEncounterAdmin(admin.ModelAdmin):
    list_display = ("encounter_date", "patient", "provider", "encounter_type", "status")
    list_filter = ("encounter_type", "status")
    search_fields = ("patient__first_name", "patient__last_name", "patient__mrn", "chief_complaint")


@admin.register(ClinicalDiagnosis)
class ClinicalDiagnosisAdmin(admin.ModelAdmin):
    list_display = ("encounter", "diagnosis_type", "code", "description")
    list_filter = ("diagnosis_type",)
    search_fields = ("code", "description", "encounter__patient__mrn")


@admin.register(ClinicalOrder)
class ClinicalOrderAdmin(admin.ModelAdmin):
    list_display = ("encounter", "order_type", "status", "description", "scheduled_for")
    list_filter = ("order_type", "status")
    search_fields = ("description", "encounter__patient__mrn", "encounter__patient__last_name")


@admin.register(Prescription)
class PrescriptionAdmin(admin.ModelAdmin):
    list_display = ("encounter", "medication_name", "dosage", "frequency", "status")
    list_filter = ("status",)
    search_fields = ("medication_name", "encounter__patient__mrn", "encounter__patient__last_name")


@admin.register(ClinicalDocument)
class ClinicalDocumentAdmin(admin.ModelAdmin):
    list_display = ("title", "patient", "document_type", "created_at")
    list_filter = ("document_type",)
    search_fields = ("title", "patient__mrn", "patient__last_name")
