from django.urls import path

from .views import CorporateGroupDashboardView, CorporateGroupReportsView, CorporateGroupTenantSwitchView


app_name = "consolidation"

urlpatterns = [
    path("groups/<int:pk>/", CorporateGroupDashboardView.as_view(), name="group_dashboard"),
    path("groups/<int:pk>/reports/", CorporateGroupReportsView.as_view(), name="group_reports"),
    path("groups/<int:group_pk>/tenants/<int:tenant_pk>/switch/", CorporateGroupTenantSwitchView.as_view(), name="group_tenant_switch"),
]
