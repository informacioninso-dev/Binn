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
            name="Patient",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("mrn", models.CharField(max_length=32, unique=True, verbose_name="Historia clinica")),
                (
                    "document_type",
                    models.CharField(
                        choices=[("NATIONAL_ID", "Cedula"), ("PASSPORT", "Pasaporte"), ("RUC", "RUC"), ("OTHER", "Otro")],
                        max_length=20,
                        verbose_name="Tipo de documento",
                    ),
                ),
                ("document_number", models.CharField(db_index=True, max_length=30, verbose_name="Numero de documento")),
                ("first_name", models.CharField(max_length=120, verbose_name="Nombres")),
                ("last_name", models.CharField(max_length=120, verbose_name="Apellidos")),
                ("birth_date", models.DateField(blank=True, null=True, verbose_name="Fecha de nacimiento")),
                (
                    "sex",
                    models.CharField(
                        choices=[("F", "Femenino"), ("M", "Masculino"), ("O", "Otro"), ("U", "No especificado")],
                        default="U",
                        max_length=1,
                        verbose_name="Sexo",
                    ),
                ),
                ("phone", models.CharField(blank=True, max_length=30, verbose_name="Telefono")),
                ("email", models.EmailField(blank=True, max_length=254, verbose_name="Correo")),
                ("address", models.CharField(blank=True, max_length=255, verbose_name="Direccion")),
                ("is_active", models.BooleanField(default=True)),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="%(class)s_created",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "updated_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="%(class)s_updated",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": ["last_name", "first_name"],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("document_type", "document_number"),
                        name="patients_unique_document",
                    )
                ],
            },
        ),
    ]
