# sales/models.py
from django.db import models
from django.utils import timezone
from core.models import AuditModel
from partners.models import Partner
from inventory.models import Product, Lot


class SaleOrderStatus(models.TextChoices):
    PENDING = "PENDING", "Pendiente"
    PROFORMA = "PROFORMA", "Proforma"
    CONFIRMED = "CONFIRMED", "Confirmado"
    PICKING = "PICKING", "En picking"
    PACKING = "PACKING", "En packing"
    DISPATCHED = "DISPATCHED", "Despachado"
    INVOICED = "INVOICED", "Facturado"
    CANCELED = "CANCELED", "Cancelado"


class SaleOrder(AuditModel):
    code = models.CharField(
        "Código", max_length=50, unique=True,
        help_text="Código interno del pedido (ej. SO-2026-0001)",
    )
    client = models.ForeignKey(
        Partner, on_delete=models.PROTECT,
        related_name="sale_orders",
        verbose_name="Cliente",
        help_text="Cliente que realiza el pedido.",
    )
    status = models.CharField(
        "Estado", max_length=20,
        choices=SaleOrderStatus.choices,
        default=SaleOrderStatus.PENDING,
    )
    created_at = models.DateTimeField("Fecha de creación", auto_now_add=True)
    updated_at = models.DateTimeField("Fecha de actualización", auto_now=True)
    delivery_date = models.DateField("Fecha de entrega", help_text="Fecha de entrega del pedido.")
    # Dirección de entrega (snapshot del cliente o personalizada)
    delivery_address = models.CharField("Dirección de entrega", max_length=300, blank=True)
    delivery_city = models.CharField("Ciudad de entrega", max_length=100, blank=True)
    delivery_phone = models.CharField("Teléfono de contacto", max_length=50, blank=True)
    notes = models.TextField("Notas", blank=True, null=True)
    payment_method = models.CharField("Método de pago", max_length=50, blank=True, null=True)

    class Meta:
        verbose_name = "Pedido de venta"
        verbose_name_plural = "Pedidos de venta"
        ordering = ["-created_at"]

    def _generate_code(self):
        year = timezone.now().year
        last = (
            SaleOrder.objects
            .filter(code__startswith=f"SO-{year}-")
            .order_by("-code")
            .values_list("code", flat=True)
            .first()
        )
        seq = int(last.split("-")[-1]) + 1 if last else 1
        return f"SO-{year}-{seq:04d}"

    def save(self, *args, **kwargs):
        if not self.code:
            self.code = self._generate_code()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"Pedido {self.code} – {self.client.trade_name}"

    def get_total(self):
        return sum(line.total_price for line in self.lines.all())

    @property
    def can_start_picking(self):
        return self.status == SaleOrderStatus.CONFIRMED

    @property
    def can_be_dispatched(self):
        return self.status == SaleOrderStatus.CONFIRMED


class SaleOrderLine(AuditModel):
    order = models.ForeignKey(SaleOrder, on_delete=models.CASCADE, related_name="lines", verbose_name="Pedido")
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name="sale_order_lines", verbose_name="Producto")
    quantity = models.DecimalField("Cantidad", max_digits=12, decimal_places=2)
    unit_price = models.DecimalField("Precio unitario", max_digits=12, decimal_places=2)
    total_price = models.DecimalField("Precio total", max_digits=12, decimal_places=2)

    def save(self, *args, **kwargs):
        self.total_price = self.quantity * self.unit_price
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.product.name} - {self.quantity} unidades"


# ─── Despacho ───────────────────────────────────────────────

class SaleDispatch(AuditModel):
    order = models.ForeignKey(SaleOrder, on_delete=models.PROTECT, related_name="dispatches", verbose_name="Pedido")
    code = models.CharField("Código", max_length=50, unique=True, blank=True, help_text="DS-2026-0001")
    dispatched_date = models.DateTimeField("Fecha de despacho", auto_now_add=True)
    notes = models.TextField("Notas", blank=True)

    class Meta:
        verbose_name = "Despacho de venta"
        verbose_name_plural = "Despachos de venta"
        ordering = ["-dispatched_date"]

    def __str__(self):
        return f"Despacho {self.code} – {self.order.code}"

    def _generate_code(self):
        year = timezone.now().year
        last = (
            SaleDispatch.objects
            .filter(code__startswith=f"DS-{year}-")
            .order_by("-code")
            .values_list("code", flat=True)
            .first()
        )
        if last:
            seq = int(last.split("-")[-1]) + 1
        else:
            seq = 1
        return f"DS-{year}-{seq:04d}"

    def save(self, *args, **kwargs):
        if not self.code:
            self.code = self._generate_code()
        super().save(*args, **kwargs)


