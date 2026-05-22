# Generated manually for tenant-level custom object configuration.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("tenants", "0009_client_allow_consolidation"),
    ]

    operations = [
        migrations.AddField(
            model_name="tenantconfig",
            name="custom_objects",
            field=models.JSONField(blank=True, default=list),
        ),
    ]
