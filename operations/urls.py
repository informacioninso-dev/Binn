from django.urls import path

from . import views

app_name = "operations"

urlpatterns = [
    path("", views.index, name="index"),
    path("sedes/", views.location_list, name="locations"),
    path("sedes/nueva/", views.location_create, name="location_create"),
    path("comisiones/", views.commission_list, name="commissions"),
    path("comisiones/generar/", views.commission_generate, name="commission_generate"),
    path("comisiones/esquemas/nuevo/", views.commission_scheme_create, name="commission_scheme_create"),
    path("automatizaciones/", views.automation_list, name="automations"),
    path("automatizaciones/nueva/", views.automation_create, name="automation_create"),
    path("automatizaciones/<int:pk>/ejecutar/", views.automation_run, name="automation_run"),
    path("integraciones/", views.integration_list, name="integrations"),
    path("integraciones/nueva/", views.integration_create, name="integration_create"),
]