class SaleDispatchLine(AuditModel):
    dispatch = models.ForeignKey(SaleDispatch, on_delete=models.CASCADE, related_name="lines", verbose_name="Despacho")
    order_line = models.ForeignKey(SaleOrderLine, on_delete=models.PROTECT, related_name="dispatch_lines", verbose_name="Línea de pedido")
    product = models.ForeignKey(Product, on_delete=models.PROTECT, verbose_name="Producto")
    lot = models.ForeignKey(Lot, on_delete=models.PROTECT, related_name="sale_dispatch_lines", verbose_name="Lote")
    quantity = models.DecimalField("Cantidad", max_digits=12, decimal_places=4)

    def __str__(self):
        return f"{self.product.name} x {self.quantity} (Lote {self.lot.internal_lot})"


# ─── Picking ───────────────────────────────────────────────

class PickingOrderStatus(models.TextChoices):
    PENDING = "PENDING", "Pendiente"
    IN_PROGRESS = "IN_PROGRESS", "En proceso"
    COMPLETED = "COMPLETED", "Completado"
    CANCELED = "CANCELED", "Cancelado"


class PickingOrder(AuditModel):
    order = models.ForeignKey(SaleOrder, on_delete=models.PROTECT, related_name="pickings", verbose_name="Pedido")
    code = models.CharField("Código", max_length=50, unique=True, blank=True, help_text="PK-2026-0001")
    status = models.CharField("Estado", max_length=20, choices=PickingOrderStatus.choices, default=PickingOrderStatus.PENDING)
    assigned_to = models.ForeignKey(
        "auth.User", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="assigned_pickings", verbose_name="Asignado a",
    )
    notes = models.TextField("Notas", blank=True)

    class Meta:
        verbose_name = "Orden de picking"
        verbose_name_plural = "Órdenes de picking"
        ordering = ["-created_at"]

    def __str__(self):
        return f"Picking {self.code} – {self.order.code}"

    def _generate_code(self):
        year = timezone.now().year
        last = (
            PickingOrder.objects
            .filter(code__startswith=f"PK-{year}-")
            .order_by("-code")
            .values_list("code", flat=True)
            .first()
        )
        seq = int(last.split("-")[-1]) + 1 if last else 1
        return f"PK-{year}-{seq:04d}"

    def save(self, *args, **kwargs):
        if not self.code:
            self.code = self._generate_code()
        super().save(*args, **kwargs)


class PickingLine(AuditModel):
    picking = models.ForeignKey(PickingOrder, on_delete=models.CASCADE, related_name="lines", verbose_name="Picking")
    order_line = models.ForeignKey(SaleOrderLine, on_delete=models.PROTECT, related_name="picking_lines", verbose_name="Línea de pedido")
    product = models.ForeignKey(Product, on_delete=models.PROTECT, verbose_name="Producto")
    lot = models.ForeignKey(Lot, on_delete=models.PROTECT, verbose_name="Lote")
    location = models.CharField("Ubicación", max_length=200, blank=True)
    quantity_requested = models.DecimalField("Cantidad solicitada", max_digits=12, decimal_places=4)
    quantity_picked = models.DecimalField("Cantidad recogida", max_digits=12, decimal_places=4, default=0)
    picked = models.BooleanField("Recogido", default=False)

    class Meta:
        verbose_name = "Línea de picking"
        verbose_name_plural = "Líneas de picking"

    def __str__(self):
        return f"{self.product.name} x {self.quantity_requested} (Lote {self.lot.internal_lot})"


# ─── Packing ──────────────────────────────────────────────

