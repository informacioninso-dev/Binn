from django.contrib import admin

from .models import ConsolidationRun, GroupMetricSnapshot, TenantMetricSnapshot


@admin.register(TenantMetricSnapshot)
class TenantMetricSnapshotAdmin(admin.ModelAdmin):
    list_display = (
        "tenant",
        "snapshot_date",
        "entity_count",
        "open_deals_count",
        "pending_activities_count",
        "last_synced_at",
    )
    list_filter = ("snapshot_date",)
    search_fields = ("tenant__name", "tenant__schema_name")
    readonly_fields = ("last_synced_at",)


@admin.register(GroupMetricSnapshot)
class GroupMetricSnapshotAdmin(admin.ModelAdmin):
    list_display = (
        "group",
        "snapshot_date",
        "included_tenants_count",
        "full_detail_tenants_count",
        "aggregate_only_tenants_count",
        "blocked_tenants_count",
        "last_synced_at",
    )
    list_filter = ("snapshot_date",)
    search_fields = ("group__name", "group__slug")
    readonly_fields = ("last_synced_at",)


@admin.register(ConsolidationRun)
class ConsolidationRunAdmin(admin.ModelAdmin):
    list_display = ("target_type", "group", "tenant", "status", "trigger", "snapshots_count", "started_at", "finished_at")
    list_filter = ("target_type", "status", "trigger")
    search_fields = ("group__name", "tenant__name", "tenant__schema_name", "actor__username")
    readonly_fields = ("started_at", "finished_at")
