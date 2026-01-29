# production/models.py
from django.db import models
from decimal import Decimal
from django.utils import timezone
from django.conf import settings
from core.models import AuditModel, Unit, Warehouse
from inventory.models import Product, Lot , ProductType
from inventory.models import Lot as RawLot


class ProductionOperationStatus(models.TextChoices):
    PENDING = "PENDING", "Pendiente"
    IN_PROGRESS = "IN_PROGRESS", "En proceso"
    DONE = "DONE", "Completada"

############################################
# Rutas de produccion
############################################

class ProductRoute(AuditModel):
    """
    Ruta de producción de un producto.
    Ej: Ruta estándar de venda elástica 4\".
    """
    product = models.ForeignKey(
        Product,
        on_delete=models.PROTECT,
        related_name="routes",
        help_text="Producto que se fabrica con esta ruta (normalmente SEMI o FG)."
    )
    name = models.CharField(
        max_length=100,
        help_text="Nombre de la ruta (ej: Ruta estándar, Ruta alternativa...)."
    )
    is_active = models.BooleanField(default=True)
    notes = models.TextField(blank=True, null=True)

    class Meta:
        verbose_name = "Ruta de producción"
        verbose_name_plural = "Rutas de producción"
        unique_together = ("product", "name")

    def __str__(self):
        return f"{self.product.code} – {self.name}"

############################################
# Lista de materiales
############################################
class BillOfMaterial(AuditModel):
    """
    Plano de fabricación (BOM) para un producto terminado.
    """
    product_finished = models.ForeignKey(
        Product,
        on_delete=models.PROTECT,
        related_name="boms",
        limit_choices_to={"product_type": ProductType.FG, "is_active": True},
        verbose_name="Producto terminado",
    )
    revision = models.CharField(
        max_length=10,
        default="1",
        help_text="Versión del plano (1, 1.1, A, B, etc.)",
    )
    description = models.TextField(
        blank=True,
        null=True,
        help_text="Descripción general del plano / notas técnicas.",
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name = "Plano de fabricación"
        verbose_name_plural = "Planos de fabricación"
        unique_together = ("product_finished", "revision")

    def __str__(self):
        return f"{self.product_finished.code} · Rev. {self.revision}"
    
class BillOfMaterialLine(AuditModel):
    """
    Línea de BOM = un componente del plano de fabricación.
    """
    bom = models.ForeignKey(
        BillOfMaterial,
        on_delete=models.CASCADE,
        related_name="lines",
        verbose_name="BOM",
    )
    component = models.ForeignKey(
        Product,
        on_delete=models.PROTECT,
        related_name="bom_components",
        verbose_name="Componente",
    )
    quantity = models.DecimalField(
        max_digits=12,
        decimal_places=4,
        help_text="Cantidad requerida por unidad de producto terminado (en unidad base del componente).",
    )
    scrap_rate = models.DecimalField(
        max_digits=5,
        decimal_places=4,
        default=0,
        help_text="Porcentaje de merma / desperdicio esperado (0–100).",
    )
    sequence = models.PositiveIntegerField(
        default=10,
        help_text="Orden lógico del componente en el plano.",
    )

    class Meta:
        verbose_name = "Línea de BOM"
        verbose_name_plural = "Líneas de BOM"
        ordering = ["sequence", "id"]

    def __str__(self):
        return f"{self.bom} · {self.component.code} x {self.quantity}"
    
class ProductionOrderOrigin(models.TextChoices):
    PLANNING = "PLANNING", "Planificación interna"
    SALES_ORDER = "SALES_ORDER", "Pedido de cliente"

class ProductionOrderStatus(models.TextChoices):
    DRAFT = "DRAFT", "Borrador"
    RELEASED = "RELEASED", "Liberada"
    IN_PROGRESS = "IN_PROGRESS", "En proceso"
    DONE = "DONE", "Terminada"
    CANCELED = "CANCELED", "Anulada"

############################################
# Orden de producción
############################################

class ProductionOrder(AuditModel):
    """
    Orden de producción principal.
    """
    code = models.CharField(
        max_length=50,
        unique=True,
        help_text="Código interno de la orden (ej: OP-2025-0001)."
    )
    product = models.ForeignKey(
        Product,
        on_delete=models.PROTECT,
        related_name="production_orders",
    )
    quantity_planned = models.DecimalField(
        max_digits=12,
        decimal_places=4,
        help_text="Cantidad planificada de producto terminado."
    )
    quantity_produced = models.DecimalField(
        max_digits=12,
        decimal_places=4,
        default=Decimal("0"),
        help_text="Cantidad realmente producida ."
    )
    route = models.ForeignKey(
        ProductRoute,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="production_orders",
    )
    bom = models.ForeignKey(
        BillOfMaterial,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="production_orders",
    )

    finished_lot = models.ForeignKey(
        Lot,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="as_finished_in_orders",
        help_text="Lote de producto terminado asociado a esta OP."
    )

    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)

    status = models.CharField(
        max_length=20,
        choices=ProductionOrderStatus.choices,
        default=ProductionOrderStatus.DRAFT,
    )

    origin_type = models.CharField(
        max_length=20,
        choices=ProductionOrderOrigin.choices,
        default=ProductionOrderOrigin.PLANNING,
    )
    origin_reference = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        help_text="Referencia externa: código de pedido u planficación de la produción.",
    )
    plan = models.ForeignKey(
        "ProductionPlan",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="orders",
        help_text="Plan de producción del que nace esta OP."
    )

    notes = models.TextField(blank=True, null=True)

    class Meta:
        verbose_name = "Orden de producción"
        verbose_name_plural = "Órdenes de producción"

    def __str__(self):
        return f"{self.code} – {self.product.code}"

    # 🔹 Generador de código tipo OP-2026-0001
    def _generate_code(self):
        year = timezone.now().year
        prefix = f"OP-{year}-"
        last = (
            ProductionOrder.objects
            .filter(code__startswith=prefix)
            .order_by("-code")
            .first()
        )
        if last and last.code:
            try:
                last_seq = int(last.code.split("-")[-1])
            except (ValueError, IndexError):
                last_seq = 0
        else:
            last_seq = 0
        return f"{prefix}{last_seq + 1:04d}"

    def save(self, *args, **kwargs):
        # Si no tiene código, lo generamos
        if not self.code:
            self.code = self._generate_code()
        super().save(*args, **kwargs)