class PackingOrderStatus(models.TextChoices):
    PENDING = "PENDING", "Pendiente"
    IN_PROGRESS = "IN_PROGRESS", "En proceso"
    COMPLETED = "COMPLETED", "Completado"
    CANCELED = "CANCELED", "Cancelado"


class PackingOrder(AuditModel):
    order = models.ForeignKey(SaleOrder, on_delete=models.PROTECT, related_name="packings", verbose_name="Pedido")
    picking = models.OneToOneField(PickingOrder, on_delete=models.PROTECT, related_name="packing", verbose_name="Picking")
    code = models.CharField("Código", max_length=50, unique=True, blank=True, help_text="PA-2026-0001")
    status = models.CharField("Estado", max_length=20, choices=PackingOrderStatus.choices, default=PackingOrderStatus.PENDING)
    num_boxes = models.PositiveIntegerField("Número de cajas", default=0)
    gross_weight = models.DecimalField("Peso bruto (kg)", max_digits=12, decimal_places=4, default=0)
    net_weight = models.DecimalField("Peso neto (kg)", max_digits=12, decimal_places=4, default=0)
    notes = models.TextField("Notas", blank=True)

    class Meta:
        verbose_name = "Orden de packing"
        verbose_name_plural = "Órdenes de packing"
        ordering = ["-created_at"]

    def __str__(self):
        return f"Packing {self.code} – {self.order.code}"

    def _generate_code(self):
        year = timezone.now().year
        last = (
            PackingOrder.objects
            .filter(code__startswith=f"PA-{year}-")
            .order_by("-code")
            .values_list("code", flat=True)
            .first()
        )
        seq = int(last.split("-")[-1]) + 1 if last else 1
        return f"PA-{year}-{seq:04d}"

    def save(self, *args, **kwargs):
        if not self.code:
            self.code = self._generate_code()
        super().save(*args, **kwargs)


class PackingLine(AuditModel):
    packing = models.ForeignKey(PackingOrder, on_delete=models.CASCADE, related_name="lines", verbose_name="Packing")
    product = models.ForeignKey(Product, on_delete=models.PROTECT, verbose_name="Producto")
    lot = models.ForeignKey(Lot, on_delete=models.PROTECT, verbose_name="Lote")
    quantity = models.DecimalField("Cantidad", max_digits=12, decimal_places=4)
    box_number = models.PositiveIntegerField("N° de caja", default=1)

    class Meta:
        verbose_name = "Línea de packing"
        verbose_name_plural = "Líneas de packing"

    def __str__(self):
        return f"{self.product.name} x {self.quantity} - Caja {self.box_number}"


# ─── Factura ────────────────────────────────────────────────

class InvoiceStatus(models.TextChoices):
    DRAFT = "DRAFT", "Borrador"
    SIGNED = "SIGNED", "Firmado"
    SENT = "SENT", "Enviado al SRI"
    AUTHORIZED = "AUTHORIZED", "Autorizado"
    REJECTED = "REJECTED", "Rechazado"
    VOIDED = "VOIDED", "Anulado"


