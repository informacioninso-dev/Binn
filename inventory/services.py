# inventory/services.py
from __future__ import annotations
from decimal import Decimal
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from django.db.models import Sum
from core.models import WarehouseType, Warehouse, Location
from quality.models import QualityInspection, InspectionStage
from procurement.models import RawMaterialReception

from .models import (
    Product,
    Stock,
    InventoryMove,
    Lot,
    LotBalance,
    LotStatus,
    MovementTypes,
)

# ---------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------

def _to_decimal(value) -> Decimal:
    if value is None or value == "":
        return Decimal("0")
    return Decimal(str(value))


def _get_or_create_default_location(warehouse: Warehouse, user=None) -> Location:
    """
    Obtiene o crea una ubicación por defecto en una bodega.
    """
    location = Location.objects.filter(
        warehouse=warehouse,
        is_active=True
    ).order_by('code').first()
    
    if not location:
        location = Location.objects.create(
            warehouse=warehouse,
            code=f'{warehouse.code}-DEFAULT',
            name='Ubicación por defecto',
            is_active=True,
            created_by=user
        )
    
    return location


def _update_lot_balance(
    *,
    lot: Lot,
    warehouse: Warehouse,
    location: Location,
    qty_delta: Decimal,
    user=None
):
    """
    Actualiza o crea LotBalance para un lote en una ubicación específica.
    qty_delta puede ser positivo (agregar) o negativo (quitar).
    """
    balance, created = LotBalance.objects.get_or_create(
        lot=lot,
        warehouse=warehouse,
        location=location,
        defaults={
            'qty': Decimal('0'),
            'created_by': user,
            'updated_by': user
        }
    )
    
    new_qty = balance.qty + qty_delta
    
    if new_qty < 0:
        raise ValidationError(
            f"La operación dejaría el balance del lote {lot.lot_number} "
            f"en {location.code} con cantidad negativa."
        )
    
    balance.qty = new_qty
    balance.updated_by = user
    balance.save(update_fields=['qty', 'updated_by', 'updated_at'])
    
    return balance


# ---------------------------------------------------------------------
# Generador de lote interno
# ---------------------------------------------------------------------
def generate_internal_lot(product: Product) -> str:
    """
    Genera un lote interno simple basado en el código del producto.
    Ej: MP-001-LOT-0005
    """
    count = Lot.objects.filter(product=product).count() + 1
    return f"{product.code}-LOT-{count:04d}"


def generate_reception_code(reception_date=None) -> str:
    """
    Genera un código tipo: REC-2026-0001, REC-2026-0002...
    Reinicia por año.
    """
    if reception_date is None:
        reception_date = timezone.localdate()

    year = reception_date.year
    prefix = f"REC-{year}-"

    last = (
        RawMaterialReception.objects
        .filter(code__startswith=prefix)
        .order_by("-code")
        .first()
    )

    last_seq = 0
    if last:
        try:
            last_seq = int(last.code.split("-")[-1])
        except (ValueError, IndexError):
            last_seq = 0

    return f"{prefix}{(last_seq + 1):04d}"


def get_default_quarantine_warehouse() -> Warehouse:
    """
    Devuelve la bodega de cuarentena por defecto.
    """
    wh = Warehouse.objects.filter(
        is_active=True,
        is_default_quarantine=True,
        type=WarehouseType.QUARANTINE,
    ).first()

    if not wh:
        raise ValidationError(
            "No existe una bodega de Cuarentena configurada como predeterminada."
        )
    return wh


# ---------------------------------------------------------------------
# Movimientos / Stock / Lotes
# ---------------------------------------------------------------------

