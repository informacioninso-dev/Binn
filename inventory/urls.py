
from django.urls import path
from . import views 


app_name = "inventory"

urlpatterns = [
  
    # Productos
    path("", views.ProductListView.as_view(), name="index"),
    path("nuevo/", views.ProductCreateView.as_view(), name="product_create"),
    path("<int:pk>/editar/", views.ProductUpdateView.as_view(), name="product_update"),
    path("<int:pk>/toggle/", views.ProductToggleActiveView.as_view(), name="product_toggle"),

    # Movimientos (Kardex)
    path("movements/", views.InventoryMoveListView.as_view(), name="movements_list"),
    path("movements/new/", views.InventoryMoveCreateView.as_view(), name="movements_create"),

    # Ubicación y transferencia de lotes
    path("lots/<int:pk>/location/", views.LotLocationUpdateView.as_view(), name="lot_location_update"),
    path("lots/<int:pk>/transfer/", views.LotTransferView.as_view(), name="lot_transfer"),

]
