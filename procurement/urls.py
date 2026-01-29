from django.urls import path
from procurement  import views 


app_name = "procurement"

urlpatterns = [
    path("orders/", views.PurchaseOrderListView.as_view(), name="order_list"),
    path("orders/new/", views.PurchaseOrderCreateView.as_view(), name="order_create"),
    path("orders/<int:pk>/edit/", views.PurchaseOrderUpdateView.as_view(), name="order_update"),

    # Recepciones de materia prima
    path("receptions/", views.RawMaterialReceptionListView.as_view(), name="receptions_list"),
    path("receptions/new/", views.RawMaterialReceptionCreateView.as_view(), name="receptions_create"),
    
]
