from django.urls import path

from . import views

app_name = "tenants"

urlpatterns = [
    path("", views.TenantListView.as_view(), name="list"),
    path("mis-accesos/", views.TenantAccessListView.as_view(), name="access_list"),
    path("volver-a-admin/", views.ReturnToPlatformView.as_view(), name="return_to_platform"),
    path("nuevo/", views.TenantCreateView.as_view(), name="create"),
    path("<int:pk>/", views.TenantDetailView.as_view(), name="detail"),
    path("<int:pk>/usuarios/", views.TenantAccessAdminView.as_view(), name="access_admin"),
    path("<int:pk>/health/", views.TenantHealthView.as_view(), name="health"),
    path("<int:pk>/editar/", views.TenantEditView.as_view(), name="edit"),
    path("<int:pk>/switch/", views.TenantSwitchView.as_view(), name="switch"),
    path("<int:pk>/toggle/", views.TenantToggleActiveView.as_view(), name="toggle_active"),
    path("miembro/<int:pk>/toggle/", views.MembershipToggleView.as_view(), name="membership_toggle"),
    path("miembro/<int:pk>/eliminar/", views.MembershipDeleteView.as_view(), name="membership_delete"),
]
