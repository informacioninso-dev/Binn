from django.urls import path
from . import views

app_name = 'production'   # <-- namespace
urlpatterns = [
    path('', views.index, name='index'),   # production:index
]
