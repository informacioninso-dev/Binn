"""
URL configuration for config project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from core import views
from django.contrib.auth import views as auth_views


urlpatterns = [
    path('admin/', admin.site.urls),
    path('', views.dashboard, name='dashboard'),
    path('inventory/', include(('inventory.urls', 'inventory'), namespace='inventory')),
    path('finance/', include(('finance.urls', 'finance'), namespace='finance')),
    path('sales/', include(('sales.urls', 'sales'), namespace='sales')),
    path('production/', include(('production.urls', 'production'), namespace='production')),
    path("core/", include("core.urls", namespace="core")),
    path('quality/', include('quality.urls',namespace="quality")),  

    # Auth (login/logout)
    path('accounts/login/',auth_views.LoginView.as_view(template_name='auth/login.html'),name='login'),
    path('accounts/logout/',auth_views.LogoutView.as_view(), name='logout'),

    # Cambio de contraseña (usuario logueado)
    path('accounts/password/change/', auth_views.PasswordChangeView.as_view(template_name='auth/password_change.html'), name='password_change'),
    path('accounts/password/change/done/', auth_views.PasswordChangeDoneView.as_view(template_name='auth/password_change_done.html'), name='password_change_done'),

    # Reset de contraseña (flujo por email)
    path('accounts/password/reset/', auth_views.PasswordResetView.as_view(
        template_name='auth/password_reset.html',
        email_template_name='auth/password_reset_email.txt',
        subject_template_name='auth/password_reset_subject.txt',
        success_url='/accounts/password/reset/done/'
    ), name='password_reset'),

    path('accounts/password/reset/done/', auth_views.PasswordResetDoneView.as_view(
        template_name='auth/password_reset_done.html'
    ), name='password_reset_done'),

    path('accounts/reset/<uidb64>/<token>/', auth_views.PasswordResetConfirmView.as_view(
        template_name='auth/password_reset_confirm.html',
        success_url='/accounts/reset/done/'
    ), name='password_reset_confirm'),
    
    path('accounts/reset/done/', auth_views.PasswordResetCompleteView.as_view(
        template_name='auth/password_reset_complete.html'
    ), name='password_reset_complete'),

    path("partners/", include("partners.urls", namespace="partners")),
    path("procurement/", include("procurement.urls", namespace="procurement")),

]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)


