# production/services.py
from __future__ import annotations
from django.db import transaction
from django.core.exceptions import ValidationError
from .models import (
    ProductionOrder,
    ProductionOperation,
    ProductionOrderStatus,
    ProductionOperationStatus,
    ProductRouteStep,ProductionPlan, ProductionPlan
)
from production.models import ProductionPlanRawLot
from django.utils import timezone
from decimal import Decimal
from inventory.models import Lot, LotStatus, MovementTypes, ProductType,Product
from inventory.services import  get_fefo_lots_for_product, register_inventory_move, pick_lots_fefo
from core.models import WarehouseType, Warehouse 
from datetime import date
from quality.models import InspectionStage


def validate_mp_lot_allowed_by_plan(*, plan, mp_lot):
    ok = ProductionPlanRawLot.objects.filter(plan=plan, lot=mp_lot).exists()
    if not ok:
        raise ValidationError(
            f"El lote MP {mp_lot.internal_lot} no está autorizado en el plan {plan.code}. "
            f"Debe ajustarse el plan o crear un plan nuevo."
        )

@transaction.atomic
def close_production_order(*, order: ProductionOrder, user) -> ProductionOrder:
    """
    Cierra la OP:
      - Verifica que todas las operaciones estén DONE
      - Toma quantity_output de la última operación como cantidad producida
      - Actualiza el lote de producto terminado (finished_lot)
      - Registra movimiento IN a bodega de FG
      - Cambia estado de la OP a DONE
    """

    # Solo permitimos cerrar si está RELEASED o IN_PROGRESS
    if order.status not in ("RELEASED", "IN_PROGRESS"):
        raise ValidationError("Solo se pueden cerrar órdenes liberadas o en proceso.")

    ops = order.operations.all()
    if not ops.exists():
        raise ValidationError("La orden no tiene operaciones generadas.")

    # Todas las operaciones deben estar DONE
    if ops.exclude(status=ProductionOperationStatus.DONE).exists():
        raise ValidationError("Aún hay operaciones pendientes o en proceso.")

    # Tomar la última operación para cantidad producida
    last_op: ProductionOperation = (
        ops.order_by("-sequence", "-id").first()
    )

    qty_output = last_op.quantity_output
    if qty_output is None or qty_output <= 0:
        raise ValidationError(
            "La última operación no tiene cantidad de salida (quantity_output) válida."
        )

    # Asegurar que la OP tenga lote de FG
    from .services import ensure_finished_lot_for_order  # evita import circular
    lot_fg = ensure_finished_lot_for_order(order=order, user=user)

    # Bodega de FG por defecto
    fg_wh = get_default_fg_warehouse()
    if fg_wh is None and lot_fg.warehouse is None:
        raise ValidationError(
            "No hay bodega de producto terminado configurada y el lote no tiene bodega."
        )

    # Si el lote no tiene bodega, le ponemos la de FG
    if lot_fg.warehouse is None:
        lot_fg.warehouse = fg_wh

    # Actualizar cantidades del lote (por ahora PENDING, ya QA FG lo cambiará)
    lot_fg.quantity_initial = qty_output
    lot_fg.quantity_current = qty_output
    lot_fg.updated_by = user
    lot_fg.save(
        update_fields=[
            "quantity_initial",
            "quantity_current",
            "warehouse",
            "updated_by",
            "updated_at",
        ]
    )

    # Movimiento de entrada a stock de FG
    register_inventory_move(
        user=user,
        product=order.product,
        movement_type=MovementTypes.IN,
        quantity=qty_output,
        unit_cost=None,  # más adelante puedes calcular costo estándar o real
        reference=order.code,
        warehouse=lot_fg.warehouse,
        location=lot_fg.location,
        area="PRODUCCION FG",
        notes=f"Ingreso de producción OP {order.code}",
        lot=lot_fg,
    )

    # Actualizar la OP
    order.quantity_produced = qty_output
    order.status = "DONE"
    order.updated_by = user
    order.save(update_fields=["quantity_produced", "status", "updated_by", "updated_at"])

    return order

