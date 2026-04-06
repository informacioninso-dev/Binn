from django.urls import path

from . import views

app_name = "clinical"

urlpatterns = [
    path("", views.index, name="index"),
    path("nuevo/", views.create, name="create"),
    path("<int:pk>/", views.detail, name="detail"),
    path("<int:pk>/editar/", views.edit, name="edit"),
    path("<int:pk>/diagnosticos/nuevo/", views.add_diagnosis, name="add_diagnosis"),
    path("<int:pk>/ordenes/nuevo/", views.add_order, name="add_order"),
    path("<int:pk>/recetas/nuevo/", views.add_prescription, name="add_prescription"),
    path("<int:pk>/documentos/nuevo/", views.add_document, name="add_document"),
]
