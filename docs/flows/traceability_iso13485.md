# Trazabilidad ISO 13485

Flujo completo de trazabilidad desde recepción de materia prima hasta despacho al cliente.

## 1. Recepción de materia prima

- Se registra `RawMaterialReception` con datos del proveedor, documento, temperatura, peso.
- Cada línea genera un `Lot` en estado **PENDING** y bodega de **Cuarentena**.
- Se registra un `InventoryMove` tipo **IN** asociado al lote.
- El lote queda bloqueado hasta aprobación QA.

## 2. Control de calidad (QA) — Materia prima

- QA realiza inspección (`QualityInspection`) con checklist dinámico según `QAPlan`.
- Si resultado es **APPROVED**:
  - Se ejecuta `transfer_lot()` hacia bodega de materia prima (`WarehouseType.RAW`).
  - Lote disponible para planificación de producción.
- Si resultado es **REJECTED**:
  - Lote se transfiere a bodega de baja (`WarehouseType.SCRAP`).
- Si resultado es **QUARANTINE**:
  - Lote permanece bloqueado para re-inspección.

## 3. Planificación de producción

- Se crea `ProductionPlan` con producto, cantidad y fecha de fabricación.
- El sistema selecciona lotes de MP por **FEFO** (First Expiry, First Out).
- Se generan registros `ProductionPlanRawLot` con cantidad teórica calculada:
  - `quantity_planned = bom_qty_per_unit × plan_qty × (1 + scrap_rate)`
- Se genera el código de lote de producción.

## 4. Orden de producción

- Se crea `ProductionOrder` desde el plan.
- Al **liberar** la OP (DRAFT → RELEASED):
  - Se generan operaciones (`ProductionOperation`) desde la ruta.
  - Se calculan fechas planificadas por operación según capacidad de estaciones.
  - Se generan transferencias de MP (`MaterialTransfer` PENDING).

## 5. Transferencia de materia prima

- El operario recibe las transferencias pendientes con cantidad solicitada.
- Confirma la cantidad real transferida desde bodega MP a estación de producción.
- Si hay desviación → se registra alerta y notas.
- Se actualiza `LotBalance`: resta del origen, suma al destino WIP.
- Se registra `InventoryMove` tipo **TRANSFER**.

## 6. Ejecución de producción

- Paso a paso, cada operación cambia de estado:
  - PENDING → IN_PROGRESS → DONE (o PAUSED / HOLD / REJECTED)
- **Primer paso**: consume MP (`InventoryMove` tipo OUT desde lotes reservados).
- **Cada paso completado**: genera lote WIP (`{OP_CODE}-WIP-{seq}`).
- **Pasos con QA**: auto-HOLD hasta aprobación.
- **Audit log**: cada cambio de estado queda registrado en `OperationStatusLog`.
- **Operario**: cada operación registra quién la ejecutó.

## 7. Cierre de orden de producción

- Último paso DONE → cierre automático.
- Se genera lote de **producto terminado** (FG) en bodega de PT.
- Se ejecuta **reconciliación de merma**:
  - Merma teórica: `quantity_planned - quantity_produced`
  - Merma real por componente: consumo registrado vs consumo teórico.
- OP pasa a estado **DONE**.

## 8. QA de producto terminado

- Se ejecuta inspección QA sobre el lote FG.
- Si **APPROVED**: lote se transfiere a bodega de producto terminado liberado.
- Si **REJECTED**: lote se mueve a bodega de baja.

## 9. Despacho y facturación

- Pedido del cliente (`SaleOrder`) con líneas de producto.
- Asignación de lotes por **FEFO**.
- Despacho (`SaleDispatch`) con referencia a lotes enviados.
- Factura (`SaleInvoice`) con referencia opcional a lotes.
- Guía de remisión con datos de transporte.

## Consultas de trazabilidad

| Consulta | Cómo |
|----------|------|
| Dado un lote MP: ¿en qué OP se consumió? | `InventoryMove` con reference = OP code, lot = lote MP |
| Dado un lote FG: ¿qué MP se usó? | `ProductionPlanRawLot` del plan de la OP |
| Dado un lote FG: ¿quién lo produjo? | `OperationStatusLog` + `ProductionOperation.operator` |
| Dado un pedido: ¿qué lotes se enviaron? | `SaleDispatch.lot` |
| Dado un lote: historial completo | `InventoryMove.objects.filter(lot=lote).order_by("date")` |
| Tiempos reales vs planificados | `ProductionOperation.started_at/finished_at` vs `planned_start/planned_end` |
