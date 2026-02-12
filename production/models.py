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
    PAUSED = "PAUSED", "Pausada"
    HOLD = "HOLD", "En espera (QA / bloqueo)"
    DONE = "DONE", "Completada"
    REJECTED = "REJECTED", "Rechazada"

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
        limit_choices_to={"product_type__in": [ProductType.RAW, ProductType.SEMI], "is_active": True},
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
        help_text="Porcentaje estimado de merma para planificación (0–1). La merma real se calcula al cerrar la OP.",
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
        help_text="Capacidad teórica por hora (unidades/hora)."
    )

    # --- Capacidad operativa ---
    num_machines = models.PositiveIntegerField(
        default=1,
        help_text="Cantidad de máquinas o puestos paralelos en esta estación.",
    )
    num_operators = models.PositiveIntegerField(
        default=1,
        help_text="Cantidad de operarios disponibles en esta estación.",
    )
    efficiency_factor = models.DecimalField(
        max_digits=5, decimal_places=4,
        default=Decimal("1.0000"),
        help_text="Factor de eficiencia real (ej: 0.85 = 85%).",
    )
    setup_time_min = models.PositiveIntegerField(
        default=0,
        help_text="Tiempo de setup/preparación por lote (minutos).",
    )
    hours_per_shift = models.DecimalField(
        max_digits=5, decimal_places=2,
        default=Decimal("8.00"),
        help_text="Horas productivas por turno.",
    )
    shifts_per_day = models.PositiveIntegerField(
        default=1,
        help_text="Cantidad de turnos por día.",
    )

    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name = "Centro de trabajo"
        verbose_name_plural = "Centros de trabajo"
        ordering = ["code"]

    def __str__(self):
        return f"{self.code} - {self.name}"

    @property
    def available_minutes_per_day(self):
        """Minutos productivos por día = horas_turno × turnos × máquinas × eficiencia × 60."""
        return (
            self.hours_per_shift
            * self.shifts_per_day
            * self.num_machines
            * self.efficiency_factor
            * 60
        )

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
        help_text="Duración esperada en minutos por unidad de producto.",
    )

    setup_time_min = models.PositiveIntegerField(
        default=0,
        help_text="Tiempo de setup específico de este paso (minutos). Si es 0 usa el del centro de trabajo.",
    )

    # ¿Se requiere QA en este paso?
    requires_qa = models.BooleanField(
        default=False,
        help_text="Si está marcado, la orden puede exigir una inspección QA en este paso."
    )

    # ¿Es el punto de conversión de unidades (MP → PT)?
    is_conversion_point = models.BooleanField(
        default=False,
        help_text="Marca el paso donde la unidad cambia de MP a PT (ej: de metros a unidades)."
    )

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

    planned_start = models.DateTimeField(null=True, blank=True, help_text="Inicio planificado (calculado al liberar).")
    planned_end = models.DateTimeField(null=True, blank=True, help_text="Fin planificado (calculado al liberar).")
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    status = models.CharField(
        max_length=20,
        choices=ProductionOperationStatus.choices,
        default=ProductionOperationStatus.PENDING,
    )

    operator = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="production_operations",
        help_text="Operario responsable de ejecutar este paso.",
    )

    materials_consumed = models.BooleanField(
        default=False,
        help_text="Indica si ya se consumió la materia prima en este paso (evita doble consumo)."
    )

    notes = models.TextField(blank=True, null=True)

    class Meta:
        verbose_name = "Operación de producción"
        verbose_name_plural = "Operaciones de producción"
        ordering = ["order", "sequence"]

    def __str__(self):
        return f"OP {self.order.code} – Paso {self.sequence} ({self.step.name})"


