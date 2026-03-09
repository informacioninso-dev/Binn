from django.urls import path

from . import views

app_name = "patients"

urlpatterns = [
    path("", views.index, name="index"),
]