############################################
# Centro de trabajo
############################################

class WorkCenter(AuditModel):
    """
    Representa una estación de trabajo (Es decir los pasos para la producción del producto)
    Configurable por empresa.
    """
    code = models.CharField(
        max_length=30,
        unique=True,
        help_text="Código interno del centro de trabajo (ej: Estación-01)"
    )
    name = models.CharField(
        max_length=100,
        help_text="Nombre descriptivo (ej: Estación que hace algo\")"
    )
    description = models.CharField(
        max_length=255,
        blank=True,
        null=True,
    )

    # Bodega por defecto donde cae el WIP de este centro (opcional)
    default_warehouse = models.ForeignKey(
        Warehouse,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="work_centers",
        help_text="Bodega por defecto donde se almacena el producto en proceso de este centro."
    )

    # Capacidad aproximada, opcional (unidades/hora, metros/hora, etc.)
    capacity_per_hour = models.DecimalField(
        max_digits=12,
        decimal_places=4,
        null=True,
        blank=True,
        help_text="Capacidad teórica por hora (solo referencial)."
    )

    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name = "Centro de trabajo"
        verbose_name_plural = "Centros de trabajo"
        ordering = ["code"]

    def __str__(self):
        return f"{self.code} - {self.name}"

class ProductRouteStep(AuditModel):
    """
    Paso dentro de una ruta de producción.
    Aquí es donde representas corte, planchado y demas como una ruta de produción.
    """
    route = models.ForeignKey(
        ProductRoute,
        on_delete=models.CASCADE,
        related_name="steps",
    )
    sequence = models.PositiveIntegerField(
        help_text="Orden del paso en la ruta (1, 2, 3...)."
    )
    work_center = models.ForeignKey(
        WorkCenter,
        on_delete=models.PROTECT,
        related_name="route_steps",
    )
    name = models.CharField(
        max_length=100,
        help_text="Nombre corto del paso (ej: Crochet, Corte, Ensamblado)."
    )
    description = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        help_text="Descripción de lo que se hace en este paso."
    )

    expected_duration_min = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Duración esperada en minutos por lote/orden (opcional)."
    )

    # ¿Se requiere QA en este paso?
    requires_qa = models.BooleanField(
        default=False,
        help_text="Si está marcado, la orden puede exigir una inspección QA en este paso."
    )

    # Nota: los planes de QA (QAPlan) los definimos en inventory,
    # y allí se puede asociar un QAPlan a un ProductRouteStep por FK.

    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name = "Paso de ruta de producción"
        verbose_name_plural = "Pasos de ruta de producción"
        ordering = ["route", "sequence"]
        unique_together = ("route", "sequence")

    def __str__(self):
        return f"{self.route} – Paso {self.sequence}: {self.name}"

