#!/usr/bin/env python
"""Verificación final antes de producción."""

import subprocess
import sys

print("=" * 80)
print("VERIFICACIÓN FINAL - SISTEMA DE LOTE ÚNICO")
print("=" * 80)

# 1. Verificar migración de datos
print("\n1. Verificando migración de datos...")
result = subprocess.run([sys.executable, "verify_lot_migration.py"], capture_output=True, text=True)
if "No hay warnings arriba" in result.stdout:
    print("   [OK] Migracion de datos OK")
else:
    print("   [ERROR] Hay warnings en la migracion de datos")
    print(result.stdout)

# 2. Verificar referencias en código activo
print("\n2. Verificando referencias en código activo...")
cmd = 'grep -r "supplier_lot\\|internal_lot" --include="*.py" . 2>/dev/null | grep -v migration | grep -v "test_" | grep -v "check_" | grep -v "fix_" | grep -v "verify_" | grep -v "models.py" | grep -v "VERIFICATION"'

try:
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True, cwd=".")
    lines = [l for l in result.stdout.split('\n') if l.strip() and 'Binary file' not in l]

    if not lines:
        print("   [OK] No hay referencias a campos deprecados en codigo activo")
    else:
        print(f"   [WARNING] Se encontraron {len(lines)} referencias:")
        for line in lines[:10]:  # Mostrar primeras 10
            print(f"     - {line}")
except Exception as e:
    print(f"   [WARNING] Error al verificar: {e}")

# 3. Verificar templates
print("\n3. Verificando templates HTML...")
cmd = 'find templates -name "*.html" -type f -exec grep -l "supplier_lot\\|internal_lot" {} \\; 2>/dev/null'

try:
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True, cwd=".")
    files = [f for f in result.stdout.split('\n') if f.strip()]

    if not files:
        print("   [OK] No hay referencias en templates")
    else:
        print(f"   [WARNING] Se encontraron referencias en {len(files)} templates:")
        for f in files[:5]:
            print(f"     - {f}")
except Exception as e:
    print(f"   [WARNING] Error al verificar: {e}")

print("\n" + "=" * 80)
print("RESUMEN")
print("=" * 80)
print("\nSi todos los checks pasan con [OK], el sistema esta listo para:")
print("  1. Pruebas manuales de UI")
print("  2. Deployment a producción")
print("\nSiguiente paso: Seguir MANUAL_TESTING_GUIDE.md")
print("=" * 80)
