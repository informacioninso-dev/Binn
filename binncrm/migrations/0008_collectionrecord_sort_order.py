from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("binncrm", "0007_timelineevent"),
    ]

    operations = [
        migrations.AddField(
            model_name="collectionrecord",
            name="sort_order",
            field=models.PositiveIntegerField(default=0),
        ),
    ]
