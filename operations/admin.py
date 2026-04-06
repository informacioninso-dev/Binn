from django.contrib import admin

from .models import (
    AutomationRule,
    AutomationRun,
    CommissionRecord,
    CommissionScheme,
    IntegrationConnection,
    Location,
)


@admin.register(Location)
class LocationAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "phone", "is_active")
    search_fields = ("code", "name", "address")
    list_filter = ("is_active",)


@admin.register(CommissionScheme)
class CommissionSchemeAdmin(admin.ModelAdmin):
    list_display = ("name", "basis", "percentage", "flat_amount", "is_active")
    search_fields = ("name", "applies_to_role")
    list_filter = ("basis", "is_active")


@admin.register(CommissionRecord)
class CommissionRecordAdmin(admin.ModelAdmin):
    list_display = ("provider", "appointment", "commission_amount", "status", "period_end")
    search_fields = ("provider__username", "appointment__patient__first_name", "appointment__patient__last_name")
    list_filter = ("status", "period_end")


@admin.register(AutomationRule)
class AutomationRuleAdmin(admin.ModelAdmin):
    list_display = ("name", "trigger", "channel", "target_role", "is_active", "last_run_at")
    search_fields = ("name", "target_role")
    list_filter = ("trigger", "channel", "is_active")


@admin.register(AutomationRun)
class AutomationRunAdmin(admin.ModelAdmin):
    list_display = ("rule", "status", "executed_at")
    search_fields = ("rule__name", "summary")
    list_filter = ("status",)


@admin.register(IntegrationConnection)
class IntegrationConnectionAdmin(admin.ModelAdmin):
    list_display = ("name", "provider", "status", "is_active")
    search_fields = ("name", "endpoint", "provider")
    list_filter = ("provider", "status", "is_active")
