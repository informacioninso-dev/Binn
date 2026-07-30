from django.conf import settings
from django.db import models
from django.urls import reverse
from django.utils.functional import cached_property
from django_tenants.models import DomainMixin, TenantMixin

from .defaults import (
    DEFAULT_LABELS,
    PROFILE_CHOICES,
    PROFILE_GENERAL,
    merge_with_profile_defaults,
    resolve_dashboard_widgets,
    resolve_module_order,
    resolve_role_policies,
)
from .operational_settings import (
    merge_operational_defaults,
    resolve_collection_settings,
    resolve_communication_settings,
    resolve_homepage_layout,
    resolve_quote_settings,
    resolve_task_presets,
)


class Client(TenantMixin):
    PLAN_SHARED = "shared"
    PLAN_ENTERPRISE = "enterprise"
    PLAN_CHOICES = [
        (PLAN_SHARED, "Shared"),
        (PLAN_ENTERPRISE, "Enterprise"),
    ]

    name = models.CharField(max_length=120)
    plan = models.CharField(max_length=20, choices=PLAN_CHOICES, default=PLAN_SHARED)
    is_active = models.BooleanField(default=True)
    allow_consolidation = models.BooleanField(default=True)
    max_users = models.PositiveIntegerField(default=25)
    storage_quota_mb = models.PositiveIntegerField(default=2048)
    created_on = models.DateField(auto_now_add=True)

    auto_create_schema = True

    def __str__(self):
        return f"{self.name} ({self.schema_name})"

    def get_absolute_url(self):
        return reverse("tenants:detail", kwargs={"pk": self.pk})

    @cached_property
    def tenant_config(self):
        defaults = merge_with_profile_defaults(PROFILE_GENERAL)
        defaults.update(merge_operational_defaults(PROFILE_GENERAL))
        config, _ = TenantConfig.objects.get_or_create(
            tenant=self,
            defaults=defaults,
        )
        return config

    @cached_property
    def primary_domain(self) -> str:
        primary = self.domains.filter(is_primary=True).first() or self.domains.first()
        return primary.domain if primary else ""

    def get_label(self, key: str, default: str | None = None) -> str:
        labels = self.tenant_config.labels or {}
        return labels.get(key, default or DEFAULT_LABELS.get(key, key.replace("_", " ").title()))

    def has_capability(self, capability: str) -> bool:
        return bool((self.tenant_config.feature_flags or {}).get(capability, False))

    @property
    def entity_fields(self) -> list[dict]:
        return list(self.tenant_config.entity_fields or [])

    @property
    def pipeline_templates(self) -> list[dict]:
        return list(self.tenant_config.pipeline_templates or [])

    @property
    def module_order(self) -> list[str]:
        return resolve_module_order(self.tenant_config.module_order)

    @property
    def custom_objects(self) -> list[dict]:
        return list(self.tenant_config.custom_objects or [])

    @property
    def dashboard_widgets(self) -> list[str]:
        return resolve_dashboard_widgets(self.tenant_config.dashboard_widgets)

    @property
    def document_blueprints(self) -> list[dict]:
        return list(self.tenant_config.document_blueprints or [])

    @property
    def role_policies(self) -> dict[str, list[str]]:
        return resolve_role_policies(self.tenant_config.role_policies)

    @property
    def task_presets(self) -> list[dict]:
        return resolve_task_presets(self.tenant_config.task_presets)

    @property
    def collection_settings(self) -> dict:
        return resolve_collection_settings(self.tenant_config.collection_settings)

    @property
    def communication_settings(self) -> dict:
        return resolve_communication_settings(self.tenant_config.communication_settings)

    @property
    def quote_settings(self) -> dict:
        return resolve_quote_settings(self.tenant_config.quote_settings)

    @property
    def homepage_layout(self) -> dict:
        return resolve_homepage_layout(self.tenant_config.homepage_layout)


class TenantConfig(models.Model):
    tenant = models.OneToOneField(Client, on_delete=models.CASCADE, related_name="config")
    profile = models.CharField(max_length=30, choices=PROFILE_CHOICES, default=PROFILE_GENERAL)
    feature_flags = models.JSONField(default=dict, blank=True)
    labels = models.JSONField(default=dict, blank=True)
    entity_fields = models.JSONField(default=list, blank=True)
    custom_objects = models.JSONField(default=list, blank=True)
    module_order = models.JSONField(default=list, blank=True)
    dashboard_widgets = models.JSONField(default=list, blank=True)
    role_policies = models.JSONField(default=dict, blank=True)
    document_blueprints = models.JSONField(default=list, blank=True)
    pipeline_templates = models.JSONField(default=list, blank=True)
    task_presets = models.JSONField(default=list, blank=True)
    collection_settings = models.JSONField(default=dict, blank=True)
    communication_settings = models.JSONField(default=dict, blank=True)
    quote_settings = models.JSONField(default=dict, blank=True)
    homepage_layout = models.JSONField(default=dict, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Tenant config"
        verbose_name_plural = "Tenant configs"

    def __str__(self):
        return f"Config {self.tenant.name}"

    def apply_profile_defaults(self, *, overwrite: bool = False):
        merged = merge_with_profile_defaults(
            self.profile,
            feature_flags={} if overwrite else self.feature_flags,
            labels={} if overwrite else self.labels,
            entity_fields=[] if overwrite else self.entity_fields,
            custom_objects=[] if overwrite else self.custom_objects,
            module_order=[] if overwrite else self.module_order,
            dashboard_widgets=[] if overwrite else self.dashboard_widgets,
            role_policies={} if overwrite else self.role_policies,
            document_blueprints=[] if overwrite else self.document_blueprints,
            pipeline_templates=[] if overwrite else self.pipeline_templates,
        )
        merged_operational = merge_operational_defaults(
            self.profile,
            task_presets=[] if overwrite else self.task_presets,
            collection_settings={} if overwrite else self.collection_settings,
            communication_settings={} if overwrite else self.communication_settings,
            quote_settings={} if overwrite else self.quote_settings,
            homepage_layout={} if overwrite else self.homepage_layout,
        )
        self.feature_flags = merged["feature_flags"]
        self.labels = merged["labels"]
        self.entity_fields = merged["entity_fields"]
        self.custom_objects = merged["custom_objects"]
        self.module_order = merged["module_order"]
        self.dashboard_widgets = merged["dashboard_widgets"]
        self.role_policies = merged["role_policies"]
        self.document_blueprints = merged["document_blueprints"]
        self.pipeline_templates = merged["pipeline_templates"]
        self.task_presets = merged_operational["task_presets"]
        self.collection_settings = merged_operational["collection_settings"]
        self.communication_settings = merged_operational["communication_settings"]
        self.quote_settings = merged_operational["quote_settings"]
        self.homepage_layout = merged_operational["homepage_layout"]


class Domain(DomainMixin):
    pass


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
