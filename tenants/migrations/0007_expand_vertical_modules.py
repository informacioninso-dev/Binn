from django.db import migrations


def forward_fill_vertical_defaults(apps, schema_editor):
    TenantConfig = apps.get_model("tenants", "TenantConfig")

    from tenants.defaults import merge_with_profile_defaults

    for config in TenantConfig.objects.all():
        merged = merge_with_profile_defaults(
            config.profile,
            feature_flags=config.feature_flags,
            labels=config.labels,
            entity_fields=config.entity_fields,
            module_order=config.module_order,
            dashboard_widgets=config.dashboard_widgets,
            role_policies=config.role_policies,
            document_blueprints=config.document_blueprints,
            pipeline_templates=config.pipeline_templates,
        )
        config.feature_flags = merged["feature_flags"]
        config.labels = merged["labels"]
        config.entity_fields = merged["entity_fields"]
        config.module_order = merged["module_order"]
        config.dashboard_widgets = merged["dashboard_widgets"]
        config.role_policies = merged["role_policies"]
        config.document_blueprints = merged["document_blueprints"]
        config.pipeline_templates = merged["pipeline_templates"]
        config.save(
            update_fields=[
                "feature_flags",
                "labels",
                "entity_fields",
                "module_order",
                "dashboard_widgets",
                "role_policies",
                "document_blueprints",
                "pipeline_templates",
            ]
        )


class Migration(migrations.Migration):
    dependencies = [
        ("tenants", "0006_tenantconfig_role_policies"),
    ]

    operations = [
        migrations.RunPython(forward_fill_vertical_defaults, migrations.RunPython.noop),
    ]
