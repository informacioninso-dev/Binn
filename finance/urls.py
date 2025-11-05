from django.urls import path
from . import views

app_name = 'finance'   # <-- REGISTRA EL NAMESPACE
urlpatterns = [
    path('', views.index, name='index'),
]
