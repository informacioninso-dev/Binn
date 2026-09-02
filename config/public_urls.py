from django.urls import include, path
from django.conf import settings
from django.conf.urls.static import static
from django.contrib.auth import views as auth_views
from django.contrib.staticfiles.urls import staticfiles_urlpatterns

from identity.forms import StrictPasswordResetForm
from tenants import views as tenant_views

urlpatterns = [
    path("", tenant_views.TenantAccessListView.as_view(), name="dashboard"),
    path("health/", tenant_views.SystemHealthView.as_view(), name="health"),
    path("health/runtime/", tenant_views.SystemRuntimeHealthView.as_view(), name="health_runtime"),
    path("tenants/", include(("tenants.urls", "tenants"), namespace="tenants")),
    path("governance/", include(("governance.urls", "governance"), namespace="governance")),
    path("consolidation/", include(("consolidation.urls", "consolidation"), namespace="consolidation")),

    path("accounts/login/", tenant_views.TenantLoginView.as_view(), name="login"),
    path("accounts/logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("accounts/password/change/", auth_views.PasswordChangeView.as_view(template_name="auth/password_change.html"), name="password_change"),
    path("accounts/password/change/done/", auth_views.PasswordChangeDoneView.as_view(template_name="auth/password_change_done.html"), name="password_change_done"),
    path("accounts/password/reset/", auth_views.PasswordResetView.as_view(
        form_class=StrictPasswordResetForm,
        template_name="auth/password_reset.html",
        email_template_name="auth/password_reset_email.txt",
        subject_template_name="auth/password_reset_subject.txt",
        success_url="/accounts/password/reset/done/",
    ), name="password_reset"),
    path("accounts/password/reset/done/", auth_views.PasswordResetDoneView.as_view(
        template_name="auth/password_reset_done.html",
    ), name="password_reset_done"),
    path("accounts/reset/<uidb64>/<token>/", auth_views.PasswordResetConfirmView.as_view(
        template_name="auth/password_reset_confirm.html",
        success_url="/accounts/reset/done/",
    ), name="password_reset_confirm"),
    path("accounts/reset/done/", auth_views.PasswordResetCompleteView.as_view(
        template_name="auth/password_reset_complete.html",
    ), name="password_reset_complete"),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += staticfiles_urlpatterns()
