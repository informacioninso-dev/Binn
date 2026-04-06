from django.urls import path

from . import views

app_name = "crm"

urlpatterns = [
    path("", views.index, name="index"),
    path("nuevo/", views.create, name="create"),
    path("<int:pk>/editar/", views.edit, name="edit"),
]

