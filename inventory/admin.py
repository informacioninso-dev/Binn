from django.contrib import admin

from .models import InventoryItem, PurchaseOrder, StockMovement, Supplier


@admin.register(Supplier)
class SupplierAdmin(admin.ModelAdmin):
    list_display = ("name", "contact_name", "phone", "email", "is_active")
    list_filter = ("is_active",)
    search_fields = ("name", "contact_name", "email")


@admin.register(InventoryItem)
class InventoryItemAdmin(admin.ModelAdmin):
    list_display = ("sku", "name", "category", "supplier", "stock_on_hand", "reorder_point", "is_active")
    list_filter = ("is_active", "category")
    search_fields = ("sku", "name", "category")


@admin.register(PurchaseOrder)
class PurchaseOrderAdmin(admin.ModelAdmin):
    list_display = ("id", "supplier", "ordered_at", "status", "reference", "total_amount")
    list_filter = ("status", "supplier")
    search_fields = ("reference", "supplier__name")


@admin.register(StockMovement)
class StockMovementAdmin(admin.ModelAdmin):
    list_display = ("moved_at", "item", "movement_type", "quantity", "purchase_order", "reference")
    list_filter = ("movement_type",)
    search_fields = ("item__name", "item__sku", "reference")
