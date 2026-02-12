#!/usr/bin/env python
"""Simple test for lot consolidation - creates minimal test data."""

import os
import django
from decimal import Decimal
from datetime import date, time

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from django_tenants.utils import schema_context
from partners.models import Partner
from inventory.models import Product, ProductType
from core.models import Unit, Warehouse, WarehouseType
from procurement.services import create_raw_material_reception
from django.contrib.auth import get_user_model

User = get_user_model()

TENANT_SCHEMA = 'acme'

print("=" * 80)
print(f"TESTING LOT CONSOLIDATION - TENANT: {TENANT_SCHEMA}")
print("=" * 80)

with schema_context(TENANT_SCHEMA):
    # Get user
    user = User.objects.first()
    print(f"\nUser: {user.username}")

    # Get or create supplier
    supplier, created = Partner.objects.get_or_create(
        identification="12345678901",
        defaults={
            "trade_name": "Test Supplier SA",
            "legal_name": "Test Supplier SA",
            "is_supplier": True,
            "is_qualified_supplier": True,
            "is_active": True,
        }
    )
    print(f"Supplier: {supplier.trade_name} {'(created)' if created else '(existing)'}")

    # Get base unit (kg)
    unit_kg = Unit.objects.filter(code='kg').first()
    if not unit_kg:
        print("ERROR: No kg unit found")
        exit(1)
    print(f"Unit: {unit_kg.name} ({unit_kg.code})")

    # Get or create a raw material product
    product, created = Product.objects.get_or_create(
        code="RM-TEST-001",
        defaults={
            "name": "Test Raw Material",
            "product_type": ProductType.RAW,
            "base_unit": unit_kg,
            "is_active": True,
            "unit_price": Decimal("10.00"),
        }
    )
    print(f"Product: {product.code} - {product.name} {'(created)' if created else '(existing)'}")

    # Get or create quarantine warehouse
    warehouse, created = Warehouse.objects.get_or_create(
        code="QUAR",
        defaults={
            "name": "Cuarentena",
            "type": WarehouseType.QUARANTINE,
            "is_default_quarantine": True,
            "is_active": True,
        }
    )

    # Update warehouse if it exists but doesn't have the right type
    if not created:
        warehouse.type = WarehouseType.QUARANTINE
        warehouse.is_default_quarantine = True
        warehouse.is_active = True
        warehouse.save()

    print(f"Warehouse: {warehouse.name} (type: {warehouse.type}) {'(created)' if created else '(updated)'}")

    # TEST 1: With supplier lot
    print("\n" + "-" * 80)
    print("TEST 1: Reception WITH supplier lot")
    print("-" * 80)

    try:
        reception_1 = create_raw_material_reception(
            user=user,
            header_data={
                "supplier_name": supplier.trade_name,
                "supplier_ruc": supplier.identification,
                "document_type": "Factura",
                "document_number": "F-001",
                "reception_date": date.today(),
                "arrival_time": time(10, 0),
            },
            lines_data=[
                {
                    "product": product,
                    "received_quantity": Decimal("100.00"),
                    "unit": unit_kg,
                    "unit_cost": Decimal("15.00"),
                    "lot_number": "SUPPLIER-LOT-ABC123",  # Supplier provides
                    "expiry_date": date(2027, 12, 31),
                    "storage_area": "Bodega A",
                }
            ]
        )

        line = reception_1.lines.first()
        print(f"Reception: {reception_1.code}")
        print(f"  Line lot_number: {line.lot_number}")
        print(f"  Expected: SUPPLIER-LOT-ABC123")
        print(f"  Match: {'YES' if line.lot_number == 'SUPPLIER-LOT-ABC123' else 'NO'}")

        # Check inventory lot
        from inventory.models import Lot
        inv_lot = Lot.objects.filter(lot_number=line.lot_number).first()
        if inv_lot:
            print(f"  Inventory Lot: {inv_lot.lot_number} (status: {inv_lot.status})")
        else:
            print(f"  ERROR: No inventory lot found")

    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()

    # TEST 2: Without supplier lot (auto-generate)
    print("\n" + "-" * 80)
    print("TEST 2: Reception WITHOUT supplier lot (auto-generate)")
    print("-" * 80)

    try:
        reception_2 = create_raw_material_reception(
            user=user,
            header_data={
                "supplier_name": supplier.trade_name,
                "supplier_ruc": supplier.identification,
                "document_type": "Factura",
                "document_number": "F-002",
                "reception_date": date.today(),
                "arrival_time": time(11, 0),
            },
            lines_data=[
                {
                    "product": product,
                    "received_quantity": Decimal("50.00"),
                    "unit": unit_kg,
                    "unit_cost": Decimal("15.00"),
                    "lot_number": "",  # Empty - should auto-generate
                    "expiry_date": date(2027, 12, 31),
                }
            ]
        )

        line = reception_2.lines.first()
        print(f"Reception: {reception_2.code}")
        print(f"  Line lot_number (auto): {line.lot_number}")
        print(f"  Starts with LOT-: {line.lot_number.startswith('LOT-')}")

        # Check inventory lot
        from inventory.models import Lot
        inv_lot = Lot.objects.filter(lot_number=line.lot_number).first()
        if inv_lot:
            print(f"  Inventory Lot: {inv_lot.lot_number} (status: {inv_lot.status})")
        else:
            print(f"  ERROR: No inventory lot found")

    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()

    print("\n" + "=" * 80)
    print("TESTS COMPLETE!")
    print("=" * 80)
    print("\nSUMMARY:")
    print("  The lot consolidation system should:")
    print("  1. Use supplier lot when provided")
    print("  2. Auto-generate lot when not provided")
    print("  3. Store in single lot_number field")
    print("  4. Create matching inventory Lot records")
    print("=" * 80)
