from django.urls import path

from . import views

app_name = "billing"

urlpatterns = [
    path("", views.index, name="index"),
    path("nuevo/", views.create, name="create"),
    path("facturas/", views.invoice_list, name="invoices"),
    path("facturas/nueva/", views.invoice_create, name="invoice_create"),
    path("facturas/<int:pk>/", views.invoice_detail, name="invoice_detail"),
    path("convenios/", views.agreement_list, name="agreements"),
    path("convenios/nuevo/", views.agreement_create, name="agreement_create"),
]
