# Arquitectura del sistema

## Principios

1. **Modularidad**: cada app Django es un dominio funcional independiente.
2. **Auditoría**: todos los modelos heredan de `AuditModel` (created_at, updated_at, created_by, updated_by).
3. **Trazabilidad total**: cada movimiento de inventario queda registrado por lote, bodega y ubicación.
4. **ISO 13485**: flujos de QA obligatorios, estados de lote (PENDING → APPROVED/REJECTED), audit logs.

## Apps y responsabilidades

```
core/         → Catálogos compartidos: Unit, Warehouse, Location, TaxScheme
inventory/    → Product, Stock, Lot, LotBalance, InventoryMove
partners/     → Partner (cliente + proveedor en una entidad)
procurement/  → PurchaseOrder, RawMaterialReception
production/   → BOM, ProductRoute, WorkCenter, ProductionPlan, ProductionOrder, ProductionOperation, MaterialTransfer
quality/      → QAPlan, QAParameterTemplate, QualityInspection
sales/        → SaleOrder, SaleDispatch, SaleInvoice
```

## Capas de la aplicación

```
┌─────────────────────────────────────────┐
│           Templates (Tailwind)          │
├─────────────────────────────────────────┤
│         Views (CBV / FBV)               │
├─────────────────────────────────────────┤
│         Forms (ModelForm)               │
├─────────────────────────────────────────┤
│     Services (lógica de dominio)        │  ← register_inventory_move, consume_raw_materials, etc.
├─────────────────────────────────────────┤
│         Models (ORM Django)             │
├─────────────────────────────────────────┤
│       Base de datos (SQLite/PG)         │
└─────────────────────────────────────────┘
```

## Inventario — modelo de datos clave

- **Stock**: cantidad total por producto (no distingue ubicación).
- **Lot**: lote con estado (PENDING, APPROVED, REJECTED, QUARANTINE), bodega y ubicación actuales.
- **LotBalance**: cantidad de un lote en una ubicación específica (unique: lot + location).
- **InventoryMove**: registro inmutable de cada movimiento (IN, OUT, ADJ, TRANSFER).

## Producción — flujo completo

```
ProductionPlan (FEFO de lotes MP)
  → ProductionOrder (DRAFT)
    → Liberación (DRAFT → RELEASED)
      → Genera operaciones desde ruta
      → Genera transferencias de MP (MaterialTransfer)
      → Calcula fechas planificadas por operación
    → Ejecución paso a paso
      → Consumo de MP en primer paso
      → WIP lots entre pasos
      → QA intermedio (HOLD automático)
      → Audit log por cambio de estado
    → Cierre OP → Lote FG + reconciliación de merma
```

## Estaciones de trabajo — capacidad operativa

Cada `WorkCenter` define:

- Máquinas/puestos paralelos (`num_machines`)
- Operarios (`num_operators`)
- Eficiencia real (`efficiency_factor`, ej: 0.85)
- Horas por turno, turnos por día
- Tiempo de setup por lote

**Minutos productivos/día** = horas_turno × turnos × máquinas × eficiencia × 60

Esto alimenta:

- `estimate_production_duration()` — estimación de duración por ruta y cantidad
- `schedule_production_order()` — asigna planned_start/planned_end al liberar OP
- `estimate_delivery_for_sale_order()` — fecha estimada de entrega para pedidos

## Bodegas (WarehouseType)

| Tipo | Código | Uso |
|------|--------|-----|
| Cuarentena | QUARANTINE | MP recién recibida, pendiente QA |
| Materia prima | RAW | MP aprobada, lista para producción |
| Semielaborado | WIP | Producto en proceso entre operaciones |
| Producto terminado | FINISHED | FG aprobado, listo para despacho |
| Baja | SCRAP | Material rechazado |
| Devoluciones | RETURNS | Devoluciones de clientes |
| Predespacho | STAGING | Zona de picking |
| Muestras | SAMPLES | Retención QA |
| Etiquetas | LABELS | Material de etiquetado |
| Empaque | PACK | Material de empaque |
