from django.db import transaction
from decimal import Decimal
from django.core.exceptions import ValidationError
from django.utils import timezone
from core.utils.unit_converter import UnitConverter  # ⭐ IMPORTAR
from .models import RawMaterialReception, RawMaterialReceptionLine, ReceptionStatus
from inventory.models import Lot, LotStatus, MovementTypes
from inventory.services import (
    generate_reception_code,
    get_default_quarantine_warehouse,
    generate_internal_lot,
    register_inventory_move,
)


def _to_decimal(value) -> Decimal:
    if value is None or value == "":
        return Decimal("0")
    return Decimal(str(value))


# procurement/services.py

@transaction.atomic
def create_raw_material_reception(
    *,
    user,
    header_data: dict,
    lines_data: list[dict],
) -> RawMaterialReception:
    """
    Crea recepción de MP con CONVERSIÓN AUTOMÁTICA de unidades.
    Usa LotBalance para tracking de cantidades.
    """
    from inventory.models import LotBalance
    from core.models import Location
    
    converter = UnitConverter()
    reception_date = header_data.get("reception_date") or timezone.localdate()
    code = header_data.get("code") or generate_reception_code(reception_date)
    quarantine_wh = get_default_quarantine_warehouse()

    reception = RawMaterialReception.objects.create(
        code=code,
        supplier_name=header_data["supplier_name"],
        supplier_ruc=header_data.get("supplier_ruc"),
        document_type=header_data.get("document_type"),
        document_number=header_data.get("document_number"),
        reception_date=reception_date,
        arrival_time=header_data.get("arrival_time"),
        transport_company=header_data.get("transport_company"),
        transport_plate=header_data.get("transport_plate"),
        temperature_recorded=header_data.get("temperature_recorded"),
        num_boxes=header_data.get("num_boxes"),
        gross_weight=header_data.get("gross_weight"),
        net_weight=header_data.get("net_weight"),
        status=ReceptionStatus.RECEIVED,
        observations=header_data.get("observations"),
        created_by=user,
        updated_by=user,
    )

    for line_data in lines_data:
        product = line_data["product"]
        received_quantity_raw = _to_decimal(line_data.get("received_quantity"))

        if received_quantity_raw <= 0:
            raise ValidationError(
                f"Cantidad recibida inválida para {product.code}."
            )

        # Obtener unidad
        from_unit = line_data.get("unit")
        if not from_unit:
            from_unit = product.base_unit
        
        # Convertir a unidad base
        received_quantity_base = converter.convert_to_base_unit(
            quantity=received_quantity_raw,
            from_unit=from_unit,
            product=product
        )
        # Determinar número de lote único
        lot_number = line_data.get("lot_number") or generate_internal_lot(product)

        # Crear línea (guarda en UNIDAD BASE para contabilidad e inventario)
        line = RawMaterialReceptionLine.objects.create(
            reception=reception,
            product=product,
            expected_quantity=line_data.get("expected_quantity"),
            received_quantity=received_quantity_base,  # ✅ En unidad base (ej: 0.5 kg)
            unit=product.base_unit,                    # ✅ Unidad base (ej: kg)
            unit_cost=line_data.get("unit_cost"),
            lot_number=lot_number,
            notes=line_data.get("line_notes") or line_data.get("notes"),
            expiry_date=line_data.get("expiry_date"),
            manufacturing_date=line_data.get("manufacturing_date"),
        )

        # ⭐ Crear lote SIN quantity_current
        lot = Lot.objects.create(
            product=product,
            lot_number=lot_number,
            quantity_initial=received_quantity_base,
            # NO quantity_current - es property calculada
            status=LotStatus.PENDING,
            origin_reference=reception.document_number or reception.code,
            warehouse=quarantine_wh,
            location=None,
            expiry_date=line.expiry_date,
            manufacturing_date=line.manufacturing_date,
            created_by=user,
            updated_by=user,
        )
        
        # ⭐ Obtener o crear ubicación
        location = Location.objects.filter(
            warehouse=quarantine_wh,
            is_active=True
        ).first()
        
        if not location:
            location = Location.objects.create(
                warehouse=quarantine_wh,
                code=f'{quarantine_wh.code}-CUARENTENA',
                name='Cuarentena',
                is_active=True,
                created_by=user
            )
        
        # Actualizar ubicación del lote
        lot.location = location
        lot.save(update_fields=['location'])
        
        # ⭐ CREAR LotBalance
        LotBalance.objects.create(
            lot=lot,
            warehouse=quarantine_wh,
            location=location,
            qty=received_quantity_base,
            created_by=user,
            updated_by=user
        )

        # Registrar movimiento de trazabilidad SOLAMENTE (NO actualiza Stock)
        # El Stock se actualiza cuando QA aprueba el lote
        from inventory.models import InventoryMove
        InventoryMove.objects.create(
            product=product,
            lot=lot,
            movement_type=MovementTypes.IN,
            quantity=received_quantity_base,
            unit_displayed=from_unit,
            quantity_displayed=received_quantity_raw,
            unit_cost=line.unit_cost,
            reference=reception.code,
            warehouse=quarantine_wh,
            location=location,
            area="CUARENTENA",
            notes=(
                f"Recepción MP {reception.code} | "
                f"Recibido: {received_quantity_raw} {from_unit.code} = "
                f"{received_quantity_base} {product.base_unit.code}"
            ),
            created_by=user,
            updated_by=user,
        )

    reception.status = ReceptionStatus.RECEIVED
    reception.updated_by = user
    reception.save(update_fields=["status", "updated_at", "updated_by"])

    return reception