from django.urls import path

from . import views

app_name = "appointments"

urlpatterns = [
    path("", views.index, name="index"),
    path("nuevo/", views.create, name="create"),
    path("<int:pk>/editar/", views.edit, name="edit"),
    path("<int:pk>/accion/<slug:action>/", views.quick_action, name="quick_action"),
]
