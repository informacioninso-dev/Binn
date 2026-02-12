# sales/pricing_service.py
"""
Servicio de gestión de precios para clientes.
Maneja listas de precios personalizadas y precios base de productos.
"""

def get_product_price_for_customer(product_id, partner_id):
    """
    Obtiene el precio de un producto para un cliente específico.

    Orden de prioridad:
    1. Precio de la lista asignada al cliente
    2. Precio base del producto (fallback)

    Args:
        product_id: ID del producto
        partner_id: ID del socio/cliente

    Returns:
        Decimal: precio unitario
    """
    from partners.models import Partner
    from inventory.models import Product
    from sales.models import PriceListItem

    try:
        partner = Partner.objects.get(pk=partner_id)

        # Si el partner tiene lista de precios asignada
        if partner.price_list:
            try:
                item = PriceListItem.objects.get(
                    price_list=partner.price_list,
                    product_id=product_id
                )
                return item.unit_price
            except PriceListItem.DoesNotExist:
                pass

        # Fallback: precio base del producto
        product = Product.objects.get(pk=product_id)
        return product.unit_price

    except Partner.DoesNotExist:
        # Sin cliente, usar precio base
        product = Product.objects.get(pk=product_id)
        return product.unit_price


def get_pricelist_for_products(partner_id, product_type="FG"):
    """
    Obtiene un diccionario con precios de todos los productos para un cliente.

    Args:
        partner_id: ID del socio/cliente
        product_type: Tipo de producto (por defecto "FG" - Producto terminado)

    Returns:
        dict: {product_id: {"unit_price": Decimal, "code": str, "name": str, "stock": Decimal}}
    """
    from partners.models import Partner
    from inventory.models import Product, ProductType, Stock
    from sales.models import PriceListItem

    # Obtener productos activos
    products = Product.objects.filter(
        is_active=True,
        product_type=getattr(ProductType, product_type)
    )

    # Obtener stock
    stocks = {
        s.product_id: s.quantity
        for s in Stock.objects.filter(product__in=products)
    }

    # Construir diccionario base con precios estándar
    result = {}
    for p in products:
        result[str(p.pk)] = {
            "unit_price": str(p.unit_price or 0),
            "code": p.code,
            "name": p.name,
            "stock": str(stocks.get(p.pk, 0)),
        }

    # Sobrescribir con precios de lista si existe
    try:
        partner = Partner.objects.get(pk=partner_id)
        if partner.price_list:
            items = PriceListItem.objects.filter(
                price_list=partner.price_list,
                product__in=products
            ).select_related("product")

            for item in items:
                if str(item.product.pk) in result:
                    result[str(item.product.pk)]["unit_price"] = str(item.unit_price)

    except Partner.DoesNotExist:
        pass

    return result
