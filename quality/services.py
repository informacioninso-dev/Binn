"""
Servicios para el módulo de calidad.
"""
from decimal import Decimal
from django.db import models, transaction
from django.core.exceptions import ValidationError
from django.utils import timezone


@transaction.atomic
def create_recall(*, product, origin, reason, description, severity, selected_lot_ids, user):
    """
    Crea un retiro de mercado para un producto.

    Args:
        product: Producto a retirar
        origin: RecallOrigin (motivo configurable)
        reason: Texto con el motivo detallado
        description: Descripción del problema
        severity: RecallSeverity (LOW, MEDIUM, HIGH, CRITICAL)
        selected_lot_ids: Lista de IDs de lotes seleccionados
        user: Usuario que crea el retiro

    Returns:
        ProductRecall: El retiro creado
    """
    from .models import ProductRecall, RecallLot, RecallAffectedClient
    from inventory.models import Lot, LotBalance
    from sales.models import SaleDispatchLine

    recall = ProductRecall.objects.create(
        product=product,
        origin=origin,
        severity=severity,
        reason=reason,
        description=description,
        created_by=user,
        updated_by=user,
    )

    # Obtener los lotes seleccionados del producto
    lots = Lot.objects.filter(
        id__in=selected_lot_ids,
        product=product,
    ).select_related("product")

    if not lots.exists():
        raise ValidationError("Debe seleccionar al menos un lote del producto.")

    for lot in lots:
        # Calcular cantidad en bodega
        warehouse_qty = (
            LotBalance.objects
            .filter(lot=lot, quantity__gt=0)
            .aggregate(total=models.Sum("quantity"))["total"]
            or Decimal("0")
        )

        # Calcular cantidad despachada a clientes
        client_qty = (
            SaleDispatchLine.objects
            .filter(lot=lot)
            .aggregate(total=models.Sum("quantity"))["total"]
            or Decimal("0")
        )

        total_affected = warehouse_qty + client_qty

        recall_lot = RecallLot.objects.create(
            recall=recall,
            lot=lot,
            quantity_affected=total_affected,
            quantity_in_warehouse=warehouse_qty,
            quantity_with_clients=client_qty,
            created_by=user,
            updated_by=user,
        )

        # Identificar clientes afectados (recibieron este lote)
        dispatch_lines = (
            SaleDispatchLine.objects
            .filter(lot=lot)
            .select_related(
                "dispatch",
                "dispatch__order",
                "dispatch__order__client",
            )
        )

        for dl in dispatch_lines:
            dispatch = dl.dispatch
            order = dispatch.order
            client = order.client

            RecallAffectedClient.objects.get_or_create(
                recall=recall,
                recall_lot=recall_lot,
                client=client,
                dispatch_code=dispatch.code,
                defaults={
                    "client_name": client.legal_name or client.trade_name,
                    "client_address": order.delivery_address or client.address,
                    "client_city": order.delivery_city or client.city,
                    "client_phone": order.delivery_phone or client.phone,
                    "client_email": client.email,
                    "dispatch_date": dispatch.dispatched_date.date() if dispatch.dispatched_date else None,
                    "quantity_dispatched": dl.quantity,
                    "created_by": user,
                    "updated_by": user,
                },
            )

    return recall


@transaction.atomic
def activate_recall(*, recall, user):
    """Activa un retiro en borrador."""
    from .models import RecallStatus

    if recall.status != RecallStatus.DRAFT:
        raise ValidationError("Solo se pueden activar retiros en borrador.")

    recall.status = RecallStatus.ACTIVE
    recall.updated_by = user
    recall.save(update_fields=["status", "updated_by", "updated_at"])

    return recall


@transaction.atomic
def start_notification(*, recall, user):
    """Inicia el proceso de notificación a clientes."""
    from .models import RecallStatus

    if recall.status != RecallStatus.ACTIVE:
        raise ValidationError("El retiro debe estar activo para notificar.")

    recall.status = RecallStatus.NOTIFYING
    recall.updated_by = user
    recall.save(update_fields=["status", "updated_by", "updated_at"])

    return recall


@transaction.atomic
def mark_client_notified(*, affected_client, notification_method, user):
    """Marca un cliente como notificado."""
    affected_client.notified = True
    affected_client.notified_date = timezone.now()
    affected_client.notification_method = notification_method
    affected_client.updated_by = user
    affected_client.save(update_fields=[
        "notified", "notified_date", "notification_method", "updated_by", "updated_at"
    ])
    return affected_client


@transaction.atomic
def mark_client_recovered(*, affected_client, quantity_recovered, recovery_notes, user):
    """Marca el producto como recuperado de un cliente."""
    affected_client.recovered = True
    affected_client.quantity_recovered = quantity_recovered
    affected_client.recovery_date = timezone.now()
    affected_client.recovery_notes = recovery_notes
    affected_client.updated_by = user
    affected_client.save(update_fields=[
        "recovered", "quantity_recovered", "recovery_date", "recovery_notes",
        "updated_by", "updated_at"
    ])

    # Actualizar cantidad recuperada en el lote
    recall_lot = affected_client.recall_lot
    recall_lot.quantity_recovered = (
        recall_lot.clients.filter(recovered=True)
        .aggregate(total=models.Sum("quantity_recovered"))["total"]
        or Decimal("0")
    )
    recall_lot.updated_by = user
    recall_lot.save(update_fields=["quantity_recovered", "updated_by", "updated_at"])

    return affected_client


@transaction.atomic
def complete_recall(*, recall, corrective_action, user):
    """Completa un retiro de mercado."""
    from .models import RecallStatus

    if recall.status not in (RecallStatus.NOTIFYING, RecallStatus.RECOVERING):
        raise ValidationError("El retiro debe estar en notificación o recuperación.")

    recall.status = RecallStatus.COMPLETED
    recall.completion_date = timezone.now()
    recall.corrective_action = corrective_action
    recall.updated_by = user
    recall.save(update_fields=[
        "status", "completion_date", "corrective_action", "updated_by", "updated_at"
    ])

    return recall


def get_lots_for_product(product):
    """
    Obtiene los lotes de un producto con información de trazabilidad.

    Returns:
        Lista de lotes con info de cantidad en bodega y cantidad con clientes.
    """
    from inventory.models import Lot, LotBalance
    from sales.models import SaleDispatchLine
    from django.db.models import Sum, Exists, OuterRef

    lots = (
        Lot.objects
        .filter(product=product)
        .select_related("product")
        .order_by("-created_at")
    )

    result = []
    for lot in lots:
        warehouse_qty = (
            LotBalance.objects
            .filter(lot=lot, quantity__gt=0)
            .aggregate(total=Sum("quantity"))["total"]
            or Decimal("0")
        )

        client_qty = (
            SaleDispatchLine.objects
            .filter(lot=lot)
            .aggregate(total=Sum("quantity"))["total"]
            or Decimal("0")
        )

        result.append({
            "lot": lot,
            "in_warehouse": warehouse_qty,
            "with_clients": client_qty,
            "total": warehouse_qty + client_qty,
            "has_movement": warehouse_qty > 0 or client_qty > 0,
        })

    return result
