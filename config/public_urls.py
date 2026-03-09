from django.urls import include, path
from django.contrib.auth import views as auth_views

from tenants import views as tenant_views

urlpatterns = [
    path("", tenant_views.TenantAccessListView.as_view(), name="dashboard"),
    path("tenants/", include(("tenants.urls", "tenants"), namespace="tenants")),

    path("accounts/login/", tenant_views.TenantLoginView.as_view(), name="login"),
    path("accounts/logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("accounts/password/change/", auth_views.PasswordChangeView.as_view(template_name="auth/password_change.html"), name="password_change"),
    path("accounts/password/change/done/", auth_views.PasswordChangeDoneView.as_view(template_name="auth/password_change_done.html"), name="password_change_done"),
]