class OperationComponentDetail(models.Model):
    """
    Detalle por componente (línea de BOM) en una operación de producción.
    Permite rastrear cantidades de entrada/salida por cada materia prima
    en pasos anteriores al punto de conversión.
    """
    operation = models.ForeignKey(
        ProductionOperation,
        on_delete=models.CASCADE,
        related_name="component_details",
    )
    bom_line = models.ForeignKey(
        BillOfMaterialLine,
        on_delete=models.CASCADE,
        related_name="operation_details",
    )
    component = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name="operation_component_details",
        help_text="Componente (redundante con bom_line, facilita queries).",
    )
    quantity_input = models.DecimalField(
        max_digits=14, decimal_places=4, null=True, blank=True,
        help_text="Cantidad de entrada (auto-llenada desde paso anterior o transferencia).",
    )
    quantity_output = models.DecimalField(
        max_digits=14, decimal_places=4, null=True, blank=True,
        help_text="Cantidad de salida registrada por el operario.",
    )

    class Meta:
        verbose_name = "Detalle de componente en operación"
        verbose_name_plural = "Detalles de componente en operación"
        unique_together = ("operation", "bom_line")
        ordering = ["bom_line__sequence"]

    def __str__(self):
        return f"{self.operation} – {self.component.code} ({self.quantity_input} → {self.quantity_output})"


class OperationStatusLog(models.Model):
    """
    Registro de auditoría ISO 13485: cada cambio de estado
    en una operación de producción queda registrado.
    """
    operation = models.ForeignKey(
        ProductionOperation,
        on_delete=models.CASCADE,
        related_name="status_logs",
    )
    from_status = models.CharField(max_length=20, blank=True, null=True)
    to_status = models.CharField(max_length=20)
    changed_at = models.DateTimeField(auto_now_add=True)
    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="operation_status_changes",
    )
    notes = models.TextField(blank=True, null=True)

    class Meta:
        verbose_name = "Log de estado de operación"
        verbose_name_plural = "Logs de estado de operación"
        ordering = ["-changed_at"]

    def __str__(self):
        return f"{self.operation} : {self.from_status} → {self.to_status} ({self.changed_at:%d/%m/%Y %H:%M})"


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
        return f"{self.plan} – MP {self.lot.lot_number}"


class MaterialTransferStatus(models.TextChoices):
    PENDING = "PENDING", "Pendiente"
    CONFIRMED = "CONFIRMED", "Confirmada"
    ADJUSTED = "ADJUSTED", "Ajustada (con desviación)"


class MaterialTransfer(AuditModel):
    """
    Transferencia de materia prima desde bodega MP hacia estación de producción.
    Se genera automáticamente al liberar una OP.
    """
    order = models.ForeignKey(
        ProductionOrder,
        on_delete=models.CASCADE,
        related_name="material_transfers",
    )
    component = models.ForeignKey(
        Product,
        on_delete=models.PROTECT,
        related_name="material_transfers",
    )
    lot = models.ForeignKey(
        RawLot,
        on_delete=models.PROTECT,
        related_name="material_transfers",
    )
    quantity_requested = models.DecimalField(
        max_digits=12, decimal_places=4,
        help_text="Cantidad calculada del plan a transferir.",
    )
    quantity_confirmed = models.DecimalField(
        max_digits=12, decimal_places=4,
        null=True, blank=True,
        help_text="Cantidad que el operario confirma haber transferido.",
    )
    from_warehouse = models.ForeignKey(
        "core.Warehouse",
        on_delete=models.PROTECT,
        related_name="transfers_out",
    )
    to_warehouse = models.ForeignKey(
        "core.Warehouse",
        on_delete=models.PROTECT,
        related_name="transfers_in",
    )
    status = models.CharField(
        max_length=20,
        choices=MaterialTransferStatus.choices,
        default=MaterialTransferStatus.PENDING,
    )
    confirmed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="confirmed_transfers",
    )
    confirmed_at = models.DateTimeField(null=True, blank=True)
    deviation_notes = models.TextField(
        blank=True, null=True,
        help_text="Notas del operario si la cantidad difiere de lo solicitado.",
    )
    inventory_move = models.ForeignKey(
        "inventory.InventoryMove",
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="material_transfers",
    )

    class Meta:
        verbose_name = "Transferencia de material"
        verbose_name_plural = "Transferencias de material"
        unique_together = ("order", "lot")

    def __str__(self):
        return f"TRF {self.order.code} – {self.component.code} ({self.get_status_display()})"










