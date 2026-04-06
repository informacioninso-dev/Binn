from django.urls import include, path
from django.conf import settings
from django.conf.urls.static import static
from django.contrib.auth import views as auth_views
from django.contrib.staticfiles.urls import staticfiles_urlpatterns

from tenants import views as tenant_views

urlpatterns = [
    path("", tenant_views.TenantAccessListView.as_view(), name="dashboard"),
    path("health/", tenant_views.SystemHealthView.as_view(), name="health"),
    path("tenants/", include(("tenants.urls", "tenants"), namespace="tenants")),

    path("accounts/login/", tenant_views.TenantLoginView.as_view(), name="login"),
    path("accounts/logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("accounts/password/change/", auth_views.PasswordChangeView.as_view(template_name="auth/password_change.html"), name="password_change"),
    path("accounts/password/change/done/", auth_views.PasswordChangeDoneView.as_view(template_name="auth/password_change_done.html"), name="password_change_done"),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += staticfiles_urlpatterns()