@transaction.atomic
def register_inventory_move(
    *,
    user,
    product: Product,
    movement_type: str,
    quantity,
    unit_cost=None,
    reference: str | None = None,
    area: str | None = None,
    notes: str | None = None,
    lot: Lot | None = None,
    lot_number: str | None = None,
    allow_pending_lot: bool = False,
    warehouse: Warehouse | None = None,
    location: Location | None = None,
    unit_displayed=None,
    quantity_displayed=None,
) -> InventoryMove:
    """
    Registra un movimiento y actualiza:
    - Stock total del producto
    - LotBalance del lote (si aplica)

    Reglas:
    - OUT con lote: lote debe estar APPROVED (salvo allow_pending_lot=True)
    - IN sin lote: si pasa lot_number, busca/crea lote (PENDING)
    """
    quantity = _to_decimal(quantity)
    if quantity <= 0:
        raise ValidationError("La cantidad debe ser mayor a cero.")

    # Lock stock para evitar carrera
    stock, _ = Stock.objects.select_for_update().get_or_create(
        product=product,
        defaults={"quantity": Decimal("0")},
    )

    # Validación lote para salidas
    if lot is not None:
        if (
            movement_type == MovementTypes.OUT
            and lot.status != LotStatus.APPROVED
            and not allow_pending_lot
        ):
            raise ValidationError("El lote no está aprobado por Control de Calidad.")

    # Si no se pasa lote, en IN intentamos resolver/crear
    if lot is None and movement_type == MovementTypes.IN:
        if not lot_number:
            lot_number = generate_internal_lot(product)

        # Buscar lote existente por número
        lot = Lot.objects.filter(product=product, lot_number=lot_number).first()

        if lot is None:
            # ⭐ Crear lote SIN quantity_current
            lot = Lot.objects.create(
                product=product,
                lot_number=lot_number,
                quantity_initial=quantity,
                # quantity_current es property calculada
                status=LotStatus.PENDING,
                origin_reference=reference,
                warehouse=warehouse,
                location=location,
                created_by=user,
                updated_by=user,
            )
            
            # ⭐ Crear LotBalance inicial
            if not location:
                location = _get_or_create_default_location(warehouse, user)
            
            LotBalance.objects.create(
                lot=lot,
                warehouse=warehouse,
                location=location,
                qty=quantity,
                created_by=user,
                updated_by=user
            )

    sign = -1 if movement_type == MovementTypes.OUT else 1

    # Stock total
    new_total = stock.quantity + (sign * quantity)
    if new_total < 0:
        raise ValidationError("El movimiento dejaría el stock TOTAL en negativo.")

    # ⭐ Stock del lote via LotBalance
    if lot is not None:
        if not warehouse:
            warehouse = lot.warehouse
        if not location:
            location = lot.location or _get_or_create_default_location(warehouse, user)
        
        # Actualizar balance
        qty_delta = sign * quantity
        _update_lot_balance(
            lot=lot,
            warehouse=warehouse,
            location=location,
            qty_delta=qty_delta,
            user=user
        )

    # Crear movimiento
    move = InventoryMove.objects.create(
        product=product,
        lot=lot,
        movement_type=movement_type,
        quantity=quantity,
        unit_displayed=unit_displayed,
        quantity_displayed=quantity_displayed,
        unit_cost=unit_cost,
        reference=reference,
        warehouse=warehouse,
        location=location,
        area=area,
        notes=notes,
        created_by=user,
        updated_by=user,
    )

    # Actualizar stock total
    stock.quantity = new_total
    stock.updated_by = user
    stock.save(update_fields=["quantity", "updated_by", "updated_at"])

    # Actualizar ubicación del lote si es necesario
    if lot is not None:
        if warehouse is not None:
            lot.warehouse = warehouse
        if location is not None:
            lot.location = location
        lot.updated_by = user
        lot.save(update_fields=["warehouse", "location", "updated_by", "updated_at"])

    return move


# ---------------------------------------------------------------------
# QA / Liberación de Lote
# ---------------------------------------------------------------------

def _get_default_warehouse_by_type(wh_type: str) -> Warehouse:
    wh = Warehouse.objects.filter(type=wh_type, is_active=True).first()
    if not wh:
        raise ValidationError(f"No existe una bodega activa para tipo: {wh_type}")
    return wh


def _get_default_location_in_warehouse(wh: Warehouse) -> Location | None:
    """Obtiene la primera ubicación activa en la bodega."""
    return Location.objects.filter(warehouse=wh, is_active=True).order_by("code").first()


