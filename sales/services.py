from decimal import Decimal
from django.db import transaction
from django.core.exceptions import ValidationError


def confirm_order_service(order):
    from .models import SaleOrderStatus
    order.status = SaleOrderStatus.CONFIRMED
    order.save(update_fields=["status"])
    return order


def check_dispatch_availability(order):
    """
    Para cada linea del pedido verifica stock disponible.
    Si falta stock, estima tiempo de produccion usando la ruta del producto.
    """
    from inventory.models import LotBalance, LotStatus
    from django.db.models import Sum

    results = []
    for line in order.lines.select_related("product__base_unit"):
        product = line.product
        needed = line.quantity

        available = LotBalance.objects.filter(
            lot__product=product,
            lot__status=LotStatus.APPROVED,
        ).aggregate(total=Sum("qty"))["total"] or Decimal("0")

        deficit = max(Decimal("0"), needed - available)
        stock_ok = deficit == Decimal("0")

        production_info = None
        if not stock_ok:
            production_info = _estimate_production_time(product, deficit)

        results.append({
            "line": line,
            "product": product,
            "needed": needed,
            "available": available,
            "deficit": deficit,
            "stock_ok": stock_ok,
            "production_info": production_info,
        })

    return results


def _estimate_production_time(product, quantity):
    from production.models import ProductRoute

    route = (
        ProductRoute.objects
        .filter(product=product, is_active=True)
        .prefetch_related("steps__work_center")
        .first()
    )
    if not route:
        return {
            "has_route": False,
            "message": "Sin ruta de producción configurada",
            "estimated_days": None,
            "steps": [],
        }

    steps_info = []
    total_minutes = Decimal("0")

    for step in route.steps.filter(is_active=True).order_by("sequence"):
        wc = step.work_center
        setup = Decimal(str(step.setup_time_min or wc.setup_time_min or 0))
        duration_per_unit = Decimal(str(step.expected_duration_min or 0))

        if wc.capacity_per_hour and wc.capacity_per_hour > 0:
            step_minutes = (quantity / wc.capacity_per_hour) * 60 + setup
        elif duration_per_unit > 0:
            step_minutes = duration_per_unit * quantity + setup
        else:
            step_minutes = setup

        total_minutes += step_minutes
        steps_info.append({
            "name": step.name,
            "work_center": wc.name,
            "minutes": round(step_minutes, 1),
        })

    if steps_info and route.steps.exists():
        first_wc = route.steps.first().work_center
        minutes_per_day = first_wc.available_minutes_per_day or Decimal("480")
    else:
        minutes_per_day = Decimal("480")

    estimated_days = total_minutes / minutes_per_day
    if estimated_days < 1 and total_minutes > 0:
        estimated_days = Decimal("1")
    else:
        estimated_days = estimated_days.quantize(Decimal("1"))

    return {
        "has_route": True,
        "message": None,
        "total_minutes": round(total_minutes, 1),
        "estimated_days": estimated_days,
        "steps": steps_info,
    }


# ─── Picking ───────────────────────────────────────────────

