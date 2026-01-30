# Módulo de Producción

App: `production/`

## Modelos

### BillOfMaterial (BOM)

Lista de materiales para fabricar un producto terminado.

| Campo | Tipo | Descripción |
|-------|------|-------------|
| product_finished | FK → Product | Producto a fabricar |
| revision | CharField(10) | Versión del BOM (ej: "A", "B") |
| is_active | Boolean | Solo un BOM activo por producto |

**BillOfMaterialLine**: cada componente del BOM.

| Campo | Tipo | Descripción |
|-------|------|-------------|
| bom | FK → BillOfMaterial | BOM padre |
| component | FK → Product | Materia prima o semielaborado |
| quantity | Decimal | Cantidad por unidad de producto terminado |
| scrap_rate | Decimal | Tasa de merma esperada (ej: 0.02 = 2%) |
| sequence | Integer | Orden de los componentes |

### WorkCenter (Estación de trabajo)

Define una estación de producción con su capacidad operativa.

| Campo | Tipo | Descripción |
|-------|------|-------------|
| code | CharField(30) | Código único |
| name | CharField(100) | Nombre descriptivo |
| default_warehouse | FK → Warehouse | Bodega WIP asociada |
| capacity_per_hour | Decimal | Unidades que procesa por hora |
| num_machines | Integer | Máquinas/puestos paralelos |
| num_operators | Integer | Operarios disponibles |
| efficiency_factor | Decimal | Factor de eficiencia (0.85 = 85%) |
| setup_time_min | Integer | Minutos de preparación por lote |
| hours_per_shift | Decimal | Horas productivas por turno |
| shifts_per_day | Integer | Turnos por día |

**Propiedad calculada**: `available_minutes_per_day` = horas × turnos × máquinas × eficiencia × 60

### ProductRoute + ProductRouteStep

Ruta de producción: secuencia de pasos para fabricar un producto.

**ProductRouteStep**:

| Campo | Tipo | Descripción |
|-------|------|-------------|
| route | FK → ProductRoute | Ruta padre |
| sequence | Integer | Orden del paso (1, 2, 3...) |
| work_center | FK → WorkCenter | Estación donde se ejecuta |
| name | CharField | Nombre del paso (ej: "Corte", "Ensamble") |
| expected_duration_min | Integer | Minutos por unidad de producto |
| setup_time_min | Integer | Setup específico (override del WC) |
| requires_qa | Boolean | Si requiere inspección QA |

### ProductionPlan

Plan de producción con selección FEFO de lotes de materia prima.

| Campo | Tipo | Descripción |
|-------|------|-------------|
| code | CharField | Código auto-generado (PP-2026-0001) |
| product | FK → Product | Producto a producir |
| lot_code | CharField | Código del lote de producción |
| manufacturing_date | Date | Fecha de fabricación planificada |
| quantity_planned | Decimal | Cantidad a producir |
| status | CharField | DRAFT / CONFIRMED / CANCELLED |

**ProductionPlanRawLot**: reserva de lote de MP por componente.

| Campo | Tipo | Descripción |
|-------|------|-------------|
| plan | FK → ProductionPlan | Plan padre |
| lot | FK → Lot | Lote de MP reservado |
| component | FK → Product | Componente del BOM |
| quantity_planned | Decimal | Cantidad total a consumir (bom_qty × plan_qty × (1 + scrap)) |

### ProductionOrder

Orden de producción generada desde un plan.

| Campo | Tipo | Descripción |
|-------|------|-------------|
| code | CharField | Auto-generado (OP-2026-0001) |
| product | FK → Product | Producto a fabricar |
| quantity_planned | Decimal | Cantidad planificada |
| quantity_produced | Decimal | Cantidad realmente producida |
| route | FK → ProductRoute | Ruta de producción |
| bom | FK → BillOfMaterial | BOM utilizado |
| plan | FK → ProductionPlan | Plan origen |
| finished_lot | FK → Lot | Lote de producto terminado (se crea al cerrar) |
| start_date / end_date | Date | Fechas de producción |
| status | CharField | DRAFT → RELEASED → IN_PROGRESS → DONE |

