from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("patients", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="Appointment",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("scheduled_at", models.DateTimeField(verbose_name="Fecha y hora")),
                ("duration_minutes", models.PositiveSmallIntegerField(default=30, verbose_name="Duracion (min)")),
                ("reason", models.CharField(blank=True, max_length=255, verbose_name="Motivo")),
                ("notes", models.TextField(blank=True, verbose_name="Notas")),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("SCHEDULED", "Programada"),
                            ("CONFIRMED", "Confirmada"),
                            ("IN_PROGRESS", "En atencion"),
                            ("COMPLETED", "Completada"),
                            ("CANCELED", "Cancelada"),
                            ("NO_SHOW", "No asistio"),
                        ],
                        default="SCHEDULED",
                        max_length=20,
                    ),
                ),
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
                    "patient",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="appointments",
                        to="patients.patient",
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
            options={"ordering": ["-scheduled_at"]},
        ),
    ]
