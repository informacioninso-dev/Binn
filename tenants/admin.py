from django.contrib import admin

from .models import Client, Domain, TenantOperationalEvent


@admin.register(Client)
class ClientAdmin(admin.ModelAdmin):
    list_display = ("name", "schema_name", "plan", "is_active", "allow_consolidation", "created_on")
    list_filter = ("plan", "is_active", "allow_consolidation")
    search_fields = ("name", "schema_name")
    readonly_fields = ("schema_name", "created_on")

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Domain)
class DomainAdmin(admin.ModelAdmin):
    list_display = ("domain", "tenant", "is_primary")
    list_filter = ("is_primary",)
    search_fields = ("domain", "tenant__name", "tenant__schema_name")


@admin.register(TenantOperationalEvent)
class TenantOperationalEventAdmin(admin.ModelAdmin):
    list_display = ("tenant", "kind", "severity", "status", "code", "title", "actor", "created_at")
    list_filter = ("kind", "severity", "status")
    search_fields = ("tenant__name", "tenant__schema_name", "code", "title", "message", "actor__username")
    readonly_fields = ("created_at",)
