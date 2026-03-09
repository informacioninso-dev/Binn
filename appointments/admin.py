from django.contrib import admin

from .models import Appointment


@admin.register(Appointment)
class AppointmentAdmin(admin.ModelAdmin):
    list_display = ("patient", "scheduled_at", "duration_minutes", "status")
    list_filter = ("status",)
    search_fields = ("patient__mrn", "patient__first_name", "patient__last_name")
