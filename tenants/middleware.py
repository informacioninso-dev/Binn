import logging
from uuid import uuid4

from django.conf import settings
from django.contrib import messages
from django.shortcuts import redirect
from django.urls import reverse

from .models import Domain, TenantMembership
from .request_context import reset_request_context, set_request_context


logger = logging.getLogger(__name__)


def build_public_app_url(request, view_name: str) -> str:
    path = reverse(view_name)
    public_domain = (
        Domain.objects.filter(
            tenant__schema_name=settings.PUBLIC_SCHEMA_NAME,
            is_primary=True,
        ).first()
        or Domain.objects.filter(tenant__schema_name=settings.PUBLIC_SCHEMA_NAME).order_by("id").first()
    )
    if not public_domain:
        return path

    scheme = "https" if request.is_secure() else "http"
    port = request.get_port()
    default_port = "443" if scheme == "https" else "80"
    host = public_domain.domain
    if port and port != default_port and ":" not in host:
        host = f"{host}:{port}"
    return f"{scheme}://{host}{path}"


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
        if not getattr(tenant, "is_active", True):
            logger.warning(
                "Intento de acceso a clinica desactivada.",
                extra={"tenant_schema": tenant.schema_name},
            )
            messages.error(request, "Esta clinica esta desactivada.")
            target_view = "dashboard" if user is not None and user.is_authenticated else "login"
            return redirect(build_public_app_url(request, target_view))

        if user is None or not user.is_authenticated:
            return None

        if user.is_superuser:
            return None

        membership = TenantMembership.objects.filter(
            tenant=tenant,
            user=user,
            is_active=True,
        ).first()

        if membership is None:
            logger.warning(
                "Usuario sin membresia intento acceder a clinica.",
                extra={
                    "tenant_schema": tenant.schema_name,
                    "actor_id": getattr(user, "pk", "-") or "-",
                },
            )
            messages.error(request, "No tienes acceso a esta clinica.")
            return redirect(build_public_app_url(request, "dashboard"))

        request.tenant_membership = membership
        return None


class RequestContextMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        tenant = getattr(request, "tenant", None)
        user = getattr(request, "user", None)
        request_id = request.headers.get("X-Request-ID") or uuid4().hex[:12]
        tenant_schema = getattr(tenant, "schema_name", settings.PUBLIC_SCHEMA_NAME)
        actor_id = str(getattr(user, "pk", "-") or "-")
        request.request_id = request_id
        tokens = set_request_context(
            request_id=request_id,
            tenant_schema=tenant_schema,
            actor_id=actor_id,
        )
        try:
            response = self.get_response(request)
        finally:
            reset_request_context(tokens)

        response["X-Request-ID"] = request_id
        return response
