from django.db import migrations, models


def forward_fill_operational_defaults(apps, schema_editor):
    TenantConfig = apps.get_model("tenants", "TenantConfig")

    from tenants.operational_settings import merge_operational_defaults

    for config in TenantConfig.objects.all():
        merged = merge_operational_defaults(
            config.profile,
            task_presets=config.task_presets,
            collection_settings=config.collection_settings,
            communication_settings=config.communication_settings,
            quote_settings=config.quote_settings,
            homepage_layout=config.homepage_layout,
        )
        config.task_presets = merged["task_presets"]
        config.collection_settings = merged["collection_settings"]
        config.communication_settings = merged["communication_settings"]
        config.quote_settings = merged["quote_settings"]
        config.homepage_layout = merged["homepage_layout"]
        config.save(
            update_fields=[
                "task_presets",
                "collection_settings",
                "communication_settings",
                "quote_settings",
                "homepage_layout",
            ]
        )


class Migration(migrations.Migration):
    dependencies = [
        ("tenants", "0012_client_capacity_controls"),
    ]

    operations = [
        migrations.AddField(
            model_name="tenantconfig",
            name="collection_settings",
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AddField(
            model_name="tenantconfig",
            name="communication_settings",
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AddField(
            model_name="tenantconfig",
            name="homepage_layout",
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AddField(
            model_name="tenantconfig",
            name="quote_settings",
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AddField(
            model_name="tenantconfig",
            name="task_presets",
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.RunPython(forward_fill_operational_defaults, migrations.RunPython.noop),
    ]

