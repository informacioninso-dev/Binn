#!/usr/bin/env python
"""Investigar las líneas de recepción sin lot_number."""

import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from django_tenants.utils import schema_context
from procurement.models import RawMaterialReceptionLine

print("=" * 80)
print("INVESTIGAR LÍNEAS SIN LOT_NUMBER")
print("=" * 80)

with schema_context('public'):
    lines = RawMaterialReceptionLine.objects.filter(lot_number__isnull=True) | RawMaterialReceptionLine.objects.filter(lot_number='')

    print(f"\nTotal de líneas sin lot_number: {lines.count()}\n")

    for line in lines:
        print(f"Line ID: {line.id}")
        print(f"  Reception: {line.reception.code}")
        print(f"  Product: {line.product.code} - {line.product.name}")
        print(f"  Quantity: {line.received_quantity}")
        print(f"  supplier_lot: '{line.supplier_lot}'")
        print(f"  internal_lot: '{line.internal_lot}'")
        print(f"  lot_number: '{line.lot_number}'")
        print()

        # Intentar encontrar el lote correspondiente en inventario
        from inventory.models import Lot
        matching_lots = Lot.objects.filter(
            product=line.product,
            origin_reference=line.reception.code
        )

        if matching_lots.exists():
            print(f"  Lotes encontrados con origin_reference={line.reception.code}:")
            for lot in matching_lots:
                print(f"    - Lot ID {lot.id}: lot_number='{lot.lot_number}', status={lot.status}")
        else:
            print(f"  [WARNING] No se encontraron lotes en inventario para esta línea")

        print("-" * 80)

print("\nANÁLISIS:")
print("Si estas líneas NO tienen supplier_lot ni internal_lot, es normal.")
print("Estas líneas se crearon SIN lote y necesitan que se les asigne uno.")
print("Opciones:")
print("  1. Asignar el lot_number del lote de inventario correspondiente")
print("  2. Dejarlas vacías (se auto-generará si se vuelve a procesar)")
print("=" * 80)