class SaleInvoice(AuditModel):
    order = models.ForeignKey(SaleOrder, on_delete=models.PROTECT, related_name="invoices", verbose_name="Pedido")
    dispatch = models.ForeignKey(SaleDispatch, on_delete=models.SET_NULL, null=True, blank=True, related_name="invoices", verbose_name="Despacho")

    # Numeración SRI: 001-001-000000001
    establishment = models.CharField("Establecimiento", max_length=3, default="001")
    emission_point = models.CharField("Punto de emisión", max_length=3, default="001")
    sequential = models.CharField("Secuencial", max_length=9, default="000000000")

    # Clave de acceso (49 dígitos)
    access_key = models.CharField("Clave de acceso", max_length=49, unique=True, default="")

    # Snapshot del comprador al momento de facturar
    buyer_identification_type = models.CharField("Tipo ID comprador", max_length=2, default="04")
    buyer_identification = models.CharField("Identificación comprador", max_length=20, default="")
    buyer_legal_name = models.CharField("Razón social comprador", max_length=300, default="")
    buyer_address = models.CharField("Dirección comprador", max_length=300, blank=True)
    buyer_email = models.EmailField("Email comprador", blank=True)

    # Montos
    subtotal_no_tax = models.DecimalField("Subtotal 0%", max_digits=12, decimal_places=2, default=0)
    subtotal_iva = models.DecimalField("Subtotal IVA", max_digits=12, decimal_places=2, default=0)
    iva_amount = models.DecimalField("IVA", max_digits=12, decimal_places=2, default=0)
    total_discount = models.DecimalField("Total descuento", max_digits=12, decimal_places=2, default=0)
    total_amount = models.DecimalField("Total", max_digits=12, decimal_places=2, default=0)

    # SRI
    status = models.CharField("Estado", max_length=20, choices=InvoiceStatus.choices, default=InvoiceStatus.DRAFT)
    authorization_number = models.CharField("Nº autorización", max_length=49, blank=True)
    authorization_date = models.DateTimeField("Fecha autorización", null=True, blank=True)
    xml_unsigned = models.TextField("XML sin firmar", blank=True)
    xml_signed = models.TextField("XML firmado", blank=True)
    sri_response = models.TextField("Respuesta SRI", blank=True)
    issue_date = models.DateTimeField("Fecha de emisión", auto_now_add=True)

    class Meta:
        verbose_name = "Factura"
        verbose_name_plural = "Facturas"
        ordering = ["-issue_date"]
        unique_together = [("establishment", "emission_point", "sequential")]

    def __str__(self):
        return f"FAC {self.establishment}-{self.emission_point}-{self.sequential}"

    @property
    def full_number(self):
        return f"{self.establishment}-{self.emission_point}-{self.sequential}"


class SaleInvoiceLine(AuditModel):
    invoice = models.ForeignKey(SaleInvoice, on_delete=models.CASCADE, related_name="lines", verbose_name="Factura")
    product = models.ForeignKey(Product, on_delete=models.PROTECT, verbose_name="Producto")
    description = models.CharField("Descripción", max_length=300)
    quantity = models.DecimalField("Cantidad", max_digits=12, decimal_places=2)
    unit_price = models.DecimalField("Precio unitario", max_digits=12, decimal_places=4)
    discount = models.DecimalField("Descuento", max_digits=12, decimal_places=2, default=0)
    subtotal = models.DecimalField("Subtotal", max_digits=12, decimal_places=2)
    # Códigos SRI de impuesto
    tax_code = models.CharField("Código impuesto", max_length=2, default="2", help_text="2=IVA")
    tax_rate_code = models.CharField("Código tarifa", max_length=4, default="2", help_text="0=0%, 2=12%, 3=14%, 4=15%")
    tax_rate = models.DecimalField("Tarifa %", max_digits=5, decimal_places=2)
    tax_amount = models.DecimalField("Valor impuesto", max_digits=12, decimal_places=2)

    class Meta:
        verbose_name = "Línea de factura"
        verbose_name_plural = "Líneas de factura"

    def __str__(self):
        return f"{self.description} x {self.quantity}"


# ─── Guía de Remisión ───────────────────────────────────────

class GuiaRemisionStatus(models.TextChoices):
    DRAFT = "DRAFT", "Borrador"
    SIGNED = "SIGNED", "Firmado"
    SENT = "SENT", "Enviado al SRI"
    AUTHORIZED = "AUTHORIZED", "Autorizado"
    REJECTED = "REJECTED", "Rechazado"
    VOIDED = "VOIDED", "Anulado"