def consume_raw_materials_for_operation(
    *,
    operation: ProductionOperation,
    user,
    quantity_fg=None,
):
    """
    Consume materia prima según el BOM de la OP para una operación dada,
    seleccionando lotes por FEFO.

    - Usa el BOM de order.bom.
    - Solo considera componentes MP (y opcionalmente PACK).
    - Calcula: qty_requerida = qty_bom_por_unidad * qty_FG * (1 + scrap_rate%).
    - Selecciona lotes por FEFO vía pick_lots_fefo.
    - Registra movimientos OUT con register_inventory_move.

    MVP: Solo consume en el PRIMER paso de la ruta.
    """
    # Obtener la orden de producción y su BOM
    order: ProductionOrder = operation.order
    bom = order.bom

    if not bom:
        raise ValidationError("La orden de producción no tiene un BOM asociado.")

    # 🔹 Solo consumimos MP en el primer paso de la ruta (MVP)
    first_op = order.operations.order_by("sequence", "id").first()
    if not first_op:
        raise ValidationError("La orden de producción no tiene operaciones generadas.")

    if operation.pk != first_op.pk:
        return []  # No consumimos materia prima si no es el primer paso

    # Cantidad de FG a la que aplicamos el BOM:
    # - Si te pasan quantity_fg → usamos eso (ej: tandas parciales)
    # - Si no, usamos la cantidad planificada de la OP
    if quantity_fg is None:
        quantity_fg = order.quantity_planned

    try:
        qty_fg = Decimal(str(quantity_fg))
    except Exception:
        raise ValidationError("La cantidad de FG a producir no es válida.")

    if qty_fg <= 0:
        raise ValidationError("La cantidad de FG a producir debe ser mayor a cero.")

    consumptions = []  # [(component, lot, qty, move.id), ...]

    # Obtener los lotes de materia prima asociados al plan de producción
    for raw_lot_entry in order.plan.raw_lots.select_related("lot"):
        lot = raw_lot_entry.lot
        component = raw_lot_entry.component

        # Solo consideramos componentes de tipo MP (Raw) y PACK si es necesario
        if component.product_type not in [ProductType.RAW, ProductType.PACK]:
            continue

        # Cantidad base = qty por unidad * cantidad de FG
        required = (raw_lot_entry.quantity_planned or Decimal("0")) * qty_fg

        # Aplicar merma / scrap si existe (scrap_rate en %)
        scrap = raw_lot_entry.scrap_rate or Decimal("0")
        required = required * (Decimal("1") + (scrap / Decimal("100")))

        if required <= 0:
            continue

        # Seleccionar lotes usando FEFO
        lots = pick_lots_fefo(
            product=component,
            quantity=required,
            allowed_lot_ids=[lot.id],  # Solo consumimos los lotes permitidos por el plan
        )

        # Registrar movimientos OUT por cada lote
        for lot, qty_to_use in lots:
            move = register_inventory_move(
                user=user,
                product=component,
                movement_type=MovementTypes.OUT,
                quantity=qty_to_use,
                unit_cost=None,  # Luego puedes calcular el costo si es necesario
                reference=order.code,
                warehouse=lot.warehouse,
                location=lot.location,
                area="CONSUMO PRODUCCION",
                notes=f"Consumo MP para OP {order.code} paso {operation.step.sequence}",
                lot=lot,
            )
            consumptions.append((component, lot, qty_to_use, move.id))

    return consumptions




def get_default_fg_warehouse() -> Warehouse | None:
    """
    Devuelve la bodega de producto terminado por defecto.

    Regla:
    - Primero intenta una bodega marcada como is_default_fg_released=True.
    - Si no hay, toma la primera bodega activa de tipo FINISHED.
    """
    qs = Warehouse.objects.filter(
        is_active=True,
        type=WarehouseType.FINISHED,
    )

    # Primero intentamos con la marcada como default para FG liberado
    wh = qs.filter(is_default_fg_released=True).first()
    if wh:
        return wh

    # Si no hay ninguna marcada, usamos la primera que cumpla el tipo
    return qs.first()


@transaction.atomic
def ensure_finished_lot_for_order(*, order: ProductionOrder, user) -> Lot:
    """
    Asegura que la OP tenga un lote de producto terminado (finished_lot).
    """
    if order.finished_lot:
        return order.finished_lot

    # Usa SIEMPRE el lote del plan → garantiza trazabilidad
    lot_code = generate_fg_lot_code(
        product=order.product,
        plan=order.plan,
    )

    fg_lot = Lot.objects.create(
        product=order.product,
        internal_lot=lot_code,
        manufacturing_date=order.plan.manufacturing_date or timezone.localdate(),
        status=LotStatus.PENDING,  # pendiente de QA FG
        quantity_initial=Decimal("0"),
        quantity_current=Decimal("0"),
        created_by=user,
        updated_by=user,
    )

    order.finished_lot = fg_lot
    order.updated_by = user
    order.save(update_fields=["finished_lot", "updated_by", "updated_at"])

    return fg_lot


