from django.contrib import admin
from .models import (
    SaleOrder, SaleOrderLine, SaleDispatch, SaleDispatchLine,
    PickingOrder, PickingLine, PackingOrder, PackingLine,
    SaleInvoice, SaleInvoiceLine,
    GuiaRemision, GuiaRemisionLine,
    ReturnReason, SaleReturn, SaleReturnLine,
    CreditNote, CreditNoteLine,
)


class SaleOrderLineInline(admin.TabularInline):
    model = SaleOrderLine
    extra = 0


@admin.register(SaleOrder)
class SaleOrderAdmin(admin.ModelAdmin):
    list_display = ("code", "client", "status", "delivery_date", "created_at")
    list_filter = ("status",)
    search_fields = ("code", "client__trade_name")
    inlines = [SaleOrderLineInline]


@admin.register(ReturnReason)
class ReturnReasonAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "reason_type", "is_active")
    list_filter = ("reason_type", "is_active")
    search_fields = ("code", "name")


class SaleReturnLineInline(admin.TabularInline):
    model = SaleReturnLine
    extra = 0


@admin.register(SaleReturn)
class SaleReturnAdmin(admin.ModelAdmin):
    list_display = ("code", "invoice", "client", "reason", "status", "return_date", "total_amount")
    list_filter = ("status", "reason__reason_type")
    search_fields = ("code", "invoice__sequential", "client__trade_name")
    inlines = [SaleReturnLineInline]


class CreditNoteLineInline(admin.TabularInline):
    model = CreditNoteLine
    extra = 0


@admin.register(CreditNote)
class CreditNoteAdmin(admin.ModelAdmin):
    list_display = ("full_number", "invoice", "status", "total_amount", "issue_date")
    list_filter = ("status",)
    inlines = [CreditNoteLineInline]


# ─── Modelos adicionales ─────────────────────────────────────

class SaleDispatchLineInline(admin.TabularInline):
    model = SaleDispatchLine
    extra = 0


@admin.register(SaleDispatch)
class SaleDispatchAdmin(admin.ModelAdmin):
    list_display = ("code", "order", "dispatched_date")
    search_fields = ("code", "order__code")
    inlines = [SaleDispatchLineInline]


class PickingLineInline(admin.TabularInline):
    model = PickingLine
    extra = 0


@admin.register(PickingOrder)
class PickingOrderAdmin(admin.ModelAdmin):
    list_display = ("code", "order", "status", "created_at")
    list_filter = ("status",)
    search_fields = ("code", "order__code")
    inlines = [PickingLineInline]


class PackingLineInline(admin.TabularInline):
    model = PackingLine
    extra = 0


@admin.register(PackingOrder)
class PackingOrderAdmin(admin.ModelAdmin):
    list_display = ("code", "picking", "status", "created_at")
    list_filter = ("status",)
    search_fields = ("code", "picking__code")
    inlines = [PackingLineInline]


class SaleInvoiceLineInline(admin.TabularInline):
    model = SaleInvoiceLine
    extra = 0


@admin.register(SaleInvoice)
class SaleInvoiceAdmin(admin.ModelAdmin):
    list_display = ("sequential", "order", "buyer_legal_name", "status", "total_amount", "issue_date")
    list_filter = ("status",)
    search_fields = ("sequential", "order__code", "buyer_legal_name", "buyer_identification")
    inlines = [SaleInvoiceLineInline]


class GuiaRemisionLineInline(admin.TabularInline):
    model = GuiaRemisionLine
    extra = 0


@admin.register(GuiaRemision)
class GuiaRemisionAdmin(admin.ModelAdmin):
    list_display = ("full_number", "dispatch", "status", "issue_date")
    list_filter = ("status",)
    search_fields = ("sequential", "dispatch__code", "carrier_legal_name")
    inlines = [GuiaRemisionLineInline]
