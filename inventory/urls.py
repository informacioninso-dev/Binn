from django.urls import path

from . import views

app_name = "inventory"

urlpatterns = [
    path("", views.index, name="index"),
    path("items/nuevo/", views.item_create, name="item_create"),
    path("proveedores/", views.supplier_list, name="suppliers"),
    path("proveedores/nuevo/", views.supplier_create, name="supplier_create"),
    path("compras/", views.purchase_list, name="purchases"),
    path("compras/nueva/", views.purchase_create, name="purchase_create"),
    path("movimientos/nuevo/", views.movement_create, name="movement_create"),
]
