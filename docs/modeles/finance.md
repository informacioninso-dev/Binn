# Módulo de Compras y Finanzas

App: `procurement/` y `partners/`

## Modelos — Compras

### PurchaseOrder (Orden de compra)

| Campo | Tipo | Descripción |
|-------|------|-------------|
| number | CharField(20) | Número de la OC |
| supplier | FK → Partner | Proveedor |
| order_date | Date | Fecha de la orden |
| status | CharField | DRAFT / CONFIRMED / RECEIVED / CANCELED |
| currency | CharField(5) | Moneda (USD, etc.) |
| total_amount | Decimal | Monto total |

### PurchaseOrderLine

| Campo | Tipo | Descripción |
|-------|------|-------------|
| order | FK → PurchaseOrder | OC padre |
| product | FK → Product | Producto a comprar |
| quantity | Decimal | Cantidad solicitada |
| unit_price | Decimal | Precio unitario |
| unit | FK → Unit | Unidad de medida |
| line_total | Decimal | Total de la línea |

### RawMaterialReception (Recepción de MP)

| Campo | Tipo | Descripción |
|-------|------|-------------|
| purchase_order | FK → PurchaseOrder | OC asociada (opcional) |
| code | CharField(50) | Código de recepción |
| supplier_name | CharField | Nombre del proveedor |
| reception_date | Date | Fecha de recepción |
| temperature_recorded | Decimal | Temperatura al recibir |
| num_boxes | Integer | Cantidad de cajas |
| gross_weight / net_weight | Decimal | Pesos bruto y neto |
| status | CharField | DRAFT / COMPLETED |

### RawMaterialReceptionLine

| Campo | Tipo | Descripción |
|-------|------|-------------|
| reception | FK → RawMaterialReception | Recepción padre |
| product | FK → Product | Producto recibido |
| received_quantity | Decimal | Cantidad recibida |
| unit | FK → Unit | Unidad de medida |
| supplier_lot | CharField | Lote del proveedor |
| internal_lot | CharField | Lote interno generado |
| expiry_date | Date | Fecha de vencimiento |

## Modelos — Partners

### Partner (Cliente / Proveedor)

Entidad única con flags `is_customer` e `is_supplier`.

| Campo | Tipo | Descripción |
|-------|------|-------------|
| code | CharField(20) | Código interno |
| identification_type | CharField | RUC / CI / PASAPORTE |
| identification | CharField | Número de identificación |
| trade_name | CharField | Nombre comercial |
| legal_name | CharField | Razón social |
| is_customer / is_supplier | Boolean | Tipo de partner |
| credit_limit / credit_available | Decimal | Crédito asignado y disponible |
| is_qualified_supplier | Boolean | Proveedor calificado ISO |
| qualification_level | CharField | Nivel de calificación |

## Flujo de compra

```
Orden de compra (DRAFT → CONFIRMED)
  → Recepción de materia prima
  → Genera lotes en PENDING + bodega Cuarentena
  → InventoryMove tipo IN
  → QA → Aprobación / Rechazo
```