def _resolve_destination_for_qa(
    *, lot: Lot, result: str, stage: str
) -> tuple[Warehouse, Location | None]:
    """Decide la bodega destino según resultado QA y etapa."""
    if result == LotStatus.QUARANTINE or result == LotStatus.PENDING:
        wh = _get_default_warehouse_by_type(WarehouseType.QUARANTINE)
        return wh, _get_default_location_in_warehouse(wh)

    if result == LotStatus.REJECTED:
        wh = _get_default_warehouse_by_type(WarehouseType.SCRAP)
        return wh, _get_default_location_in_warehouse(wh)

    if result == LotStatus.APPROVED:
        if stage == InspectionStage.RAW:
            wh = _get_default_warehouse_by_type(WarehouseType.RAW)
            return wh, _get_default_location_in_warehouse(wh)

        if stage == InspectionStage.WIP:
            wh = _get_default_warehouse_by_type(WarehouseType.WIP)
            return wh, _get_default_location_in_warehouse(wh)

        if stage == InspectionStage.FG:
            wh = Warehouse.objects.filter(
                is_default_fg_released=True, is_active=True
            ).first()
            if not wh:
                wh = _get_default_warehouse_by_type(WarehouseType.FINISHED)
            return wh, _get_default_location_in_warehouse(wh)

    raise ValidationError("No se pudo resolver bodega destino para QA.")


@transaction.atomic
def release_lot_by_qa(
    *,
    user,
    lot: Lot,
    result: str,
    checklist: dict | None = None,
    notes: str | None = None,
    stage: str = InspectionStage.RAW,
    destination_location: Location | None = None,
) -> QualityInspection:
    """
    Registra/actualiza inspección QA, cambia estado del lote y lo mueve a bodega destino.
    """
    if result not in (LotStatus.APPROVED, LotStatus.REJECTED, LotStatus.QUARANTINE):
        raise ValidationError("Resultado de QA inválido para liberación de lote.")

    # 1) Inspección QA
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

    if not created:
        inspection.inspected_at = timezone.now()
        inspection.inspected_by = user
        inspection.result = result
        if checklist is not None:
            inspection.checklist = checklist
        if notes is not None:
            inspection.notes = notes
        inspection.updated_by = user
        inspection.save(
            update_fields=[
                "inspected_at",
                "inspected_by",
                "result",
                "checklist",
                "notes",
                "updated_by",
                "updated_at",
            ]
        )

    # 2) Cambiar estado del lote
    lot.status = result
    lot.updated_by = user
    lot.save(update_fields=["status", "updated_by", "updated_at"])

    # 3) Resolver bodega destino
    to_wh, to_loc = _resolve_destination_for_qa(lot=lot, result=result, stage=stage)

    # Si el usuario eligió una ubicación destino específica (al aprobar), usarla
    if destination_location and result == LotStatus.APPROVED:
        to_loc = destination_location

    # ⭐ Obtener quantity_current (es property ahora)
    qty = lot.quantity_current

    # 4) Registrar movimiento
    InventoryMove.objects.create(
        product=lot.product,
        lot=lot,
        movement_type=MovementTypes.TRANSFER,
        quantity=qty,
        reference=f"Liberación QA - Lote {lot.lot_number}",
        warehouse=to_wh,
        location=to_loc,
        area="Liberación QA",
        notes=notes,
        created_by=user,
        updated_by=user,
    )

    # 5) Mover LotBalance de ubicación anterior a nueva
    if lot.warehouse and lot.location:
        # Restar de ubicación anterior
        _update_lot_balance(
            lot=lot,
            warehouse=lot.warehouse,
            location=lot.location,
            qty_delta=-qty,
            user=user
        )
    
    # Sumar a nueva ubicación
    if not to_loc:
        to_loc = _get_or_create_default_location(to_wh, user)
    
    _update_lot_balance(
        lot=lot,
        warehouse=to_wh,
        location=to_loc,
        qty_delta=qty,
        user=user
    )

    # 6) Actualizar ubicación del lote
    lot.warehouse = to_wh
    lot.location = to_loc
    lot.save(update_fields=["warehouse", "location", "updated_by", "updated_at"])

    # 7) Actualizar Stock SOLO si el lote fue APROBADO
    #    El stock no se toca en recepción (cuarentena) ni en rechazo
    if result == LotStatus.APPROVED:
        stock, _ = Stock.objects.select_for_update().get_or_create(
            product=lot.product,
            defaults={"quantity": Decimal("0")},
        )
        stock.quantity += qty
        stock.updated_by = user
        stock.save(update_fields=["quantity", "updated_by", "updated_at"])

    return inspection


