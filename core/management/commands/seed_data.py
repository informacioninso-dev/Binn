from django.core.management.base import BaseCommand
from core.models import TaxScheme, Unit, Warehouse, WarehouseType, Location
from django.utils import timezone
from decimal import Decimal

class Command(BaseCommand):
    help = 'Cargar datos iniciales (seed) en las tablas de la base de datos.'

    def handle(self, *args, **kwargs):
        # Crear un esquema tributario
        tax_scheme_iva = TaxScheme.objects.create(
            code="IVA12",
            name="IVA 12%",
            rate=Decimal('12.00'),
            is_active=True,
            applies_sales=True,
            applies_purchases=True
        )
        self.stdout.write(self.style.SUCCESS(f"Esquema tributario creado: {tax_scheme_iva}"))
        tax_scheme_iva = TaxScheme.objects.create(
            code="IVA15",
            name="IVA 15%",
            rate=Decimal('15.00'),
            is_active=True,
            applies_sales=True,
            applies_purchases=True
        )
        self.stdout.write(self.style.SUCCESS(f"Esquema tributario creado: {tax_scheme_iva}"))
        

        # Crear unidades de medida
        unit_kg = Unit.objects.create(
            code="kg",
            name="Kilogramo",
            category="COUNT",  # Asumimos que COUNT es lo adecuado
            factor_to_base=Decimal('1000'),
            is_active=True
        )
        self.stdout.write(self.style.SUCCESS(f"Unidad creada: {unit_kg}"))

        unit_m = Unit.objects.create(
            code="m",
            name="Metro",
            category="LENGTH",
            factor_to_base=Decimal('1'),
            is_active=True
        )
        self.stdout.write(self.style.SUCCESS(f"Unidad creada: {unit_m}"))

        # Crear bodegas
        warehouse_raw = Warehouse.objects.create(
            code="BOD-MP",
            name="Bodega de Materia Prima",
            type=WarehouseType.RAW,
            is_active=True,
            is_default_quarantine=False,
            is_default_for_raw=True,
            is_default_fg_released=False
        )
        self.stdout.write(self.style.SUCCESS(f"Bodega creada: {warehouse_raw}"))

        warehouse_finished = Warehouse.objects.create(
            code="BOD-PT",
            name="Bodega de Producto Terminado",
            type=WarehouseType.FINISHED,
            is_active=True,
            is_default_quarantine=False,
            is_default_for_raw=False,
            is_default_fg_released=True
        )
        self.stdout.write(self.style.SUCCESS(f"Bodega creada: {warehouse_finished}"))

        # Crear ubicaciones en bodega
        location_01 = Location.objects.create(
            warehouse=warehouse_raw,
            code="EST-01-N1-A",
            name="Estante 1 - Nivel 1 - A",
            description="Primer estante de materia prima",
            row="1",
            rack="1",
            level="1",
            is_active=True
        )
        self.stdout.write(self.style.SUCCESS(f"Ubicación creada: {location_01}"))

        location_02 = Location.objects.create(
            warehouse=warehouse_finished,
            code="EST-01-N1-B",
            name="Estante 2 - Nivel 1 - B",
            description="Estante para productos terminados",
            row="1",
            rack="2",
            level="1",
            is_active=True
        )
        self.stdout.write(self.style.SUCCESS(f"Ubicación creada: {location_02}"))

        # Fin del seed
        self.stdout.write(self.style.SUCCESS("¡Datos iniciales cargados correctamente!"))
