#!/usr/bin/env python
"""Actualizar referencias de supplier_lot/internal_lot a lot_number en templates."""

import os
import re
from pathlib import Path

TEMPLATES_DIR = Path("templates")

# Patrones a reemplazar
REPLACEMENTS = [
    # lot.internal_lot -> lot.lot_number
    (r'lot\.internal_lot', 'lot.lot_number'),

    # line.internal_lot -> line.lot_number
    (r'line\.internal_lot', 'line.lot_number'),

    # line.supplier_lot -> line.lot_number
    (r'line\.supplier_lot', 'line.lot_number'),

    # lot.supplier_lot -> lot.lot_number
    (r'lot\.supplier_lot', 'line.lot_number'),

    # move.lot.internal_lot -> move.lot.lot_number
    (r'move\.lot\.internal_lot', 'move.lot.lot_number'),

    # input_lot.internal_lot -> input_lot.lot_number
    (r'input_lot\.internal_lot', 'input_lot.lot_number'),

    # output_lot.internal_lot -> output_lot.lot_number
    (r'output_lot\.internal_lot', 'output_lot.lot_number'),

    # item.lot.internal_lot -> item.lot.lot_number
    (r'item\.lot\.internal_lot', 'item.lot.lot_number'),
]

def update_file(file_path):
    """Actualizar un archivo HTML."""
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()

    original_content = content
    changes = []

    for pattern, replacement in REPLACEMENTS:
        if re.search(pattern, content):
            count = len(re.findall(pattern, content))
            content = re.sub(pattern, replacement, content)
            changes.append(f"  - {pattern} -> {replacement} ({count} occurrences)")

    if content != original_content:
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(content)
        return changes

    return None

def main():
    print("=" * 80)
    print("ACTUALIZANDO TEMPLATES")
    print("=" * 80)

    updated_files = 0
    total_changes = 0

    for html_file in TEMPLATES_DIR.rglob("*.html"):
        changes = update_file(html_file)
        if changes:
            updated_files += 1
            total_changes += len(changes)
            print(f"\n{html_file}:")
            for change in changes:
                print(change)

    print("\n" + "=" * 80)
    print("RESUMEN")
    print("=" * 80)
    print(f"Archivos actualizados: {updated_files}")
    print(f"Total de cambios: {total_changes}")
    print("=" * 80)

if __name__ == "__main__":
    main()
