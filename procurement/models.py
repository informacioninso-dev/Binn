# procurement/models.py
from django.db import models
from django.utils import timezone
from django.conf import settings
from core.models import AuditModel   # asumiendo que ya lo usas
from inventory.models import Product
from partners.models import Partner  # tu modelo de terceros
from core.models import Unit

class PurchaseOrderStatus(models.TextChoices):
    DRAFT = "DRAFT", "Borrador"
    SENT = "SENT", "Enviada al proveedor"
    CONFIRMED = "CONFIRMED", "Confirmada"
    RECEIVED = "RECEIVED", "Recibida"
    CANCELLED = "CANCELLED", "Anulada"


class PurchaseOrder(AuditModel):
    number = models.CharField(
        "Número de orden",
        max_length=20,
        unique=True,
        editable=False,
    )
    supplier = models.ForeignKey(
        Partner,
        on_delete=models.PROTECT,
        related_name="purchase_orders",
        limit_choices_to={"is_supplier": True},
        verbose_name="Proveedor",
    )
    order_date = models.DateField(
        "Fecha de emisión",
        default=timezone.now,
        editable=False,
    )
    status = models.CharField(
        max_length=20,
        choices=PurchaseOrderStatus.choices,
        default=PurchaseOrderStatus.DRAFT,
        verbose_name="Estado",
    )
    currency = models.CharField(
        "Moneda",
        max_length=5,
        default="USD",
    )

    # Total denormalizado (para consultas rápidas)
    total_amount = models.DecimalField(
        "Total de la orden",
        max_digits=14,
        decimal_places=4,
        default=0,
    )

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_purchase_orders",
        verbose_name="Creado por",
    )

    class Meta:
        verbose_name = "Orden de compra"
        verbose_name_plural = "Órdenes de compra"
        ordering = ["-order_date", "-id"]

    def __str__(self):
        return self.number or f"PO #{self.pk}"

    def _generate_number(self):
        """
        Genera un número tipo: OC-2026-0001
        """
        year = timezone.now().year
        prefix = f"OC-{year}-"
        last = (
            PurchaseOrder.objects
            .filter(number__startswith=prefix)
            .order_by("-number")
            .first()
        )
        if last and last.number:
            last_seq = int(last.number.split("-")[-1])
        else:
            last_seq = 0
        return f"{prefix}{last_seq + 1:04d}"

    def recalc_total(self):
        total = sum(
            (line.line_total or 0) for line in self.lines.all()
        )
        self.total_amount = total
        return total

    def save(self, *args, **kwargs):
        # número secuencial automático
        if not self.number:
            self.number = self._generate_number()
        super().save(*args, **kwargs)
    @property
    def can_be_received(self) -> bool:
        """
        Regla simple:
        - No permitir recepción si la OC está anulada o marcada como RECEIVED.
        - Además, si ya tiene una recepción activa, también la bloqueamos.
        """
        if self.status in [PurchaseOrderStatus.CANCELLED, PurchaseOrderStatus.RECEIVED]:
            return False

        # Si quieres limitar a UNA recepción por OC:
        # RawMaterialReception y ReceptionStatus ya están en este mismo módulo

        has_active_reception = RawMaterialReception.objects.filter(
            purchase_order=self
        ).exclude(
            status=ReceptionStatus.CANCELLED
        ).exists()

        if has_active_reception:
            return False

        return True


class PurchaseOrderLine(models.Model):
    order = models.ForeignKey(
        PurchaseOrder,
        on_delete=models.CASCADE,
        related_name="lines",
        verbose_name="Orden de compra",
    )
    product = models.ForeignKey(
        Product,
        on_delete=models.PROTECT,
        related_name="purchase_lines",
        verbose_name="Producto",
    )
    description = models.CharField(
        "Descripción",
        max_length=255,
        blank=True,
    )
    quantity = models.DecimalField(
        "Cantidad",
        max_digits=12,
        decimal_places=4,
    )
    unit_price = models.DecimalField(
        "Precio unitario",
        max_digits=12,
        decimal_places=4,
        default=0,
    )
    unit = models.ForeignKey(
        Unit, on_delete=models.PROTECT, 
        related_name="purchase_lines",
        verbose_name="Unidad de medida"
    )

    line_total = models.DecimalField(
        "Total de la línea",
        max_digits=14,
        decimal_places=4,
        default=0,
    )

    class Meta:
        verbose_name = "Línea de orden de compra"
        verbose_name_plural = "Líneas de orden de compra"

    def __str__(self):
        return f"{self.product} x {self.quantity}"
    
    def save(self, *args, **kwargs):
        # Unidad base del producto, automática
        if self.product and not self.unit:
            self.unit = self.product.base_unit  # Usa la unidad base del producto si no se selecciona

        # Total por ítem
        if self.quantity and self.unit_price is not None:
            self.line_total = self.quantity * self.unit_price

        super().save(*args, **kwargs)

        # Actualizar total de la orden
        if self.order_id:
            self.order.recalc_total()
            self.order.save(update_fields=["total_amount"])