@transaction.atomic
def create_picking(*, order, user):
    """
    Genera orden de picking para un pedido confirmado.
    Selecciona lotes por FEFO y genera líneas con ubicación.
    NO descuenta stock aún.
    """
    from .models import (
        PickingOrder, PickingLine, PickingOrderStatus,
        SaleOrderStatus,
    )
    from inventory.models import LotBalance, LotStatus

    if order.status != SaleOrderStatus.CONFIRMED:
        raise ValidationError("El pedido debe estar confirmado para iniciar picking.")

    # Verificar disponibilidad
    availability = check_dispatch_availability(order)
    for item in availability:
        if not item["stock_ok"]:
            raise ValidationError(
                f"Stock insuficiente para {item['product'].name}: "
                f"necesita {item['needed']}, disponible {item['available']}"
            )

    picking = PickingOrder.objects.create(
        order=order,
        status=PickingOrderStatus.PENDING,
        created_by=user,
        updated_by=user,
    )

    for item in availability:
        line = item["line"]
        product = item["product"]
        remaining = item["needed"]

        balances = (
            LotBalance.objects
            .filter(
                lot__product=product,
                lot__status=LotStatus.APPROVED,
                qty__gt=0,
            )
            .select_related("lot", "warehouse", "location")
            .order_by("lot__expiry_date", "lot__created_at")
        )

        for balance in balances:
            if remaining <= 0:
                break

            qty_to_take = min(remaining, balance.qty)

            location_str = ""
            if balance.location:
                location_str = str(balance.location)
            elif balance.warehouse:
                location_str = str(balance.warehouse)

            PickingLine.objects.create(
                picking=picking,
                order_line=line,
                product=product,
                lot=balance.lot,
                location=location_str,
                quantity_requested=qty_to_take,
                quantity_picked=0,
                picked=False,
                created_by=user,
                updated_by=user,
            )

            remaining -= qty_to_take

        if remaining > 0:
            raise ValidationError(
                f"No hay suficientes lotes aprobados de {product.name}."
            )

    # Cambiar estado del pedido
    order.status = SaleOrderStatus.PICKING
    order.save(update_fields=["status"])

    return picking


@transaction.atomic
def complete_picking(*, picking, picked_quantities, user):
    """
    Marca el picking como completado.
    picked_quantities: dict {picking_line_id: quantity_picked}
    """
    from .models import PickingOrderStatus, SaleOrderStatus

    if picking.status not in (PickingOrderStatus.PENDING, PickingOrderStatus.IN_PROGRESS):
        raise ValidationError("Este picking ya fue completado o cancelado.")

    for pl in picking.lines.all():
        qty = picked_quantities.get(pl.pk, pl.quantity_requested)
        pl.quantity_picked = qty
        pl.picked = True
        pl.updated_by = user
        pl.save(update_fields=["quantity_picked", "picked", "updated_by", "updated_at"])

    picking.status = PickingOrderStatus.COMPLETED
    picking.updated_by = user
    picking.save(update_fields=["status", "updated_by", "updated_at"])

    # Cambiar estado del pedido a PACKING
    picking.order.status = SaleOrderStatus.PACKING
    picking.order.save(update_fields=["status"])

    return picking


# ─── Packing ──────────────────────────────────────────────

@transaction.atomic
def create_packing(*, picking, user):
    """
    Crea orden de packing a partir de un picking completado.
    Copia las líneas del picking como líneas de packing.
    """
    from .models import (
        PackingOrder, PackingLine, PackingOrderStatus,
        PickingOrderStatus,
    )

    if picking.status != PickingOrderStatus.COMPLETED:
        raise ValidationError("El picking debe estar completado para iniciar packing.")

    packing = PackingOrder.objects.create(
        order=picking.order,
        picking=picking,
        status=PackingOrderStatus.PENDING,
        created_by=user,
        updated_by=user,
    )

    for pl in picking.lines.filter(picked=True, quantity_picked__gt=0):
        PackingLine.objects.create(
            packing=packing,
            product=pl.product,
            lot=pl.lot,
            quantity=pl.quantity_picked,
            box_number=1,
            created_by=user,
            updated_by=user,
        )

    return packing


@transaction.atomic
def complete_packing(*, packing, packing_data, user):
    """
    Completa el packing con datos de empaque.
    packing_data: dict con num_boxes, gross_weight, net_weight, notes
    box_assignments: dict {packing_line_id: box_number} (opcional)
    """
    from .models import PackingOrderStatus

    if packing.status not in (PackingOrderStatus.PENDING, PackingOrderStatus.IN_PROGRESS):
        raise ValidationError("Este packing ya fue completado o cancelado.")

    packing.num_boxes = packing_data.get("num_boxes", packing.num_boxes)
    packing.gross_weight = packing_data.get("gross_weight", packing.gross_weight)
    packing.net_weight = packing_data.get("net_weight", packing.net_weight)
    packing.notes = packing_data.get("notes", packing.notes)
    packing.status = PackingOrderStatus.COMPLETED
    packing.updated_by = user
    packing.save()

    # Actualizar asignaciones de caja si vienen
    box_assignments = packing_data.get("box_assignments", {})
    for pl in packing.lines.all():
        box = box_assignments.get(str(pl.pk))
        if box:
            pl.box_number = int(box)
            pl.save(update_fields=["box_number"])

    return packing


