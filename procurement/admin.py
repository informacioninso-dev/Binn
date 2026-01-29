from django.contrib import admin
from django.utils.translation import gettext_lazy as _
from .models import PurchaseOrder, PurchaseOrderLine, PurchaseOrderStatus
from .forms import PurchaseOrderLineForm
from .models import RawMaterialReception, RawMaterialReceptionLine  # Importando los modelos de inventory
from partners.models import Partner
from inventory.models import Product


# ------------------------ Registro de RawMaterialReception ------------------------

class RawMaterialReceptionLineInline(admin.TabularInline):
    """
    Inline para las líneas de recepción de materia prima.
    """
    model = RawMaterialReceptionLine
    extra = 1  # Número de formularios vacíos a mostrar
    fields = ('product', 'quantity', 'unit_price', 'received_quantity')  # Los campos que deseas mostrar en la línea de recepción
    readonly_fields = ('received_quantity',)  # El total recibido no es editable
    show_change_link = True

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("product")


class RawMaterialReceptionAdmin(admin.ModelAdmin):
    """
    Admin para gestionar la recepción de materia prima.
    """
    list_display = ('code', 'supplier_name', 'reception_date', 'status', 'total_amount')
    search_fields = ('code', 'supplier_name')
    list_filter = ('status', 'currency')
    inlines = [RawMaterialReceptionLineInline]  # Mostramos las líneas de la recepción de materia prima en el mismo formulario
    readonly_fields = ('total_amount',)  # El total es solo de lectura

    def save_model(self, request, obj, form, change):
        if not obj.number:
            obj.number = obj._generate_number()  # Generar número automáticamente si no existe
        super().save_model(request, obj, form, change)


# ------------------------ Registro de PurchaseOrder ------------------------

class PurchaseOrderLineInline(admin.TabularInline):
    model = PurchaseOrderLine
    form = PurchaseOrderLineForm
    extra = 1  # Número de formularios vacíos a mostrar
    fields = ('product', 'description', 'quantity', 'unit', 'unit_price')  # Los campos a mostrar en la línea
    readonly_fields = ('line_total',)  # El total de la línea no es editable
    show_change_link = True

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("product", "unit")


class PurchaseOrderAdmin(admin.ModelAdmin):
    list_display = ('number', 'supplier', 'order_date', 'status', 'total_amount', 'currency')
    search_fields = ('number', 'supplier__trade_name', 'supplier__legal_name')
    list_filter = ('status', 'currency')
    inlines = [PurchaseOrderLineInline]  # Agrega las líneas de compra dentro de la orden de compra
    readonly_fields = ('total_amount', 'number')  # El total y el número son solo de lectura

    def save_model(self, request, obj, form, change):
        if not obj.number:
            obj.number = obj._generate_number()  # Generar número automáticamente si no existe
        super().save_model(request, obj, form, change)


# ------------------------ Registro de PurchaseOrderLine ------------------------

class PurchaseOrderLineAdmin(admin.ModelAdmin):
    list_display = ('order', 'product', 'quantity', 'unit', 'unit_price', 'line_total')
    search_fields = ('order__number', 'product__code')
    list_filter = ('order__status',)
    readonly_fields = ('line_total',)

admin.site.register(PurchaseOrder, PurchaseOrderAdmin)
admin.site.register(PurchaseOrderLine, PurchaseOrderLineAdmin)





@admin.register(RawMaterialReception)
class RawMaterialReceptionAdmin(admin.ModelAdmin):
    list_display = (
        "code",
        "supplier_name",
        "document_type",
        "document_number",
        "reception_date",
        "arrival_time",
        "status",
        "created_at",
    )
    list_filter = ("status", "reception_date", "supplier_name")
    search_fields = ("code", "supplier_name", "supplier_ruc", "document_number")
    ordering = ("-reception_date", "-created_at")
    inlines = [RawMaterialReceptionLineInline]


# Si aún quieres ver líneas también como tabla independiente, deja esto.
# Si no, puedes quitarlo y te quedas solo con el inline.
@admin.register(RawMaterialReceptionLine)
class RawMaterialReceptionLineAdmin(admin.ModelAdmin):
    list_display = (
        "reception",
        "product",
        "received_quantity",
        "unit_cost",
        "supplier_lot",
        "internal_lot",
        "storage_area",
    )
    list_filter = ("reception__status", "product__product_type")
    search_fields = ("reception__code", "product__code", "product__name", "supplier_lot", "internal_lot")
    ordering = ("-id",)

