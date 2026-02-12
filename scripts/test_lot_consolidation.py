#!/usr/bin/env python
"""Test the consolidated lot system with a reception."""

import os
import django
from decimal import Decimal
from datetime import date, time

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from django_tenants.utils import schema_context
from partners.models import Partner
from inventory.models import Product, ProductType
from procurement.services import create_raw_material_reception
from django.contrib.auth import get_user_model

User = get_user_model()

# Use a test tenant
TENANT_SCHEMA = 'acme'  # Changed from 'test' to 'acme' which has more data

print("=" * 80)
print(f"TESTING LOT CONSOLIDATION IN TENANT: {TENANT_SCHEMA}")
print("=" * 80)

with schema_context(TENANT_SCHEMA):
    # Get or create test user
    try:
        user = User.objects.first()
        if not user:
            print("ERROR: No users found in database")
            exit(1)
        print(f"\nUsing user: {user.username}")
    except Exception as e:
        print(f"ERROR getting user: {e}")
        exit(1)

    # Get or create test supplier
    try:
        supplier = Partner.objects.filter(is_supplier=True, is_active=True).first()
        if not supplier:
            print("ERROR: No active suppliers found")
            exit(1)
        print(f"Using supplier: {supplier.trade_name}")
    except Exception as e:
        print(f"ERROR getting supplier: {e}")
        exit(1)

    # Get a raw material product
    try:
        product = Product.objects.filter(
            product_type=ProductType.RAW,
            is_active=True
        ).first()

        if not product:
            print("ERROR: No active raw material products found")
            exit(1)

        print(f"Using product: {product.code} - {product.name}")
        print(f"  Base unit: {product.base_unit.name}")
    except Exception as e:
        print(f"ERROR getting product: {e}")
        exit(1)

    # Test Case 1: Reception WITH supplier lot number
    print("\n" + "-" * 80)
    print("TEST 1: Reception with SUPPLIER LOT NUMBER")
    print("-" * 80)

    header_data_1 = {
        "supplier_name": supplier.trade_name,
        "supplier_ruc": supplier.tax_id or "",
        "document_type": "Factura",
        "document_number": "F001-12345",
        "reception_date": date.today(),
        "arrival_time": time(14, 30),
        "transport_company": "Transporte Test S.A.",
        "transport_plate": "ABC-123",
        "observations": "Test con lote de proveedor",
    }

    lines_data_1 = [
        {
            "product": product,
            "received_quantity": Decimal("100.00"),
            "unit": product.base_unit,
            "unit_cost": Decimal("15.50"),
            "lot_number": "PROV-LOT-2026-001",  # Supplier provides lot number
            "expiry_date": date(2027, 12, 31),
            "manufacturing_date": date(2026, 1, 1),
            "storage_area": "Bodega A",
            "line_notes": "Lote del proveedor",
        }
    ]

    try:
        reception_1 = create_raw_material_reception(
            user=user,
            header_data=header_data_1,
            lines_data=lines_data_1
        )

        print(f"\n[SUCCESS] Reception created: {reception_1.code}")
        print(f"  Status: {reception_1.get_status_display()}")
        print(f"  Lines: {reception_1.lines.count()}")

        # Check the reception line
        line = reception_1.lines.first()
        print(f"\n  Line details:")
        print(f"    Product: {line.product.code}")
        print(f"    Quantity: {line.received_quantity} {line.unit.symbol}")
        print(f"    LOT NUMBER: {line.lot_number}")  # Should be PROV-LOT-2026-001
        print(f"    Expiry: {line.expiry_date}")

        # Check if lot was created in inventory
        from inventory.models import Lot
        lot = Lot.objects.filter(product=product, lot_number=line.lot_number).first()
        if lot:
            print(f"\n  Inventory Lot created:")
            print(f"    Lot number: {lot.lot_number}")  # Should match
            print(f"    Initial quantity: {lot.quantity_initial}")
            print(f"    Status: {lot.get_status_display()}")
        else:
            print(f"\n  [WARNING] No Lot found in inventory with lot_number: {line.lot_number}")

    except Exception as e:
        print(f"\n[ERROR] Failed to create reception 1: {e}")
        import traceback
        traceback.print_exc()

    # Test Case 2: Reception WITHOUT supplier lot (should auto-generate)
    print("\n" + "-" * 80)
    print("TEST 2: Reception WITHOUT supplier lot (auto-generate)")
    print("-" * 80)

    header_data_2 = {
        "supplier_name": supplier.trade_name,
        "supplier_ruc": supplier.tax_id or "",
        "document_type": "Factura",
        "document_number": "F001-12346",
        "reception_date": date.today(),
        "arrival_time": time(15, 45),
        "observations": "Test sin lote de proveedor - deberia autogenerar",
    }

    lines_data_2 = [
        {
            "product": product,
            "received_quantity": Decimal("50.00"),
            "unit": product.base_unit,
            "unit_cost": Decimal("15.50"),
            "lot_number": "",  # Empty - should auto-generate
            "expiry_date": date(2027, 12, 31),
            "storage_area": "Bodega B",
        }
    ]

    try:
        reception_2 = create_raw_material_reception(
            user=user,
            header_data=header_data_2,
            lines_data=lines_data_2
        )

        print(f"\n[SUCCESS] Reception created: {reception_2.code}")

        line = reception_2.lines.first()
        print(f"\n  Line details:")
        print(f"    Product: {line.product.code}")
        print(f"    Quantity: {line.received_quantity} {line.unit.symbol}")
        print(f"    LOT NUMBER (auto-generated): {line.lot_number}")  # Should be auto-generated
        print(f"    Pattern should be: LOT-{product.code}-XXXXXX")

        # Check inventory lot
        from inventory.models import Lot
        lot = Lot.objects.filter(product=product, lot_number=line.lot_number).first()
        if lot:
            print(f"\n  Inventory Lot created:")
            print(f"    Lot number: {lot.lot_number}")
            print(f"    Matches reception line: {lot.lot_number == line.lot_number}")
        else:
            print(f"\n  [WARNING] No Lot found in inventory")

    except Exception as e:
        print(f"\n[ERROR] Failed to create reception 2: {e}")
        import traceback
        traceback.print_exc()

    print("\n" + "=" * 80)
    print("TEST COMPLETE")
    print("=" * 80)
    print("\nVERIFICATION:")
    print("  1. Both receptions should have created successfully")
    print("  2. Reception 1 should use supplier lot: PROV-LOT-2026-001")
    print("  3. Reception 2 should have auto-generated lot starting with LOT-")
    print("  4. Each reception line should have matching Lot in inventory")
    print("  5. NO supplier_lot or internal_lot fields should be used (deprecated)")
    print("=" * 80)
