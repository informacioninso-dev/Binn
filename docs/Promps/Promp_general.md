============================================================
CONTEXTO PERMANENTE DEL PROYECTO DJANGO (MICRO-ERP)
============================================================

Quiero que actúes como arquitecto y desarrollador experto en Django + PostgreSQL para ayudarme a construir un micro-ERP modular orientado a manufactura y distribución, alineado con ISO 13485 y buenas prácticas de inventario, producción, calidad, compras y ventas.

Stack actual:
- Backend: Django
- Base de datos actual: sqlite3 (luego se migrará a PostgreSQL)
- Proyecto: config
- Apps instaladas: core, inventory, finance, sales, production, quality, procurement, partners
- Uso un modelo base de auditoría con campos `created_at`, `updated_at`, `created_by`, `updated_by`.

La idea general del sistema:
- **core**: catálogos base (unidades, bodegas, ubicaciones, impuestos).
- **inventory**: productos, stock, lotes, movimientos e inventario por lote/ubicación.
- **sales**: pedidos de venta, despachos, facturas (pensado para integrar SRI).
- **production**: BOMs, rutas, órdenes de producción, operaciones, planes de producción.
- **quality**: planes de calidad, parámetros de inspección, inspecciones sobre lotes/op.
- **procurement**: órdenes de compra, recepciones de materia prima, lotes de MP.
- **partners**: clientes y proveedores (una sola entidad Partner con flags).

A continuación te detallo los modelos principales y relaciones (esto es importante para que entiendas el dominio de datos y me ayudes a construir vistas, templates, servicios de dominio y lógica de negocio coherente):

============================================================
MODELOS Y CAMPOS
============================================================

────────────────────────────────────────────────────────────
APP: core
────────────────────────────────────────────────────────────

  Modelo: TaxScheme
  Tabla: core_taxscheme

  Campos:
    • products (ManyToOneRel) [null=True] -> Product
    • id (BigAutoField) [blank=True]
    • created_at (DateTimeField) [blank=True]
    • updated_at (DateTimeField) [blank=True]
    • created_by (ForeignKey) [null=True] [blank=True] -> User
    • updated_by (ForeignKey) [null=True] [blank=True] -> User
    • code (CharField) [max_length=20]
    • name (CharField) [max_length=100]
    • rate (DecimalField)
    • is_active (BooleanField)
    • applies_sales (BooleanField)
    • applies_purchases (BooleanField)

  Modelo: Unit
  Tabla: core_unit

  Campos:
    • products (ManyToOneRel) [null=True] -> Product
    • inventorymove (ManyToOneRel) [null=True] -> InventoryMove
    • purchase_lines (ManyToOneRel) [null=True] -> PurchaseOrderLine
    • rawmaterialreceptionline (ManyToOneRel) [null=True] -> RawMaterialReceptionLine
    • id (BigAutoField) [blank=True]
    • created_at (DateTimeField) [blank=True]
    • updated_at (DateTimeField) [blank=True]
    • created_by (ForeignKey) [null=True] [blank=True] -> User
    • updated_by (ForeignKey) [null=True] [blank=True] -> User
    • code (CharField) [max_length=10]
    • name (CharField) [max_length=50]
    • category (CharField) [max_length=10]
    • factor_to_base (DecimalField)
    • is_active (BooleanField)

  Modelo: Warehouse
  Tabla: core_warehouse

  Campos:
    • locations (ManyToOneRel) [null=True] -> Location
    • lots (ManyToOneRel) [null=True] -> Lot
    • lot_balances (ManyToOneRel) [null=True] -> LotBalance
    • moves (ManyToOneRel) [null=True] -> InventoryMove
    • moves_from_wh (ManyToOneRel) [null=True] -> InventoryMove
    • moves_to_wh (ManyToOneRel) [null=True] -> InventoryMove
    • work_centers (ManyToOneRel) [null=True] -> WorkCenter
    • id (BigAutoField) [blank=True]
    • created_at (DateTimeField) [blank=True]
    • updated_at (DateTimeField) [blank=True]
    • created_by (ForeignKey) [null=True] [blank=True] -> User
    • updated_by (ForeignKey) [null=True] [blank=True] -> User
    • code (CharField) [max_length=20]
    • name (CharField) [max_length=100]
    • type (CharField) [max_length=20]
    • is_active (BooleanField)
    • is_default_quarantine (BooleanField)
    • is_default_for_raw (BooleanField)
    • is_default_fg_released (BooleanField)

  Modelo: Location
  Tabla: core_location

  Campos:
    • lots (ManyToOneRel) [null=True] -> Lot
    • lot_balances (ManyToOneRel) [null=True] -> LotBalance
    • moves (ManyToOneRel) [null=True] -> InventoryMove
    • moves_from (ManyToOneRel) [null=True] -> InventoryMove
    • moves_to (ManyToOneRel) [null=True] -> InventoryMove
    • id (BigAutoField) [blank=True]
    • created_at (DateTimeField) [blank=True]
    • updated_at (DateTimeField) [blank=True]
    • created_by (ForeignKey) [null=True] [blank=True] -> User
    • updated_by (ForeignKey) [null=True] [blank=True] -> User
    • warehouse (ForeignKey) -> Warehouse
    • code (CharField) [max_length=30]
    • name (CharField) [max_length=100] [null=True] [blank=True]
    • description (CharField) [max_length=255] [null=True] [blank=True]
    • row (CharField) [max_length=10] [null=True] [blank=True]
    • rack (CharField) [max_length=10] [null=True] [blank=True]
    • level (CharField) [max_length=10] [null=True] [blank=True]
    • is_active (BooleanField)

