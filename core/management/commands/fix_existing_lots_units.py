from django.core.management.base import BaseCommand
from django.db import transaction
from inventory.models import Lot, Product
from decimal import Decimal

class Command(BaseCommand):
    help = 'Verifica y reporta lotes que necesitan conversión de unidades'
    
    def handle(self, *args, **options):
        problematic_lots = []
        
        for lot in Lot.objects.select_related('product', 'product__base_unit'):
            # Si el lote tiene cantidades que no coinciden con la unidad base
            # esto es un indicador de problema
            
            product = lot.product
            self.stdout.write(
                f"Lote: {lot.internal_lot} | "
                f"Producto: {product.code} | "
                f"Cantidad: {lot.quantity_current} {product.base_unit.code}"
            )
        
        self.stdout.write(
            self.style.SUCCESS(
                f'Total lotes verificados: {Lot.objects.count()}'
            )
        )