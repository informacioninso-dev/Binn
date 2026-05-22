from __future__ import annotations

from decimal import Decimal

from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.text import slugify


class CorporateGroup(models.Model):
    OPERATING_MODEL_ISLANDS = "islands"
    OPERATING_MODEL_FAMILY = "family"
    OPERATING_MODEL_CHOICES = [
        (OPERATING_MODEL_ISLANDS, "Islas"),
        (OPERATING_MODEL_FAMILY, "Familia"),
    ]

    MODE_BLOCKED = "blocked"
    MODE_AGGREGATE_ONLY = "aggregate_only"
    MODE_FULL = "full"
    CONSOLIDATION_MODE_CHOICES = [
        (MODE_BLOCKED, "Blocked"),
        (MODE_AGGREGATE_ONLY, "Aggregate only"),
        (MODE_FULL, "Full"),
    ]

    STATUS_ACTIVE = "active"
    STATUS_SUSPENDED = "suspended"
    STATUS_CHOICES = [
        (STATUS_ACTIVE, "Activo"),
        (STATUS_SUSPENDED, "Suspendido"),
    ]

    name = models.CharField(max_length=160)
    slug = models.SlugField(max_length=180, unique=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_ACTIVE)
    operating_model = models.CharField(
        max_length=20,
        choices=OPERATING_MODEL_CHOICES,
        default=OPERATING_MODEL_ISLANDS,
    )
    consolidation_mode = models.CharField(
        max_length=20,
        choices=CONSOLIDATION_MODE_CHOICES,
        default=MODE_AGGREGATE_ONLY,
    )
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="owned_corporate_groups",
    )
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name", "id"]
        verbose_name = "Corporate group"
        verbose_name_plural = "Corporate groups"

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)[:180]
        super().save(*args, **kwargs)

    @property
    def requires_operational_grant(self) -> bool:
        return self.operating_model == self.OPERATING_MODEL_ISLANDS


class GroupTenantLink(models.Model):
    MODE_BLOCKED = CorporateGroup.MODE_BLOCKED
    MODE_AGGREGATE_ONLY = CorporateGroup.MODE_AGGREGATE_ONLY
    MODE_FULL = CorporateGroup.MODE_FULL
    CONSOLIDATION_MODE_CHOICES = CorporateGroup.CONSOLIDATION_MODE_CHOICES

    group = models.ForeignKey(CorporateGroup, on_delete=models.CASCADE, related_name="tenant_links")
    tenant = models.ForeignKey("tenants.Client", on_delete=models.CASCADE, related_name="corporate_links")
    consolidation_mode = models.CharField(
        max_length=20,
        choices=CONSOLIDATION_MODE_CHOICES,
        default=MODE_BLOCKED,
    )
    is_primary = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    joined_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("group", "tenant")
        ordering = ["group__name", "tenant__name"]
        verbose_name = "Group tenant link"
        verbose_name_plural = "Group tenant links"

    def __str__(self):
        return f"{self.group.name} -> {self.tenant.name}"

    @property
    def effective_mode(self) -> str:
        if not self.is_active or self.group.status != CorporateGroup.STATUS_ACTIVE:
            return self.MODE_BLOCKED
        if not getattr(self.tenant, "allow_consolidation", True):
            return self.MODE_BLOCKED
        if self.group.consolidation_mode == self.MODE_BLOCKED:
            return self.MODE_BLOCKED
        if self.consolidation_mode == self.MODE_BLOCKED:
            return self.MODE_BLOCKED
        if (
            self.group.consolidation_mode == self.MODE_AGGREGATE_ONLY
            or self.consolidation_mode == self.MODE_AGGREGATE_ONLY
        ):
            return self.MODE_AGGREGATE_ONLY
        return self.MODE_FULL


class GroupMembership(models.Model):
    ROLE_OWNER = "owner"
    ROLE_ADMIN = "admin"
    ROLE_EXECUTIVE = "executive"
    ROLE_ANALYST = "analyst"
    ROLE_VIEWER = "viewer"
    ROLE_CHOICES = [
        (ROLE_OWNER, "Owner"),
        (ROLE_ADMIN, "Administrador"),
        (ROLE_EXECUTIVE, "Ejecutivo"),
        (ROLE_ANALYST, "Analista"),
        (ROLE_VIEWER, "Consulta"),
    ]

    group = models.ForeignKey(CorporateGroup, on_delete=models.CASCADE, related_name="memberships")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="group_memberships")
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default=ROLE_VIEWER)
    is_active = models.BooleanField(default=True)
    granted_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("group", "user")
        ordering = ["group__name", "user__username"]
        verbose_name = "Group membership"
        verbose_name_plural = "Group memberships"

    def __str__(self):
        return f"{self.user} -> {self.group}"

    def allows_permission(self, permission_code: str, *, effective_mode: str) -> bool:
        if not self.is_active or effective_mode == CorporateGroup.MODE_BLOCKED:
            return False
        if effective_mode == CorporateGroup.MODE_AGGREGATE_ONLY:
            return False
        if permission_code == "tenant.access":
            return True
        if self.role in {self.ROLE_OWNER, self.ROLE_ADMIN}:
            return True
        return permission_code.endswith(".view")

    def can_view_group_dashboard(self) -> bool:
        return self.is_active and self.group.status == CorporateGroup.STATUS_ACTIVE

    def can_manage_group(self) -> bool:
        return self.is_active and self.role in {self.ROLE_OWNER, self.ROLE_ADMIN}

    def can_manage_billing(self) -> bool:
        return self.can_manage_group()

    def can_manage_members(self) -> bool:
        return self.can_manage_group()

    def can_request_operational_access(self) -> bool:
        return self.is_active and self.role in {self.ROLE_OWNER, self.ROLE_ADMIN, self.ROLE_EXECUTIVE}


