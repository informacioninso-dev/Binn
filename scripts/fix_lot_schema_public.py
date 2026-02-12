#!/usr/bin/env python
"""Hacer internal_lot y supplier_lot nullable en schema público."""

import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from django.db import connection

print("=" * 80)
print("ARREGLANDO SCHEMA DE LOT EN PUBLIC")
print("=" * 80)

with connection.cursor() as cursor:
    cursor.execute("SET search_path TO public;")

    # Verificar estado actual
    print("\n1. Estado actual de inventory_lot:")
    cursor.execute("""
        SELECT column_name, is_nullable, data_type
        FROM information_schema.columns
        WHERE table_schema='public'
        AND table_name='inventory_lot'
        AND column_name IN ('internal_lot', 'supplier_lot', 'lot_number')
        ORDER BY column_name;
    """)

    for row in cursor.fetchall():
        print(f"  {row[0]:20s} nullable={row[1]:3s} type={row[2]}")

    # Hacer internal_lot nullable
    print("\n2. Haciendo internal_lot nullable...")
    cursor.execute("""
        ALTER TABLE inventory_lot
        ALTER COLUMN internal_lot DROP NOT NULL;
    """)
    print("  [OK] internal_lot ahora es nullable")

    # Hacer supplier_lot nullable (si no lo es)
    print("\n3. Haciendo supplier_lot nullable...")
    cursor.execute("""
        ALTER TABLE inventory_lot
        ALTER COLUMN supplier_lot DROP NOT NULL;
    """)
    print("  [OK] supplier_lot ahora es nullable")

    # Verificar estado final
    print("\n4. Estado final de inventory_lot:")
    cursor.execute("""
        SELECT column_name, is_nullable, data_type
        FROM information_schema.columns
        WHERE table_schema='public'
        AND table_name='inventory_lot'
        AND column_name IN ('internal_lot', 'supplier_lot', 'lot_number')
        ORDER BY column_name;
    """)

    for row in cursor.fetchall():
        print(f"  {row[0]:20s} nullable={row[1]:3s} type={row[2]}")

print("\n" + "=" * 80)
print("SCHEMA ARREGLADO")
print("=" * 80)
