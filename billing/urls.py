from django.urls import path
from . import views

app_name = 'billing'  # <-- namespace
urlpatterns = [
    path('', views.index, name='index'),  # billing:index
]
