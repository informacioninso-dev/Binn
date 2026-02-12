#!/usr/bin/env python
"""Manually add lot_number column to public schema."""

import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from django.db import connection

print("Adding lot_number column to public.procurement_rawmaterialreceptionline...")

with connection.cursor() as cursor:
    # Set to public schema
    cursor.execute("SET search_path TO public;")

    # Add lot_number column if it doesn't exist
    cursor.execute("""
        ALTER TABLE procurement_rawmaterialreceptionline
        ADD COLUMN IF NOT EXISTS lot_number VARCHAR(50) NULL;
    """)

    print("  Column added successfully")

    # Add comment to document the field
    cursor.execute("""
        COMMENT ON COLUMN procurement_rawmaterialreceptionline.lot_number IS
        'Número de lote único (puede ser del proveedor o auto-generado). Este será el lote usado en todo el sistema para trazabilidad.';
    """)

    print("  Comment added")

    # Verify
    cursor.execute("""
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema='public'
        AND table_name='procurement_rawmaterialreceptionline'
        AND column_name='lot_number';
    """)

    result = cursor.fetchone()
    if result:
        print("\nSUCCESS: lot_number column now exists in public schema")
    else:
        print("\nERROR: Column was not created")

print("\nNow adding lot_number column to public.inventory_lot...")

with connection.cursor() as cursor:
    cursor.execute("SET search_path TO public;")

    # Add lot_number column to Lot table
    cursor.execute("""
        ALTER TABLE inventory_lot
        ADD COLUMN IF NOT EXISTS lot_number VARCHAR(50) NULL;
    """)

    print("  Column added successfully")

    # Add comment
    cursor.execute("""
        COMMENT ON COLUMN inventory_lot.lot_number IS
        'Número de lote único para trazabilidad (del proveedor o auto-generado)';
    """)

    print("  Comment added")

    # Verify
    cursor.execute("""
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema='public'
        AND table_name='inventory_lot'
        AND column_name='lot_number';
    """)

    result = cursor.fetchone()
    if result:
        print("\nSUCCESS: lot_number column now exists in inventory_lot table")
    else:
        print("\nERROR: Column was not created")

print("\n" + "=" * 80)
print("Schema fix complete!")
print("=" * 80)