class GroupTenantAccess(models.Model):
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

    group = models.ForeignKey(CorporateGroup, on_delete=models.CASCADE, related_name="tenant_accesses")
    tenant = models.ForeignKey("tenants.Client", on_delete=models.CASCADE, related_name="group_tenant_accesses")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="group_tenant_accesses")
    role = models.CharField(max_length=30, choices=ROLE_CHOICES, default=ROLE_OPERATOR)
    is_active = models.BooleanField(default=True)
    granted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="granted_group_tenant_accesses",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("group", "tenant", "user")
        ordering = ["group__name", "tenant__name", "user__username"]
        verbose_name = "Group tenant access"
        verbose_name_plural = "Group tenant accesses"

    def __str__(self):
        return f"{self.group.name} -> {self.tenant.name} -> {self.user}"

    @property
    def role_label(self) -> str:
        return self.get_role_display()


class BillingAccount(models.Model):
    STATUS_ACTIVE = "active"
    STATUS_HOLD = "hold"
    STATUS_CANCELLED = "cancelled"
    STATUS_CHOICES = [
        (STATUS_ACTIVE, "Activa"),
        (STATUS_HOLD, "En revision"),
        (STATUS_CANCELLED, "Cancelada"),
    ]

    group = models.OneToOneField(CorporateGroup, on_delete=models.CASCADE, related_name="billing_account")
    billing_name = models.CharField(max_length=180, blank=True)
    billing_email = models.EmailField(blank=True)
    tax_id = models.CharField(max_length=40, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_ACTIVE)
    external_reference = models.CharField(max_length=80, blank=True)
    seat_limit = models.PositiveIntegerField(default=25)
    manager_limit = models.PositiveIntegerField(default=5)
    storage_limit_mb = models.PositiveIntegerField(default=10240)
    monthly_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    currency = models.CharField(max_length=8, default="USD")
    renews_on = models.DateField(null=True, blank=True)
    enforce_limits = models.BooleanField(default=True)
    notes = models.TextField(blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Billing account"
        verbose_name_plural = "Billing accounts"

    def __str__(self):
        return self.billing_name or self.group.name


class OperationalAccessGrant(models.Model):
    ACCESS_DETAIL = "detail"
    ACCESS_LEVEL_CHOICES = [
        (ACCESS_DETAIL, "Detalle operativo"),
    ]

    STATUS_PENDING = "pending"
    STATUS_APPROVED = "approved"
    STATUS_REJECTED = "rejected"
    STATUS_REVOKED = "revoked"
    STATUS_CHOICES = [
        (STATUS_PENDING, "Pendiente"),
        (STATUS_APPROVED, "Aprobada"),
        (STATUS_REJECTED, "Rechazada"),
        (STATUS_REVOKED, "Revocada"),
    ]

    group = models.ForeignKey(CorporateGroup, on_delete=models.CASCADE, related_name="operational_access_grants")
    tenant = models.ForeignKey("tenants.Client", on_delete=models.CASCADE, related_name="operational_access_grants")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="operational_access_grants")
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="requested_operational_access_grants",
    )
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="decided_operational_access_grants",
    )
    access_level = models.CharField(max_length=20, choices=ACCESS_LEVEL_CHOICES, default=ACCESS_DETAIL)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING)
    justification = models.TextField(blank=True)
    decision_note = models.TextField(blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    decided_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        verbose_name = "Operational access grant"
        verbose_name_plural = "Operational access grants"

    def __str__(self):
        return f"{self.user} -> {self.tenant} ({self.get_status_display()})"

    @property
    def is_active(self) -> bool:
        if self.status != self.STATUS_APPROVED:
            return False
        if self.expires_at and self.expires_at <= timezone.now():
            return False
        return True


class GovernanceEvent(models.Model):
    group = models.ForeignKey(
        CorporateGroup,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="events",
    )
    tenant = models.ForeignKey(
        "tenants.Client",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="governance_events",
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="governance_events",
    )
    event_type = models.CharField(max_length=80)
    message = models.TextField(blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        verbose_name = "Governance event"
        verbose_name_plural = "Governance events"

    def __str__(self):
        return self.event_type
