# Trazabilidad ISO 13485

Este sistema permite trazar la historia de un lote desde recepción hasta despacho:

## 1. Recepción de materia prima

- Se registra `RawMaterialReception` con datos del proveedor, documento, temperatura, etc.
- Cada línea genera un `Lot` en estado PENDING y bodega de Cuarentena.
- Se registra un `InventoryMove` tipo IN asociado al lote.

## 2. Control de Calidad (QA)

- QA realiza inspección (`QualityInspection`).
- Si el resultado es `APPROVED`:
  - Se puede ejecutar `transfer_lot` hacia bodega de materia prima (`WarehouseType.RAW`).
- Si es `REJECTED`:
  - El lote puede transferirse a bodega de baja o scrap (`WarehouseType.SCRAP`).

## 3. Producción

- Las órdenes de producción (futuro módulo) consumen lotes:
  - `InventoryMove` tipo OUT desde bodegas de MP.
- Se generan nuevos lotes de producto terminado en bodega PT.

## 4. Despacho y facturación

- El despacho usa información de lotes (qué lotes se asignan a cada guía de remisión).
- La factura puede incluir referencia de lote (opcional según cliente/regulador).

## Consultas de trazabilidad

- Dado un lote: ver recepciones, QA, transferencias y consumos.
- Dada una guía de remisión: ver qué lotes se enviaron.
