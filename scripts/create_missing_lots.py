#!/usr/bin/env python
"""Crear lotes faltantes para recepciones sin lot_number."""

import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from django_tenants.utils import schema_context
from procurement.models import RawMaterialReceptionLine
from inventory.models import Lot, LotStatus
from datetime import datetime

print("=" * 80)
print("CREAR LOTES FALTANTES")
print("=" * 80)

with schema_context('public'):
    # Obtener líneas sin lot_number en recepciones RECEIVED
    lines = (
        RawMaterialReceptionLine.objects
        .filter(lot_number__isnull=True)
        | RawMaterialReceptionLine.objects.filter(lot_number='')
    )

    print(f"\nTotal de líneas sin lot_number: {lines.count()}\n")

    created_lots = 0
    updated_lines = 0

    for line in lines:
        print(f"Procesando Line ID {line.id}:")
        print(f"  Reception: {line.reception.code}")
        print(f"  Product: {line.product.code}")
        print(f"  Quantity: {line.received_quantity} {line.unit.code}")

        # Generar lot_number automático
        # Formato: {product_code}-LOT-{timestamp}
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        lot_number = f"{line.product.code}-LOT-{timestamp}"

        print(f"  Generando lot_number: {lot_number}")

        # Actualizar la línea de recepción
        line.lot_number = lot_number
        line.save(update_fields=['lot_number'])
        updated_lines += 1
        print(f"  [OK] Línea actualizada con lot_number")

        # Verificar si ya existe un lote con este lot_number
        existing_lot = Lot.objects.filter(lot_number=lot_number).first()

        if existing_lot:
            print(f"  [INFO] Ya existe un lote con este lot_number")
        else:
            # Crear el lote en inventario
            # Nota: Como estas recepciones ya están en estado RECEIVED,
            # los lotes deberían estar en estado PENDING (esperando inspección QA)
            lot = Lot.objects.create(
                product=line.product,
                lot_number=lot_number,
                quantity_initial=line.received_quantity,
                status=LotStatus.PENDING,  # Pending inspection
                origin_reference=line.reception.code,
                manufacturing_date=line.manufacturing_date,
                expiry_date=line.expiry_date,
            )
            created_lots += 1
            print(f"  [OK] Lote creado en inventario (ID: {lot.id}, status: {lot.status})")

        print()

    print("=" * 80)
    print("RESUMEN")
    print("=" * 80)
    print(f"Líneas actualizadas: {updated_lines}")
    print(f"Lotes creados: {created_lots}")
    print("=" * 80)
