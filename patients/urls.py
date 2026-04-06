from django.urls import path

from . import views

app_name = "patients"

urlpatterns = [
    path("", views.index, name="index"),
    path("nuevo/", views.create, name="create"),
    path("<int:pk>/", views.detail, name="detail"),
    path("<int:pk>/editar/", views.edit, name="edit"),
]
