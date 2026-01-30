# production/services.py
from __future__ import annotations
from django.db import models as db_models, transaction
from django.core.exceptions import ValidationError
from .models import (
    ProductionOrder,
    ProductionOperation,
    ProductionOrderStatus,
    ProductionOperationStatus,
    ProductRouteStep,
    ProductionPlan,
    OperationStatusLog,
)
from production.models import ProductionPlanRawLot
from django.utils import timezone
from decimal import Decimal
from inventory.models import Lot, LotStatus, LotBalance, MovementTypes, ProductType, Product
from inventory.services import get_fefo_lots_for_product, register_inventory_move, pick_lots_fefo, _get_or_create_default_location
from core.models import WarehouseType, Warehouse
from datetime import date, datetime, timedelta
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

    # Idempotencia: si ya está cerrada, no hacer nada
    if order.status == ProductionOrderStatus.DONE:
        return order

    # Solo permitimos cerrar si está RELEASED o IN_PROGRESS
    if order.status not in (ProductionOrderStatus.RELEASED, ProductionOrderStatus.IN_PROGRESS):
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
    order.status = ProductionOrderStatus.DONE
    order.end_date = timezone.localdate()
    order.updated_by = user
    order.save(update_fields=["quantity_produced", "status", "end_date", "updated_by", "updated_at"])

    # --- Reconciliación de merma real vs estimada ---
    scrap_report = reconcile_scrap(order=order, qty_produced=qty_output)

    # Log de auditoría
    log_operation_status_change(
        operation=last_op,
        from_status=ProductionOperationStatus.DONE,
        to_status=ProductionOperationStatus.DONE,
        user=user,
        notes=f"OP cerrada. Producido: {qty_output}. {scrap_report}",
    )

    return order


def reconcile_scrap(*, order: ProductionOrder, qty_produced: Decimal) -> str:
    """
    Compara merma estimada vs real al cerrar la OP.
    Retorna un string descriptivo para el log de auditoría.

    Merma estimada = quantity_planned - quantity_planned (ya es 0% si no hay scrap)
    Merma real = quantity_planned - qty_produced

    También compara por componente MP: consumo teórico vs consumo real
    (basado en movimientos OUT registrados).
    """
    from inventory.models import InventoryMove

    qty_planned = order.quantity_planned or Decimal("0")
    scrap_fg = qty_planned - qty_produced
    scrap_pct = (scrap_fg / qty_planned * 100).quantize(Decimal("0.01")) if qty_planned > 0 else Decimal("0")

    lines = [f"Merma FG: {scrap_fg} unidades ({scrap_pct}%)"]

    # Merma por componente MP
    if order.bom:
        for bom_line in order.bom.lines.select_related("component"):
            component = bom_line.component
            qty_per_unit = Decimal(bom_line.quantity)
            scrap_rate = Decimal(bom_line.scrap_rate or 0)
            factor = Decimal("1") + (scrap_rate / Decimal("100"))

            # Teórico: lo que debería haberse consumido según BOM * qty_produced
            theoretical = (qty_per_unit * qty_produced * factor).quantize(Decimal("0.0001"))

            # Real: suma de movimientos OUT para este componente en esta OP
            actual = (
                InventoryMove.objects
                .filter(
                    product=component,
                    reference=order.code,
                    movement_type=MovementTypes.OUT,
                )
                .aggregate(total=db_models.Sum("quantity"))["total"]
                or Decimal("0")
            )

            diff = actual - theoretical
            if diff != 0:
                lines.append(
                    f"  {component.code}: teórico={theoretical}, real={actual}, "
                    f"diferencia={diff} ({'+' if diff > 0 else ''}{(diff / theoretical * 100).quantize(Decimal('0.01')) if theoretical > 0 else 0}%)"
                )

    return " | ".join(lines)

