from __future__ import annotations
from decimal import Decimal
from django.db import transaction
from django.core.exceptions import ValidationError

from core.models import WarehouseType, Warehouse, Location
from inventory.models import Lot, LotStatus, InventoryMove, MovementTypes  # ajusta imports


def validate_lot_warehouse(lot: Lot, to_warehouse: Warehouse) -> None:
    # Reglas mínimas
    if lot.status in (LotStatus.PENDING, LotStatus.QUARANTINE):
        if to_warehouse.type != WarehouseType.QUARANTINE:
            raise ValidationError("Lote en PENDING/QUARANTINE solo puede estar en bodega QUARANTINE.")

    if lot.status == LotStatus.APPROVED:
        # FG permitido en FINISHED o STAGING (predespacho)
        if lot.product.product_type == "FG":
            if to_warehouse.type not in (WarehouseType.FINISHED, WarehouseType.STAGING):
                raise ValidationError("Lote FG APPROVED solo puede estar en FINISHED o STAGING.")
        # RAW/PACK/SEMI: define tu política
        # ejemplo simple:
        if lot.product.product_type == "RAW" and to_warehouse.type not in (WarehouseType.RAW, WarehouseType.STAGING):
            raise ValidationError("Lote RAW APPROVED solo puede estar en RAW (o STAGING si aplica).")

    if lot.status == LotStatus.REJECTED:
        if to_warehouse.type not in (WarehouseType.SCRAP, WarehouseType.RECALL, WarehouseType.RETURNS):
            raise ValidationError("Lote REJECTED debe ir a SCRAP/RECALL/RETURNS según disposición.")


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
    lot = Lot.objects.select_for_update().select_related("warehouse", "location", "product").get(id=lot_id)
    to_wh = Warehouse.objects.get(id=to_warehouse_id)
    to_loc = Location.objects.get(id=to_location_id) if to_location_id else None

    validate_lot_warehouse(lot, to_wh)

    # registrar movimiento (con from/to si ya lo agregaste)
    mv = InventoryMove.objects.create(
        product=lot.product,
        lot=lot,
        movement_type=movement_type,
        quantity=qty,
        reference=reference,
        notes=notes,
        area="LOGISTICS",
        # from_warehouse=lot.warehouse, to_warehouse=to_wh,
        # from_location=lot.location, to_location=to_loc,
        created_by=user,
        updated_by=user,
    )

    # actualizar “ubicación actual” del lote (modelo simple, 1 ubicación)
    lot.warehouse = to_wh
    lot.location = to_loc
    lot.save(update_fields=["warehouse", "location"])

    return mv.id
