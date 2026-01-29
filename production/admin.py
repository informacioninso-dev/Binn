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
    ProductionOperationStatus,  # Eliminado de aquí.
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

# Ya no hay necesidad de registrar ProductionOperationStatus