def consume_raw_materials_for_operation(
    *,
    operation: ProductionOperation,
    user,
):
    """
    Consume materia prima según las reservas del plan de la OP,
    solo en el PRIMER paso de la ruta.

    - quantity_planned de ProductionPlanRawLot ya incluye:
      bom_qty_per_unit * plan_qty * (1 + scrap_rate)
      por lo que se usa directamente sin recalcular.
    - Registra movimientos OUT con register_inventory_move.
    """
    order: ProductionOrder = operation.order

    # Guard: OP sin plan no tiene reservas de MP
    if not order.plan:
        return []

    # Guard: idempotencia — no consumir dos veces
    if operation.materials_consumed:
        return []

    if not order.bom:
        raise ValidationError("La orden de producción no tiene un BOM asociado.")

    # Solo consumimos MP en el primer paso de la ruta
    first_op = order.operations.order_by("sequence", "id").first()
    if not first_op:
        raise ValidationError("La orden de producción no tiene operaciones generadas.")

    if operation.pk != first_op.pk:
        return []

    consumptions = []

    for raw_lot_entry in order.plan.raw_lots.select_related("lot", "component"):
        lot = raw_lot_entry.lot
        component = raw_lot_entry.component

        if component.product_type not in [ProductType.RAW, ProductType.PACK]:
            continue

        # quantity_planned ya es la cantidad total a consumir (calculada en el plan)
        required = raw_lot_entry.quantity_planned or Decimal("0")

        if required <= 0:
            continue

        # Registrar movimiento OUT directamente con el lote reservado
        move = register_inventory_move(
            user=user,
            product=component,
            movement_type=MovementTypes.OUT,
            quantity=required,
            unit_cost=None,
            reference=order.code,
            warehouse=lot.warehouse,
            location=lot.location,
            area="CONSUMO PRODUCCION",
            notes=f"Consumo MP para OP {order.code} paso {operation.step.sequence}",
            lot=lot,
        )
        consumptions.append((component, lot, required, move.id))

    # Marcar como consumido para evitar doble consumo
    operation.materials_consumed = True
    operation.save(update_fields=["materials_consumed"])

    return consumptions




def log_operation_status_change(
    *,
    operation: ProductionOperation,
    from_status: str | None,
    to_status: str,
    user,
    notes: str | None = None,
) -> OperationStatusLog:
    """
    Registra un cambio de estado en el log de auditoría ISO 13485.
    """
    return OperationStatusLog.objects.create(
        operation=operation,
        from_status=from_status,
        to_status=to_status,
        changed_by=user,
        notes=notes,
    )


@transaction.atomic
def create_wip_lot_for_operation(
    *,
    operation: ProductionOperation,
    user,
) -> Lot:
    """
    Crea un lote WIP (Work In Progress) como output_lot de una operación.
    El lote se asocia a la bodega WIP del centro de trabajo.

    Código de lote WIP: {OP_CODE}-WIP-{sequence}
    """
    order = operation.order

    lot_code = f"{order.code}-WIP-{operation.sequence:02d}"

    # Verificar si ya existe
    existing = Lot.objects.filter(
        product=order.product,
        internal_lot=lot_code,
    ).first()
    if existing:
        return existing

    # Bodega WIP: del centro de trabajo o la primera WIP del sistema
    wip_wh = operation.step.work_center.default_warehouse
    if not wip_wh:
        wip_wh = Warehouse.objects.filter(
            type=WarehouseType.WIP, is_active=True
        ).first()

    wip_lot = Lot.objects.create(
        product=order.product,
        internal_lot=lot_code,
        manufacturing_date=order.start_date or timezone.localdate(),
        status=LotStatus.PENDING,
        quantity_initial=Decimal("0"),
        warehouse=wip_wh,
        origin_reference=order.code,
        created_by=user,
        updated_by=user,
    )

    return wip_lot


