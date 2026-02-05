# quality/admin.py
from django.contrib import admin
from django.utils.html import format_html
from django.utils.text import Truncator
from .models import (
    QAPlan, QAParameterTemplate, QualityInspection,
    RecallOrigin, ProductRecall, RecallLot, RecallAffectedClient,
)


class QAParameterTemplateInline(admin.TabularInline):
    model = QAParameterTemplate
    extra = 0
    fields = (
        "order",
        "code",
        "label",
        "data_type",
        "unit",
        "min_value",
        "max_value",
        "is_required",
    )
    ordering = ("order", "id")
    show_change_link = True


@admin.register(QAPlan)
class QAPlanAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "stage",
        "product",
        "work_center",
        "route_step",
        "is_active",
        "updated_at",
    )
    list_filter = ("stage", "is_active", "work_center")
    search_fields = ("name", "product__code", "product__name", "work_center__name")
    ordering = ("-is_active", "stage", "name")
    inlines = [QAParameterTemplateInline]

    # Para bases grandes (más rápido que dropdown gigante)
    raw_id_fields = ("product", "work_center", "route_step")


@admin.register(QAParameterTemplate)
class QAParameterTemplateAdmin(admin.ModelAdmin):
    list_display = (
        "plan",
        "order",
        "code",
        "label",
        "data_type",
        "unit",
        "min_value",
        "max_value",
        "is_required",
        "updated_at",
    )
    list_filter = ("data_type", "is_required", "plan__stage")
    search_fields = ("code", "label", "plan__name")
    ordering = ("plan", "order", "id")
    raw_id_fields = ("plan",)


def _checklist_preview(obj: QualityInspection) -> str:
    """
    Muestra un resumen del JSON checklist sin llenar el admin de texto.
    Espera estructura tipo:
    {"params": [{"code":"ANCHO","value":"20","ok":true}, ...]}
    """
    if not obj.checklist:
        return "-"
    params = obj.checklist.get("params") if isinstance(obj.checklist, dict) else None
    if not params:
        # fallback: muestra JSON truncado
        return Truncator(str(obj.checklist)).chars(80)

    # arma algo corto: ANCHO=20(OK), PESO=...(NO)
    parts = []
    for p in params[:4]:  # máximo 4 en preview
        code = p.get("code", "")
        val = p.get("value", "")
        ok = p.get("ok", None)
        tag = "OK" if ok is True else ("NO" if ok is False else "")
        parts.append(f"{code}={val}{'('+tag+')' if tag else ''}")

    more = f" +{len(params)-4}" if len(params) > 4 else ""
    return ", ".join(parts) + more


@admin.register(QualityInspection)
class QualityInspectionAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "lot",
        "product_code",
        "stage",
        "result",
        "inspected_at",
        "inspected_by",
        "operation",
        "checklist_short",
        "updated_at",
    )
    list_filter = ("stage", "result", "inspected_by", "inspected_at")
    search_fields = (
        "lot__internal_lot",
        "lot__supplier_lot",
        "lot__product__code",
        "lot__product__name",
        "notes",
    )
    ordering = ("-inspected_at", "-updated_at")

    raw_id_fields = ("lot", "operation", "inspected_by")

    def product_code(self, obj: QualityInspection):
        try:
            return obj.lot.product.code
        except Exception:
            return "-"
    product_code.short_description = "Código producto"
    product_code.admin_order_field = "lot__product__code"

    def checklist_short(self, obj: QualityInspection):
        return _checklist_preview(obj)
    checklist_short.short_description = "Checklist (resumen)"


# ─── Retiro de Mercado ──────────────────────────────────────────


@admin.register(RecallOrigin)
class RecallOriginAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "origin_type", "is_active")
    list_filter = ("origin_type", "is_active")
    search_fields = ("code", "name")


class RecallLotInline(admin.TabularInline):
    model = RecallLot
    extra = 0
    fields = ("lot", "quantity_affected", "quantity_in_warehouse", "quantity_with_clients", "quantity_recovered")
    raw_id_fields = ("lot",)


class RecallAffectedClientInline(admin.TabularInline):
    model = RecallAffectedClient
    extra = 0
    fields = ("client", "client_name", "dispatch_code", "quantity_dispatched", "notified", "recovered")
    raw_id_fields = ("client",)


@admin.register(ProductRecall)
class ProductRecallAdmin(admin.ModelAdmin):
    list_display = ("code", "product", "origin", "severity", "status", "recall_date")
    list_filter = ("status", "severity", "origin__origin_type")
    search_fields = ("code", "product__name", "product__code", "reason")
    raw_id_fields = ("product", "origin")
    inlines = [RecallLotInline, RecallAffectedClientInline]


@admin.register(RecallLot)
class RecallLotAdmin(admin.ModelAdmin):
    list_display = ("recall", "lot", "quantity_affected", "quantity_recovered")
    list_filter = ("recall__status",)
    search_fields = ("recall__code", "lot__internal_lot")
    raw_id_fields = ("recall", "lot")

