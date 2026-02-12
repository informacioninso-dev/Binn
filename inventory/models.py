# inventory/model.py
from django.db import models
from django.conf import settings
from core.models import AuditModel, TaxScheme, Unit, Warehouse, Location
from decimal import Decimal
from django.db.models import Sum

#-----------------Tipo de producto
class ProductType(models.TextChoices):
    """
    Tipos de productos considierando producción y distribución
    """
    RAW = "RAW", "Materia prima"
    PACK = "PACK", "Material de empaque"
    SEMI = "SEMI", "Producto semielaborado"
    FG = "FG", "Producto terminado"
    SERVICE = "SERVICE", "Servicio"

#-----------------Modelo de Producto
class Product(AuditModel):
    """
    Modelo que describe la entidad producto
    Considera el modelo Product_type de "inventory/models" como product_type
    Considera el modelo Unit de "core/models" como base_unit
    Considera el modelo TaxScheme de "core/models" como taxScheme
    """
    product_type = models.CharField(
    max_length=10,
    choices=ProductType.choices,
    default=ProductType.RAW,   # Por defecto materia prima
    )
    code = models.CharField(max_length=50, unique=True ) # codigo uncio de producto
    code_2 = models.CharField(max_length=50, blank=True, null=True)
    name = models.CharField(max_length=200)
    base_unit = models.ForeignKey(   #  unidad técnica base
        Unit,
        on_delete=models.PROTECT,
        related_name="products",
        verbose_name="Unidad base",
    )
    unit_price = models.DecimalField(max_digits=10, decimal_places=4, default=0)
    unit_cost = models.DecimalField(max_digits=10, decimal_places=4,  null=True, blank=True)
    # Vinculación al esquema tributario para que sea selecionado en documentos de venta, compra e inventarios
    tax_scheme = models.ForeignKey(
        TaxScheme,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="products",
        verbose_name="Esquema tributario",
    )
    provider = models.CharField(max_length=200, blank=True, null=True)
    category = models.CharField(max_length=100, blank=True, null=True)
    brand = models.CharField(max_length=100, blank=True, null=True)
    attribute1 = models.CharField(max_length=100, blank=True, null=True)
    attribute2 = models.CharField(max_length=100, blank=True, null=True)
    is_active = models.BooleanField(default=True)
    lot_prefix = models.CharField(
        max_length=20,
        blank=True,
        null=True,
        help_text="Prefijo para el lote de producción (ej: CAP, CAM, 00101, 00102)."
    )
    use_date_in_lot = models.BooleanField(
        default=True,
        help_text="Si está activo, el lote incluye mes y año de fabricación."
    )

    # Metadatos y permisos 
    # Ejemplo: permiso para exportar productos  
    class Meta:
        ordering = ["name"]
        verbose_name = "Producto"
        verbose_name_plural = "Productos"
        permissions = [
            ("export_product", "Puede exportar productos"),
        ]
    # Representación en cadena del producto
    def __str__(self):
        return f"{self.code} - {self.name}"

#----------------------------Modelos de Inventario 
class Stock(AuditModel):
    """
    Esto gestiona las cantidades en existencia de los productos
    Modelo que las cantidades de producto de "inventory/models"
    """
    product = models.OneToOneField(Product, on_delete=models.CASCADE, related_name="stock")
    quantity = models.DecimalField(max_digits=12, decimal_places=4, default=0)

    @property
    def quantity_by_warehouse(self):
        """Cantidad por bodega"""
        return LotBalance.objects.filter(
            lot__product=self.product
        ).values('warehouse__name').annotate(total=Sum('qty'))


    class Meta:
        verbose_name = "Stock"
        verbose_name_plural = "Stocks"

    def __str__(self):
        return f"{self.product.code} - {self.quantity}"

#----------------------------Modelo de tipo de movimientos de inventario
class MovementTypes(models.TextChoices):
    """
    Esto gestiona los tipos de movimientos de productos 
    """
    IN = "IN", "Ingreso"
    OUT = "OUT", "Salida"
    ADJ = "ADJ", "Ajuste"
    TRANSFER = "TRF", "Transferencia"

class MovementReason(models.TextChoices):
    RECEIPT = "RECEIPT", "Recepción"
    QA_TO_QUARANTINE = "QA_TO_QUARANTINE", "Ingreso a cuarentena"
    RELEASE_TO_STOCK = "RELEASE_TO_STOCK", "Liberación a stock"
    PICKING = "PICKING", "Picking"
    SHIPPING = "SHIPPING", "Despacho"
    RETURN = "RETURN", "Devolución"
    RECALL = "RECALL", "Retiro"



# ---------------------------- Modelos de Lotes y QA -------------------------
# Modelo de Lote - Estados de lote
class LotStatus(models.TextChoices):
    PENDING = "PENDING", "Pendiente de inspección"
    APPROVED = "APPROVED", "Aprobado"
    REJECTED = "REJECTED", "Rechazado"
    QUARANTINE = "QUARANTINE", "Cuarentena"