@transaction.atomic
def link_wip_lots_on_done(
    *,
    operation: ProductionOperation,
    user,
) -> None:
    """
    Al completar una operación (DONE):
    - Crea/asigna output_lot como WIP del paso actual
    - Asigna input_lot del siguiente paso = output_lot del paso actual
    - Si es el primer paso, input_lot = lotes MP del plan
    - Registra quantity_output en el lote WIP como balance
    """
    order = operation.order

    # Solo crear WIP si hay quantity_output
    if not operation.quantity_output or operation.quantity_output <= 0:
        return

    # Crear lote WIP para esta operación
    wip_lot = create_wip_lot_for_operation(operation=operation, user=user)

    # Asignar como output_lot
    operation.output_lot = wip_lot
    operation.save(update_fields=["output_lot"])

    # Actualizar el balance del lote WIP con la cantidad de salida
    wip_wh = wip_lot.warehouse
    if wip_wh:
        wip_loc = _get_or_create_default_location(wip_wh, user)
        balance, _ = LotBalance.objects.get_or_create(
            lot=wip_lot,
            warehouse=wip_wh,
            location=wip_loc,
            defaults={"qty": Decimal("0"), "created_by": user, "updated_by": user},
        )
        balance.qty = operation.quantity_output
        balance.updated_by = user
        balance.save(update_fields=["qty", "updated_by", "updated_at"])

    # Asignar input_lot al siguiente paso
    next_op = (
        order.operations
        .filter(sequence__gt=operation.sequence)
        .order_by("sequence", "id")
        .first()
    )
    if next_op and not next_op.input_lot:
        next_op.input_lot = wip_lot
        next_op.quantity_input = operation.quantity_output
        next_op.save(update_fields=["input_lot", "quantity_input"])


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
    


##########################################################
# Estimación y planificación de capacidad
##########################################################

def estimate_production_duration(*, route, quantity, start_date=None):
    """
    Calcula la duración estimada de producción para una ruta y cantidad dadas.

    Retorna dict:
      - total_minutes: minutos brutos totales
      - total_days: días calendario estimados
      - estimated_end_date: fecha estimada de fin (date)
      - steps: lista con detalle por paso
    """
    from .models import ProductRouteStep

    if start_date is None:
        start_date = timezone.localdate()

    steps_qs = (
        ProductRouteStep.objects
        .filter(route=route, is_active=True)
        .select_related("work_center")
        .order_by("sequence", "id")
    )

    total_minutes = Decimal("0")
    step_details = []

    for step in steps_qs:
        wc = step.work_center

        # Tiempo de proceso
        if step.expected_duration_min:
            # expected_duration_min = minutos por unidad
            process_min = Decimal(str(step.expected_duration_min)) * quantity
        elif wc.capacity_per_hour and wc.capacity_per_hour > 0:
            # capacity_per_hour = unidades/hora → minutos = qty / cap * 60
            process_min = (quantity / wc.capacity_per_hour) * 60
        else:
            # Sin datos de duración, no podemos estimar este paso
            step_details.append({
                "step_name": step.name,
                "work_center": wc.code,
                "minutes": None,
                "days": None,
                "note": "Sin datos de duración configurados",
            })
            continue

        # Setup: prioridad paso > centro de trabajo
        setup = Decimal(str(step.setup_time_min or wc.setup_time_min or 0))

        gross_min = setup + process_min

        # Ajustar por máquinas paralelas y eficiencia
        machines = Decimal(str(wc.num_machines or 1))
        efficiency = wc.efficiency_factor or Decimal("1")
        effective_min = gross_min / (machines * efficiency)

        # Días calendario
        avail_min_day = wc.available_minutes_per_day
        if avail_min_day and avail_min_day > 0:
            days = effective_min / avail_min_day
        else:
            days = effective_min / Decimal("480")  # fallback 8h

        total_minutes += effective_min
        step_details.append({
            "step_name": step.name,
            "work_center": wc.code,
            "setup_min": float(setup),
            "process_min": float(process_min),
            "effective_min": float(effective_min),
            "days": float(days),
        })

    # Días totales (suma secuencial)
    total_days = sum(s["days"] for s in step_details if s.get("days") is not None)
    import math
    calendar_days = math.ceil(total_days) if total_days else 0
    estimated_end = start_date + timedelta(days=calendar_days)

    return {
        "total_minutes": float(total_minutes),
        "total_days": round(total_days, 2),
        "calendar_days": calendar_days,
        "estimated_end_date": estimated_end,
        "start_date": start_date,
        "steps": step_details,
    }


