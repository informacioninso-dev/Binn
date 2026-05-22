# Generated manually for Fase 5 consolidation baseline.

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("governance", "0001_initial"),
        ("tenants", "0009_client_allow_consolidation"),
    ]

    operations = [
        migrations.CreateModel(
            name="ConsolidationRun",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("target_type", models.CharField(choices=[("tenant", "Tenant"), ("group", "Group")], default="group", max_length=20)),
                ("status", models.CharField(choices=[("running", "Running"), ("succeeded", "Succeeded"), ("failed", "Failed")], default="running", max_length=20)),
                ("trigger", models.CharField(default="manual", max_length=40)),
                ("snapshots_count", models.PositiveIntegerField(default=0)),
                ("metadata", models.JSONField(blank=True, default=dict)),
                ("error_message", models.TextField(blank=True)),
                ("started_at", models.DateTimeField(auto_now_add=True)),
                ("finished_at", models.DateTimeField(blank=True, null=True)),
                (
                    "actor",
                    models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="consolidation_runs", to=settings.AUTH_USER_MODEL),
                ),
                (
                    "group",
                    models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="consolidation_runs", to="governance.corporategroup"),
                ),
                (
                    "tenant",
                    models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="consolidation_runs", to="tenants.client"),
                ),
            ],
            options={
                "verbose_name": "Consolidation run",
                "verbose_name_plural": "Consolidation runs",
                "ordering": ["-started_at", "-id"],
            },
        ),
        migrations.CreateModel(
            name="TenantMetricSnapshot",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("snapshot_date", models.DateField()),
                ("entity_count", models.PositiveIntegerField(default=0)),
                ("open_deals_count", models.PositiveIntegerField(default=0)),
                ("won_deals_count", models.PositiveIntegerField(default=0)),
                ("lost_deals_count", models.PositiveIntegerField(default=0)),
                ("pending_activities_count", models.PositiveIntegerField(default=0)),
                ("overdue_activities_count", models.PositiveIntegerField(default=0)),
                ("documents_count", models.PositiveIntegerField(default=0)),
                ("expiring_documents_count", models.PositiveIntegerField(default=0)),
                ("open_proposals_count", models.PositiveIntegerField(default=0)),
                ("open_collections_count", models.PositiveIntegerField(default=0)),
                ("overdue_collections_count", models.PositiveIntegerField(default=0)),
                ("open_deal_amounts", models.JSONField(blank=True, default=dict)),
                ("outstanding_balance_amounts", models.JSONField(blank=True, default=dict)),
                ("metrics", models.JSONField(blank=True, default=dict)),
                ("last_synced_at", models.DateTimeField(auto_now=True)),
                (
                    "tenant",
                    models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="consolidation_snapshot", to="tenants.client"),
                ),
            ],
            options={
                "verbose_name": "Tenant metric snapshot",
                "verbose_name_plural": "Tenant metric snapshots",
                "ordering": ["tenant__name"],
            },
        ),
        migrations.CreateModel(
            name="GroupMetricSnapshot",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("snapshot_date", models.DateField()),
                ("included_tenants_count", models.PositiveIntegerField(default=0)),
                ("full_detail_tenants_count", models.PositiveIntegerField(default=0)),
                ("aggregate_only_tenants_count", models.PositiveIntegerField(default=0)),
                ("blocked_tenants_count", models.PositiveIntegerField(default=0)),
                ("entity_count", models.PositiveIntegerField(default=0)),
                ("open_deals_count", models.PositiveIntegerField(default=0)),
                ("won_deals_count", models.PositiveIntegerField(default=0)),
                ("lost_deals_count", models.PositiveIntegerField(default=0)),
                ("pending_activities_count", models.PositiveIntegerField(default=0)),
                ("overdue_activities_count", models.PositiveIntegerField(default=0)),
                ("documents_count", models.PositiveIntegerField(default=0)),
                ("expiring_documents_count", models.PositiveIntegerField(default=0)),
                ("open_proposals_count", models.PositiveIntegerField(default=0)),
                ("open_collections_count", models.PositiveIntegerField(default=0)),
                ("overdue_collections_count", models.PositiveIntegerField(default=0)),
                ("open_deal_amounts", models.JSONField(blank=True, default=dict)),
                ("outstanding_balance_amounts", models.JSONField(blank=True, default=dict)),
                ("metrics", models.JSONField(blank=True, default=dict)),
                ("last_synced_at", models.DateTimeField(auto_now=True)),
                (
                    "group",
                    models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="metric_snapshot", to="governance.corporategroup"),
                ),
            ],
            options={
                "verbose_name": "Group metric snapshot",
                "verbose_name_plural": "Group metric snapshots",
                "ordering": ["group__name"],
            },
        ),
    ]
