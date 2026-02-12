from django.urls import path
from procurement import views
from procurement import exports


app_name = "procurement"

urlpatterns = [
    path("orders/", views.PurchaseOrderListView.as_view(), name="order_list"),
    path("orders/new/", views.PurchaseOrderCreateView.as_view(), name="order_create"),
    path("orders/<int:pk>/edit/", views.PurchaseOrderUpdateView.as_view(), name="order_update"),

    # AJAX Endpoints
    path("ajax/supplier/<int:supplier_id>/products/", views.get_supplier_products_ajax, name="ajax_supplier_products"),

    # Recepciones de materia prima
    path("receptions/", views.RawMaterialReceptionListView.as_view(), name="receptions_list"),
    path("receptions/new/", views.RawMaterialReceptionCreateView.as_view(), name="receptions_create"),

    # Exportaciones — listado
    path("receptions/export/pdf/", exports.ReceptionListPDFView.as_view(), name="receptions_list_pdf"),
    path("receptions/export/excel/", exports.ReceptionListExcelView.as_view(), name="receptions_list_excel"),

    # Exportaciones — detalle individual
    path("receptions/<int:pk>/export/pdf/", exports.ReceptionDetailPDFView.as_view(), name="reception_detail_pdf"),
    path("receptions/<int:pk>/export/excel/", exports.ReceptionDetailExcelView.as_view(), name="reception_detail_excel"),

    # Exportaciones — órdenes de compra
    path("orders/export/pdf/", exports.PurchaseOrderListPDFView.as_view(), name="order_list_pdf"),
    path("orders/export/excel/", exports.PurchaseOrderListExcelView.as_view(), name="order_list_excel"),
    path("orders/<int:pk>/export/pdf/", exports.PurchaseOrderDetailPDFView.as_view(), name="order_detail_pdf"),
    path("orders/<int:pk>/export/excel/", exports.PurchaseOrderDetailExcelView.as_view(), name="order_detail_excel"),
]
