# Generated manually for Fase 3 governance baseline.

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("tenants", "0008_alter_tenantconfig_profile"),
    ]

    operations = [
        migrations.CreateModel(
            name="CorporateGroup",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=160)),
                ("slug", models.SlugField(max_length=180, unique=True)),
                ("status", models.CharField(choices=[("active", "Activo"), ("suspended", "Suspendido")], default="active", max_length=20)),
                (
                    "consolidation_mode",
                    models.CharField(
                        choices=[("blocked", "Blocked"), ("aggregate_only", "Aggregate only"), ("full", "Full")],
                        default="aggregate_only",
                        max_length=20,
                    ),
                ),
                ("notes", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "owner",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="owned_corporate_groups",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "verbose_name": "Corporate group",
                "verbose_name_plural": "Corporate groups",
                "ordering": ["name", "id"],
            },
        ),
        migrations.CreateModel(
            name="GovernanceEvent",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("event_type", models.CharField(max_length=80)),
                ("message", models.TextField(blank=True)),
                ("metadata", models.JSONField(blank=True, default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "actor",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="governance_events",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "group",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="events",
                        to="governance.corporategroup",
                    ),
                ),
                (
                    "tenant",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="governance_events",
                        to="tenants.client",
                    ),
                ),
            ],
            options={
                "verbose_name": "Governance event",
                "verbose_name_plural": "Governance events",
                "ordering": ["-created_at", "-id"],
            },
        ),
        migrations.CreateModel(
            name="GroupMembership",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "role",
                    models.CharField(
                        choices=[
                            ("owner", "Owner"),
                            ("admin", "Administrador"),
                            ("executive", "Ejecutivo"),
                            ("analyst", "Analista"),
                            ("viewer", "Consulta"),
                        ],
                        default="viewer",
                        max_length=20,
                    ),
                ),
                ("is_active", models.BooleanField(default=True)),
                ("granted_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "group",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="memberships",
                        to="governance.corporategroup",
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="group_memberships",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "verbose_name": "Group membership",
                "verbose_name_plural": "Group memberships",
                "ordering": ["group__name", "user__username"],
                "unique_together": {("group", "user")},
            },
        ),
        migrations.CreateModel(
            name="GroupTenantLink",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "consolidation_mode",
                    models.CharField(
                        choices=[("blocked", "Blocked"), ("aggregate_only", "Aggregate only"), ("full", "Full")],
                        default="blocked",
                        max_length=20,
                    ),
                ),
                ("is_primary", models.BooleanField(default=False)),
                ("is_active", models.BooleanField(default=True)),
                ("joined_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "group",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="tenant_links",
                        to="governance.corporategroup",
                    ),
                ),
                (
                    "tenant",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="corporate_links",
                        to="tenants.client",
                    ),
                ),
            ],
            options={
                "verbose_name": "Group tenant link",
                "verbose_name_plural": "Group tenant links",
                "ordering": ["group__name", "tenant__name"],
                "unique_together": {("group", "tenant")},
            },
        ),
    ]
