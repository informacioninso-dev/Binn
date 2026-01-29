# sales/models.py
from django.db import models
from core.models import AuditModel
from partners.models import Partner  # Cliente asociado
from inventory.models import Product,Lot

class SaleOrderStatus(models.TextChoices):
    PENDING = "PENDING", "Pendiente"
    PROFORMA = "PROFORMA", "Proforma"
    CONFIRMED = "CONFIRMED", "Confirmado"
    INVOICED = "INVOICED", "Facturado"
    DISPATCHED = "DISPATCHED", "Despachado"
    CANCELED = "CANCELED", "Cancelado"

class SaleOrder(AuditModel):
    code = models.CharField(max_length=50, unique=True, help_text="Código interno del pedido (ej. SO-2026-0001)")
    client = models.ForeignKey(Partner, on_delete=models.PROTECT, related_name="sale_orders", help_text="Cliente que realiza el pedido.")
    status = models.CharField(max_length=20, choices=SaleOrderStatus.choices, default=SaleOrderStatus.PENDING)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    delivery_date = models.DateField(help_text="Fecha de entrega del pedido.")
    notes = models.TextField(blank=True, null=True, help_text="Notas adicionales sobre el pedido.")
    payment_method = models.CharField(max_length=50, blank=True, null=True, help_text="Método de pago (transferencia, efectivo, etc.)")

    class Meta:
        verbose_name = "Pedido de venta"
        verbose_name_plural = "Pedidos de venta"
        ordering = ["-created_at"]

    def __str__(self):
        return f"Pedido {self.code} – Cliente: {self.client.trade_name}"

    def get_total(self):
        return sum(line.total_price for line in self.lines.all())

class SaleOrderLine(AuditModel):
    order = models.ForeignKey(SaleOrder, on_delete=models.CASCADE, related_name="lines")
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name="sale_order_lines")
    quantity = models.DecimalField(max_digits=12, decimal_places=2)
    unit_price = models.DecimalField(max_digits=12, decimal_places=2)
    total_price = models.DecimalField(max_digits=12, decimal_places=2)

    def save(self, *args, **kwargs):
        self.total_price = self.quantity * self.unit_price
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.product.name} - {self.quantity} unidades"


#########################################
###### Despacho
###########################################
# sales/models.py
class SaleDispatch(AuditModel):
    """
    Genera el despacho de productos de un pedido.
    """
    order = models.ForeignKey(SaleOrder, on_delete=models.PROTECT, related_name="dispatches")
    dispatched_date = models.DateTimeField(auto_now_add=True)
    total_amount = models.DecimalField(max_digits=12, decimal_places=2)
    status = models.CharField(
        max_length=20, choices=SaleOrderStatus.choices, default=SaleOrderStatus.DISPATCHED
    )
    # Aquí podemos registrar los lotes que fueron utilizados
    lot = models.ForeignKey(Lot, on_delete=models.PROTECT, related_name="dispatches")

    def __str__(self):
        return f"Despacho {self.order.code} - {self.status}"


#########################################################
#########Factura
###########################################################
# sales/models.py
class SaleInvoice(AuditModel):
    """
    Genera la factura electrónica para un pedido.
    """
    order = models.ForeignKey(SaleOrder, on_delete=models.PROTECT, related_name="invoices")
    invoice_code = models.CharField(max_length=50, unique=True)
    issue_date = models.DateTimeField(auto_now_add=True)
    total_amount = models.DecimalField(max_digits=12, decimal_places=2)
    status = models.CharField(
        max_length=20, choices=SaleOrderStatus.choices, default=SaleOrderStatus.INVOICED
    )
    # Factura electrónica SRI
    sri_status = models.CharField(max_length=20, default="PENDING")
    xml_data = models.TextField()  # XML firmado

    def __str__(self):
        return f"Factura {self.invoice_code} - {self.order.customer.trade_name}"

    def generate_invoice_xml(self):
        """
        Función para generar el XML de la factura electrónica.
        Aquí va la lógica de integración con el SRI.
        """
        pass

    def send_to_sri(self):
        """
        Enviar la factura al SRI utilizando su API.
        """
        pass
