# partners/urls.py
from django.urls import path
from .views import PartnerListView, PartnerCreateView, PartnerUpdateView

app_name = "partners"

urlpatterns = [
    path("", PartnerListView.as_view(), name="index"),
    path("nuevo/", PartnerCreateView.as_view(), name="create"),
    path("<int:pk>/editar/", PartnerUpdateView.as_view(), name="update"),
]
