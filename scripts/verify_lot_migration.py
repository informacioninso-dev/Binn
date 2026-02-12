#!/usr/bin/env python
"""Verificar que la migración de lotes se completó correctamente."""

import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from django_tenants.utils import schema_context, get_tenant_model
from inventory.models import Lot
from procurement.models import RawMaterialReceptionLine

print("=" * 80)
print("VERIFICACIÓN DE MIGRACIÓN DE LOTES")
print("=" * 80)

# Get all tenants
TenantModel = get_tenant_model()
tenants = TenantModel.objects.all()

for tenant in tenants:
    print(f"\n{'=' * 80}")
    print(f"TENANT: {tenant.schema_name} ({tenant.name})")
    print("=" * 80)

    with schema_context(tenant.schema_name):
        # Verificar lotes de inventario
        print("\n1. LOTES DE INVENTARIO (inventory.Lot)")
        print("-" * 80)

        total_lots = Lot.objects.count()
        lots_with_lot_number = Lot.objects.exclude(lot_number__isnull=True).exclude(lot_number='').count()
        lots_without_lot_number = total_lots - lots_with_lot_number

        print(f"  Total de lotes: {total_lots}")
        print(f"  Con lot_number: {lots_with_lot_number}")
        print(f"  Sin lot_number: {lots_without_lot_number}")

        if lots_without_lot_number > 0:
            print(f"\n  [WARNING] Hay {lots_without_lot_number} lotes SIN lot_number!")
            print("  Primeros 5 lotes problemáticos:")
            problem_lots = Lot.objects.filter(lot_number__isnull=True) | Lot.objects.filter(lot_number='')
            for lot in problem_lots[:5]:
                print(f"    - Lot ID {lot.id}: Product {lot.product.code}, supplier_lot={lot.supplier_lot}, internal_lot={lot.internal_lot}")
        else:
            print(f"  [OK] Todos los lotes tienen lot_number")

        # Mostrar algunos ejemplos
        if total_lots > 0:
            print("\n  Ejemplos de lotes (primeros 5):")
            for lot in Lot.objects.all()[:5]:
                print(f"    - {lot.product.code}: lot_number='{lot.lot_number}', status={lot.status}")

        # Verificar líneas de recepción
        print("\n2. LÍNEAS DE RECEPCIÓN (procurement.RawMaterialReceptionLine)")
        print("-" * 80)

        total_lines = RawMaterialReceptionLine.objects.count()
        lines_with_lot_number = RawMaterialReceptionLine.objects.exclude(lot_number__isnull=True).exclude(lot_number='').count()
        lines_without_lot_number = total_lines - lines_with_lot_number

        print(f"  Total de líneas: {total_lines}")
        print(f"  Con lot_number: {lines_with_lot_number}")
        print(f"  Sin lot_number: {lines_without_lot_number}")

        if lines_without_lot_number > 0:
            print(f"\n  [WARNING] Hay {lines_without_lot_number} líneas SIN lot_number!")
            print("  Primeras 5 líneas problemáticas:")
            problem_lines = RawMaterialReceptionLine.objects.filter(lot_number__isnull=True) | RawMaterialReceptionLine.objects.filter(lot_number='')
            for line in problem_lines[:5]:
                print(f"    - Line ID {line.id}: Reception {line.reception.code}, Product {line.product.code}")
        else:
            print(f"  [OK] Todas las líneas tienen lot_number")

        # Mostrar algunos ejemplos
        if total_lines > 0:
            print("\n  Ejemplos de líneas de recepción (primeras 5):")
            for line in RawMaterialReceptionLine.objects.all()[:5]:
                print(f"    - {line.reception.code}: Product {line.product.code}, lot_number='{line.lot_number}'")

        # Verificar campos deprecados
        print("\n3. CAMPOS DEPRECADOS (supplier_lot, internal_lot)")
        print("-" * 80)

        lots_with_supplier_lot = Lot.objects.exclude(supplier_lot__isnull=True).exclude(supplier_lot='').count()
        lots_with_internal_lot = Lot.objects.exclude(internal_lot__isnull=True).exclude(internal_lot='').count()

        print(f"  Lotes con supplier_lot aún poblado: {lots_with_supplier_lot}")
        print(f"  Lotes con internal_lot aún poblado: {lots_with_internal_lot}")
        print(f"  [INFO] Estos campos están deprecados pero se mantienen por ahora")

        lines_with_supplier_lot = RawMaterialReceptionLine.objects.exclude(supplier_lot__isnull=True).exclude(supplier_lot='').count()
        lines_with_internal_lot = RawMaterialReceptionLine.objects.exclude(internal_lot__isnull=True).exclude(internal_lot='').count()

        print(f"  Líneas con supplier_lot aún poblado: {lines_with_supplier_lot}")
        print(f"  Líneas con internal_lot aún poblado: {lines_with_internal_lot}")

print("\n" + "=" * 80)
print("RESUMEN")
print("=" * 80)
print("La migración está completa si:")
print("  1. Todos los lotes tienen lot_number")
print("  2. Todas las líneas de recepción tienen lot_number")
print("  3. No hay warnings arriba")
print("\nSi todo está OK, puedes proceder a probar la UI manualmente.")
print("=" * 80)
