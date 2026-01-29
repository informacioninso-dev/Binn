from django.contrib import admin
from.models import TaxScheme, Unit , UnitCategory, Warehouse, Location


# Register your models here.
admin.site.register(TaxScheme)
admin.site.register(Unit)
admin.site.register(Warehouse)
admin.site.register(Location)
