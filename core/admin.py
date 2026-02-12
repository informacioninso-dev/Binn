from django.contrib import admin
from .models import TaxScheme, Unit, UnitCategory, Warehouse, Location, CompanyConfig


admin.site.register(TaxScheme)
admin.site.register(Unit)
@admin.register(Warehouse)
class WarehouseAdmin(admin.ModelAdmin):
    search_fields = ["code", "name"]


@admin.register(Location)
class LocationAdmin(admin.ModelAdmin):
    list_display = ["code", "warehouse", "row", "rack", "level", "is_active"]
    list_filter = ["warehouse", "is_active"]
    search_fields = ["code", "row", "rack", "level"]
    autocomplete_fields = ["warehouse"]
    readonly_fields = ["created_at", "updated_at", "created_by", "updated_by"]

    fieldsets = (
        ("Información básica", {
            "fields": ("warehouse", "code", "is_active")
        }),
        ("Ubicación física", {
            "fields": ("row", "rack", "level"),
            "description": "Especifica la posición dentro de la bodega (ej: Pasillo A, Rack 3, Nivel 2)"
        }),
        ("Auditoría", {
            "fields": ("created_at", "updated_at", "created_by", "updated_by"),
            "classes": ("collapse",)
        }),
    )


@admin.register(CompanyConfig)
class CompanyConfigAdmin(admin.ModelAdmin):
    fieldsets = (
        ("Datos del Emisor", {
            "fields": ("ruc", "legal_name", "trade_name", "address"),
        }),
        ("Numeración", {
            "fields": ("establishment_code", "emission_point"),
        }),
        ("Tributario", {
            "fields": ("special_taxpayer", "obligated_accounting"),
        }),
        ("SRI - Ambiente", {
            "fields": ("environment", "emission_type"),
            "description": "Ambiente 1 = Pruebas (celcer.sri.gob.ec), Ambiente 2 = Producción (cel.sri.gob.ec)",
        }),
        ("Certificado Digital", {
            "fields": ("certificate_file", "certificate_password"),
            "description": "Archivo .p12 y su contraseña para firma electrónica.",
        }),
        ("Logo", {
            "fields": ("logo",),
        }),
    )

    def has_add_permission(self, request):
        # Singleton: solo permitir agregar si no existe ninguno
        return not CompanyConfig.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False
