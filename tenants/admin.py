from django.contrib import admin

from .models import Client, Domain, TenantMembership


@admin.register(Client)
class ClientAdmin(admin.ModelAdmin):
    list_display = ("name", "schema_name", "plan", "is_active", "created_on")
    list_filter = ("plan", "is_active")
    search_fields = ("name", "schema_name")
    readonly_fields = ("schema_name", "created_on")

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Domain)
class DomainAdmin(admin.ModelAdmin):
    list_display = ("domain", "tenant", "is_primary")
    list_filter = ("is_primary",)
    search_fields = ("domain", "tenant__name", "tenant__schema_name")


@admin.register(TenantMembership)
class TenantMembershipAdmin(admin.ModelAdmin):
    list_display = ("tenant", "user", "is_admin", "is_active")
    list_filter = ("is_admin", "is_active")
    search_fields = ("tenant__name", "tenant__schema_name", "user__username", "user__email")
