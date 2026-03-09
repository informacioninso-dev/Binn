from django.contrib import admin

from .models import Patient


@admin.register(Patient)
class PatientAdmin(admin.ModelAdmin):
    list_display = ("mrn", "last_name", "first_name", "document_type", "document_number", "is_active")
    list_filter = ("is_active", "document_type", "sex")
    search_fields = ("mrn", "last_name", "first_name", "document_number")
