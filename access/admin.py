from django.contrib import admin

from .models import ActiveAccessContext, TenantMembership


@admin.register(TenantMembership)
class TenantMembershipAdmin(admin.ModelAdmin):
    list_display = ("tenant", "user", "role", "is_admin", "is_active")
    list_filter = ("role", "is_admin", "is_active")
    search_fields = ("tenant__name", "tenant__schema_name", "user__username", "user__email")


@admin.register(ActiveAccessContext)
class ActiveAccessContextAdmin(admin.ModelAdmin):
    list_display = ("user", "scope", "active_tenant", "corporate_group", "last_resolved_at")
    list_filter = ("scope", "corporate_group")
    search_fields = (
        "user__username",
        "user__email",
        "active_tenant__name",
        "active_tenant__schema_name",
        "corporate_group__name",
    )
