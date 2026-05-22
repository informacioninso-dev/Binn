from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin

from .models import GlobalSession, User


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    fieldsets = DjangoUserAdmin.fieldsets + (
        (
            "Global identity",
            {
                "fields": (
                    "uuid",
                    "preferred_name",
                    "display_name",
                    "account_status",
                    "must_rotate_password",
                    "last_global_login_at",
                )
            },
        ),
    )
    readonly_fields = ("uuid", "last_global_login_at")
    list_display = (
        "username",
        "email",
        "account_status",
        "is_active",
        "is_staff",
        "last_login",
        "last_global_login_at",
    )
    list_filter = ("account_status", "is_active", "is_staff", "is_superuser")
    search_fields = ("username", "email", "first_name", "last_name", "display_name", "preferred_name")


@admin.register(GlobalSession)
class GlobalSessionAdmin(admin.ModelAdmin):
    list_display = (
        "user",
        "state",
        "scope",
        "active_tenant_schema",
        "ip_address",
        "last_seen_at",
    )
    list_filter = ("state", "scope", "active_tenant_schema")
    search_fields = ("user__username", "user__email", "session_key", "request_id", "active_tenant_schema")
    readonly_fields = (
        "user",
        "session_key",
        "auth_backend",
        "state",
        "scope",
        "ip_address",
        "user_agent",
        "request_id",
        "active_tenant_schema",
        "impersonator_user_id",
        "created_at",
        "last_seen_at",
        "ended_at",
        "revoked_at",
        "ended_reason",
    )
