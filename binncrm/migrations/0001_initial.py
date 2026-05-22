from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="Entity",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("full_name", models.CharField(max_length=180, verbose_name="Nombre")),
                ("legal_id", models.CharField(blank=True, max_length=20, verbose_name="RUC/Cedula")),
                ("phone", models.CharField(blank=True, max_length=30, verbose_name="Telefono")),
                ("email", models.EmailField(blank=True, max_length=254, verbose_name="Correo")),
                ("data_extra", models.JSONField(blank=True, default=dict)),
                ("notes", models.TextField(blank=True, verbose_name="Notas")),
                ("is_active", models.BooleanField(default=True)),
                ("created_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="%(class)s_created", to=settings.AUTH_USER_MODEL)),
                ("updated_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="%(class)s_updated", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ["full_name"]},
        ),
        migrations.CreateModel(
            name="Pipeline",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("name", models.CharField(max_length=120)),
                ("key", models.SlugField(max_length=60, unique=True)),
                ("stages", models.JSONField(blank=True, default=list)),
                ("position", models.PositiveIntegerField(default=0)),
                ("is_default", models.BooleanField(default=False)),
                ("is_active", models.BooleanField(default=True)),
                ("created_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="%(class)s_created", to=settings.AUTH_USER_MODEL)),
                ("updated_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="%(class)s_updated", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ["position", "name"]},
        ),
        migrations.CreateModel(
            name="Deal",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("title", models.CharField(max_length=160)),
                ("amount", models.DecimalField(decimal_places=2, default=0, max_digits=12)),
                ("currency", models.CharField(default="USD", max_length=8)),
                ("stage", models.CharField(max_length=120)),
                ("status", models.CharField(choices=[("open", "Abierto"), ("won", "Ganado"), ("lost", "Perdido")], default="open", max_length=20)),
                ("expected_close_on", models.DateField(blank=True, null=True)),
                ("notes", models.TextField(blank=True)),
                ("sort_order", models.PositiveIntegerField(default=0)),
                ("is_active", models.BooleanField(default=True)),
                ("created_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="%(class)s_created", to=settings.AUTH_USER_MODEL)),
                ("updated_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="%(class)s_updated", to=settings.AUTH_USER_MODEL)),
                ("entity", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="deals", to="binncrm.entity")),
                ("pipeline", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="deals", to="binncrm.pipeline")),
            ],
            options={"ordering": ["pipeline__position", "sort_order", "-updated_at"]},
        ),
        migrations.CreateModel(
            name="Activity",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("activity_type", models.CharField(choices=[("call", "Llamada"), ("whatsapp", "WhatsApp"), ("note", "Nota"), ("email", "Correo"), ("task", "Tarea")], default="note", max_length=20)),
                ("title", models.CharField(max_length=160)),
                ("description", models.TextField(blank=True)),
                ("due_at", models.DateTimeField(blank=True, null=True)),
                ("completed_at", models.DateTimeField(blank=True, null=True)),
                ("created_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="%(class)s_created", to=settings.AUTH_USER_MODEL)),
                ("updated_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="%(class)s_updated", to=settings.AUTH_USER_MODEL)),
                ("deal", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name="activities", to="binncrm.deal")),
                ("entity", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="activities", to="binncrm.entity")),
            ],
            options={"ordering": ["-created_at"]},
        ),
        migrations.CreateModel(
            name="Document",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("title", models.CharField(max_length=180)),
                ("document_type", models.CharField(default="general", max_length=80)),
                ("bucket_name", models.CharField(blank=True, max_length=160)),
                ("storage_key", models.CharField(max_length=255)),
                ("content_type", models.CharField(blank=True, max_length=120)),
                ("file_size", models.PositiveIntegerField(default=0)),
                ("metadata", models.JSONField(blank=True, default=dict)),
                ("is_active", models.BooleanField(default=True)),
                ("created_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="%(class)s_created", to=settings.AUTH_USER_MODEL)),
                ("updated_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="%(class)s_updated", to=settings.AUTH_USER_MODEL)),
                ("deal", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name="documents", to="binncrm.deal")),
                ("entity", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name="documents", to="binncrm.entity")),
            ],
            options={"ordering": ["-created_at"]},
        ),
    ]
