# sales/services.py



from .models import SaleOrder, SaleOrderLine
from inventory.models import Product, Lot

def confirm_order_service(order):
    """
    Lógica para confirmar el pedido.
    Cambia el estado del pedido a 'CONFIRMED'.
    """
    order.status = 'CONFIRMED'
    order.save()
    return order

def add_product_to_order(order, product_id, quantity, unit_price):
    """
    Agrega un producto a una orden de venta.
    """
    product = Product.objects.get(id=product_id)
    total_price = quantity * unit_price
    line = SaleOrderLine(order=order, product=product, quantity=quantity, 
                         unit_price=unit_price, total_price=total_price)
    line.save()
    return line

