from django.contrib import admin
from .models import (
    BillOfMaterial,
    BillOfMaterialLine,
    WorkCenter,
    ProductRoute,
    ProductRouteStep,
    ProductionOrder,
    ProductionOrderStatus,
    ProductionOperation,
    ProductionOperationStatus,
    OperationStatusLog,
    ProductionPlan,
    ProductionPlanRawLot,
    MaterialTransfer,
)

@admin.register(BillOfMaterial)
class BillOfMaterialAdmin(admin.ModelAdmin):
    list_display = ("product_finished", "revision", "is_active")
    search_fields = ("product_finished__code", "product_finished__name")
    list_filter = ("is_active", "revision")

@admin.register(BillOfMaterialLine)
class BillOfMaterialLineAdmin(admin.ModelAdmin):
    list_display = ("bom", "component", "quantity", "scrap_rate")
    search_fields = ("bom__product_finished__code", "component__code")
    list_filter = ("bom__product_finished",)

@admin.register(WorkCenter)
class WorkCenterAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "default_warehouse", "capacity_per_hour", "is_active")
    search_fields = ("code", "name")

@admin.register(ProductRoute)
class ProductRouteAdmin(admin.ModelAdmin):
    list_display = ("product", "name", "is_active")
    search_fields = ("product__code", "product__name")
    list_filter = ("is_active",)

@admin.register(ProductRouteStep)
class ProductRouteStepAdmin(admin.ModelAdmin):
    list_display = ("route", "sequence", "work_center", "name", "expected_duration_min", "requires_qa")
    search_fields = ("route__name", "work_center__code", "name")
    list_filter = ("route", "work_center", "requires_qa")

@admin.register(ProductionOrder)
class ProductionOrderAdmin(admin.ModelAdmin):
    list_display = ("code", "product", "quantity_planned", "quantity_produced", "status", "start_date", "end_date")
    search_fields = ("product__code", "product__name", "code")
    list_filter = ("status", "product", "start_date", "end_date")

@admin.register(ProductionOperation)
class ProductionOperationAdmin(admin.ModelAdmin):
    list_display = ("order", "step", "sequence", "status", "started_at", "finished_at")
    search_fields = ("order__code", "step__name", "status")
    list_filter = ("status", "order", "step")

# ─── Modelos adicionales ─────────────────────────────────────

@admin.register(OperationStatusLog)
class OperationStatusLogAdmin(admin.ModelAdmin):
    list_display = ("operation", "from_status", "to_status", "changed_at", "changed_by")
    list_filter = ("from_status", "to_status")
    search_fields = ("operation__order__code",)


class ProductionPlanRawLotInline(admin.TabularInline):
    model = ProductionPlanRawLot
    extra = 0


@admin.register(ProductionPlan)
class ProductionPlanAdmin(admin.ModelAdmin):
    list_display = ("code", "product", "lot_code", "quantity_planned", "status", "manufacturing_date", "created_at")
    list_filter = ("status",)
    search_fields = ("code", "product__code", "product__name", "lot_code")
    inlines = [ProductionPlanRawLotInline]


@admin.register(MaterialTransfer)
class MaterialTransferAdmin(admin.ModelAdmin):
    list_display = ("order", "component", "lot", "quantity_requested", "status", "created_at")
    list_filter = ("status",)
    search_fields = ("order__code", "lot__internal_lot", "component__code")