def schedule_production_order(*, order: ProductionOrder):
    """
    Calcula planned_start / planned_end para cada operación de la OP
    y actualiza order.end_date con la fecha estimada de fin.
    Debe llamarse después de crear las operaciones (al liberar).
    """
    if not order.route:
        return

    ops = list(
        order.operations
        .select_related("step", "step__work_center")
        .order_by("sequence", "id")
    )
    if not ops:
        return

    start_dt = timezone.now()
    if order.start_date:
        start_dt = timezone.make_aware(
            datetime.combine(order.start_date, datetime.min.time())
        ) if timezone.is_naive(
            datetime.combine(order.start_date, datetime.min.time())
        ) else datetime.combine(order.start_date, datetime.min.time())

    cursor = start_dt

    for op in ops:
        step = op.step
        wc = step.work_center

        # Calcular duración de este paso
        if step.expected_duration_min:
            process_min = Decimal(str(step.expected_duration_min)) * order.quantity_planned
        elif wc.capacity_per_hour and wc.capacity_per_hour > 0:
            process_min = (order.quantity_planned / wc.capacity_per_hour) * 60
        else:
            process_min = Decimal("0")

        setup = Decimal(str(step.setup_time_min or wc.setup_time_min or 0))
        gross_min = setup + process_min
        machines = Decimal(str(wc.num_machines or 1))
        efficiency = wc.efficiency_factor or Decimal("1")
        effective_min = gross_min / (machines * efficiency)

        op.planned_start = cursor
        op.planned_end = cursor + timedelta(minutes=float(effective_min))
        op.save(update_fields=["planned_start", "planned_end"])

        cursor = op.planned_end

    # Actualizar end_date de la OP
    order.end_date = cursor.date() if hasattr(cursor, 'date') else cursor
    order.save(update_fields=["end_date", "updated_at"])


def estimate_delivery_for_sale_order(*, sale_order):
    """
    Para cada línea del pedido que requiere producción,
    estima la duración y retorna la fecha más lejana.
    """
    from .models import ProductRoute

    latest_end = None
    line_estimates = []

    for line in sale_order.lines.select_related("product"):
        route = (
            ProductRoute.objects
            .filter(product=line.product, is_active=True)
            .first()
        )
        if not route:
            line_estimates.append({
                "product": line.product.code,
                "quantity": float(line.quantity),
                "note": "Sin ruta de producción configurada",
                "estimated_end_date": None,
            })
            continue

        est = estimate_production_duration(
            route=route,
            quantity=line.quantity,
        )
        line_estimates.append({
            "product": line.product.code,
            "quantity": float(line.quantity),
            "estimated_end_date": est["estimated_end_date"],
            "total_days": est["total_days"],
            "steps": est["steps"],
        })

        if latest_end is None or est["estimated_end_date"] > latest_end:
            latest_end = est["estimated_end_date"]

    return {
        "estimated_delivery_date": latest_end,
        "lines": line_estimates,
    }


def generate_material_transfers(*, order: ProductionOrder, user):
    """
    Al liberar una OP, genera registros MaterialTransfer PENDING
    para cada lote de MP reservado en el plan.
    """
    from .models import MaterialTransfer, MaterialTransferStatus

    if not order.plan:
        return []

    first_step = (
        ProductRouteStep.objects
        .filter(route=order.route, is_active=True)
        .order_by("sequence", "id")
        .select_related("work_center")
        .first()
    )
    if not first_step:
        return []

    to_wh = first_step.work_center.default_warehouse
    if not to_wh:
        to_wh = Warehouse.objects.filter(type=WarehouseType.WIP, is_active=True).first()

    transfers = []
    for entry in order.plan.raw_lots.select_related("lot", "component"):
        qty = entry.quantity_planned or Decimal("0")
        if qty <= 0:
            continue

        from_wh = entry.lot.warehouse
        if not from_wh:
            continue

        tf, created = MaterialTransfer.objects.get_or_create(
            order=order,
            lot=entry.lot,
            defaults={
                "component": entry.component,
                "quantity_requested": qty,
                "from_warehouse": from_wh,
                "to_warehouse": to_wh,
                "status": MaterialTransferStatus.PENDING,
                "created_by": user,
                "updated_by": user,
            },
        )
        if created:
            transfers.append(tf)

    return transfers


