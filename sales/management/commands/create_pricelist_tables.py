from django.core.management.base import BaseCommand
from django.db import connection
from sales.models import PriceList, PriceListItem
from tenants.models import Client
from django_tenants.utils import schema_context


class Command(BaseCommand):
    help = 'Crea las tablas de PriceList en todos los tenants'

    def handle(self, *args, **options):
        for tenant in Client.objects.exclude(schema_name='public'):
            with schema_context(tenant.schema_name):
                cursor = connection.cursor()
                # Verificar si la tabla existe
                cursor.execute("""
                    SELECT EXISTS (
                        SELECT FROM information_schema.tables
                        WHERE table_schema = current_schema()
                        AND table_name = 'sales_pricelist'
                    )
                """)
                table_exists = cursor.fetchone()[0]

                if not table_exists:
                    self.stdout.write(f"Creando tablas en schema {tenant.schema_name}...")
                    # Crear tablas usando Django schema editor
                    with connection.schema_editor() as schema_editor:
                        schema_editor.create_model(PriceList)
                        schema_editor.create_model(PriceListItem)
                    self.stdout.write(self.style.SUCCESS(f"✓ Tablas creadas en {tenant.schema_name}"))
                else:
                    self.stdout.write(self.style.WARNING(f"  Tablas ya existen en {tenant.schema_name}"))

        self.stdout.write(self.style.SUCCESS('\n¡Listo! Todas las tablas han sido verificadas/creadas.'))
