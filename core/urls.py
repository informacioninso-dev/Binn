from django.urls import path
from core.views import (
    dashboard,
    SettingsView,
    TaxSchemeCreateView, TaxSchemeListView,
    UnitCreateView, UnitListView,
    WarehouseCreateView, WarehouseListView,
    LocationCreateView, LocationListView,
    CompanyConfigView,
)

app_name = "core"
urlpatterns = [
    path('dashboard/', dashboard),
    path("settings/", SettingsView.as_view(), name="settings"),
    path('taxscheme/create/', TaxSchemeCreateView.as_view(), name='taxscheme_create'),
    path('taxscheme/list/', TaxSchemeListView.as_view(), name='taxscheme_list'),
    path('unit/create/', UnitCreateView.as_view(), name='unit_create'),
    path('unit/list/', UnitListView.as_view(), name='unit_list'),
    path('warehouse/create/', WarehouseCreateView.as_view(), name='warehouse_create'),
    path('warehouse/list/', WarehouseListView.as_view(), name='warehouse_list'),
    path('location/create/', LocationCreateView.as_view(), name='location_create'),
    path('location/list/', LocationListView.as_view(), name='location_list'),
    path('company/', CompanyConfigView.as_view(), name='company_config'),
]