class ProductionOperation(AuditModel):
    """
    Ejecución de un paso de la ruta dentro de una Orden de Producción.
    Aquí podrás enganchar QA por paso.
    """
    order = models.ForeignKey(
        ProductionOrder,
        on_delete=models.CASCADE,
        related_name="operations",
    )
    step = models.ForeignKey(
        ProductRouteStep,
        on_delete=models.PROTECT,
        related_name="operations",
    )
    sequence = models.PositiveIntegerField(
        help_text="Orden de la operación dentro de la OP (normalmente coincide con step.sequence)."
    )

    # Lote sobre el que se está trabajando en este paso (WIP)
    input_lot = models.ForeignKey(
        Lot,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="operations_as_input",
        help_text="Lote de entrada (producto en proceso)."
    )
    output_lot = models.ForeignKey(
        Lot,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="operations_as_output",
        help_text="Lote resultante de esta operación (si aplica)."
    )

    quantity_input = models.DecimalField(
        max_digits=12,
        decimal_places=4,
        null=True,
        blank=True,
    )
    quantity_output = models.DecimalField(
        max_digits=12,
        decimal_places=4,
        null=True,
        blank=True,
    )

    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    status = models.CharField(
        max_length=20,
        choices=ProductionOperationStatus.choices,
        default=ProductionOperationStatus.PENDING,
    )

    notes = models.TextField(blank=True, null=True)

    class Meta:
        verbose_name = "Operación de producción"
        verbose_name_plural = "Operaciones de producción"
        ordering = ["order", "sequence"]

    def __str__(self):
        return f"OP {self.order.code} – Paso {self.sequence} ({self.step.name})"


class ProductionPlanStatus(models.TextChoices):
    ACTIVE = "ACTIVE", "Activo"
    COMPLETED = "COMPLETED", "Completado"
    CANCELED = "CANCELED", "Anulado"


class ProductionPlan(AuditModel):
    """
    Plan de producción por SKU y por lote de producción.
    Ej: Cabestrillo Pequeño – lote CAP012026 – 10.000 unidades.
    """
    code = models.CharField(
        max_length=30,
        unique=True,
        verbose_name="Código del plan",
        help_text="Ej: PP-2026-0001",
    )
    product = models.ForeignKey(
        Product,
        on_delete=models.PROTECT,
        related_name="production_plans",
        limit_choices_to={"product_type": ProductType.FG, "is_active": True},
        verbose_name="Producto terminado (SKU)",
    )

    # Lote de producción (ej: CAP012026, 00101012026, etc.)
    lot_code = models.CharField(
        max_length=50,
        verbose_name="Código de lote de producción",
        help_text="Ej: CAP012026. Debe ser único por producto y fecha.",
    )

    manufacturing_date = models.DateField(
        verbose_name="Fecha de fabricación del lote",
    )

    quantity_planned = models.DecimalField(
        max_digits=12,
        decimal_places=4,
        verbose_name="Cantidad total planificada del lote",
        help_text="Ej: 10000 unidades para el lote completo.",
    )

    status = models.CharField(
        max_length=20,
        choices=ProductionPlanStatus.choices,
        default=ProductionPlanStatus.ACTIVE,
    )

    notes = models.TextField(blank=True, null=True)

    class Meta:
        verbose_name = "Plan de producción"
        verbose_name_plural = "Planes de producción"
        unique_together = ("product", "lot_code")

    def __str__(self):
        return f"{self.product.code} – Lote {self.lot_code}"

    @property
    def quantity_assigned_to_orders(self) -> Decimal:
        from .models import ProductionOrder
        total = (
            self.orders.filter(
                status__in=[
                    ProductionOrderStatus.IN_PROGRESS,
                    ProductionOrderStatus.DONE,
                ]
            )
            .aggregate(total=models.Sum("quantity_planned"))
            ["total"]
            or Decimal("0")
        )
        return total


    @property
    def quantity_pending(self) -> Decimal:
        """
        Cantidad del lote aún pendiente de planificar en OP.
        """
        return (self.quantity_planned or Decimal("0")) - self.quantity_assigned_to_orders


class ProductionPlanRawLot(models.Model):
    plan = models.ForeignKey(
        ProductionPlan,
        on_delete=models.CASCADE,
        related_name="raw_lots",
    )
    lot = models.ForeignKey(
        RawLot,
        on_delete=models.PROTECT,
        related_name="used_in_plans",
    )
    # opcional: consumo teórico esperado
    quantity_planned = models.DecimalField(
        max_digits=12,
        decimal_places=4,
        null=True,
        blank=True,
        help_text="Cantidad teórica de consumo de este lote de MP en el plan."
    )

    component = models.ForeignKey(   # 👈 FALTABA
        Product,
        on_delete=models.PROTECT,
        related_name="as_component_in_plans",
        limit_choices_to={"product_type": ProductType.RAW, "is_active": True},)
    

    class Meta:
        unique_together = ("plan", "component")

    def __str__(self):
        return f"{self.plan} – MP {self.lot.internal_lot}"












