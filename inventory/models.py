from decimal import Decimal

from django.db import models
from django.db.models import F
from django.utils import timezone

from core.models import AuditModel


class Supplier(AuditModel):
    name = models.CharField("Proveedor", max_length=160)
    contact_name = models.CharField("Contacto", max_length=120, blank=True)
    phone = models.CharField("Telefono", max_length=30, blank=True)
    email = models.EmailField("Correo", blank=True)
    notes = models.TextField("Notas", blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class InventoryItem(AuditModel):
    sku = models.CharField("SKU", max_length=40, unique=True)
    name = models.CharField("Nombre", max_length=160)
    category = models.CharField("Categoria", max_length=120, blank=True)
    unit = models.CharField("Unidad", max_length=40, default="unidad")
    supplier = models.ForeignKey(
        Supplier,
        on_delete=models.SET_NULL,
        related_name="items",
        null=True,
        blank=True,
    )
    stock_on_hand = models.DecimalField("Stock actual", max_digits=10, decimal_places=2, default=Decimal("0.00"))
    reorder_point = models.DecimalField("Punto de reposicion", max_digits=10, decimal_places=2, default=Decimal("0.00"))
    unit_cost = models.DecimalField("Costo unitario", max_digits=10, decimal_places=2, default=Decimal("0.00"))
    sale_price = models.DecimalField("Precio de venta", max_digits=10, decimal_places=2, default=Decimal("0.00"))
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name

    @property
    def needs_restock(self):
        return self.stock_on_hand <= self.reorder_point


class StockMovementType(models.TextChoices):
    INBOUND = "INBOUND", "Entrada"
    OUTBOUND = "OUTBOUND", "Salida"
    ADJUSTMENT = "ADJUSTMENT", "Ajuste"


class PurchaseOrderStatus(models.TextChoices):
    OPEN = "OPEN", "Abierta"
    RECEIVED = "RECEIVED", "Recibida"
    CANCELED = "CANCELED", "Cancelada"


class PurchaseOrder(AuditModel):
    supplier = models.ForeignKey(
        Supplier,
        on_delete=models.PROTECT,
        related_name="purchase_orders",
    )
    ordered_at = models.DateTimeField("Fecha de orden", default=timezone.now)
    expected_on = models.DateField("Esperada para", null=True, blank=True)
    status = models.CharField(
        "Estado",
        max_length=20,
        choices=PurchaseOrderStatus.choices,
        default=PurchaseOrderStatus.OPEN,
    )
    reference = models.CharField("Referencia", max_length=80, blank=True)
    total_amount = models.DecimalField("Total", max_digits=10, decimal_places=2, default=Decimal("0.00"))
    notes = models.TextField("Notas", blank=True)

    class Meta:
        ordering = ["-ordered_at", "-id"]

    def __str__(self):
        return f"OC {self.id} - {self.supplier.name}"


class StockMovement(AuditModel):
    item = models.ForeignKey(
        InventoryItem,
        on_delete=models.PROTECT,
        related_name="movements",
    )
    purchase_order = models.ForeignKey(
        PurchaseOrder,
        on_delete=models.SET_NULL,
        related_name="movements",
        null=True,
        blank=True,
    )
    movement_type = models.CharField(
        "Tipo",
        max_length=20,
        choices=StockMovementType.choices,
        default=StockMovementType.INBOUND,
    )
    moved_at = models.DateTimeField("Fecha", default=timezone.now)
    quantity = models.DecimalField("Cantidad", max_digits=10, decimal_places=2, default=Decimal("0.00"))
    unit_cost = models.DecimalField("Costo unitario", max_digits=10, decimal_places=2, default=Decimal("0.00"))
    reference = models.CharField("Referencia", max_length=80, blank=True)
    notes = models.TextField("Notas", blank=True)

    class Meta:
        ordering = ["-moved_at", "-id"]

    def __str__(self):
        return f"{self.get_movement_type_display()} - {self.item.name}"

    @property
    def signed_quantity(self):
        if self.movement_type == StockMovementType.OUTBOUND:
            return -self.quantity
        return self.quantity

    def save(self, *args, **kwargs):
        previous_signed_quantity = Decimal("0.00")
        previous_item_id = None
        if self.pk:
            previous = type(self).objects.get(pk=self.pk)
            previous_signed_quantity = previous.signed_quantity
            previous_item_id = previous.item_id

        super().save(*args, **kwargs)

        if previous_item_id and previous_item_id != self.item_id:
            InventoryItem.objects.filter(pk=previous_item_id).update(
                stock_on_hand=F("stock_on_hand") - previous_signed_quantity
            )
            previous_signed_quantity = Decimal("0.00")

        delta = self.signed_quantity - previous_signed_quantity
        if delta != Decimal("0.00"):
            InventoryItem.objects.filter(pk=self.item_id).update(stock_on_hand=F("stock_on_hand") + delta)
            self.item.refresh_from_db(fields=["stock_on_hand"])