────────────────────────────────────────────────────────────
APP: inventory
────────────────────────────────────────────────────────────

  Modelo: Product
  Tabla: inventory_product

  Campos:
    • stock (OneToOneRel) [null=True] -> Stock
    • lots (ManyToOneRel) [null=True] -> Lot
    • moves (ManyToOneRel) [null=True] -> InventoryMove
    • sale_order_lines (ManyToOneRel) [null=True] -> SaleOrderLine
    • routes (ManyToOneRel) [null=True] -> ProductRoute
    • boms (ManyToOneRel) [null=True] -> BillOfMaterial
    • bom_components (ManyToOneRel) [null=True] -> BillOfMaterialLine
    • production_orders (ManyToOneRel) [null=True] -> ProductionOrder
    • production_plans (ManyToOneRel) [null=True] -> ProductionPlan
    • as_component_in_plans (ManyToOneRel) [null=True] -> ProductionPlanRawLot
    • qa_plans (ManyToOneRel) [null=True] -> QAPlan
    • purchase_lines (ManyToOneRel) [null=True] -> PurchaseOrderLine
    • reception_lines (ManyToOneRel) [null=True] -> RawMaterialReceptionLine
    • id (BigAutoField) [blank=True]
    • created_at (DateTimeField) [blank=True]
    • updated_at (DateTimeField) [blank=True]
    • created_by (ForeignKey) [null=True] [blank=True] -> User
    • updated_by (ForeignKey) [null=True] [blank=True] -> User
    • product_type (CharField) [max_length=10]
    • code (CharField) [max_length=50]
    • code_2 (CharField) [max_length=50] [null=True] [blank=True]
    • name (CharField) [max_length=200]
    • base_unit (ForeignKey) -> Unit
    • unit_price (DecimalField)
    • unit_cost (DecimalField) [null=True] [blank=True]
    • tax_scheme (ForeignKey) [null=True] [blank=True] -> TaxScheme
    • provider (CharField) [max_length=200] [null=True] [blank=True]
    • category (CharField) [max_length=100] [null=True] [blank=True]
    • brand (CharField) [max_length=100] [null=True] [blank=True]
    • attribute1 (CharField) [max_length=100] [null=True] [blank=True]
    • attribute2 (CharField) [max_length=100] [null=True] [blank=True]
    • is_active (BooleanField)
    • lot_prefix (CharField) [max_length=20] [null=True] [blank=True]
    • use_date_in_lot (BooleanField)

  Modelo: Stock
  Tabla: inventory_stock

  Campos:
    • product (OneToOneField) -> Product
    • quantity (DecimalField)
    • id, created_at, updated_at, created_by, updated_by

  Modelo: Lot
  Tabla: inventory_lot

  Campos:
    • product (ForeignKey) -> Product
    • internal_lot (CharField) [max_length=50]
    • supplier_lot (CharField) [max_length=50] [null=True] [blank=True]
    • quantity_initial (DecimalField)
    • warehouse (ForeignKey) [null=True] [blank=True] -> Warehouse
    • location (ForeignKey) [null=True] [blank=True] -> Location
    • manufacturing_date (DateField) [null=True] [blank=True]
    • expiry_date (DateField) [null=True] [blank=True]
    • origin_reference (CharField) [max_length=100] [null=True] [blank=True]
    • status (CharField) [max_length=20]
    • id, created_at, updated_at, created_by, updated_by

  Modelo: LotBalance
  Tabla: inventory_lotbalance

  Campos:
    • lot (ForeignKey) -> Lot
    • warehouse (ForeignKey) -> Warehouse
    • location (ForeignKey) -> Location
    • qty (DecimalField)
    • id, created_at, updated_at, created_by, updated_by

  Modelo: InventoryMove
  Tabla: inventory_inventorymove

  Campos:
    • product (ForeignKey) -> Product
    • lot (ForeignKey) [null=True] [blank=True] -> Lot
    • movement_type (CharField) [max_length=3]
    • date (DateTimeField) [blank=True]
    • quantity (DecimalField)                 # en unidad base
    • unit_displayed (ForeignKey) [null=True] -> Unit
    • quantity_displayed (DecimalField) [null=True]
    • unit_cost (DecimalField) [null=True] [blank=True]
    • reference (CharField) [max_length=100] [null=True] [blank=True]
    • warehouse (ForeignKey) [null=True] [blank=True] -> Warehouse
    • location (ForeignKey) [null=True] [blank=True] -> Location
    • area (CharField) [max_length=100] [null=True] [blank=True]
    • notes (TextField) [null=True] [blank=True]
    • reason (CharField) [max_length=30] [null=True] [blank=True]
    • from_location, to_location (ForeignKey) [null=True] [blank=True] -> Location
    • from_warehouse, to_warehouse (ForeignKey) [null=True] [blank=True] -> Warehouse
    • id, created_at, updated_at, created_by, updated_by

