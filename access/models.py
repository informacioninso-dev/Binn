from __future__ import annotations

from django.conf import settings
from django.db import models

from .contracts import SessionScope


class TenantMembership(models.Model):
    ROLE_OWNER = "owner"
    ROLE_MANAGER = "manager"
    ROLE_OPERATOR = "operator"
    ROLE_ANALYST = "analyst"
    ROLE_VIEWER = "viewer"
    ROLE_CHOICES = [
        (ROLE_OWNER, "Owner"),
        (ROLE_MANAGER, "Manager"),
        (ROLE_OPERATOR, "Operador"),
        (ROLE_ANALYST, "Analista"),
        (ROLE_VIEWER, "Consulta"),
    ]

    tenant = models.ForeignKey("tenants.Client", on_delete=models.CASCADE, related_name="memberships")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="tenant_memberships")
    role = models.CharField(max_length=30, choices=ROLE_CHOICES, default=ROLE_OPERATOR)
    is_admin = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["tenant__name", "user__username"]
        verbose_name = "Tenant membership"
        verbose_name_plural = "Tenant memberships"
        unique_together = ("tenant", "user")

    def __str__(self):
        return f"{self.user} -> {self.tenant}"

    @property
    def role_label(self):
        if self.is_admin and self.role != self.ROLE_OWNER:
            return "Administrador"
        return self.get_role_display()


class ActiveAccessContext(models.Model):
    global_session = models.OneToOneField(
        "identity.GlobalSession",
        on_delete=models.CASCADE,
        related_name="access_context",
    )
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="active_access_contexts")
    scope = models.CharField(
        max_length=32,
        choices=[(scope.value, scope.name.replace("_", " ").title()) for scope in SessionScope],
        default=SessionScope.STRICT_ISOLATION.value,
    )
    active_tenant = models.ForeignKey(
        "tenants.Client",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="active_access_contexts",
    )
    corporate_group = models.ForeignKey(
        "governance.CorporateGroup",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="active_access_contexts",
    )
    impersonator = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="impersonated_access_contexts",
    )
    reason = models.CharField(max_length=160, blank=True)
    last_resolved_at = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-last_resolved_at", "-id"]
        verbose_name = "Active access context"
        verbose_name_plural = "Active access contexts"

    def __str__(self):
        return f"{self.user} [{self.scope}]"
