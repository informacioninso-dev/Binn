from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("tenants", "0011_backfill_custom_objects"),
    ]

    operations = [
        migrations.AddField(
            model_name="client",
            name="max_users",
            field=models.PositiveIntegerField(default=25),
        ),
        migrations.AddField(
            model_name="client",
            name="storage_quota_mb",
            field=models.PositiveIntegerField(default=2048),
        ),
    ]