────────────────────────────────────────────────────────────
APP: sales
────────────────────────────────────────────────────────────

  Modelo: SaleOrder
  Tabla: sales_saleorder

  Campos:
    • code (CharField) [max_length=50]
    • client (ForeignKey) -> Partner
    • status (CharField) [max_length=20]
    • delivery_date (DateField)
    • notes (TextField) [null=True] [blank=True]
    • payment_method (CharField) [max_length=50] [null=True] [blank=True]
    • id, created_at, updated_at, created_by, updated_by
    • Rel: lines, dispatches, invoices

  Modelo: SaleOrderLine
  Tabla: sales_saleorderline

  Campos:
    • order (ForeignKey) -> SaleOrder
    • product (ForeignKey) -> Product
    • quantity (DecimalField)
    • unit_price (DecimalField)
    • total_price (DecimalField)
    • id, created_at, updated_at, created_by, updated_by

  Modelo: SaleDispatch
  Tabla: sales_saledispatch

  Campos:
    • order (ForeignKey) -> SaleOrder
    • dispatched_date (DateTimeField) [blank=True]
    • total_amount (DecimalField)
    • status (CharField) [max_length=20]
    • lot (ForeignKey) -> Lot
    • id, created_at, updated_at, created_by, updated_by

  Modelo: SaleInvoice
  Tabla: sales_saleinvoice

  Campos:
    • order (ForeignKey) -> SaleOrder
    • invoice_code (CharField) [max_length=50]
    • issue_date (DateTimeField) [blank=True]
    • total_amount (DecimalField)
    • status (CharField) [max_length=20]
    • sri_status (CharField) [max_length=20]
    • xml_data (TextField)    # XML para SRI
    • id, created_at, updated_at, created_by, updated_by

