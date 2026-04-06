from django.contrib import admin

from .models import Lead


@admin.register(Lead)
class LeadAdmin(admin.ModelAdmin):
    list_display = ("full_name", "phone", "source", "stage", "assigned_to", "is_active")
    list_filter = ("source", "stage", "is_active")
    search_fields = ("full_name", "phone", "email", "interested_service")

