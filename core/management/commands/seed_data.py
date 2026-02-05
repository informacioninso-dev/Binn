from decimal import Decimal
from django.core.management.base import BaseCommand
from core.models import (
    CompanyConfig,
    SRIEnvironment,
    TaxScheme,
    Unit,
    UnitCategory,
    Warehouse,
    WarehouseType,
    Location,
)
from sales.models import ReturnReason, ReturnReasonType
from quality.models import RecallOrigin, RecallOriginType


class Command(BaseCommand):
    help = "Cargar datos base minimos para iniciar la configuracion del sistema."

    def handle(self, *args, **kwargs):
        # Empresa base (singleton)
        if not CompanyConfig.objects.exists():
            CompanyConfig.objects.create(
                ruc="1799999999001",
                legal_name="CyC Soluciones",
                trade_name="CyC Soluciones",
                address="Av. Principal 123, Quito",
                establishment_code="001",
                emission_point="001",
                obligated_accounting=True,
                environment=SRIEnvironment.PRUEBAS,
                emission_type="1",
            )
            self.stdout.write(self.style.SUCCESS("Empresa creada: CyC Soluciones"))

        # Esquemas tributarios base
        tax_scheme_iva12, _ = TaxScheme.objects.get_or_create(
            code="IVA12",
            defaults={
                "name": "IVA 12%",
                "rate": Decimal("12.00"),
                "is_active": True,
                "applies_sales": True,
                "applies_purchases": True,
            },
        )
        self.stdout.write(self.style.SUCCESS(f"Esquema tributario listo: {tax_scheme_iva12}"))

        tax_scheme_iva15, _ = TaxScheme.objects.get_or_create(
            code="IVA15",
            defaults={
                "name": "IVA 15%",
                "rate": Decimal("15.00"),
                "is_active": True,
                "applies_sales": True,
                "applies_purchases": True,
            },
        )
        self.stdout.write(self.style.SUCCESS(f"Esquema tributario listo: {tax_scheme_iva15}"))

        tax_scheme_iva0, _ = TaxScheme.objects.get_or_create(
            code="IVA0",
            defaults={
                "name": "IVA 0%",
                "rate": Decimal("0.00"),
                "is_active": True,
                "applies_sales": True,
                "applies_purchases": True,
            },
        )
        self.stdout.write(self.style.SUCCESS(f"Esquema tributario listo: {tax_scheme_iva0}"))

        # Unidades de medida base
        unit_kg, _ = Unit.objects.get_or_create(
            code="kg",
            defaults={
                "name": "Kilogramo",
                "category": UnitCategory.MASS,
                "factor_to_base": Decimal("1"),
                "is_active": True,
            },
        )
        self.stdout.write(self.style.SUCCESS(f"Unidad lista: {unit_kg}"))

        unit_un, _ = Unit.objects.get_or_create(
            code="un",
            defaults={
                "name": "Unidad",
                "category": UnitCategory.COUNT,
                "factor_to_base": Decimal("1"),
                "is_active": True,
            },
        )
        self.stdout.write(self.style.SUCCESS(f"Unidad lista: {unit_un}"))

        unit_m, _ = Unit.objects.get_or_create(
            code="m",
            defaults={
                "name": "Metro",
                "category": UnitCategory.LENGTH,
                "factor_to_base": Decimal("1"),
                "is_active": True,
            },
        )
        self.stdout.write(self.style.SUCCESS(f"Unidad lista: {unit_m}"))

        # Bodegas minimas
        warehouse_raw, _ = Warehouse.objects.get_or_create(
            code="BOD-MP",
            defaults={
                "name": "Bodega de Materia Prima",
                "type": WarehouseType.RAW,
                "is_active": True,
                "is_default_quarantine": False,
                "is_default_for_raw": True,
                "is_default_fg_released": False,
            },
        )
        self.stdout.write(self.style.SUCCESS(f"Bodega lista: {warehouse_raw}"))

        warehouse_finished, _ = Warehouse.objects.get_or_create(
            code="BOD-PT",
            defaults={
                "name": "Bodega de Producto Terminado",
                "type": WarehouseType.FINISHED,
                "is_active": True,
                "is_default_quarantine": False,
                "is_default_for_raw": False,
                "is_default_fg_released": True,
            },
        )
        self.stdout.write(self.style.SUCCESS(f"Bodega lista: {warehouse_finished}"))

        # Ubicaciones minimas
        location_01, _ = Location.objects.get_or_create(
            warehouse=warehouse_raw,
            code="EST-01-N1-A",
            defaults={
                "name": "Estante 1 - Nivel 1 - A",
                "description": "Primer estante de materia prima",
                "row": "1",
                "rack": "1",
                "level": "1",
                "is_active": True,
            },
        )
        self.stdout.write(self.style.SUCCESS(f"Ubicacion lista: {location_01}"))

        location_02, _ = Location.objects.get_or_create(
            warehouse=warehouse_finished,
            code="EST-01-N1-B",
            defaults={
                "name": "Estante 2 - Nivel 1 - B",
                "description": "Estante para productos terminados",
                "row": "1",
                "rack": "2",
                "level": "1",
                "is_active": True,
            },
        )
        self.stdout.write(self.style.SUCCESS(f"Ubicacion lista: {location_02}"))

        # Motivos de devolución - Comerciales
        commercial_reasons = [
            ("COM-001", "Cambio de producto", "Cliente solicita cambio por otro producto"),
            ("COM-002", "Error en pedido", "Producto no corresponde al pedido del cliente"),
            ("COM-003", "Exceso de inventario", "Cliente devuelve por exceso de stock"),
            ("COM-004", "Desistimiento de compra", "Cliente desiste de la compra"),
        ]
        for code, name, desc in commercial_reasons:
            reason, created = ReturnReason.objects.get_or_create(
                code=code,
                defaults={
                    "name": name,
                    "reason_type": ReturnReasonType.COMMERCIAL,
                    "description": desc,
                    "is_active": True,
                },
            )
            if created:
                self.stdout.write(self.style.SUCCESS(f"Motivo de devolución creado: {reason}"))

        # Motivos de devolución - No conformidad
        nc_reasons = [
            ("NC-001", "Producto dañado", "Producto llegó dañado o en mal estado"),
            ("NC-002", "Producto vencido", "Producto entregado con fecha de vencimiento expirada"),
            ("NC-003", "Defecto de fabricación", "Producto presenta defectos de manufactura"),
            ("NC-004", "Especificaciones incorrectas", "Producto no cumple especificaciones técnicas"),
            ("NC-005", "Contaminación", "Producto presenta signos de contaminación"),
        ]
        for code, name, desc in nc_reasons:
            reason, created = ReturnReason.objects.get_or_create(
                code=code,
                defaults={
                    "name": name,
                    "reason_type": ReturnReasonType.NON_CONFORMITY,
                    "description": desc,
                    "is_active": True,
                },
            )
            if created:
                self.stdout.write(self.style.SUCCESS(f"Motivo de devolución creado: {reason}"))

        # Orígenes de retiro de mercado
        recall_origins = [
            ("RO-001", "Producto no conforme detectado", RecallOriginType.NON_CONFORMITY,
             "Producto que no cumple especificaciones de calidad"),
            ("RO-002", "Contaminación detectada", RecallOriginType.HEALTH_RISK,
             "Contaminación microbiológica, química o física"),
            ("RO-003", "Alérgeno no declarado", RecallOriginType.HEALTH_RISK,
             "Presencia de alérgenos no indicados en etiqueta"),
            ("RO-004", "Notificación ARCSA", RecallOriginType.REGULATORY,
             "Retiro ordenado por autoridad sanitaria"),
            ("RO-005", "Defecto de envasado", RecallOriginType.QUALITY_ISSUE,
             "Problema con el empaque o sellado del producto"),
            ("RO-006", "Error de etiquetado", RecallOriginType.QUALITY_ISSUE,
             "Información incorrecta en etiqueta"),
            ("RO-007", "Reclamo de cliente grave", RecallOriginType.OTHER,
             "Reclamo que requiere investigación y retiro preventivo"),
        ]
        for code, name, origin_type, desc in recall_origins:
            origin, created = RecallOrigin.objects.get_or_create(
                code=code,
                defaults={
                    "name": name,
                    "origin_type": origin_type,
                    "description": desc,
                    "is_active": True,
                },
            )
            if created:
                self.stdout.write(self.style.SUCCESS(f"Origen de retiro creado: {origin}"))

        self.stdout.write(self.style.SUCCESS("Datos iniciales cargados correctamente."))
