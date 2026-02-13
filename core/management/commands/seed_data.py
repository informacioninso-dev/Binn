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
        units_data = [
            # Masa
            ("kg", "Kilogramo", UnitCategory.MASS, Decimal("1")),
            ("g", "Gramo", UnitCategory.MASS, Decimal("0.001")),
            ("lb", "Libra", UnitCategory.MASS, Decimal("0.4536")),
            ("oz", "Onza", UnitCategory.MASS, Decimal("0.02835")),
            # Conteo
            ("un", "Unidad", UnitCategory.COUNT, Decimal("1")),
            ("caja", "Caja", UnitCategory.COUNT, Decimal("1")),
            ("rollo", "Rollo", UnitCategory.COUNT, Decimal("1")),
            ("par", "Par", UnitCategory.COUNT, Decimal("1")),
            ("paq", "Paquete", UnitCategory.COUNT, Decimal("1")),
            # Longitud
            ("m", "Metro", UnitCategory.LENGTH, Decimal("1")),
            ("cm", "Centímetro", UnitCategory.LENGTH, Decimal("0.01")),
            ("mm", "Milímetro", UnitCategory.LENGTH, Decimal("0.001")),
            ("pulg", "Pulgada", UnitCategory.LENGTH, Decimal("0.0254")),
            # Volumen
            ("L", "Litro", UnitCategory.VOLUME, Decimal("1")),
            ("mL", "Mililitro", UnitCategory.VOLUME, Decimal("0.001")),
            ("gal", "Galón", UnitCategory.VOLUME, Decimal("3.7854")),
            # Área
            ("m2", "Metro cuadrado", UnitCategory.AREA, Decimal("1")),
        ]
        for code, name, category, factor in units_data:
            unit, created = Unit.objects.get_or_create(
                code=code,
                defaults={
                    "name": name,
                    "category": category,
                    "factor_to_base": factor,
                    "is_active": True,
                },
            )
            status = "creada" if created else "ya existía"
            self.stdout.write(self.style.SUCCESS(f"Unidad {status}: {unit}"))

        # Bodegas mínimas
        warehouses_data = [
            ("BOD-CUA", "Cuarentena", WarehouseType.QUARANTINE, True, False, False),
            ("BOD-MP", "Bodega de Materia Prima", WarehouseType.RAW, False, True, False),
            ("BOD-SE", "Bodega de Semielaborado", WarehouseType.WIP, False, False, False),
            ("BOD-PT", "Bodega de Producto Terminado", WarehouseType.FINISHED, False, False, True),
            ("BOD-SCR", "Bodega de Scrap / Rechazo", WarehouseType.SCRAP, False, False, False),
            ("BOD-RET", "Retiro de Mercado", WarehouseType.RECALL, False, False, False),
            ("BOD-DEV", "Devoluciones de Clientes", WarehouseType.RETURNS, False, False, False),
            ("BOD-DES", "Zona de Predespacho", WarehouseType.STAGING, False, False, False),
            ("BOD-MUE", "Muestras / Retención", WarehouseType.SAMPLES, False, False, False),
            ("BOD-EMP", "Material de Empaque", WarehouseType.PACK, False, False, False),
        ]
        warehouses = {}
        for code, name, wtype, is_quarantine, is_raw, is_fg in warehouses_data:
            wh, created = Warehouse.objects.get_or_create(
                code=code,
                defaults={
                    "name": name,
                    "type": wtype,
                    "is_active": True,
                    "is_default_quarantine": is_quarantine,
                    "is_default_for_raw": is_raw,
                    "is_default_fg_released": is_fg,
                },
            )
            warehouses[code] = wh
            status = "creada" if created else "ya existía"
            self.stdout.write(self.style.SUCCESS(f"Bodega {status}: {wh}"))

        # Ubicaciones mínimas (1 por bodega)
        for code, wh in warehouses.items():
            loc_code = f"{code}-LOC-01"
            loc, created = Location.objects.get_or_create(
                warehouse=wh,
                code=loc_code,
                defaults={
                    "name": f"Ubicación principal - {wh.name}",
                    "description": f"Ubicación por defecto de {wh.name}",
                    "row": "1",
                    "rack": "1",
                    "level": "1",
                    "is_active": True,
                },
            )
            status = "creada" if created else "ya existía"
            self.stdout.write(self.style.SUCCESS(f"Ubicación {status}: {loc}"))

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