# ---------------------------------------------------------------------
# Transferencias
# ---------------------------------------------------------------------

@transaction.atomic
def transfer_lot(
    *,
    user,
    lot: Lot,
    new_warehouse: Warehouse,
    new_location: Location | None = None,
    notes: str | None = None,
) -> InventoryMove:
    """
    Transfiere un lote a otra bodega.
    Mueve el LotBalance de una ubicación a otra.
    """
    if lot.status != LotStatus.APPROVED:
        raise ValidationError("El lote debe estar aprobado para ser transferido.")

    if new_warehouse.type == WarehouseType.QUARANTINE:
        raise ValidationError(
            "No se puede transferir el lote a una bodega de cuarentena."
        )

    # ⭐ Cantidad actual (property)
    qty = lot.quantity_current

    # Crear movimiento
    move = InventoryMove.objects.create(
        product=lot.product,
        lot=lot,
        movement_type=MovementTypes.TRANSFER,
        quantity=qty,
        unit_cost=None,
        reference=f"Transferencia {lot.lot_number}",
        warehouse=new_warehouse,
        location=new_location,
        area="TRANSFERENCIA",
        notes=notes,
        created_by=user,
        updated_by=user,
    )

    # ⭐ Mover LotBalance
    if lot.warehouse and lot.location:
        _update_lot_balance(
            lot=lot,
            warehouse=lot.warehouse,
            location=lot.location,
            qty_delta=-qty,
            user=user
        )
    
    if not new_location:
        new_location = _get_or_create_default_location(new_warehouse, user)
    
    _update_lot_balance(
        lot=lot,
        warehouse=new_warehouse,
        location=new_location,
        qty_delta=qty,
        user=user
    )

    # Actualizar lote
    lot.warehouse = new_warehouse
    lot.location = new_location
    lot.updated_by = user
    lot.save(update_fields=["warehouse", "location", "updated_by", "updated_at"])

    return move


# ---------------------------------------------------------------------
# FEFO / FIFO
# ---------------------------------------------------------------------

def pick_lots_fefo(
    *, product: Product, quantity, warehouse: Warehouse | None = None
):
    """
    Selecciona lotes para consumir siguiendo FEFO/FIFO.
    Ahora usa quantity_current como property.
    """
    qty_needed = _to_decimal(quantity)
    if qty_needed <= 0:
        raise ValidationError("La cantidad a consumir debe ser mayor a cero.")

    # ⭐ No podemos filtrar por quantity_current__gt=0 ya que es property
    # Debemos obtener todos los lotes y filtrar en Python
    qs = Lot.objects.filter(
        product=product,
        status=LotStatus.APPROVED,
    )

    if warehouse is not None:
        qs = qs.filter(warehouse=warehouse)

    qs = qs.order_by("created_at", "id")

    remaining = qty_needed
    picked = []

    for lot in qs:
        if remaining <= 0:
            break

        available = lot.quantity_current  # ⭐ Property
        if available <= 0:
            continue

        take = available if available <= remaining else remaining
        picked.append((lot, take))
        remaining -= take

    if remaining > 0:
        raise ValidationError(
            f"No hay stock suficiente de {product.code} para consumir {qty_needed} "
            f"(faltan {remaining})."
        )

    return picked


def get_fefo_lots_for_product(
    *,
    product: Product,
    required_qty: Decimal,
) -> list[tuple[Lot, Decimal]]:
    """
    Devuelve lista de (lote, cantidad_a_consumir) siguiendo FEFO.
    """
    required_qty = _to_decimal(required_qty)
    if required_qty <= 0:
        raise ValidationError("La cantidad requerida debe ser mayor a cero.")

    qs = Lot.objects.filter(
        product=product,
        status=LotStatus.APPROVED,
    ).order_by("expiry_date", "created_at", "id")

    remaining = required_qty
    result: list[tuple[Lot, Decimal]] = []

    for lot in qs:
        if remaining <= 0:
            break

        available = lot.quantity_current  # ⭐ Property
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


