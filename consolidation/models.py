from __future__ import annotations

from django.conf import settings
from django.db import models


class ConsolidationRun(models.Model):
    TARGET_TENANT = "tenant"
    TARGET_GROUP = "group"
    TARGET_CHOICES = [
        (TARGET_TENANT, "Tenant"),
        (TARGET_GROUP, "Group"),
    ]

    STATUS_RUNNING = "running"
    STATUS_SUCCEEDED = "succeeded"
    STATUS_FAILED = "failed"
    STATUS_CHOICES = [
        (STATUS_RUNNING, "Running"),
        (STATUS_SUCCEEDED, "Succeeded"),
        (STATUS_FAILED, "Failed"),
    ]

    target_type = models.CharField(max_length=20, choices=TARGET_CHOICES, default=TARGET_GROUP)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_RUNNING)
    trigger = models.CharField(max_length=40, default="manual")
    tenant = models.ForeignKey(
        "tenants.Client",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="consolidation_runs",
    )
    group = models.ForeignKey(
        "governance.CorporateGroup",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="consolidation_runs",
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="consolidation_runs",
    )
    snapshots_count = models.PositiveIntegerField(default=0)
    metadata = models.JSONField(default=dict, blank=True)
    error_message = models.TextField(blank=True)
    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-started_at", "-id"]
        verbose_name = "Consolidation run"
        verbose_name_plural = "Consolidation runs"

    def __str__(self):
        if self.target_type == self.TARGET_TENANT and self.tenant_id:
            return f"Tenant sync {self.tenant}"
        if self.group_id:
            return f"Group sync {self.group}"
        return f"Consolidation run {self.pk}"


class TenantMetricSnapshot(models.Model):
    tenant = models.OneToOneField(
        "tenants.Client",
        on_delete=models.CASCADE,
        related_name="consolidation_snapshot",
    )
    snapshot_date = models.DateField()
    entity_count = models.PositiveIntegerField(default=0)
    open_deals_count = models.PositiveIntegerField(default=0)
    won_deals_count = models.PositiveIntegerField(default=0)
    lost_deals_count = models.PositiveIntegerField(default=0)
    pending_activities_count = models.PositiveIntegerField(default=0)
    overdue_activities_count = models.PositiveIntegerField(default=0)
    documents_count = models.PositiveIntegerField(default=0)
    expiring_documents_count = models.PositiveIntegerField(default=0)
    open_proposals_count = models.PositiveIntegerField(default=0)
    open_collections_count = models.PositiveIntegerField(default=0)
    overdue_collections_count = models.PositiveIntegerField(default=0)
    open_deal_amounts = models.JSONField(default=dict, blank=True)
    outstanding_balance_amounts = models.JSONField(default=dict, blank=True)
    metrics = models.JSONField(default=dict, blank=True)
    last_synced_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["tenant__name"]
        verbose_name = "Tenant metric snapshot"
        verbose_name_plural = "Tenant metric snapshots"

    def __str__(self):
        return f"Snapshot {self.tenant}"


class GroupMetricSnapshot(models.Model):
    group = models.OneToOneField(
        "governance.CorporateGroup",
        on_delete=models.CASCADE,
        related_name="metric_snapshot",
    )
    snapshot_date = models.DateField()
    included_tenants_count = models.PositiveIntegerField(default=0)
    full_detail_tenants_count = models.PositiveIntegerField(default=0)
    aggregate_only_tenants_count = models.PositiveIntegerField(default=0)
    blocked_tenants_count = models.PositiveIntegerField(default=0)
    entity_count = models.PositiveIntegerField(default=0)
    open_deals_count = models.PositiveIntegerField(default=0)
    won_deals_count = models.PositiveIntegerField(default=0)
    lost_deals_count = models.PositiveIntegerField(default=0)
    pending_activities_count = models.PositiveIntegerField(default=0)
    overdue_activities_count = models.PositiveIntegerField(default=0)
    documents_count = models.PositiveIntegerField(default=0)
    expiring_documents_count = models.PositiveIntegerField(default=0)
    open_proposals_count = models.PositiveIntegerField(default=0)
    open_collections_count = models.PositiveIntegerField(default=0)
    overdue_collections_count = models.PositiveIntegerField(default=0)
    open_deal_amounts = models.JSONField(default=dict, blank=True)
    outstanding_balance_amounts = models.JSONField(default=dict, blank=True)
    metrics = models.JSONField(default=dict, blank=True)
    last_synced_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["group__name"]
        verbose_name = "Group metric snapshot"
        verbose_name_plural = "Group metric snapshots"

    def __str__(self):
        return f"Group snapshot {self.group}"