# ─── Despacho ──────────────────────────────────────────────

@transaction.atomic
def create_dispatch(*, order, user):
    """
    Crea despacho final. Requiere picking y packing completados.
    Descuenta stock via LotBalance e InventoryMove.
    """
    from .models import (
        SaleDispatch, SaleDispatchLine, SaleOrderStatus,
        PackingOrderStatus,
    )
    from inventory.models import (
        Stock, LotBalance, InventoryMove, MovementTypes,
    )

    # Buscar packing completado
    packing = (
        order.packings
        .filter(status=PackingOrderStatus.COMPLETED)
        .select_related("picking")
        .prefetch_related("lines__product", "lines__lot")
        .first()
    )
    if not packing:
        raise ValidationError("No hay packing completado para este pedido.")

    dispatch = SaleDispatch.objects.create(
        order=order,
        created_by=user,
        updated_by=user,
    )

    picking = packing.picking

    # Descontar stock por cada línea del picking (que tiene info de balance/ubicación)
    for picking_line in picking.lines.filter(picked=True, quantity_picked__gt=0):
        product = picking_line.product
        lot = picking_line.lot
        qty = picking_line.quantity_picked

        # Crear línea de despacho
        SaleDispatchLine.objects.create(
            dispatch=dispatch,
            order_line=picking_line.order_line,
            product=product,
            lot=lot,
            quantity=qty,
            created_by=user,
            updated_by=user,
        )

        # Descontar LotBalance
        balances = LotBalance.objects.filter(lot=lot, qty__gt=0).order_by("-qty")
        remaining = qty
        for balance in balances:
            if remaining <= 0:
                break
            take = min(remaining, balance.qty)
            balance.qty -= take
            balance.updated_by = user
            balance.save(update_fields=["qty", "updated_by", "updated_at"])
            remaining -= take

            # Movimiento de inventario
            InventoryMove.objects.create(
                product=product,
                lot=lot,
                movement_type=MovementTypes.OUT,
                quantity=take,
                unit_cost=picking_line.order_line.unit_price,
                reference=dispatch.code,
                warehouse=balance.warehouse,
                location=balance.location,
                area="DESPACHO",
                notes=f"Despacho {dispatch.code} | Pedido {order.code}",
                created_by=user,
                updated_by=user,
            )

        # Descontar Stock global
        stock, _ = Stock.objects.get_or_create(
            product=product,
            defaults={"created_by": user, "updated_by": user},
        )
        stock.quantity -= qty
        stock.updated_by = user
        stock.save(update_fields=["quantity", "updated_by", "updated_at"])

    # Cambiar estado
    order.status = SaleOrderStatus.DISPATCHED
    order.save(update_fields=["status"])

    return dispatch


# ─── Devoluciones ──────────────────────────────────────────