# Modelo de Lote de Producto 
# Cada lote está asociado a un producto específico
class Lot(AuditModel):
    """
    Esto gestiona los lotes de productos
    Modelo que las cantidades de product de "inventory/models" como Product
    Modelo que las cantidades de Warehouse de "code/models" como warehouse
    Modelo que las cantidades de Location de "code/models" como  location
    """
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name="lots")
    lot_number = models.CharField(
        max_length=50,
        null=True,
        blank=True,
        verbose_name="Número de lote",
        help_text="Número de lote único para trazabilidad (del proveedor o auto-generado)"
    )
    # Campos deprecados - mantener temporalmente para migración de datos
    internal_lot = models.CharField(max_length=50, null=True, blank=True)
    supplier_lot = models.CharField(max_length=50, blank=True, null=True)
    quantity_initial = models.DecimalField(max_digits=12, decimal_places=4)
    warehouse = models.ForeignKey(
        Warehouse,
        on_delete=models.PROTECT,
        related_name="lots",
        verbose_name="Bodega actual",
        blank=True,
        null=True)
    location = models.ForeignKey(
        Location,
        on_delete=models.PROTECT,
        related_name="lots",
        verbose_name="Ubicación actual",
        blank=True,
        null=True
    )
    manufacturing_date = models.DateField(null=True, blank=True)
    expiry_date = models.DateField(null=True, blank=True, help_text="Usado para FEFO y trazabilidad.")
    
    origin_reference = models.CharField(max_length=100, blank=True, null=True)  # factura, OC, OP
    status = models.CharField(max_length=20,choices=LotStatus.choices,default=LotStatus.PENDING)
    @property
    def quantity_current(self):
        """Calcula cantidad actual desde LotBalance"""
        from django.db.models import Sum
        total = self.balances.aggregate(total=Sum('qty'))['total']
        return total or Decimal('0')
    
    class Meta:
        unique_together = ("product", "lot_number")
        verbose_name = "Lote"
        verbose_name_plural = "Lotes"

    def __str__(self):
        return f"{self.product.code} - Lote {self.lot_number}"

# ---------------------------- Modelos de Recepción de Materia Prima -------------------------



### Este modelo te permite ver salgo por lote y ubicacion
class LotBalance(AuditModel):
    lot = models.ForeignKey("Lot", on_delete=models.PROTECT, related_name="balances")
    warehouse = models.ForeignKey(Warehouse, on_delete=models.PROTECT, related_name="lot_balances")
    location = models.ForeignKey(Location, on_delete=models.PROTECT, related_name="lot_balances")
    qty = models.DecimalField(max_digits=12, decimal_places=4, default=0)

    class Meta:
        unique_together = ("lot", "location")
        indexes = [
            models.Index(fields=["warehouse", "location"]),
            models.Index(fields=["lot"]),
        ]

    def __str__(self):
        return f"{self.lot.lot_number} @ {self.location.code} = {self.qty}"


#----------------------------Modelo de Movimiento de Inventario

class InventoryMove(AuditModel):
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name="moves")
    lot = models.ForeignKey(Lot, on_delete=models.PROTECT, related_name="moves", null=True, blank=True)
    movement_type = models.CharField(max_length=3, choices=MovementTypes.choices)
    date = models.DateTimeField(auto_now_add=True)
    quantity = models.DecimalField(max_digits=12, decimal_places=4)
    unit_displayed = models.ForeignKey(Unit,on_delete=models.PROTECT, null=True)  # Unidad que vio el usuario
    quantity_displayed = models.DecimalField(max_digits=10, decimal_places=4,null=True)  # Cantidad que ingresó el usuario
    unit_cost = models.DecimalField(max_digits=10, decimal_places=4, null=True, blank=True)
    reference = models.CharField(max_length=100, blank=True, null=True)  # ej: factura, OC
    warehouse = models.ForeignKey(
        Warehouse,
        on_delete=models.PROTECT,
        related_name="moves",
        verbose_name="Bodega",
        null=True,
        blank=True,
    )
    location = models.ForeignKey(
        Location,
        on_delete=models.PROTECT,
        related_name="moves",
        verbose_name="Ubicación",
        null=True,
        blank=True,
    )
    area = models.CharField(max_length=100, blank=True, null=True)  # ej: Bodega, Producción
    notes = models.TextField(blank=True, null=True)
    reason = models.CharField(max_length=30, choices=MovementReason.choices, blank=True, null=True)
    from_location = models.ForeignKey(Location, on_delete=models.PROTECT, related_name="moves_from", null=True, blank=True)
    to_location = models.ForeignKey(Location, on_delete=models.PROTECT, related_name="moves_to", null=True, blank=True)
    from_warehouse = models.ForeignKey(Warehouse, on_delete=models.PROTECT, related_name="moves_from_wh", null=True, blank=True)
    to_warehouse = models.ForeignKey(Warehouse, on_delete=models.PROTECT, related_name="moves_to_wh", null=True, blank=True)

    class Meta:
        verbose_name = "Movimiento de inventario"
        verbose_name_plural = "Movimientos de inventario"
        ordering = ["-date"]

    # Propiedad para obtener el signo del movimiento
    @property
    def sign(self):
        if self.movement_type == MovementTypes.OUT:
            return -1
        return 1  # IN y ADJ positivos por defecto, si quieres ajustes negativos, se maneja por quantity

    # Total del costo, calculado sobre la cantidad
    @property
    def total_cost(self):
        if self.unit_cost is None:
            return None
        return self.unit_cost * self.quantity

    def __str__(self):
        return f"{self.get_movement_type_display()} {self.quantity} de {self.product.code} en {self.date:%d/%m/%Y}"