────────────────────────────────────────────────────────────
APP: production
────────────────────────────────────────────────────────────

  Modelo: ProductRoute
  Tabla: production_productroute
    • product (ForeignKey) -> Product
    • name (CharField) [max_length=100]
    • is_active (BooleanField)
    • notes (TextField) [null=True] [blank=True]
    • id, created_at, updated_at, created_by, updated_by
    • Rel: steps, production_orders

  Modelo: BillOfMaterial
  Tabla: production_billofmaterial
    • product_finished (ForeignKey) -> Product
    • revision (CharField) [max_length=10]
    • description (TextField) [null=True] [blank=True]
    • is_active (BooleanField)
    • id, created_at, updated_at, created_by, updated_by
    • Rel: lines, production_orders

  Modelo: BillOfMaterialLine
  Tabla: production_billofmaterialline
    • bom (ForeignKey) -> BillOfMaterial
    • component (ForeignKey) -> Product
    • quantity (DecimalField)
    • scrap_rate (DecimalField)
    • sequence (PositiveIntegerField)
    • id, created_at, updated_at, created_by, updated_by

  Modelo: ProductionOrder
  Tabla: production_productionorder
    • code (CharField) [max_length=50]
    • product (ForeignKey) -> Product
    • quantity_planned (DecimalField)
    • quantity_produced (DecimalField)
    • route (ForeignKey) [null=True] [blank=True] -> ProductRoute
    • bom (ForeignKey) [null=True] [blank=True] -> BillOfMaterial
    • finished_lot (ForeignKey) [null=True] [blank=True] -> Lot
    • start_date, end_date (DateField) [null=True] [blank=True]
    • status (CharField) [max_length=20]
    • origin_type (CharField) [max_length=20]
    • origin_reference (CharField) [max_length=100] [null=True] [blank=True]
    • plan (ForeignKey) [null=True] [blank=True] -> ProductionPlan
    • notes (TextField) [null=True] [blank=True]
    • id, created_at, updated_at, created_by, updated_by
    • Rel: operations

  Modelo: WorkCenter
  Tabla: production_workcenter
    • code (CharField) [max_length=30]
    • name (CharField) [max_length=100]
    • description (CharField) [max_length=255] [null=True] [blank=True]
    • default_warehouse (ForeignKey) [null=True] [blank=True] -> Warehouse
    • capacity_per_hour (DecimalField) [null=True] [blank=True]
    • num_machines (PositiveIntegerField) [default=1]
    • num_operators (PositiveIntegerField) [default=1]
    • efficiency_factor (DecimalField) [default=1.0]
    • setup_time_min (PositiveIntegerField) [default=0]
    • hours_per_shift (DecimalField) [default=8.0]
    • shifts_per_day (PositiveIntegerField) [default=1]
    • is_active (BooleanField)
    • id, created_at, updated_at, created_by, updated_by
    • Property: available_minutes_per_day = hours_per_shift × shifts_per_day × num_machines × efficiency_factor × 60

  Modelo: ProductRouteStep
  Tabla: production_productroutestep
    • route (ForeignKey) -> ProductRoute
    • sequence (PositiveIntegerField)
    • work_center (ForeignKey) -> WorkCenter
    • name (CharField) [max_length=100]
    • description (CharField) [max_length=255] [null=True] [blank=True]
    • expected_duration_min (PositiveIntegerField) [null=True] [blank=True] — minutos por unidad de producto
    • setup_time_min (PositiveIntegerField) [default=0] — setup específico del paso
    • requires_qa (BooleanField)
    • is_active (BooleanField)
    • id, created_at, updated_at, created_by, updated_by

  Modelo: ProductionOperation
  Tabla: production_productionoperation
    • order (ForeignKey) -> ProductionOrder
    • step (ForeignKey) -> ProductRouteStep
    • sequence (PositiveIntegerField)
    • input_lot, output_lot (ForeignKey) [null=True] [blank=True] -> Lot
    • quantity_input, quantity_output (DecimalField) [null=True] [blank=True]
    • planned_start, planned_end (DateTimeField) [null=True] [blank=True] — fechas planificadas (calculadas al liberar)
    • started_at, finished_at (DateTimeField) [null=True] [blank=True] — fechas reales
    • status (CharField) [max_length=20] — PENDING / IN_PROGRESS / PAUSED / HOLD / DONE / REJECTED
    • operator (ForeignKey) [null=True] [blank=True] -> User
    • materials_consumed (BooleanField) [default=False]
    • notes (TextField) [null=True] [blank=True]
    • id, created_at, updated_at, created_by, updated_by

  Modelo: OperationStatusLog
  Tabla: production_operationstatuslog
    • operation (ForeignKey) -> ProductionOperation
    • from_status (CharField) [max_length=20] [null=True]
    • to_status (CharField) [max_length=20]
    • changed_at (DateTimeField) [auto_now_add=True]
    • changed_by (ForeignKey) [null=True] -> User
    • notes (TextField) [null=True]

  Modelo: MaterialTransfer
  Tabla: production_materialtransfer
    • order (ForeignKey) -> ProductionOrder
    • component (ForeignKey) -> Product
    • lot (ForeignKey) -> Lot
    • quantity_requested (DecimalField)
    • quantity_confirmed (DecimalField) [null=True]
    • from_warehouse (ForeignKey) -> Warehouse
    • to_warehouse (ForeignKey) -> Warehouse
    • status (CharField) [max_length=20] — PENDING / CONFIRMED / ADJUSTED
    • confirmed_by (ForeignKey) [null=True] -> User
    • confirmed_at (DateTimeField) [null=True]
    • deviation_notes (TextField) [null=True]
    • inventory_move (ForeignKey) [null=True] -> InventoryMove
    • id, created_at, updated_at, created_by, updated_by
    • Unique: (order, lot)

  Modelo: ProductionPlan
  Tabla: production_productionplan
    • code (CharField) [max_length=30]
    • product (ForeignKey) -> Product
    • lot_code (CharField) [max_length=50]
    • manufacturing_date (DateField)
    • quantity_planned (DecimalField)
    • status (CharField) [max_length=20]
    • notes (TextField) [null=True] [blank=True]
    • id, created_at, updated_at, created_by, updated_by
    • Rel: orders, raw_lots

  Modelo: ProductionPlanRawLot
  Tabla: production_productionplanrawlot
    • plan (ForeignKey) -> ProductionPlan
    • lot (ForeignKey) -> Lot
    • quantity_planned (DecimalField) [null=True] [blank=True]
    • component (ForeignKey) -> Product
    • id (BigAutoField)