@transaction.atomic
def create_return(*, client, invoice, reason, reason_notes, lines_data, user):
    """
    Crea una devolución desde una factura.
    lines_data: [{'invoice_line_id': int, 'quantity_returned': Decimal}, ...]

    Estados: GENERATED → RECEIVED → PENDING_INSPECTION → APPROVED/REJECTED
    """
    from .models import (
        SaleReturn, SaleReturnLine, SaleReturnStatus,
        SaleInvoiceLine,
    )

    # Snapshot del cliente
    return_doc = SaleReturn.objects.create(
        client=client,
        invoice=invoice,
        client_identification=client.identification or "",
        client_legal_name=client.legal_name or client.trade_name or "",
        client_address=client.address or "",
        client_phone=client.phone or "",
        client_email=client.email or "",
        reason=reason,
        reason_notes=reason_notes,
        status=SaleReturnStatus.GENERATED,
        created_by=user,
        updated_by=user,
    )

    subtotal = Decimal("0")
    for ld in lines_data:
        inv_line = SaleInvoiceLine.objects.select_related("product").get(
            id=ld["invoice_line_id"]
        )
        qty = Decimal(str(ld["quantity_returned"]))
        if qty <= 0 or qty > inv_line.quantity:
            raise ValidationError(
                f"Cantidad inválida para {inv_line.product.name} "
                f"(máx {inv_line.quantity})."
            )

        unit_price = inv_line.unit_price
        line_sub = qty * unit_price

        SaleReturnLine.objects.create(
            return_doc=return_doc,
            invoice_line=inv_line,
            product=inv_line.product,
            quantity_returned=qty,
            unit_price=unit_price,
            created_by=user,
            updated_by=user,
        )
        subtotal += line_sub

    tax_amount = (subtotal * Decimal("0.15")).quantize(Decimal("0.01"))
    return_doc.subtotal = subtotal
    return_doc.tax_amount = tax_amount
    return_doc.total_amount = subtotal + tax_amount
    return_doc.save(update_fields=["subtotal", "tax_amount", "total_amount"])

    return return_doc


@transaction.atomic
def receive_return(*, return_doc, user):
    """
    Recepción del producto devuelto.
    - Crea lotes nuevos para los productos devueltos
    - Los envía a cuarentena
    - Cambia estado a RECEIVED, luego a PENDING_INSPECTION
    - Aparecerá en el módulo de calidad para inspección
    """
    from .models import SaleReturnStatus
    from inventory.models import Lot, LotStatus, LotBalance, InventoryMove, MovementTypes
    from inventory.services import get_default_quarantine_warehouse, _get_or_create_default_location, generate_internal_lot
    from django.utils import timezone as tz

    if return_doc.status != SaleReturnStatus.GENERATED:
        raise ValidationError("Solo se pueden recibir devoluciones en estado 'Generada'.")

    quarantine_wh = get_default_quarantine_warehouse()
    quarantine_loc = _get_or_create_default_location(quarantine_wh, user)

    for line in return_doc.lines.select_related("product"):
        # Crear nuevo lote para el producto devuelto
        lot = Lot.objects.create(
            product=line.product,
            lot_number=generate_internal_lot(line.product),
            quantity_initial=line.quantity_returned,
            status=LotStatus.QUARANTINE,
            warehouse=quarantine_wh,
            location=quarantine_loc,
            origin_reference=f"Devolución {return_doc.code}",
            created_by=user,
            updated_by=user,
        )

        # Asignar lote a la línea de devolución
        line.lot = lot
        line.save(update_fields=["lot"])

        # Crear balance del lote en cuarentena
        LotBalance.objects.create(
            lot=lot,
            warehouse=quarantine_wh,
            location=quarantine_loc,
            qty=line.quantity_returned,
            created_by=user,
            updated_by=user,
        )

        # Movimiento de inventario
        InventoryMove.objects.create(
            product=line.product,
            lot=lot,
            movement_type=MovementTypes.IN,
            quantity=line.quantity_returned,
            reference=return_doc.code,
            warehouse=quarantine_wh,
            location=quarantine_loc,
            area="DEVOLUCIÓN",
            notes=f"Devolución {return_doc.code} – {return_doc.reason.name if return_doc.reason else 'Sin motivo'}",
            created_by=user,
            updated_by=user,
        )

    return_doc.status = SaleReturnStatus.PENDING_INSPECTION
    return_doc.received_date = tz.now()
    return_doc.updated_by = user
    return_doc.save(update_fields=["status", "received_date", "updated_by", "updated_at"])

    return return_doc


