# Generated manually for Fase 3 access baseline.

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("identity", "0001_initial"),
        ("governance", "0001_initial"),
        ("tenants", "0008_alter_tenantconfig_profile"),
    ]

    operations = [
        migrations.CreateModel(
            name="TenantMembership",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "role",
                    models.CharField(
                        choices=[
                            ("owner", "Owner"),
                            ("manager", "Manager"),
                            ("operator", "Operador"),
                            ("analyst", "Analista"),
                            ("viewer", "Consulta"),
                        ],
                        default="operator",
                        max_length=30,
                    ),
                ),
                ("is_admin", models.BooleanField(default=False)),
                ("is_active", models.BooleanField(default=True)),
                (
                    "tenant",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="memberships",
                        to="tenants.client",
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="tenant_memberships",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "verbose_name": "Tenant membership",
                "verbose_name_plural": "Tenant memberships",
                "ordering": ["tenant__name", "user__username"],
                "unique_together": {("tenant", "user")},
            },
        ),
        migrations.CreateModel(
            name="ActiveAccessContext",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "scope",
                    models.CharField(
                        choices=[
                            ("strict_isolation", "Strict Isolation"),
                            ("consolidated", "Consolidated"),
                            ("impersonated", "Impersonated"),
                        ],
                        default="strict_isolation",
                        max_length=32,
                    ),
                ),
                ("reason", models.CharField(blank=True, max_length=160)),
                ("last_resolved_at", models.DateTimeField(auto_now=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "active_tenant",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="active_access_contexts",
                        to="tenants.client",
                    ),
                ),
                (
                    "corporate_group",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="active_access_contexts",
                        to="governance.corporategroup",
                    ),
                ),
                (
                    "global_session",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="access_context",
                        to="identity.globalsession",
                    ),
                ),
                (
                    "impersonator",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="impersonated_access_contexts",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="active_access_contexts",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "verbose_name": "Active access context",
                "verbose_name_plural": "Active access contexts",
                "ordering": ["-last_resolved_at", "-id"],
            },
        ),
    ]
