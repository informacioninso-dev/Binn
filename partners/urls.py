# partners/urls.py
from django.urls import path
from .views import (
    PartnerListView,
    PartnerCreateView,
    PartnerUpdateView,
    PartnerCatalogView,
    partner_catalog_add_product,
    partner_catalog_delete_product,
    suggest_partner_code,
)

app_name = "partners"

urlpatterns = [
    path("", PartnerListView.as_view(), name="index"),
    path("nuevo/", PartnerCreateView.as_view(), name="create"),
    path("<int:pk>/editar/", PartnerUpdateView.as_view(), name="update"),
    path("<int:pk>/catalogo/", PartnerCatalogView.as_view(), name="catalog"),
    path("<int:partner_pk>/catalogo/agregar/", partner_catalog_add_product, name="catalog_add_product"),
    path("<int:partner_pk>/catalogo/<int:item_pk>/eliminar/", partner_catalog_delete_product, name="catalog_delete_product"),

    # AJAX
    path("ajax/suggest-code/", suggest_partner_code, name="ajax_suggest_code"),
]
