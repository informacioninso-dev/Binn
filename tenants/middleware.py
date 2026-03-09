from django.conf import settings
from django.contrib import messages
from django.contrib.auth import logout
from django.shortcuts import redirect

from .models import TenantMembership


class TenantAccessMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self._enforce(request)
        if response is not None:
            return response
        return self.get_response(request)

    def _enforce(self, request):
        tenant = getattr(request, "tenant", None)
        if not tenant:
            return None

        if tenant.schema_name == settings.PUBLIC_SCHEMA_NAME:
            return None

        user = getattr(request, "user", None)
        if user is None or not user.is_authenticated:
            return None

        if user.is_superuser:
            return None

        allowed = TenantMembership.objects.filter(
            tenant=tenant,
            user=user,
            is_active=True,
        ).exists()

        if not allowed:
            logout(request)
            messages.error(request, "No tienes acceso a esta clinica.")
            return redirect(settings.LOGIN_URL)

        return None
