# Generated manually for tenant-level consolidation control.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("tenants", "0008_alter_tenantconfig_profile"),
    ]

    operations = [
        migrations.AddField(
            model_name="client",
            name="allow_consolidation",
            field=models.BooleanField(default=True),
        ),
    ]
