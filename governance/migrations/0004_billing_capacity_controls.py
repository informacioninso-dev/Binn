import decimal

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("governance", "0003_grouptenantaccess"),
    ]

    operations = [
        migrations.AddField(
            model_name="billingaccount",
            name="currency",
            field=models.CharField(default="USD", max_length=8),
        ),
        migrations.AddField(
            model_name="billingaccount",
            name="enforce_limits",
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name="billingaccount",
            name="manager_limit",
            field=models.PositiveIntegerField(default=5),
        ),
        migrations.AddField(
            model_name="billingaccount",
            name="monthly_amount",
            field=models.DecimalField(decimal_places=2, default=decimal.Decimal("0.00"), max_digits=12),
        ),
        migrations.AddField(
            model_name="billingaccount",
            name="renews_on",
            field=models.DateField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="billingaccount",
            name="seat_limit",
            field=models.PositiveIntegerField(default=25),
        ),
        migrations.AddField(
            model_name="billingaccount",
            name="storage_limit_mb",
            field=models.PositiveIntegerField(default=10240),
        ),
    ]
