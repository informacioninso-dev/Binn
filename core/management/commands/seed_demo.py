from decimal import Decimal
import random
from django.core.management.base import BaseCommand
from django.utils import timezone

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
from partners.models import Partner, IdentificationType, PartnerCategory, CompanyType
from inventory.models import (
    Product,
    ProductType,
    Stock,
    Lot,
    LotBalance,
    InventoryMove,
    MovementTypes,
)
from sales.models import SaleOrder, SaleOrderLine, SaleOrderStatus, SaleInvoice, InvoiceStatus


class Command(BaseCommand):
    help = "Genera datos demo (random simple) para mostrar la app."

    def add_arguments(self, parser):
        parser.add_argument("--customers", type=int, default=100)
        parser.add_argument("--suppliers", type=int, default=100)
        parser.add_argument("--raw", type=int, default=60)
        parser.add_argument("--fg", type=int, default=30)
        parser.add_argument("--labels", type=int, default=30)
        parser.add_argument("--packs", type=int, default=30)
        parser.add_argument("--orders", type=int, default=50)
        parser.add_argument("--seed", type=int, default=20260201)

    def handle(self, *args, **options):
        rnd = random.Random(options["seed"])

        tax_iva12, _ = TaxScheme.objects.get_or_create(
            code="IVA12",
            defaults={
                "name": "IVA 12%",
                "rate": Decimal("12.00"),
                "is_active": True,
                "applies_sales": True,
                "applies_purchases": True,
            },
        )

        unit_kg, _ = Unit.objects.get_or_create(
            code="kg",
            defaults={
                "name": "Kilogramo",
                "category": UnitCategory.MASS,
                "factor_to_base": Decimal("1"),
                "is_active": True,
            },
        )
        unit_un, _ = Unit.objects.get_or_create(
            code="un",
            defaults={
                "name": "Unidad",
                "category": UnitCategory.COUNT,
                "factor_to_base": Decimal("1"),
                "is_active": True,
            },
        )
        unit_m, _ = Unit.objects.get_or_create(
            code="m",
            defaults={
                "name": "Metro",
                "category": UnitCategory.LENGTH,
                "factor_to_base": Decimal("1"),
                "is_active": True,
            },
        )

        wh_raw, _ = Warehouse.objects.get_or_create(
            code="BOD-MP",
            defaults={
                "name": "Bodega MP",
                "type": WarehouseType.RAW,
                "is_active": True,
                "is_default_for_raw": True,
            },
        )
        wh_fg, _ = Warehouse.objects.get_or_create(
            code="BOD-PT",
            defaults={
                "name": "Bodega PT",
                "type": WarehouseType.FINISHED,
                "is_active": True,
                "is_default_fg_released": True,
            },
        )

        loc_raw, _ = Location.objects.get_or_create(
            warehouse=wh_raw,
            code="EST-01-N1-A",
            defaults={"name": "Estante MP A", "row": "1", "rack": "1", "level": "1"},
        )
        loc_fg, _ = Location.objects.get_or_create(
            warehouse=wh_fg,
            code="EST-01-N1-B",
            defaults={"name": "Estante PT B", "row": "1", "rack": "2", "level": "1"},
        )

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

        customers = self._create_partners(
            rnd=rnd,
            count=options["customers"],
            prefix="CLI",
            is_customer=True,
            is_supplier=False,
        )
        suppliers = self._create_partners(
            rnd=rnd,
            count=options["suppliers"],
            prefix="PRV",
            is_customer=False,
            is_supplier=True,
        )

        products = []
        products += self._create_products(
            rnd=rnd,
            count=options["raw"],
            prefix="MP",
            product_type=ProductType.RAW,
            base_unit=unit_kg,
            tax_scheme=tax_iva12,
        )
        products += self._create_products(
            rnd=rnd,
            count=options["fg"],
            prefix="PT",
            product_type=ProductType.FG,
            base_unit=unit_un,
            tax_scheme=tax_iva12,
        )
        products += self._create_products(
            rnd=rnd,
            count=options["labels"],
            prefix="ETQ",
            product_type=ProductType.PACK,
            base_unit=unit_un,
            tax_scheme=tax_iva12,
        )
        products += self._create_products(
            rnd=rnd,
            count=options["packs"],
            prefix="EMP",
            product_type=ProductType.PACK,
            base_unit=unit_un,
            tax_scheme=tax_iva12,
        )

        self._seed_inventory(
            rnd=rnd,
            products=products,
            wh_raw=wh_raw,
            wh_fg=wh_fg,
            loc_raw=loc_raw,
            loc_fg=loc_fg,
            unit_un=unit_un,
        )

        self._seed_orders(
            rnd=rnd,
            orders_count=options["orders"],
            customers=customers,
            products=products,
        )

        self.stdout.write(self.style.SUCCESS("Seed demo completado."))

    def _create_partners(self, rnd, count, prefix, is_customer, is_supplier):
        existing = set(Partner.objects.filter(code__startswith=prefix).values_list("code", flat=True))
        created = []
        idx = 1
        while len(created) < count:
            code = f"{prefix}-{idx:04d}"
            idx += 1
            if code in existing:
                continue
            ident = f"{rnd.randint(1_000_000_000, 2_399_999_999)}"
            partner = Partner.objects.create(
                code=code,
                identification_type=IdentificationType.RUC,
                identification=ident,
                trade_name=f"{prefix} Empresa {code[-4:]}",
                legal_name=f"{prefix} Empresa {code[-4:]} S.A.",
                category=PartnerCategory.A if rnd.random() < 0.4 else PartnerCategory.B,
                company_type=CompanyType.COMPANY,
                is_customer=is_customer,
                is_supplier=is_supplier,
                credit_limit=Decimal("5000.00"),
                credit_available=Decimal("5000.00"),
                credit_used=Decimal("0.00"),
                credit_terms_days=30,
                city="Quito",
                province="Pichincha",
                country="Ecuador",
                contact_name=f"Contacto {code[-4:]}",
                contact_email=f"{code.lower()}@demo.com",
                contact_phone=f"09{rnd.randint(10000000, 99999999)}",
                is_active=True,
            )
            created.append(partner)
        return created

    def _create_products(self, rnd, count, prefix, product_type, base_unit, tax_scheme):
        existing = set(Product.objects.filter(code__startswith=prefix).values_list("code", flat=True))
        created = []
        idx = 1
        while len(created) < count:
            code = f"{prefix}-{idx:04d}"
            idx += 1
            if code in existing:
                continue
            product = Product.objects.create(
                product_type=product_type,
                code=code,
                name=f"{prefix} Producto {code[-4:]}",
                base_unit=base_unit,
                unit_price=Decimal(str(rnd.randint(5, 80))) + Decimal("0.99"),
                unit_cost=Decimal(str(rnd.randint(2, 50))) + Decimal("0.50"),
                tax_scheme=tax_scheme,
                provider="Proveedor demo",
                category=prefix,
                brand="CyC",
                is_active=True,
            )
            created.append(product)
        return created

    def _seed_inventory(self, rnd, products, wh_raw, wh_fg, loc_raw, loc_fg, unit_un):
        for product in products:
            Stock.objects.get_or_create(product=product, defaults={"quantity": Decimal("0")})
            is_fg = product.product_type == ProductType.FG
            wh = wh_fg if is_fg else wh_raw
            loc = loc_fg if is_fg else loc_raw
            lot_code = f"{product.code}-{rnd.randint(1000, 9999)}"
            lot, _ = Lot.objects.get_or_create(
                product=product,
                internal_lot=lot_code,
                defaults={
                    "quantity_initial": Decimal(str(rnd.randint(20, 200))),
                    "warehouse": wh,
                    "location": loc,
                    "origin_reference": "SEED",
                },
            )
            qty = Decimal(str(rnd.randint(10, 200)))
            LotBalance.objects.get_or_create(
                lot=lot,
                location=loc,
                defaults={"warehouse": wh, "qty": qty},
            )
            Stock.objects.filter(product=product).update(quantity=qty)
            InventoryMove.objects.create(
                product=product,
                lot=lot,
                movement_type=MovementTypes.IN,
                quantity=qty,
                unit_displayed=unit_un,
                quantity_displayed=qty,
                unit_cost=product.unit_cost or Decimal("1.00"),
                reference="SEED",
                warehouse=wh,
                location=loc,
                area="Bodega",
            )

    def _seed_orders(self, rnd, orders_count, customers, products):
        if not customers or not products:
            return
        for _ in range(orders_count):
            customer = rnd.choice(customers)
            order = SaleOrder.objects.create(
                client=customer,
                status=rnd.choice(
                    [SaleOrderStatus.PENDING, SaleOrderStatus.CONFIRMED, SaleOrderStatus.DISPATCHED]
                ),
                delivery_date=timezone.now().date(),
                notes="Pedido demo",
                payment_method="Transferencia",
            )
            lines_count = rnd.randint(1, 4)
            for _ in range(lines_count):
                product = rnd.choice(products)
                qty = Decimal(str(rnd.randint(1, 20)))
                price = product.unit_price or Decimal("10.00")
                SaleOrderLine.objects.create(
                    order=order,
                    product=product,
                    quantity=qty,
                    unit_price=price,
                    total_price=qty * price,
                )

            if order.status == SaleOrderStatus.DISPATCHED:
                sequential = f"{rnd.randint(1, 999999999):09d}"
                SaleInvoice.objects.create(
                    order=order,
                    establishment="001",
                    emission_point="001",
                    sequential=sequential,
                    access_key=f"9{sequential}{rnd.randint(10**20, 10**21-1)}",
                    buyer_identification=customer.identification,
                    buyer_legal_name=customer.legal_name,
                    buyer_address=customer.address or "Quito",
                    status=InvoiceStatus.DRAFT,
                    total_amount=order.get_total(),
                )
