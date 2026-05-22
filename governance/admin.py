from django.contrib import admin

from .models import BillingAccount, CorporateGroup, GovernanceEvent, GroupMembership, GroupTenantAccess, GroupTenantLink, OperationalAccessGrant


@admin.register(CorporateGroup)
class CorporateGroupAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "status", "operating_model", "consolidation_mode", "owner", "updated_at")
    list_filter = ("status", "operating_model", "consolidation_mode")
    search_fields = ("name", "slug", "owner__username", "owner__email")


@admin.register(GroupTenantLink)
class GroupTenantLinkAdmin(admin.ModelAdmin):
    list_display = ("group", "tenant", "consolidation_mode", "is_primary", "is_active", "updated_at")
    list_filter = ("consolidation_mode", "is_primary", "is_active")
    search_fields = ("group__name", "tenant__name", "tenant__schema_name")


@admin.register(GroupMembership)
class GroupMembershipAdmin(admin.ModelAdmin):
    list_display = ("group", "user", "role", "is_active", "updated_at")
    list_filter = ("role", "is_active")
    search_fields = ("group__name", "user__username", "user__email")


@admin.register(GroupTenantAccess)
class GroupTenantAccessAdmin(admin.ModelAdmin):
    list_display = ("group", "tenant", "user", "role", "is_active", "updated_at")
    list_filter = ("role", "is_active")
    search_fields = ("group__name", "tenant__name", "user__username", "user__email")


@admin.register(BillingAccount)
class BillingAccountAdmin(admin.ModelAdmin):
    list_display = ("group", "billing_name", "billing_email", "status", "seat_limit", "storage_limit_mb", "updated_at")
    list_filter = ("status",)
    search_fields = ("group__name", "billing_name", "billing_email", "tax_id", "external_reference")


@admin.register(OperationalAccessGrant)
class OperationalAccessGrantAdmin(admin.ModelAdmin):
    list_display = ("group", "tenant", "user", "status", "expires_at", "decided_at", "updated_at")
    list_filter = ("status", "access_level")
    search_fields = ("group__name", "tenant__name", "user__username", "user__email", "justification", "decision_note")


@admin.register(GovernanceEvent)
class GovernanceEventAdmin(admin.ModelAdmin):
    list_display = ("event_type", "group", "tenant", "actor", "created_at")
    list_filter = ("event_type",)
    search_fields = ("event_type", "message", "group__name", "tenant__name", "actor__username")
