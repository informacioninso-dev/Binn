from copy import deepcopy

from django.db import migrations


def backfill_custom_objects(apps, schema_editor):
    TenantConfig = apps.get_model("tenants", "TenantConfig")
    from tenants.defaults import get_profile_defaults

    for config in TenantConfig.objects.all().iterator():
        if config.custom_objects:
            continue
        defaults = get_profile_defaults(config.profile)
        custom_objects = deepcopy(defaults.get("custom_objects", []))
        if not custom_objects:
            continue
        config.custom_objects = custom_objects
        config.save(update_fields=["custom_objects", "updated_at"])


def noop_reverse(apps, schema_editor):
    return


class Migration(migrations.Migration):

    dependencies = [
        ("tenants", "0010_tenantconfig_custom_objects"),
    ]

    operations = [
        migrations.RunPython(backfill_custom_objects, noop_reverse),
    ]
