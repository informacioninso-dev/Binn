from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("tenants", "0004_tenantconfig_and_membership_roles"),
    ]

    operations = [
        migrations.AddField(
            model_name="tenantconfig",
            name="dashboard_widgets",
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.AddField(
            model_name="tenantconfig",
            name="document_blueprints",
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.AddField(
            model_name="tenantconfig",
            name="module_order",
            field=models.JSONField(blank=True, default=list),
        ),
    ]