@transaction.atomic
def consume_bom_materials_for_order(
    *,
    order: ProductionOrder,
    user,
) -> None:
    """
    Consume materia prima para la OP según su BOM, usando FEFO.

    Reglas:
      - Usa order.bom (debe estar seteado)
      - Calcula cantidad requerida por componente:
          qty = quantity_planned * quantity * (1 + scrap_rate/100)
      - Elige lotes APPROVED por FEFO y hace movimientos OUT
      - Deja trazabilidad por:
          - InventoryMove.reference = order.code
          - lot en cada movimiento
    """

    if not order.bom:
        raise ValidationError("La orden no tiene un BOM asociado.")

    if order.quantity_planned is None or order.quantity_planned <= 0:
        raise ValidationError("La cantidad planificada de la OP no es válida.")

    # Por si no quieres duplicar consumo, podrías validar aquí si ya hay
    # movimientos OUT con referencia = order.code.
    # Ejemplo (si luego lo quieres):
    # from inventory.models import InventoryMove
    # if InventoryMove.objects.filter(reference=order.code, movement_type=MovementTypes.OUT).exists():
    #     raise ValidationError("La OP ya tiene consumo de materia prima registrado.")

    qty_planned = Decimal(order.quantity_planned)

    for line in order.bom.lines.all():
        component = line.component
        qty_per_unit = Decimal(line.quantity)
        scrap_rate = Decimal(line.scrap_rate or 0)  # porcentaje

        # Cantidad teórica base
        base_required = qty_planned * qty_per_unit

        # Ajuste por scrap (ej: 5% → 1.05)
        factor = Decimal("1") + (scrap_rate / Decimal("100"))
        required_qty = (base_required * factor).quantize(Decimal("0.0001"))

        if required_qty <= 0:
            continue

        # Obtener lotes por FEFO
        fefo_lots = get_fefo_lots_for_product(
            product=component,
            required_qty=required_qty,
        )

        # Registrar movimientos OUT por cada lote
        for lot, qty in fefo_lots:
            register_inventory_move(
                user=user,
                product=component,
                movement_type=MovementTypes.OUT,
                quantity=qty,
                unit_cost=None,  # luego puedes calcular costo promedio/FIFO, etc.
                reference=order.code,
                warehouse=lot.warehouse,
                location=lot.location,
                area="CONSUMO PRODUCCION",
                notes=f"Consumo MP para OP {order.code}",
                lot=lot,
            )



def generate_production_lot_code(product: Product, manufacturing_date: date) -> str:
    """
    Genera el código de lote de producción para un producto terminado.
    Ejemplo típico: CAP012026 (prefijo CAP + MMYYYY)
    """
    prefix = product.lot_prefix or product.code  # fallback al código si no hay prefijo
    if not manufacturing_date:
        return prefix

    month = f"{manufacturing_date.month:02d}"
    year = manufacturing_date.year

    # Por ahora implementamos patrón: PREFIJO + MMYYYY
    # CAP + 01 + 2026 → CAP012026
    # Si más adelante quieres 00101012026, añadimos otro patrón aquí.
    if getattr(product, "use_month_year_in_lot", True):
        return f"{prefix}{month}{year}"
    return prefix


def generate_production_plan_code(manufacturing_date=None) -> str:
    """
    Genera un código único para el plan de producción, tipo:
    PP-2026-0001, PP-2026-0002, etc.
    """
    if manufacturing_date is None:
        manufacturing_date = timezone.localdate()

    year = manufacturing_date.year
    prefix = f"PP-{year}-"

    last = (
        ProductionPlan.objects
        .filter(code__startswith=prefix)
        .order_by("-code")
        .first()
    )

    last_seq = 0
    if last and last.code:
        try:
            last_seq = int(last.code.split("-")[-1])
        except (ValueError, IndexError):
            last_seq = 0

    return f"{prefix}{(last_seq + 1):04d}"

