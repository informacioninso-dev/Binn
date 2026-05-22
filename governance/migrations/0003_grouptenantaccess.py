# Generated manually for hierarchical group tenant access.

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("governance", "0002_operating_model_and_grants"),
        ("tenants", "0009_client_allow_consolidation"),
    ]

    operations = [
        migrations.CreateModel(
            name="GroupTenantAccess",
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
                ("is_active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "granted_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="granted_group_tenant_accesses",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "group",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="tenant_accesses",
                        to="governance.corporategroup",
                    ),
                ),
                (
                    "tenant",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="group_tenant_accesses",
                        to="tenants.client",
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="group_tenant_accesses",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "verbose_name": "Group tenant access",
                "verbose_name_plural": "Group tenant accesses",
                "ordering": ["group__name", "tenant__name", "user__username"],
                "unique_together": {("group", "tenant", "user")},
            },
        ),
    ]