@transaction.atomic
def confirm_material_transfer(*, transfer, quantity_confirmed: Decimal, user, notes: str = ""):
    """
    Operario confirma la transferencia de MP.
    Registra movimiento TRANSFER en inventario y actualiza LotBalance.
    """
    from .models import MaterialTransfer, MaterialTransferStatus
    from inventory.models import InventoryMove

    if transfer.status != MaterialTransferStatus.PENDING:
        raise ValidationError("Esta transferencia ya fue procesada.")

    if quantity_confirmed <= 0:
        raise ValidationError("La cantidad confirmada debe ser mayor a cero.")

    lot = transfer.lot
    from_wh = transfer.from_warehouse
    to_wh = transfer.to_warehouse

    from_loc = lot.location
    to_loc = _get_or_create_default_location(to_wh, user)

    # Verificar stock disponible
    if lot.quantity_current < quantity_confirmed:
        raise ValidationError(
            f"Stock insuficiente del lote {lot.internal_lot}. "
            f"Disponible: {lot.quantity_current}, solicitado: {quantity_confirmed}."
        )

    # Crear movimiento TRANSFER
    move = InventoryMove.objects.create(
        product=transfer.component,
        lot=lot,
        movement_type=MovementTypes.TRANSFER,
        quantity=quantity_confirmed,
        reference=transfer.order.code,
        warehouse=to_wh,
        location=to_loc,
        from_warehouse=from_wh,
        from_location=from_loc,
        to_warehouse=to_wh,
        to_location=to_loc,
        area="TRANSFERENCIA PRODUCCION",
        notes=f"Transferencia MP para OP {transfer.order.code}: {transfer.component.code}",
        created_by=user,
        updated_by=user,
    )

    # Mover LotBalance: restar del origen
    if from_wh and from_loc:
        from inventory.services import _update_lot_balance
        _update_lot_balance(lot=lot, warehouse=from_wh, location=from_loc, qty_delta=-quantity_confirmed, user=user)

    # Mover LotBalance: sumar al destino
    from inventory.services import _update_lot_balance
    _update_lot_balance(lot=lot, warehouse=to_wh, location=to_loc, qty_delta=quantity_confirmed, user=user)

    # Determinar estado
    is_deviation = quantity_confirmed != transfer.quantity_requested
    transfer.quantity_confirmed = quantity_confirmed
    transfer.status = MaterialTransferStatus.ADJUSTED if is_deviation else MaterialTransferStatus.CONFIRMED
    transfer.confirmed_by = user
    transfer.confirmed_at = timezone.now()
    transfer.inventory_move = move
    transfer.updated_by = user
    if is_deviation:
        transfer.deviation_notes = notes or f"Desviación: solicitado {transfer.quantity_requested}, confirmado {quantity_confirmed}"
    transfer.save()

    # Log de auditoría
    log_operation_status_change(
        operation=transfer.order.operations.order_by("sequence", "id").first(),
        from_status=None,
        to_status=f"TRF-{transfer.status}",
        user=user,
        notes=f"Transferencia {transfer.component.code}: {quantity_confirmed} (solicitado: {transfer.quantity_requested})"
        + (f" | DESVIACION: {notes}" if is_deviation else ""),
    )

    return transfer


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
        reference=f"Liberación QA - Lote {lot.internal_lot}",
        warehouse=to_wh,
        location=to_loc,
        area="Liberación QA",
        notes=notes,
        created_by=user,
        updated_by=user,
    )

    # Actualizar ubicación del lote
    lot.warehouse = to_wh
    lot.location = to_loc
    lot.save(update_fields=["warehouse", "location", "updated_by"])

    return inspection
