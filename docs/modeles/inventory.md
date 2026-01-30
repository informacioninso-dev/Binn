# Módulo de Inventario

App: `inventory/`

## Modelos

### Product

Producto del catálogo (MP, semielaborado, producto terminado, empaque).

| Campo | Tipo | Descripción |
|-------|------|-------------|
| product_type | CharField | RAW / SEMI / FG / PACK |
| code | CharField(50) | Código único del producto |
| name | CharField(200) | Nombre descriptivo |
| base_unit | FK → Unit | Unidad de medida base (kg, m, unid) |
| unit_price | Decimal | Precio de venta |
| unit_cost | Decimal | Costo unitario |
| lot_prefix | CharField | Prefijo para generar códigos de lote |
| is_active | Boolean | Estado del producto |

### Stock

Cantidad total de un producto (una fila por producto, sin distinción de ubicación).

| Campo | Tipo | Descripción |
|-------|------|-------------|
| product | OneToOne → Product | Producto |
| quantity | Decimal(12,4) | Cantidad total en inventario |

### Lot

Lote de producto con trazabilidad completa.

| Campo | Tipo | Descripción |
|-------|------|-------------|
| product | FK → Product | Producto del lote |
| internal_lot | CharField(50) | Código de lote interno |
| supplier_lot | CharField(50) | Código de lote del proveedor |
| quantity_initial | Decimal | Cantidad inicial al crear el lote |
| warehouse | FK → Warehouse | Bodega actual |
| location | FK → Location | Ubicación actual |
| manufacturing_date | Date | Fecha de fabricación |
| expiry_date | Date | Fecha de vencimiento (para FEFO) |
| status | CharField | PENDING / APPROVED / REJECTED / QUARANTINE |

**Propiedad**: `quantity_current` = suma de todos los `LotBalance.qty` del lote.

### LotBalance

Cantidad de un lote en una ubicación específica. Permite rastrear el mismo lote en múltiples bodegas.

| Campo | Tipo | Descripción |
|-------|------|-------------|
| lot | FK → Lot | Lote |
| warehouse | FK → Warehouse | Bodega |
| location | FK → Location | Ubicación dentro de la bodega |
| qty | Decimal(12,4) | Cantidad en esta ubicación |

**Constraint**: unique (lot, location)

### InventoryMove

Registro inmutable de cada movimiento de inventario.

| Campo | Tipo | Descripción |
|-------|------|-------------|
| product | FK → Product | Producto movido |
| lot | FK → Lot | Lote asociado |
| movement_type | CharField | IN / OUT / ADJ / TRANSFER |
| quantity | Decimal | Cantidad en unidad base |
| unit_displayed | FK → Unit | Unidad que vio el usuario |
| quantity_displayed | Decimal | Cantidad ingresada por el usuario |
| warehouse | FK → Warehouse | Bodega destino |
| location | FK → Location | Ubicación destino |
| from_warehouse / to_warehouse | FK → Warehouse | Para transferencias |
| from_location / to_location | FK → Location | Para transferencias |
| reference | CharField | Referencia (OP, factura, etc.) |
| area | CharField | Área funcional (CONSUMO PRODUCCION, TRANSFERENCIA, etc.) |
| reason | CharField | RECEIPT / QA_TO_QUARANTINE / RELEASE_TO_STOCK / PICKING / SHIPPING / RETURN / RECALL |

## Servicios principales

| Función | Descripción |
|---------|-------------|
| `register_inventory_move()` | Registra movimiento, actualiza Stock y LotBalance. Usa `select_for_update()` para evitar race conditions |
| `transfer_lot()` | Transfiere un lote completo a otra bodega (actualiza LotBalance) |
| `pick_lots_fefo()` | Selecciona lotes por FEFO (First Expiry, First Out) |
| `get_fefo_lots_for_product()` | Obtiene lotes disponibles ordenados por fecha de vencimiento |

## Reglas de negocio

- Stock no puede ser negativo.
- LotBalance no puede ser negativo.
- Solo se pueden consumir (OUT) lotes con status = APPROVED.
- Las transferencias no permiten mover a bodega QUARANTINE.
- Toda operación sobre lotes queda registrada como InventoryMove.