class GuiaRemision(AuditModel):
    dispatch = models.ForeignKey(
        SaleDispatch, on_delete=models.PROTECT,
        related_name="guias_remision", verbose_name="Despacho",
    )
    order = models.ForeignKey(
        SaleOrder, on_delete=models.PROTECT,
        related_name="guias_remision", verbose_name="Pedido",
    )

    # Numeración SRI
    establishment = models.CharField("Establecimiento", max_length=3, default="001")
    emission_point = models.CharField("Punto de emisión", max_length=3, default="001")
    sequential = models.CharField("Secuencial", max_length=9, default="000000000")
    access_key = models.CharField("Clave de acceso", max_length=49, unique=True, default="")

    # Transportista (snapshot)
    carrier = models.ForeignKey(
        Partner, on_delete=models.PROTECT,
        related_name="guias_as_carrier", verbose_name="Transportista",
        limit_choices_to={"is_carrier": True},
    )
    carrier_legal_name = models.CharField("Razón social transportista", max_length=300)
    carrier_identification_type = models.CharField("Tipo ID transportista", max_length=2, default="04")
    carrier_identification = models.CharField("RUC/Cédula transportista", max_length=20)
    vehicle_plate = models.CharField("Placa", max_length=20)
    driver_name = models.CharField("Conductor", max_length=200, blank=True)
    driver_identification = models.CharField("Cédula conductor", max_length=20, blank=True)

    # Fechas de transporte
    transport_start_date = models.DateField("Fecha inicio transporte")
    transport_end_date = models.DateField("Fecha fin transporte")

    # Destinatario (snapshot)
    recipient_identification_type = models.CharField("Tipo ID destinatario", max_length=2, default="04")
    recipient_identification = models.CharField("Identificación destinatario", max_length=20)
    recipient_legal_name = models.CharField("Razón social destinatario", max_length=300)
    recipient_address = models.CharField("Dirección destinatario", max_length=300)

    # Partida y traslado
    origin_address = models.CharField("Dirección de partida", max_length=300)
    transfer_reason = models.CharField("Motivo traslado", max_length=300, default="Venta")
    route = models.CharField("Ruta", max_length=300, blank=True)

    # Documento de sustento
    supporting_doc_type = models.CharField("Tipo doc sustento", max_length=2, default="01")
    supporting_doc_number = models.CharField("Nº doc sustento", max_length=17, blank=True)
    supporting_doc_authorization = models.CharField("Autorización doc sustento", max_length=49, blank=True)
    supporting_doc_date = models.DateField("Fecha emisión doc sustento", null=True, blank=True)

    # SRI
    status = models.CharField("Estado", max_length=20, choices=GuiaRemisionStatus.choices, default=GuiaRemisionStatus.DRAFT)
    authorization_number = models.CharField("Nº autorización", max_length=49, blank=True)
    authorization_date = models.DateTimeField("Fecha autorización", null=True, blank=True)
    xml_unsigned = models.TextField("XML sin firmar", blank=True)
    xml_signed = models.TextField("XML firmado", blank=True)
    sri_response = models.TextField("Respuesta SRI", blank=True)
    issue_date = models.DateTimeField("Fecha de emisión", auto_now_add=True)

    notes = models.TextField("Notas", blank=True)

    class Meta:
        verbose_name = "Guía de remisión"
        verbose_name_plural = "Guías de remisión"
        ordering = ["-issue_date"]
        unique_together = [("establishment", "emission_point", "sequential")]

    def __str__(self):
        return f"GR {self.establishment}-{self.emission_point}-{self.sequential}"

    @property
    def full_number(self):
        return f"{self.establishment}-{self.emission_point}-{self.sequential}"


class GuiaRemisionLine(AuditModel):
    guia = models.ForeignKey(
        GuiaRemision, on_delete=models.CASCADE,
        related_name="lines", verbose_name="Guía de remisión",
    )
    product = models.ForeignKey(Product, on_delete=models.PROTECT, verbose_name="Producto")
    description = models.CharField("Descripción", max_length=300)
    quantity = models.DecimalField("Cantidad", max_digits=12, decimal_places=2)

    class Meta:
        verbose_name = "Línea de guía de remisión"
        verbose_name_plural = "Líneas de guía de remisión"

    def __str__(self):
        return f"{self.description} x {self.quantity}"


# ─── Devoluciones ──────────────────────────────────────────

class ReturnReasonType(models.TextChoices):
    COMMERCIAL = "COMMERCIAL", "Comercial"
    NON_CONFORMITY = "NON_CONFORMITY", "No Conformidad del Producto"