def generate_fg_lot_code(*, product: Product, plan: ProductionPlan | None) -> str:
    """
    Genera el código de lote para producto terminado (FG).

    REGLA DE NEGOCIO:
    - Debe venir SIEMPRE del plan de producción.
    - Si no hay plan o no tiene lot_code, disparamos ValidationError.

    Esto garantiza trazabilidad: mismo lote en plan, OP, QA e inventario.
    """
    if plan is None:
        raise ValidationError(
            "La orden de producción no tiene un plan asociado; no se puede generar lote de FG "
            "sin plan de producción."
        )

    if not plan.lot_code:
        raise ValidationError(
            f"El plan de producción {plan.code} no tiene definido un código de lote."
        )

    return plan.lot_code




####################
##Funcion para ermitiar unicamente MP contenida en el Plan de produccion

def get_fefo_lots_within_allowed(
    *,
    product: Product,
    required_qty: Decimal,
    allowed_lot_ids: list[int],  # Solo permite MP lotes que ya están aprobados para este plan
) -> list[tuple[Lot, Decimal]]:
    required_qty = _to_decimal(required_qty)
    
    # Filtramos solo los lotes permitidos por el plan y que tienen cantidad disponible
    qs = (
        Lot.objects
        .filter(
            id__in=allowed_lot_ids,  # solo permite estos lotes
            product=product,
            status=LotStatus.APPROVED,
            quantity_current__gt=0,
        )
        .order_by("expiry_date", "created_at", "id")  # FEFO: primero los lotes más cercanos a expirar
    )

    remaining = required_qty
    result: list[tuple[Lot, Decimal]] = []

    for lot in qs:
        if remaining <= 0:
            break

        available = lot.quantity_current
        if available <= 0:
            continue

        consume = available if available <= remaining else remaining
        result.append((lot, consume))
        remaining -= consume

    if remaining > 0:
        raise ValidationError(
            f"No hay stock suficiente de {product.code}. "
            f"Requerido: {required_qty}, disponible: {required_qty - remaining}."
        )

    return result



def validate_mp_lot_allowed_by_plan(*, plan, mp_lot):
    # Validamos que el lote MP esté autorizado en el plan
    ok = ProductionPlanRawLot.objects.filter(plan=plan, lot=mp_lot).exists()
    if not ok:
        raise ValidationError(
            f"El lote MP {mp_lot.internal_lot} no está autorizado en el plan {plan.code}. "
            f"Debe ajustarse el plan o crear un plan nuevo."
        )
    


####################################################3
### Revisión de calidad de FG
##################################################
@transaction.atomic
def release_lot_by_qa(
    *,
    user,
    lot: Lot,
    result: str,
    checklist: dict | None = None,
    notes: str | None = None,
    stage: str = InspectionStage.FG,
) -> QualityInspection:
    """
    Registra/actualiza la inspección QA, cambia estado del lote y lo mueve a bodega destino.
    result permitido: APPROVED / REJECTED / QUARANTINE
    """
    if result not in (LotStatus.APPROVED, LotStatus.REJECTED, LotStatus.QUARANTINE):
        raise ValidationError("Resultado de QA inválido para liberación de lote.")

    # Crear o actualizar la inspección de QA
    inspection, created = QualityInspection.objects.get_or_create(
        lot=lot,
        stage=stage,
        defaults={
            "inspected_at": timezone.now(),
            "inspected_by": user,
            "checklist": checklist,
            "result": result,
            "notes": notes,
            "created_by": user,
            "updated_by": user,
        },
    )

    # Actualizamos la inspección si no es nueva
    if not created:
        inspection.inspected_at = timezone.now()
        inspection.inspected_by = user
        inspection.result = result
        if checklist is not None:
            inspection.checklist = checklist
        if notes is not None:
            inspection.notes = notes
        inspection.updated_by = user
        inspection.save()

    # Cambiar estado del lote
    lot.status = result
    lot.updated_by = user
    lot.save(update_fields=["status", "updated_by"])

    # Resolver la bodega destino y mover el lote
    to_wh, to_loc = _resolve_destination_for_qa(lot=lot, result=result, stage=stage)

    # Registrar movimiento del lote
    InventoryMove.objects.create(
        product=lot.product,
        lot=lot,
        movement_type=MovementTypes.TRANSFER,
        quantity=lot.quantity_current,
        reference=f"QA-{result}-{stage}",
        warehouse=to_wh,
        location=to_loc,
        area="QA_RELEASE",
        notes=notes,
        created_by=user,
        updated_by=user,
    )

    # Actualizar ubicación del lote
    lot.warehouse = to_wh
    lot.location = to_loc
    lot.save(update_fields=["warehouse", "location", "updated_by"])

    return inspection
