from django.db import models
from core.models import AuditModel

class Product(AuditModel):
    code = models.CharField(max_length=50, unique=True)
    code_2 = models.CharField(max_length=50, blank=True, null=True)
    name = models.CharField(max_length=200)
    unit_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)  # Permitir nulo
    tax_rate = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    unit_cost = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    provider = models.CharField(max_length=200, blank=True, null=True)
    category = models.CharField(max_length=100, blank=True, null=True)
    brand = models.CharField(max_length=100, blank=True, null=True)
    unit = models.CharField(max_length=20, default='unidad', null=True)
    is_active = models.BooleanField(default=True, null=True)

    class Meta:
        ordering = ["name"]
        verbose_name = "Producto"
        verbose_name_plural = "Productos"
        permissions = [
            ("export_product", "Puede exportar productos"),
        ]

    def __str__(self):
        return f"{self.code} - {self.name}"