────────────────────────────────────────────────────────────
APP: quality
────────────────────────────────────────────────────────────

  Modelo: QAPlan
  Tabla: quality_qaplan
    • name (CharField) [max_length=100]
    • product (ForeignKey) [null=True] [blank=True] -> Product
    • stage (CharField) [max_length=10]
    • work_center (ForeignKey) [null=True] [blank=True] -> WorkCenter
    • route_step (ForeignKey) [null=True] [blank=True] -> ProductRouteStep
    • is_active (BooleanField)
    • id, created_at, updated_at, created_by, updated_by
    • Rel: parameters, inspections

  Modelo: QAParameterTemplate
  Tabla: quality_qaparametertemplate
    • plan (ForeignKey) -> QAPlan
    • code (CharField) [max_length=50]
    • label (CharField) [max_length=100]
    • unit (CharField) [max_length=20] [null=True] [blank=True]
    • data_type (CharField) [max_length=10]
    • min_value (DecimalField) [null=True] [blank=True]
    • max_value (DecimalField) [null=True] [blank=True]
    • is_required (BooleanField)
    • order (PositiveIntegerField)
    • id, created_at, updated_at, created_by, updated_by

  Modelo: QualityInspection
  Tabla: quality_qualityinspection
    • lot (ForeignKey) -> Lot
    • stage (CharField) [max_length=10]
    • operation (ForeignKey) [null=True] [blank=True] -> ProductionOperation
    • plan (ForeignKey) [null=True] [blank=True] -> QAPlan
    • inspected_at (DateTimeField) [null=True] [blank=True]
    • inspected_by (ForeignKey) [null=True] [blank=True] -> User
    • checklist (JSONField) [null=True] [blank=True]
    • result (CharField) [max_length=20] [null=True] [blank=True]
    • notes (TextField) [null=True] [blank=True]
    • id, created_at, updated_at, created_by, updated_by

────────────────────────────────────────────────────────────
APP: procurement
────────────────────────────────────────────────────────────

  Modelo: PurchaseOrder
  Tabla: procurement_purchaseorder
    • number (CharField) [max_length=20]
    • supplier (ForeignKey) -> Partner
    • order_date (DateField)
    • status (CharField) [max_length=20]
    • currency (CharField) [max_length=5]
    • total_amount (DecimalField)
    • id, created_at, updated_at, created_by, updated_by
    • Rel: lines, receptions

  Modelo: PurchaseOrderLine
  Tabla: procurement_purchaseorderline
    • order (ForeignKey) -> PurchaseOrder
    • product (ForeignKey) -> Product
    • description (CharField) [max_length=255] [blank=True]
    • quantity (DecimalField)
    • unit_price (DecimalField)
    • unit (ForeignKey) -> Unit
    • line_total (DecimalField)
    • id (BigAutoField)

  Modelo: RawMaterialReception
  Tabla: procurement_rawmaterialreception
    • purchase_order (ForeignKey) [null=True] [blank=True] -> PurchaseOrder
    • code (CharField) [max_length=50]
    • supplier_name (CharField) [max_length=200]
    • supplier_ruc (CharField) [max_length=20] [null=True] [blank=True]
    • document_type (CharField) [max_length=50] [null=True] [blank=True]
    • document_number (CharField) [max_length=50] [null=True] [blank=True]
    • reception_date (DateField)
    • arrival_time (TimeField) [null=True] [blank=True]
    • transport_company (CharField) [max_length=200] [null=True] [blank=True]
    • transport_plate (CharField) [max_length=20] [null=True] [blank=True]
    • temperature_recorded (DecimalField) [null=True] [blank=True]
    • num_boxes (PositiveIntegerField) [null=True] [blank=True]
    • gross_weight (DecimalField) [null=True] [blank=True]
    • net_weight (DecimalField) [null=True] [blank=True]
    • status (CharField) [max_length=20]
    • observations (TextField) [null=True] [blank=True]
    • id, created_at, updated_at, created_by, updated_by
    • Rel: lines

  Modelo: RawMaterialReceptionLine
  Tabla: procurement_rawmaterialreceptionline
    • reception (ForeignKey) -> RawMaterialReception
    • product (ForeignKey) -> Product
    • expected_quantity (DecimalField) [null=True] [blank=True]
    • received_quantity (DecimalField)
    • unit_cost (DecimalField) [null=True] [blank=True]
    • unit (ForeignKey) -> Unit
    • supplier_lot (CharField) [max_length=50] [null=True] [blank=True]
    • internal_lot (CharField) [max_length=50] [null=True] [blank=True]
    • expiry_date (DateField) [null=True] [blank=True]
    • storage_area (CharField) [max_length=100] [null=True] [blank=True]
    • notes (TextField) [null=True] [blank=True]
    • id (BigAutoField)

