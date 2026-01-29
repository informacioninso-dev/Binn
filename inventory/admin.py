from django.contrib import admin
from .models import (
    Product,
    Stock,
    InventoryMove,
    Lot,LotBalance,
)

@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = (
        "code",
        "name",
        "product_type",
        "category",
        "brand",
        "base_unit",
        "unit_price",
        "unit_cost",
        "is_active",
        "created_at",
    )
    list_filter = ("is_active", "product_type", "category", "brand")
    search_fields = ("code", "code_2", "name", "provider", "category", "brand")
    ordering = ("name",)


@admin.register(Stock)
class StockAdmin(admin.ModelAdmin):
    list_display = ("product", "quantity", "updated_at")
    search_fields = ("product__code", "product__name")
    ordering = ("product__name",)


@admin.register(InventoryMove)
class InventoryMoveAdmin(admin.ModelAdmin):
    list_display = (
        "date",
        "product",
        "movement_type",
        "quantity",
        "unit_cost",
        "reference",
        "warehouse",
        "location",
        "area",
        "created_by",
    )
    list_filter = ("movement_type", "area", "warehouse", "date")
    search_fields = ("product__code", "product__name", "reference", "area")
    ordering = ("-date",)


@admin.register(Lot)
class LotAdmin(admin.ModelAdmin):
    list_display = (
        "product",
        "internal_lot",
        "supplier_lot",
        "status",
        "quantity_current",
        "warehouse",
        "location",
        "manufacturing_date",
        "expiry_date",
    )
    list_filter = ("status", "warehouse", "product__product_type")
    search_fields = ("product__code", "product__name", "internal_lot", "supplier_lot", "origin_reference")
    ordering = ("-created_at",)


@admin.register(LotBalance)
class LotBalanceAdmin(admin.ModelAdmin):
    list_display = ("lot", "warehouse", "location", "qty")
    list_filter = ("warehouse", "location", "lot")
    search_fields = ("lot__internal_lot", "lot__product__name", "warehouse__name", "location__code")
    ordering = ("lot__internal_lot", "location__code")