class ReturnReason(AuditModel):
    """Motivos de devolución configurables desde el sistema."""
    code = models.CharField("Código", max_length=20, unique=True)
    name = models.CharField("Nombre", max_length=200)
    reason_type = models.CharField(
        "Tipo", max_length=20,
        choices=ReturnReasonType.choices,
        default=ReturnReasonType.COMMERCIAL,
    )
    description = models.TextField("Descripción", blank=True)
    is_active = models.BooleanField("Activo", default=True)

    class Meta:
        verbose_name = "Motivo de devolución"
        verbose_name_plural = "Motivos de devolución"
        ordering = ["reason_type", "name"]

    def __str__(self):
        return f"{self.name} ({self.get_reason_type_display()})"


class SaleReturnStatus(models.TextChoices):
    GENERATED = "GENERATED", "Generada"
    RECEIVED = "RECEIVED", "Producto Recibido"
    PENDING_INSPECTION = "PENDING_INSPECTION", "Por Inspeccionar"
    APPROVED = "APPROVED", "Aprobada (ingresó a stock)"
    REJECTED = "REJECTED", "Rechazada (producto dado de baja)"
    CANCELED = "CANCELED", "Cancelada"


class SaleReturn(AuditModel):
    code = models.CharField("Código", max_length=50, unique=True, blank=True)

    # Cliente y factura origen
    client = models.ForeignKey(
        Partner, on_delete=models.PROTECT,
        related_name="sale_returns", verbose_name="Cliente",
    )
    invoice = models.ForeignKey(
        "SaleInvoice", on_delete=models.PROTECT,
        related_name="returns", verbose_name="Factura",
        null=True, blank=True,
    )

    # Snapshot del cliente al momento de la devolución
    client_identification = models.CharField("RUC/CI Cliente", max_length=20, default="")
    client_legal_name = models.CharField("Razón Social", max_length=300, default="")
    client_address = models.CharField("Dirección", max_length=300, blank=True)
    client_phone = models.CharField("Teléfono", max_length=50, blank=True)
    client_email = models.EmailField("Email", blank=True)

    # Motivo
    reason = models.ForeignKey(
        ReturnReason, on_delete=models.PROTECT,
        related_name="returns", verbose_name="Motivo",
        null=True, blank=True,
    )
    reason_notes = models.TextField("Observaciones del motivo", blank=True)

    # Estado y fechas
    status = models.CharField(
        "Estado", max_length=20,
        choices=SaleReturnStatus.choices,
        default=SaleReturnStatus.GENERATED,
    )
    return_date = models.DateTimeField("Fecha de solicitud", auto_now_add=True)
    received_date = models.DateTimeField("Fecha de recepción", null=True, blank=True)
    inspection_date = models.DateTimeField("Fecha de inspección", null=True, blank=True)
    resolution_date = models.DateTimeField("Fecha de resolución", null=True, blank=True)

    # Montos
    subtotal = models.DecimalField("Subtotal", max_digits=12, decimal_places=2, default=0)
    tax_amount = models.DecimalField("IVA", max_digits=12, decimal_places=2, default=0)
    total_amount = models.DecimalField("Total", max_digits=12, decimal_places=2, default=0)

    # Nota de crédito (si aplica)
    credit_note = models.OneToOneField(
        "CreditNote", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="sale_return",
    )

    # Notas internas
    notes = models.TextField("Notas internas", blank=True)
    inspection_notes = models.TextField("Notas de inspección QA", blank=True)

    class Meta:
        verbose_name = "Devolución de venta"
        verbose_name_plural = "Devoluciones de venta"
        ordering = ["-return_date"]

    def _generate_code(self):
        year = timezone.now().year
        prefix = f"DEV-{year}-"
        last = (
            SaleReturn.objects.filter(code__startswith=prefix)
            .order_by("-code").values_list("code", flat=True).first()
        )
        seq = int(last.split("-")[-1]) + 1 if last else 1
        return f"{prefix}{seq:04d}"

    def save(self, *args, **kwargs):
        if not self.code:
            self.code = self._generate_code()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"Devolución {self.code}"