def get_default_fg_released_warehouse() -> Warehouse:
    wh = Warehouse.objects.filter(
        is_active=True,
        type=WarehouseType.FINISHED,
        is_default_fg_released=True,
    ).first()
    if not wh:
        raise ValidationError(
            "No existe una bodega de Producto Terminado Liberado configurada."
        )
    return wh


# ---------------------------------------------------------------------
# ISO 13485 - Validaciones
# ---------------------------------------------------------------------

def inv_lot_validate_destination(*, lot: Lot, to_warehouse: Warehouse) -> None:
    """Reglas de validación para movimientos de lotes."""
    if lot.status in (LotStatus.PENDING, LotStatus.QUARANTINE):
        if to_warehouse.type != WarehouseType.QUARANTINE:
            raise ValidationError(
                "Lote PENDING/QUARANTINE solo puede estar en bodega QUARANTINE."
            )

    if lot.status == LotStatus.APPROVED:
        if lot.product.product_type == "FG":
            if to_warehouse.type not in (WarehouseType.FINISHED, WarehouseType.STAGING):
                raise ValidationError(
                    "Lote FG APPROVED solo puede estar en FINISHED (o STAGING)."
                )

    if lot.status == LotStatus.REJECTED:
        if to_warehouse.type not in (
            WarehouseType.SCRAP,
            WarehouseType.RECALL,
            WarehouseType.RETURNS,
        ):
            raise ValidationError(
                "Lote REJECTED debe ir a SCRAP/RECALL/RETURNS según disposición final."
            )


@transaction.atomic
def inv_lot_move(
    *,
    lot_id: int,
    qty: Decimal,
    movement_type: str,
    to_warehouse_id: int | None = None,
    to_location_id: int | None = None,
    reference: str | None = None,
    notes: str | None = None,
    user=None,
) -> int:
    """Mueve un lote de forma controlada."""
    lot = Lot.objects.select_for_update().select_related(
        "warehouse", "location", "product"
    ).get(id=lot_id)

    to_wh = Warehouse.objects.get(id=to_warehouse_id) if to_warehouse_id else lot.warehouse
    to_loc = Location.objects.get(id=to_location_id) if to_location_id else lot.location

    if to_wh is None:
        raise ValidationError("El lote debe tener bodega destino.")

    inv_lot_validate_destination(lot=lot, to_warehouse=to_wh)

    InventoryMove.objects.create(
        product=lot.product,
        lot=lot,
        movement_type=movement_type,
        quantity=qty,
        reference=reference,
        warehouse=to_wh,
        location=to_loc,
        area="LOT_FLOW",
        notes=notes,
        created_by=user,
        updated_by=user,
    )

    lot.warehouse = to_wh
    lot.location = to_loc
    lot.save(update_fields=["warehouse", "location"])

    return lot.id


def inv_get_or_create_location(
    *, warehouse: Warehouse, code: str, name: str = "", description: str = ""
) -> Location:
    loc, _ = Location.objects.get_or_create(
        warehouse=warehouse,
        code=code,
        defaults={"name": name or code, "description": description},
    )
    return loc


def validate_lot_warehouse(lot: Lot, to_warehouse: Warehouse) -> None:
    """Alias para inv_lot_validate_destination."""
    inv_lot_validate_destination(lot=lot, to_warehouse=to_warehouse)


@transaction.atomic
def move_lot(
    *,
    lot_id: int,
    qty: Decimal,
    to_warehouse_id: int,
    to_location_id: int | None,
    movement_type: str,
    reference: str | None = None,
    notes: str | None = None,
    user=None,
):
    """Alias para inv_lot_move."""
    return inv_lot_move(
        lot_id=lot_id,
        qty=qty,
        movement_type=movement_type,
        to_warehouse_id=to_warehouse_id,
        to_location_id=to_location_id,
        reference=reference,
        notes=notes,
        user=user,
    )


def check_stock(
    product: Product, quantity_required: Decimal, warehouse: Warehouse | None = None
) -> bool:
    """Verifica si hay suficiente stock disponible."""
    if quantity_required <= 0:
        raise ValidationError("La cantidad requerida debe ser mayor que cero.")

    stock = Stock.objects.filter(product=product)

    if warehouse:
        stock = stock.filter(warehouse=warehouse)

    total_available = stock.aggregate(total=Sum("quantity"))["total"] or Decimal("0")

    return total_available >= quantity_required