# Modelo de Recepción de Materia Prima    
class ReceptionStatus(models.TextChoices):
    DRAFT = "DRAFT", "Borrador"
    RECEIVED = "RECEIVED", "Recibido en bodega"
    UNDER_QA = "UNDER_QA", "En inspección"
    COMPLETED = "COMPLETED", "Completada"
    CANCELLED = "CANCELLED", "Anulada"

## Cabecera de la recepción
class RawMaterialReception(AuditModel):
        
    purchase_order = models.ForeignKey(
        "procurement.PurchaseOrder",  # Aquí es la cadena de texto
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="receptions",
        verbose_name="Orden de compra asociada",)
    
    code = models.CharField(
        max_length=50,
        unique=True,
        help_text="Código interno de recepción (ej: REC-2025-0001)"
    )

    supplier_name = models.CharField(max_length=200)
    supplier_ruc = models.CharField(max_length=20, blank=True, null=True)

    document_type = models.CharField(
        max_length=50,
        blank=True,
        null=True,
        help_text="Factura, guía, etc."
    )
    document_number = models.CharField(max_length=50, blank=True, null=True)
    reception_date = models.DateField()
    arrival_time = models.TimeField(null=True, blank=True)
    transport_company = models.CharField(max_length=200, blank=True, null=True)
    transport_plate = models.CharField(max_length=20, blank=True, null=True)

    temperature_recorded = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Temperatura registrada al ingreso (si aplica)"
    )
    num_boxes = models.PositiveIntegerField(null=True, blank=True)
    gross_weight = models.DecimalField(max_digits=12, decimal_places=4, null=True, blank=True)
    net_weight = models.DecimalField(max_digits=12, decimal_places=4, null=True, blank=True)

    status = models.CharField(
        max_length=20,
        choices=ReceptionStatus.choices,
        default=ReceptionStatus.DRAFT
    )

    observations = models.TextField(blank=True, null=True)

    class Meta:
        verbose_name = "Recepción de Materia Prima"
        verbose_name_plural = "Recepciones de Materia Prima"
        ordering = ["-reception_date", "-code"]

    def __str__(self):
        return self.code
    
## Lineas de recepción
class RawMaterialReceptionLine(models.Model):
    """
    Esto gestiona la recepción de materias primas por filas, es decir el formulario 
    el cual esta conformado por dos partes la cabeza y la parte de lineas ( por producto)
    Modelo que las cantidades de de  RawMaterialReception  "inventory/models" como Recepcion 
    Modelo que las cantidades de Product de "code/models" como producto

    """
    reception = models.ForeignKey(  RawMaterialReception,on_delete=models.CASCADE, related_name="lines")
    product = models.ForeignKey(Product,on_delete=models.PROTECT,related_name="reception_lines")
    expected_quantity = models.DecimalField(
        max_digits=12,
        decimal_places=4,
        null=True,
        blank=True,
        help_text="Cantidad esperada según factura/OC"
    )
    received_quantity = models.DecimalField(
        max_digits=12,
        decimal_places=4,
        help_text="Cantidad realmente recibida"
    )

    unit_cost = models.DecimalField(
        max_digits=10,
        decimal_places=4,
        null=True,
        blank=True
    )
    unit = models.ForeignKey(
        Unit,
        on_delete=models.PROTECT,
        verbose_name="Unidad de medida recibida",
        help_text="Unidad en la que se recibió el material (puede diferir de la base)"
    )

    supplier_lot = models.CharField(
        max_length=50,
        blank=True,
        null=True,
        help_text="Lote según etiqueta del proveedor (si existe)"
    )
    internal_lot = models.CharField(
        max_length=50,
        blank=True,
        null=True,
        help_text="Lote interno asignado por la empresa (si ya lo tienes al recibir)"
    )
    manufacturing_date = models.DateField(
        null=True,
        blank=True,
        verbose_name="Fecha de elaboración",
        help_text="Fecha de elaboración/fabricación del lote."
    )
    expiry_date = models.DateField(
        null=True,
        blank=True,
        verbose_name="Fecha de caducidad",
        help_text="Fecha de vencimiento indicada por el proveedor."
    )
    storage_area = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        help_text="Área/bodega de almacenamiento inicial"
    )

    notes = models.TextField(blank=True, null=True)

    class Meta:
        verbose_name = "Línea de Recepción de Materia Prima"
        verbose_name_plural = "Líneas de Recepción de Materia Prima"

    def __str__(self):
        return f"{self.reception.code} - {self.product.code} ({self.received_quantity})"
