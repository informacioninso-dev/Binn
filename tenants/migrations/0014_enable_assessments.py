from django.db import migrations


def enable_assessments(apps, schema_editor):
    TenantConfig = apps.get_model("tenants", "TenantConfig")
    for config in TenantConfig.objects.all().iterator():
        feature_flags = dict(config.feature_flags or {})
        module_order = list(config.module_order or [])
        changed = False
        if "assessments" not in feature_flags:
            feature_flags["assessments"] = True
            changed = True
        if "assessments" not in module_order:
            module_order.append("assessments")
            changed = True
        if changed:
            config.feature_flags = feature_flags
            config.module_order = module_order
            config.save(update_fields=["feature_flags", "module_order", "updated_at"])


class Migration(migrations.Migration):
    dependencies = [("tenants", "0013_tenantconfig_operational_settings")]

    operations = [migrations.RunPython(enable_assessments, migrations.RunPython.noop)]
