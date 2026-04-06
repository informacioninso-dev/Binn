from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import DecimalField, ExpressionWrapper, F, Q, Sum
from django.shortcuts import redirect, render

from tenants.permissions import INVENTORY_ALLOWED_ROLES, tenant_capability_required, tenant_role_required

from .forms import InventoryItemForm, PurchaseOrderForm, StockMovementForm, SupplierForm
from .models import InventoryItem, PurchaseOrder, PurchaseOrderStatus, StockMovement, Supplier


def _save_with_audit(instance, request):
    if instance.pk:
        instance.updated_by = request.user
    else:
        instance.created_by = request.user
        instance.updated_by = request.user
    instance.save()
    return instance


@login_required
@tenant_capability_required("inventory.basic")
@tenant_role_required(*INVENTORY_ALLOWED_ROLES)
def index(request):
    q = (request.GET.get("q") or "").strip()
    items = InventoryItem.objects.select_related("supplier")
    if q:
        items = items.filter(Q(name__icontains=q) | Q(sku__icontains=q) | Q(category__icontains=q))

    stock_value = (
        InventoryItem.objects.aggregate(
            total=Sum(
                ExpressionWrapper(F("stock_on_hand") * F("unit_cost"), output_field=DecimalField(max_digits=12, decimal_places=2))
            )
        )["total"]
        or 0
    )

    return render(
        request,
        "inventory/index.html",
        {
            "q": q,
            "items": items.order_by("name")[:100],
            "low_stock_items": InventoryItem.objects.filter(stock_on_hand__lte=F("reorder_point")).order_by("name")[:8],
            "recent_movements": StockMovement.objects.select_related("item", "purchase_order").order_by("-moved_at", "-id")[:8],
            "open_purchase_orders": PurchaseOrder.objects.select_related("supplier").filter(
                status=PurchaseOrderStatus.OPEN
            )[:8],
            "summary": {
                "items": InventoryItem.objects.filter(is_active=True).count(),
                "low_stock": InventoryItem.objects.filter(stock_on_hand__lte=F("reorder_point"), is_active=True).count(),
                "stock_value": stock_value,
                "open_purchase_orders": PurchaseOrder.objects.filter(status=PurchaseOrderStatus.OPEN).count(),
            },
        },
    )


@login_required
@tenant_capability_required("inventory.basic")
@tenant_role_required(*INVENTORY_ALLOWED_ROLES)
def item_create(request):
    if request.method == "POST":
        form = InventoryItemForm(request.POST)
        if form.is_valid():
            item = form.save(commit=False)
            _save_with_audit(item, request)
            messages.success(request, "Item de inventario registrado.")
            return redirect("inventory:index")
    else:
        form = InventoryItemForm(initial={"is_active": True})

    return render(
        request,
        "inventory/form.html",
        {"form": form, "page_title": "Nuevo item", "submit_label": "Guardar item"},
    )


@login_required
@tenant_capability_required("inventory.basic")
@tenant_role_required(*INVENTORY_ALLOWED_ROLES)
def supplier_list(request):
    q = (request.GET.get("q") or "").strip()
    suppliers = Supplier.objects.all()
    if q:
        suppliers = suppliers.filter(Q(name__icontains=q) | Q(contact_name__icontains=q) | Q(email__icontains=q))

    return render(
        request,
        "inventory/supplier_list.html",
        {
            "q": q,
            "suppliers": suppliers.order_by("name")[:100],
            "summary": {
                "active": Supplier.objects.filter(is_active=True).count(),
                "inactive": Supplier.objects.filter(is_active=False).count(),
            },
        },
    )


@login_required
@tenant_capability_required("inventory.basic")
@tenant_role_required(*INVENTORY_ALLOWED_ROLES)
def supplier_create(request):
    if request.method == "POST":
        form = SupplierForm(request.POST)
        if form.is_valid():
            supplier = form.save(commit=False)
            _save_with_audit(supplier, request)
            messages.success(request, "Proveedor registrado.")
            return redirect("inventory:suppliers")
    else:
        form = SupplierForm(initial={"is_active": True})

    return render(
        request,
        "inventory/form.html",
        {"form": form, "page_title": "Nuevo proveedor", "submit_label": "Guardar proveedor"},
    )


@login_required
@tenant_capability_required("purchases.basic")
@tenant_role_required(*INVENTORY_ALLOWED_ROLES)
def purchase_list(request):
    q = (request.GET.get("q") or "").strip()
    purchases = PurchaseOrder.objects.select_related("supplier")
    if q:
        purchases = purchases.filter(Q(reference__icontains=q) | Q(supplier__name__icontains=q))

    return render(
        request,
        "inventory/purchase_list.html",
        {
            "q": q,
            "purchase_orders": purchases.order_by("-ordered_at", "-id")[:100],
            "summary": {
                "open": PurchaseOrder.objects.filter(status=PurchaseOrderStatus.OPEN).count(),
                "received": PurchaseOrder.objects.filter(status=PurchaseOrderStatus.RECEIVED).count(),
                "canceled": PurchaseOrder.objects.filter(status=PurchaseOrderStatus.CANCELED).count(),
            },
        },
    )


@login_required
@tenant_capability_required("purchases.basic")
@tenant_role_required(*INVENTORY_ALLOWED_ROLES)
def purchase_create(request):
    if request.method == "POST":
        form = PurchaseOrderForm(request.POST)
        if form.is_valid():
            purchase_order = form.save(commit=False)
            _save_with_audit(purchase_order, request)
            messages.success(request, "Orden de compra registrada.")
            return redirect("inventory:purchases")
    else:
        form = PurchaseOrderForm()

    return render(
        request,
        "inventory/form.html",
        {"form": form, "page_title": "Nueva orden de compra", "submit_label": "Guardar orden"},
    )


@login_required
@tenant_capability_required("inventory.basic")
@tenant_role_required(*INVENTORY_ALLOWED_ROLES)
def movement_create(request):
    if request.method == "POST":
        form = StockMovementForm(request.POST)
        if form.is_valid():
            movement = form.save(commit=False)
            _save_with_audit(movement, request)
            messages.success(request, "Movimiento de stock registrado.")
            return redirect("inventory:index")
    else:
        form = StockMovementForm()

    return render(
        request,
        "inventory/form.html",
        {"form": form, "page_title": "Nuevo movimiento de stock", "submit_label": "Guardar movimiento"},
    )
