# Generated manually for removing recall models and adding delivery address

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('sales', '0008_return_restructure'),
    ]

    operations = [
        # Remove old recall tables from sales
        migrations.RunSQL(
            sql=[
                "DROP TABLE IF EXISTS sales_recalldispatch;",
                "DROP TABLE IF EXISTS sales_recalllot;",
                "DROP TABLE IF EXISTS sales_productrecall;",
            ],
            reverse_sql=migrations.RunSQL.noop,
        ),
        # Add delivery address fields to SaleOrder
        migrations.AddField(
            model_name='saleorder',
            name='delivery_address',
            field=models.CharField(blank=True, max_length=300, verbose_name='Dirección de entrega'),
        ),
        migrations.AddField(
            model_name='saleorder',
            name='delivery_city',
            field=models.CharField(blank=True, max_length=100, verbose_name='Ciudad de entrega'),
        ),
        migrations.AddField(
            model_name='saleorder',
            name='delivery_phone',
            field=models.CharField(blank=True, max_length=50, verbose_name='Teléfono de contacto'),
        ),
    ]