class SaleReturnLine(AuditModel):
    return_doc = models.ForeignKey(
        SaleReturn, on_delete=models.CASCADE,
        related_name="lines", verbose_name="Devolución",
    )
    invoice_line = models.ForeignKey(
        "SaleInvoiceLine", on_delete=models.PROTECT,
        related_name="return_lines", verbose_name="Línea de factura",
        null=True, blank=True,
    )
    product = models.ForeignKey(Product, on_delete=models.PROTECT, verbose_name="Producto")
    lot = models.ForeignKey(
        Lot, on_delete=models.PROTECT, verbose_name="Lote",
        null=True, blank=True, help_text="Lote del producto devuelto",
    )
    quantity_returned = models.DecimalField("Cantidad devuelta", max_digits=12, decimal_places=4)
    unit_price = models.DecimalField("Precio unitario", max_digits=12, decimal_places=4)
    subtotal = models.DecimalField("Subtotal", max_digits=12, decimal_places=2, default=0)

    class Meta:
        verbose_name = "Línea de devolución"
        verbose_name_plural = "Líneas de devolución"

    def save(self, *args, **kwargs):
        self.subtotal = self.quantity_returned * self.unit_price
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.product.name} x {self.quantity_returned}"


# ─── Nota de Crédito ──────────────────────────────────────

class CreditNoteStatus(models.TextChoices):
    DRAFT = "DRAFT", "Borrador"
    SIGNED = "SIGNED", "Firmado"
    SENT = "SENT", "Enviado al SRI"
    AUTHORIZED = "AUTHORIZED", "Autorizado"
    REJECTED = "REJECTED", "Rechazado"
    VOIDED = "VOIDED", "Anulado"


class CreditNote(AuditModel):
    invoice = models.ForeignKey(
        SaleInvoice, on_delete=models.PROTECT,
        related_name="credit_notes", verbose_name="Factura",
    )
    establishment = models.CharField("Establecimiento", max_length=3, default="001")
    emission_point = models.CharField("Punto de emisión", max_length=3, default="001")
    sequential = models.CharField("Secuencial", max_length=9, default="000000000")
    access_key = models.CharField("Clave de acceso", max_length=49, blank=True)

    reason = models.CharField("Motivo", max_length=300)
    subtotal = models.DecimalField("Subtotal", max_digits=12, decimal_places=2, default=0)
    tax_amount = models.DecimalField("IVA", max_digits=12, decimal_places=2, default=0)
    total_amount = models.DecimalField("Total", max_digits=12, decimal_places=2, default=0)

    status = models.CharField(
        "Estado", max_length=20,
        choices=CreditNoteStatus.choices,
        default=CreditNoteStatus.DRAFT,
    )
    authorization_number = models.CharField("Nº autorización", max_length=49, blank=True)
    authorization_date = models.DateTimeField("Fecha autorización", null=True, blank=True)
    xml_unsigned = models.TextField("XML sin firmar", blank=True)
    xml_signed = models.TextField("XML firmado", blank=True)
    sri_response = models.TextField("Respuesta SRI", blank=True)
    issue_date = models.DateTimeField("Fecha de emisión", auto_now_add=True)

    class Meta:
        verbose_name = "Nota de crédito"
        verbose_name_plural = "Notas de crédito"
        ordering = ["-issue_date"]
        unique_together = [("establishment", "emission_point", "sequential")]

    def __str__(self):
        return f"NC {self.establishment}-{self.emission_point}-{self.sequential}"

    @property
    def full_number(self):
        return f"{self.establishment}-{self.emission_point}-{self.sequential}"


class CreditNoteLine(AuditModel):
    credit_note = models.ForeignKey(
        CreditNote, on_delete=models.CASCADE,
        related_name="lines", verbose_name="Nota de crédito",
    )
    product = models.ForeignKey(Product, on_delete=models.PROTECT, verbose_name="Producto")
    description = models.CharField("Descripción", max_length=300)
    quantity = models.DecimalField("Cantidad", max_digits=12, decimal_places=2)
    unit_price = models.DecimalField("Precio unitario", max_digits=12, decimal_places=4)
    subtotal = models.DecimalField("Subtotal", max_digits=12, decimal_places=2)
    tax_rate = models.DecimalField("Tarifa %", max_digits=5, decimal_places=2)
    tax_amount = models.DecimalField("Valor impuesto", max_digits=12, decimal_places=2)

    class Meta:
        verbose_name = "Línea de nota de crédito"
        verbose_name_plural = "Líneas de nota de crédito"

    def __str__(self):
        return f"{self.description} x {self.quantity}"
