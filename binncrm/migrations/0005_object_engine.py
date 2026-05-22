# Generated manually for object engine foundation.

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("binncrm", "0004_document_expires_on_document_external_url_and_more"),
    ]

    operations = [
        migrations.CreateModel(
            name="ObjectSchema",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("key", models.SlugField(max_length=60, unique=True)),
                ("label", models.CharField(max_length=120)),
                ("description", models.TextField(blank=True)),
                ("source", models.CharField(choices=[("system", "Sistema"), ("custom", "Custom")], default="system", max_length=20)),
                ("settings", models.JSONField(blank=True, default=dict)),
                ("is_active", models.BooleanField(default=True)),
                ("created_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="%(class)s_created", to=settings.AUTH_USER_MODEL)),
                ("updated_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="%(class)s_updated", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ["label", "id"]},
        ),
        migrations.CreateModel(
            name="ObjectField",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("key", models.SlugField(max_length=60)),
                ("label", models.CharField(max_length=120)),
                (
                    "field_type",
                    models.CharField(
                        choices=[
                            ("text", "Texto"),
                            ("textarea", "Texto largo"),
                            ("number", "Numero"),
                            ("email", "Correo"),
                            ("date", "Fecha"),
                            ("boolean", "Booleano"),
                        ],
                        default="text",
                        max_length=20,
                    ),
                ),
                ("position", models.PositiveIntegerField(default=0)),
                ("required", models.BooleanField(default=False)),
                ("config", models.JSONField(blank=True, default=dict)),
                ("is_system", models.BooleanField(default=False)),
                ("is_active", models.BooleanField(default=True)),
                ("created_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="%(class)s_created", to=settings.AUTH_USER_MODEL)),
                ("object_schema", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="fields", to="binncrm.objectschema")),
                ("updated_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="%(class)s_updated", to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "ordering": ["object_schema__label", "position", "label", "id"],
                "unique_together": {("object_schema", "key")},
            },
        ),
        migrations.CreateModel(
            name="ObjectView",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("key", models.SlugField(max_length=60)),
                ("label", models.CharField(max_length=120)),
                ("description", models.TextField(blank=True)),
                ("view_type", models.CharField(choices=[("table", "Tabla"), ("kanban", "Kanban"), ("list", "Lista")], default="table", max_length=20)),
                ("position", models.PositiveIntegerField(default=0)),
                ("config", models.JSONField(blank=True, default=dict)),
                ("is_default", models.BooleanField(default=False)),
                ("is_active", models.BooleanField(default=True)),
                ("created_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="%(class)s_created", to=settings.AUTH_USER_MODEL)),
                ("object_schema", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="views", to="binncrm.objectschema")),
                ("updated_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="%(class)s_updated", to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "ordering": ["object_schema__label", "position", "label", "id"],
                "unique_together": {("object_schema", "key")},
            },
        ),
    ]
