from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("tenants", "0003_tenantmembership_role"),
    ]

    operations = [
        migrations.CreateModel(
            name="TenantConfig",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("profile", models.CharField(choices=[("general", "General"), ("condominio", "Administracion de condominios"), ("broker", "Broker de seguros"), ("marketing", "Agencia de marketing")], default="general", max_length=30)),
                ("feature_flags", models.JSONField(blank=True, default=dict)),
                ("labels", models.JSONField(blank=True, default=dict)),
                ("entity_fields", models.JSONField(blank=True, default=list)),
                ("pipeline_templates", models.JSONField(blank=True, default=list)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("tenant", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="config", to="tenants.client")),
            ],
            options={
                "verbose_name": "Tenant config",
                "verbose_name_plural": "Tenant configs",
            },
        ),
    ]
