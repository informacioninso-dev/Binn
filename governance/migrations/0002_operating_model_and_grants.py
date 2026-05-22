# Generated manually for governance productization.

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("governance", "0001_initial"),
        ("tenants", "0009_client_allow_consolidation"),
    ]

    operations = [
        migrations.AddField(
            model_name="corporategroup",
            name="operating_model",
            field=models.CharField(
                choices=[("islands", "Islas"), ("family", "Familia")],
                default="islands",
                max_length=20,
            ),
        ),
        migrations.CreateModel(
            name="BillingAccount",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("billing_name", models.CharField(blank=True, max_length=180)),
                ("billing_email", models.EmailField(blank=True, max_length=254)),
                ("tax_id", models.CharField(blank=True, max_length=40)),
                (
                    "status",
                    models.CharField(
                        choices=[("active", "Activa"), ("hold", "En revision"), ("cancelled", "Cancelada")],
                        default="active",
                        max_length=20,
                    ),
                ),
                ("external_reference", models.CharField(blank=True, max_length=80)),
                ("notes", models.TextField(blank=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "group",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="billing_account",
                        to="governance.corporategroup",
                    ),
                ),
            ],
            options={
                "verbose_name": "Billing account",
                "verbose_name_plural": "Billing accounts",
            },
        ),
        migrations.CreateModel(
            name="OperationalAccessGrant",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("access_level", models.CharField(choices=[("detail", "Detalle operativo")], default="detail", max_length=20)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("pending", "Pendiente"),
                            ("approved", "Aprobada"),
                            ("rejected", "Rechazada"),
                            ("revoked", "Revocada"),
                        ],
                        default="pending",
                        max_length=20,
                    ),
                ),
                ("justification", models.TextField(blank=True)),
                ("decision_note", models.TextField(blank=True)),
                ("expires_at", models.DateTimeField(blank=True, null=True)),
                ("decided_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "decided_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="decided_operational_access_grants",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "group",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="operational_access_grants",
                        to="governance.corporategroup",
                    ),
                ),
                (
                    "requested_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="requested_operational_access_grants",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "tenant",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="operational_access_grants",
                        to="tenants.client",
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="operational_access_grants",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "verbose_name": "Operational access grant",
                "verbose_name_plural": "Operational access grants",
                "ordering": ["-created_at", "-id"],
            },
        ),
    ]
