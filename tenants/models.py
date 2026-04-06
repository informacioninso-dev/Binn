from django.conf import settings
from django.db import models
from django.urls import reverse
from django_tenants.models import TenantMixin, DomainMixin


class Client(TenantMixin):
    PLAN_SHARED = 'shared'
    PLAN_ENTERPRISE = 'enterprise'
    PLAN_CHOICES = [
        (PLAN_SHARED, 'Shared'),
        (PLAN_ENTERPRISE, 'Enterprise'),
    ]

    name = models.CharField(max_length=120)
    plan = models.CharField(max_length=20, choices=PLAN_CHOICES, default=PLAN_SHARED)
    is_active = models.BooleanField(default=True)
    created_on = models.DateField(auto_now_add=True)

    auto_create_schema = True

    def __str__(self):
        return f"{self.name} ({self.schema_name})"

    def get_absolute_url(self):
        return reverse("tenants:detail", kwargs={"pk": self.pk})

    @property
    def plan_definition(self):
        from .plans import get_plan_definition

        return get_plan_definition(self.plan)

    def has_capability(self, capability: str) -> bool:
        return capability in self.plan_definition.capabilities


class Domain(DomainMixin):
    pass


class TenantMembership(models.Model):
    ROLE_CLINIC_ADMIN = "clinic_admin"
    ROLE_DOCTOR = "doctor"
    ROLE_RECEPTION = "reception"
    ROLE_CASHIER = "cashier"
    ROLE_ASSISTANT = "assistant"
    ROLE_CHOICES = [
        (ROLE_CLINIC_ADMIN, "Admin de clinica"),
        (ROLE_DOCTOR, "Profesional"),
        (ROLE_RECEPTION, "Recepcion"),
        (ROLE_CASHIER, "Caja"),
        (ROLE_ASSISTANT, "Asistente"),
    ]

    tenant = models.ForeignKey(Client, on_delete=models.CASCADE, related_name='memberships')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='tenant_memberships')
    role = models.CharField(max_length=30, choices=ROLE_CHOICES, default=ROLE_ASSISTANT)
    is_admin = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)

    class Meta:
        unique_together = ('tenant', 'user')
        verbose_name = 'Tenant membership'
        verbose_name_plural = 'Tenant memberships'

    def __str__(self):
        return f"{self.user} -> {self.tenant}"

    @property
    def role_label(self):
        if self.is_admin:
            return "Admin de clinica"
        return self.get_role_display()


class TenantOperationalEvent(models.Model):
    KIND_AUDIT = "audit"
    KIND_HEALTH = "health"
    KIND_CHOICES = [
        (KIND_AUDIT, "Audit"),
        (KIND_HEALTH, "Health"),
    ]

    SEVERITY_INFO = "info"
    SEVERITY_WARNING = "warning"
    SEVERITY_ERROR = "error"
    SEVERITY_CHOICES = [
        (SEVERITY_INFO, "Info"),
        (SEVERITY_WARNING, "Warning"),
        (SEVERITY_ERROR, "Error"),
    ]

    STATUS_RECORDED = "recorded"
    STATUS_OPEN = "open"
    STATUS_RESOLVED = "resolved"
    STATUS_CHOICES = [
        (STATUS_RECORDED, "Recorded"),
        (STATUS_OPEN, "Open"),
        (STATUS_RESOLVED, "Resolved"),
    ]

    tenant = models.ForeignKey(Client, on_delete=models.CASCADE, related_name="operational_events")
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        related_name="tenant_operational_events",
        on_delete=models.SET_NULL,
    )
    kind = models.CharField(max_length=20, choices=KIND_CHOICES, default=KIND_AUDIT)
    severity = models.CharField(max_length=20, choices=SEVERITY_CHOICES, default=SEVERITY_INFO)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_RECORDED)
    code = models.CharField(max_length=80, blank=True)
    title = models.CharField(max_length=160)
    message = models.TextField(blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at", "-id")
        verbose_name = "Tenant operational event"
        verbose_name_plural = "Tenant operational events"

    def __str__(self):
        return f"{self.tenant.schema_name} | {self.title}"