@transaction.atomic
def approve_return(*, return_doc, user):
    """
    QA aprueba la devolución: producto ingresa a stock disponible.
    """
    from .models import SaleReturnStatus
    from inventory.models import LotStatus, Stock
    from inventory.services import release_lot_by_qa
    from quality.models import InspectionStage
    from django.utils import timezone as tz

    if return_doc.status != SaleReturnStatus.PENDING_INSPECTION:
        raise ValidationError("Solo se pueden aprobar devoluciones en estado 'Por Inspeccionar'.")

    for line in return_doc.lines.select_related("product", "lot"):
        if line.lot:
            # Usar release_lot_by_qa para mover a bodega liberada
            release_lot_by_qa(
                user=user,
                lot=line.lot,
                result=LotStatus.APPROVED,
                notes=f"Devolución {return_doc.code} aprobada por QA",
                stage=InspectionStage.FG,
            )

    return_doc.status = SaleReturnStatus.APPROVED
    return_doc.inspection_date = tz.now()
    return_doc.resolution_date = tz.now()
    return_doc.updated_by = user
    return_doc.save(update_fields=["status", "inspection_date", "resolution_date", "updated_by", "updated_at"])

    return return_doc


@transaction.atomic
def reject_return(*, return_doc, rejection_notes, user):
    """
    QA rechaza la devolución: producto va a bodega de baja.
    """
    from .models import SaleReturnStatus
    from inventory.models import LotStatus
    from inventory.services import release_lot_by_qa
    from quality.models import InspectionStage
    from django.utils import timezone as tz

    if return_doc.status != SaleReturnStatus.PENDING_INSPECTION:
        raise ValidationError("Solo se pueden rechazar devoluciones en estado 'Por Inspeccionar'.")

    for line in return_doc.lines.select_related("product", "lot"):
        if line.lot:
            # Usar release_lot_by_qa para mover a bodega de scrap
            release_lot_by_qa(
                user=user,
                lot=line.lot,
                result=LotStatus.REJECTED,
                notes=f"Devolución {return_doc.code} rechazada: {rejection_notes}",
                stage=InspectionStage.FG,
            )

    return_doc.status = SaleReturnStatus.REJECTED
    return_doc.inspection_date = tz.now()
    return_doc.resolution_date = tz.now()
    return_doc.inspection_notes = rejection_notes
    return_doc.updated_by = user
    return_doc.save(update_fields=[
        "status", "inspection_date", "resolution_date",
        "inspection_notes", "updated_by", "updated_at"
    ])

    return return_doc


@transaction.atomic
def issue_credit_note(*, return_doc, user):
    """
    Genera nota de crédito desde una devolución aprobada.
    """
    from .models import (
        SaleReturnStatus, CreditNote, CreditNoteLine,
    )

    if return_doc.status != SaleReturnStatus.APPROVED:
        raise ValidationError("Solo se puede emitir nota de crédito para devoluciones aprobadas.")
    if return_doc.credit_note:
        raise ValidationError("Ya existe una nota de crédito para esta devolución.")
    if not return_doc.invoice:
        raise ValidationError("No hay factura asociada a esta devolución.")

    cn = CreditNote.objects.create(
        invoice=return_doc.invoice,
        reason=f"{return_doc.reason.name if return_doc.reason else 'Devolución'} - {return_doc.reason_notes}",
        subtotal=return_doc.subtotal,
        tax_amount=return_doc.tax_amount,
        total_amount=return_doc.total_amount,
        created_by=user,
        updated_by=user,
    )

    for line in return_doc.lines.select_related("product"):
        tax_rate = Decimal("15")
        line_tax = (line.subtotal * tax_rate / Decimal("100")).quantize(Decimal("0.01"))

        CreditNoteLine.objects.create(
            credit_note=cn,
            product=line.product,
            description=line.product.name,
            quantity=line.quantity_returned,
            unit_price=line.unit_price,
            subtotal=line.subtotal,
            tax_rate=tax_rate,
            tax_amount=line_tax,
            created_by=user,
            updated_by=user,
        )

    return_doc.credit_note = cn
    return_doc.updated_by = user
    return_doc.save(update_fields=["credit_note", "updated_by", "updated_at"])

    return cn
