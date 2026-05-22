from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("tenants", "0005_tenantconfig_admin_controls"),
    ]

    operations = [
        migrations.AddField(
            model_name="tenantconfig",
            name="role_policies",
            field=models.JSONField(blank=True, default=dict),
        ),
    ]
