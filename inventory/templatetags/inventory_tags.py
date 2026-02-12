from django import template
from inventory.models import Product, ProductType

register = template.Library()


@register.simple_tag
def get_finished_products():
    """Obtiene todos los productos terminados activos."""
    return Product.objects.filter(
        is_active=True,
        product_type=ProductType.FG
    ).order_by('code')


@register.simple_tag
def get_all_products():
    """Obtiene todos los productos activos (MP, WIP, FG)."""
    return Product.objects.filter(
        is_active=True
    ).order_by('product_type', 'code')
