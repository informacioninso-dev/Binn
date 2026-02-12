from django.contrib import admin

# Register your models here.
# partners/admin.py

from django.contrib import admin
from .models import Partner, SupplierProduct


class SupplierProductInline(admin.TabularInline):
    """Inline para gestionar catálogo de productos del proveedor"""
    model = SupplierProduct
    extra = 1
    autocomplete_fields = ["product"]
    fields = [
        "product",
        "supplier_unit_price",
        "minimum_order_quantity",
        "lead_time_days",
        "supplier_product_code",
        "is_preferred",
    ]


@admin.register(Partner)
class PartnerAdmin(admin.ModelAdmin):
    # Qué ves en el listado
    list_display = (
        "code",
        "trade_name",
        "legal_name",
        "identification_type",
        "identification",
        "company_type",
        "is_customer",
        "is_supplier",
        "is_public_entity",
        "category",
        "retention_profile",
        "credit_limit",
        "credit_available",
        "is_qualified_supplier",
        "price_list",
        "is_active",
    )

    # Filtros laterales
    list_filter = (
        "is_active",
        "is_customer",
        "is_supplier",
        "is_public_entity",
        "company_type",
        "identification_type",
        "category",
        "retention_profile",
        "is_qualified_supplier",
        "price_list",
        "province",
        "city",
    )

    # Búsqueda rápida
    search_fields = (
        "code",
        "alt_code",
        "trade_name",
        "legal_name",
        "identification",
        "contact_name",
        "contact_email",
        "contact_phone",
        "city",
        "province",
    )

    # Orden por defecto en el admin
    ordering = ("trade_name", "legal_name", "code")

    # Campos solo lectura (si tu AuditModel los tiene, descomenta)
    # readonly_fields = ("created_at", "updated_at", "created_by", "updated_by")

    # Mejor UX en formularios largos
    list_per_page = 50
    save_on_top = True

    # Inlines (catálogo de productos para proveedores)
    inlines = [SupplierProductInline]

    # Layout del formulario
    fieldsets = (
        ("Identificación y tipo", {
            "fields": (
                ("code", "alt_code"),
                ("identification_type", "identification"),
                ("company_type", "category"),
                ("is_active",),
            )
        }),
        ("Nombres", {
            "fields": (
                "trade_name",
                "legal_name",
            )
        }),
        ("Uso en el sistema", {
            "fields": (
                ("is_customer", "is_supplier", "is_public_entity"),
            )
        }),
        ("Lista de precios (clientes)", {
            "fields": (
                "price_list",
            )
        }),
        ("Crédito y condiciones", {
            "fields": (
                ("credit_terms_days", "retention_profile"),
                ("credit_limit", "credit_available", "credit_used"),
            )
        }),
        ("Ubicación", {
            "fields": (
                "branch_name",
                "address",
                ("city", "province", "country"),
            )
        }),
        ("Contacto", {
            "fields": (
                "contact_name",
                ("contact_email", "contact_phone"),
                "website",
            )
        }),
        ("Calificación ISO 13485 (proveedores)", {
            "fields": (
                "is_qualified_supplier",
                "qualification_level",
                "qualification_date",
                "qualification_notes",
            )
        }),
        ("Notas", {
            "fields": ("notes",)
        }),
    )

    # Acciones útiles
    actions = [
        "mark_active",
        "mark_inactive",
        "mark_as_customer",
        "mark_as_supplier",
        "mark_as_qualified_supplier",
        "unmark_as_qualified_supplier",
    ]

    @admin.action(description="Marcar como Activo")
    def mark_active(self, request, queryset):
        queryset.update(is_active=True)

    @admin.action(description="Marcar como Inactivo")
    def mark_inactive(self, request, queryset):
        queryset.update(is_active=False)

    @admin.action(description="Marcar como Cliente")
    def mark_as_customer(self, request, queryset):
        queryset.update(is_customer=True)

    @admin.action(description="Marcar como Proveedor")
    def mark_as_supplier(self, request, queryset):
        queryset.update(is_supplier=True)

    @admin.action(description="Marcar como Proveedor calificado ISO 13485")
    def mark_as_qualified_supplier(self, request, queryset):
        queryset.update(is_qualified_supplier=True)

    @admin.action(description="Quitar Proveedor calificado ISO 13485")
    def unmark_as_qualified_supplier(self, request, queryset):
        queryset.update(is_qualified_supplier=False)


@admin.register(SupplierProduct)
class SupplierProductAdmin(admin.ModelAdmin):
    """Admin para gestionar catálogo de productos por proveedor"""
    list_display = [
        "supplier",
        "product",
        "supplier_unit_price",
        "minimum_order_quantity",
        "lead_time_days",
        "is_preferred",
    ]
    list_filter = ["is_preferred", "supplier"]
    search_fields = [
        "supplier__trade_name",
        "product__code",
        "product__name",
        "supplier_product_code",
    ]
    autocomplete_fields = ["supplier", "product"]
    list_per_page = 50
