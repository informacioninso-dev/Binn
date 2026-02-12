#!/usr/bin/env python
"""Check database schema for lot_number column across tenant schemas."""

import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from django.db import connection

def check_schema_columns(schema_name):
    """Check if lot_number column exists in a schema."""
    with connection.cursor() as cursor:
        cursor.execute(f"SET search_path TO {schema_name};")
        cursor.execute("""
            SELECT column_name, data_type
            FROM information_schema.columns
            WHERE table_schema=%s
            AND table_name='procurement_rawmaterialreceptionline'
            ORDER BY ordinal_position;
        """, [schema_name])

        columns = cursor.fetchall()
        return columns

# Check public schema
print("=" * 80)
print("PUBLIC SCHEMA")
print("=" * 80)
cols = check_schema_columns('public')
if cols:
    print(f"Found {len(cols)} columns:")
    for col_name, col_type in cols:
        marker = " <-- NEW" if col_name == 'lot_number' else ""
        marker = marker or (" <-- DEPRECATED" if col_name in ['supplier_lot', 'internal_lot'] else "")
        print(f"  {col_name:30s} {col_type:20s}{marker}")
else:
    print("  Table not found")

# Get all tenant schemas
print("\n" + "=" * 80)
print("TENANT SCHEMAS")
print("=" * 80)

with connection.cursor() as cursor:
    cursor.execute("""
        SELECT schema_name
        FROM information_schema.schemata
        WHERE schema_name NOT IN ('public', 'information_schema', 'pg_catalog', 'pg_toast')
        AND schema_name NOT LIKE 'pg_%'
        ORDER BY schema_name;
    """)
    tenant_schemas = [row[0] for row in cursor.fetchall()]

if not tenant_schemas:
    print("No tenant schemas found")
else:
    for schema in tenant_schemas:
        print(f"\nSchema: {schema}")
        cols = check_schema_columns(schema)
        if cols:
            has_lot_number = any(col[0] == 'lot_number' for col in cols)
            has_old_fields = any(col[0] in ['supplier_lot', 'internal_lot'] for col in cols)

            if has_lot_number and not has_old_fields:
                print(f"  [OK] Has lot_number, no deprecated fields")
            elif has_lot_number and has_old_fields:
                print(f"  [TRANSITION] Has lot_number AND deprecated fields (normal during migration)")
            elif not has_lot_number and has_old_fields:
                print(f"  [MISSING] No lot_number, only deprecated fields - NEEDS MIGRATION")
            else:
                print(f"  [UNKNOWN STATE]")
        else:
            print(f"  Table not found in this schema")

print("\n" + "=" * 80)
