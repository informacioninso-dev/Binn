from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):

    dependencies = [
        ("binncrm", "0006_objectrecord"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="TimelineEvent",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("category", models.CharField(choices=[("entity", "Ficha"), ("deal", "Deal"), ("proposal", "Propuesta"), ("collection", "Cobranza"), ("activity", "Actividad"), ("document", "Documento"), ("object_record", "Objeto custom")], db_index=True, max_length=30)),
                ("event_key", models.SlugField(max_length=80)),
                ("kind_label", models.CharField(max_length=80)),
                ("title", models.CharField(max_length=180)),
                ("meta", models.CharField(blank=True, max_length=180)),
                ("description", models.TextField(blank=True)),
                ("accent", models.CharField(blank=True, max_length=60)),
                ("payload", models.JSONField(blank=True, default=dict)),
                ("occurred_at", models.DateTimeField(db_index=True, default=django.utils.timezone.now)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("activity", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name="timeline_events", to="binncrm.activity")),
                ("actor", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="timeline_events", to=settings.AUTH_USER_MODEL)),
                ("collection", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name="timeline_events", to="binncrm.collectionrecord")),
                ("deal", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name="timeline_events", to="binncrm.deal")),
                ("document", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name="timeline_events", to="binncrm.document")),
                ("entity", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name="timeline_events", to="binncrm.entity")),
                ("object_record", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name="timeline_events", to="binncrm.objectrecord")),
                ("proposal", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name="timeline_events", to="binncrm.proposal")),
            ],
            options={
                "ordering": ["-occurred_at", "-id"],
            },
        ),
    ]