────────────────────────────────────────────────────────────
APP: partners
────────────────────────────────────────────────────────────

  Modelo: Partner
  Tabla: partners_partner

  Campos:
    • code (CharField) [max_length=20]
    • alt_code (CharField) [max_length=20] [null=True] [blank=True]
    • identification_type (CharField) [max_length=20]
    • identification (CharField) [max_length=20]
    • trade_name (CharField) [max_length=150] [blank=True]
    • legal_name (CharField) [max_length=200]
    • category (CharField) [max_length=10] [blank=True]
    • company_type (CharField) [max_length=20]
    • is_customer (BooleanField)
    • is_supplier (BooleanField)
    • is_public_entity (BooleanField)
    • credit_limit (DecimalField)
    • credit_available (DecimalField)
    • credit_used (DecimalField)
    • credit_terms_days (PositiveIntegerField)
    • retention_profile (CharField) [max_length=20]
    • branch_name (CharField) [max_length=100] [blank=True]
    • address (CharField) [max_length=255] [blank=True]
    • city (CharField) [max_length=100] [blank=True]
    • province (CharField) [max_length=100] [blank=True]
    • country (CharField) [max_length=100] [blank=True]
    • contact_name (CharField) [max_length=150] [blank=True]
    • contact_email (EmailField) [max_length=254] [blank=True]
    • contact_phone (CharField) [max_length=50] [blank=True]
    • website (URLField) [max_length=200] [blank=True]
    • is_qualified_supplier (BooleanField)
    • qualification_level (CharField) [max_length=50] [blank=True]
    • qualification_date (DateField) [null=True] [blank=True]
    • qualification_notes (TextField) [blank=True]
    • notes (TextField) [blank=True]
    • is_active (BooleanField)
    • id, created_at, updated_at, created_by, updated_by
    • Rel: sale_orders, purchase_orders

============================================================
LO QUE ESPERO DE TI
============================================================

Con toda esta estructura como contexto fijo, ayúdame a:

- Diseñar y optimizar vistas (FBV/CBV), templates (con Tailwind), URLs y formularios para cada módulo.
- Implementar servicios de dominio para:
  - Movimientos de inventario (entradas, salidas, transferencias, ajustes) con control por lote y ubicación.
  - Flujo de recepción de MP → lotes → QA → liberación/cuarentena.
  - Flujo de producción: plan de producción → órdenes → operaciones → consumo de BOM → generación de lote terminado.
  - Flujo comercial: pedido → despacho → factura → integración futura con SRI.
  - Gestión de calidad: planes QA por producto/etapa, checklist dinámico, registro de inspecciones.
- Mantener siempre la integridad de datos (no romper consistencia de lotes, stock y balances por ubicación).
- Sugerirme buenas prácticas de arquitectura Django (servicios, signals, validaciones, permisos, etc.).

A partir de ahora, cuando te pida algo, asume TODO este contexto como base del proyecto y respóndeme directamente con código, explicaciones y pasos claros según lo que solicite en cada mensaje.

Ahora mi siguiente petición es:
[ESCRIBIR AQUÍ LO QUE QUIERO HACER: por ejemplo "crear las vistas y templates para CRUD de Warehouse" o "diseñar el flujo de recepción de materia prima con creación de lotes e InventoryMove"].
