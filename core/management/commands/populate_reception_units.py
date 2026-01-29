from django.core.management.base import BaseCommand
from django.db import transaction
from procurement.models import RawMaterialReceptionLine
from decimal import Decimal


class Command(BaseCommand):
    help = 'Asigna unidad base a líneas de recepción existentes sin unidad'
    
    @transaction.atomic
    def handle(self, *args, **options):
        lines_without_unit = RawMaterialReceptionLine.objects.filter(
            unit__isnull=True
        ).select_related('product', 'product__base_unit')
        
        count = lines_without_unit.count()
        
        if count == 0:
            self.stdout.write(
                self.style.SUCCESS('✅ Todas las líneas ya tienen unidad asignada')
            )
            return
        
        self.stdout.write(f'Encontradas {count} líneas sin unidad. Asignando...')
        
        updated = 0
        for line in lines_without_unit:
            if line.product and line.product.base_unit:
                line.unit = line.product.base_unit
                line.save(update_fields=['unit'])
                updated += 1
                
                self.stdout.write(
                    f'  ✓ Línea {line.id}: {line.product.code} → '
                    f'{line.product.base_unit.code}'
                )
        
        self.stdout.write(
            self.style.SUCCESS(
                f'\n✅ {updated} líneas actualizadas correctamente'
            )
        )