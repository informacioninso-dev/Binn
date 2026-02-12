#!/usr/bin/env python
"""Verificar el estado de las recepciones sin lotes."""

import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from django_tenants.utils import schema_context
from procurement.models import RawMaterialReceptionLine, RawMaterialReception

print("=" * 80)
print("VERIFICAR ESTADO DE RECEPCIONES")
print("=" * 80)

with schema_context('public'):
    # Obtener las líneas sin lot_number
    lines = RawMaterialReceptionLine.objects.filter(lot_number__isnull=True) | RawMaterialReceptionLine.objects.filter(lot_number='')

    # Obtener las recepciones únicas
    reception_ids = lines.values_list('reception_id', flat=True).distinct()
    receptions = RawMaterialReception.objects.filter(id__in=reception_ids)

    print(f"\nRecepciones con líneas sin lot_number: {receptions.count()}\n")

    for reception in receptions:
        print(f"Reception: {reception.code}")
        print(f"  Estado: {reception.get_status_display()}")
        print(f"  Fecha: {reception.reception_date}")
        print(f"  Proveedor: {reception.supplier_name}")

        # Líneas de esta recepción
        reception_lines = lines.filter(reception=reception)
        print(f"  Líneas sin lot_number: {reception_lines.count()}")

        for line in reception_lines:
            print(f"    - Product: {line.product.code}, Qty: {line.received_quantity}")

        print()

print("\nCONCLUSIÓN:")
print("Si las recepciones están en estado DRAFT, es normal que no tengan lotes.")
print("Si están en estado COMPLETED/RECEIVED, necesitan corrección.")
print("=" * 80)