### ProductionOperation

Ejecución de un paso de la ruta dentro de una OP.

| Campo | Tipo | Descripción |
|-------|------|-------------|
| order | FK → ProductionOrder | Orden padre |
| step | FK → ProductRouteStep | Paso de la ruta |
| sequence | Integer | Orden dentro de la OP |
| input_lot / output_lot | FK → Lot | Lotes WIP de entrada/salida |
| planned_start / planned_end | DateTime | Fechas planificadas (calculadas al liberar) |
| started_at / finished_at | DateTime | Fechas reales de ejecución |
| status | CharField | PENDING / IN_PROGRESS / PAUSED / HOLD / DONE / REJECTED |
| operator | FK → User | Operario que ejecuta |
| materials_consumed | Boolean | Guard de idempotencia |

### MaterialTransfer

Transferencia de MP desde bodega a estación de producción.

| Campo | Tipo | Descripción |
|-------|------|-------------|
| order | FK → ProductionOrder | OP asociada |
| component | FK → Product | MP a transferir |
| lot | FK → Lot | Lote específico |
| quantity_requested | Decimal | Cantidad calculada del plan |
| quantity_confirmed | Decimal | Cantidad confirmada por operario |
| from_warehouse / to_warehouse | FK → Warehouse | Origen y destino |
| status | CharField | PENDING / CONFIRMED / ADJUSTED |
| deviation_notes | Text | Notas si hay desviación |
| inventory_move | FK → InventoryMove | Movimiento registrado |

### OperationStatusLog

Registro de auditoría ISO 13485 por cada cambio de estado en operaciones.

| Campo | Tipo | Descripción |
|-------|------|-------------|
| operation | FK → ProductionOperation | Operación afectada |
| from_status / to_status | CharField | Estado anterior y nuevo |
| changed_at | DateTime | Fecha/hora del cambio |
| changed_by | FK → User | Usuario que realizó el cambio |
| notes | Text | Notas adicionales |

## Servicios principales

| Función | Descripción |
|---------|-------------|
| `consume_raw_materials_for_operation()` | Consume MP en el primer paso usando quantity_planned del plan |
| `close_production_order()` | Cierra OP, genera lote FG, reconcilia merma |
| `generate_material_transfers()` | Genera transferencias PENDING al liberar OP |
| `confirm_material_transfer()` | Operario confirma transferencia, registra movimiento TRANSFER |
| `estimate_production_duration()` | Estima duración por ruta considerando capacidad de estaciones |
| `schedule_production_order()` | Calcula planned_start/end por operación al liberar |
| `estimate_delivery_for_sale_order()` | Estima fecha de entrega para un pedido de venta |
| `log_operation_status_change()` | Registra cambio de estado en audit log |
| `create_wip_lot_for_operation()` | Crea lote WIP al completar una operación |
| `link_wip_lots_on_done()` | Encadena output_lot → input_lot entre operaciones |
| `reconcile_scrap()` | Compara merma teórica vs real al cerrar OP |

## Flujo completo

```
1. Crear ProductionPlan → selecciona lotes MP con FEFO
2. Crear ProductionOrder desde plan
3. Liberar OP (DRAFT → RELEASED):
   - Genera operaciones desde pasos de la ruta
   - Calcula fechas planificadas por operación
   - Genera transferencias de MP (MaterialTransfer PENDING)
4. Operario confirma transferencias de MP
5. Ejecución paso a paso:
   - Primer paso: consume MP (InventoryMove OUT)
   - Cada paso completado: genera lote WIP
   - Si requires_qa: auto-HOLD, espera aprobación QA
   - Audit log por cada cambio de estado
6. Último paso DONE → cierre automático:
   - Genera lote de producto terminado
   - Reconcilia merma (teórica vs real)
   - OP pasa a DONE
```
