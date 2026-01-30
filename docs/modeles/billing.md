# Módulo de Ventas y Facturación

App: `sales/`

## Modelos

### SaleOrder (Pedido de venta)

| Campo | Tipo | Descripción |
|-------|------|-------------|
| code | CharField(50) | Código único (SO-2026-0001) |
| client | FK → Partner | Cliente |
| status | CharField | PENDING / PROFORMA / CONFIRMED / INVOICED / DISPATCHED / CANCELED |
| delivery_date | Date | Fecha de entrega solicitada |
| payment_method | CharField | Método de pago |
| notes | Text | Observaciones |

### SaleOrderLine

| Campo | Tipo | Descripción |
|-------|------|-------------|
| order | FK → SaleOrder | Pedido padre |
| product | FK → Product | Producto solicitado |
| quantity | Decimal | Cantidad |
| unit_price | Decimal | Precio unitario |
| total_price | Decimal | Total (auto-calculado) |

### SaleDispatch (Despacho)

| Campo | Tipo | Descripción |
|-------|------|-------------|
| order | FK → SaleOrder | Pedido asociado |
| dispatched_date | DateTime | Fecha de despacho |
| total_amount | Decimal | Monto total despachado |
| status | CharField | Estado del despacho |
| lot | FK → Lot | Lote despachado |

### SaleInvoice (Factura)

| Campo | Tipo | Descripción |
|-------|------|-------------|
| order | FK → SaleOrder | Pedido asociado |
| invoice_code | CharField(50) | Número de factura |
| issue_date | DateTime | Fecha de emisión |
| total_amount | Decimal | Monto total |
| status | CharField | PENDING / AUTHORIZED / REJECTED |
| sri_status | CharField | Estado SRI (integración futura) |
| xml_data | Text | XML para facturación electrónica SRI |

## Flujo

```
Pedido (PENDING)
  → Confirmación (CONFIRMED)
  → Asignación de lotes FEFO
  → Despacho / Picking (DISPATCHED)
  → Factura electrónica (INVOICED)
  → Guía de remisión
```
