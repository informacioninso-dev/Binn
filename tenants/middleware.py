import logging
from uuid import uuid4

from django.conf import settings
from django.contrib import messages
from django.db import connection
from django.shortcuts import redirect
from django.urls import reverse
from django.urls import set_urlconf

from access.runtime import build_access_subject, get_tenant_membership
from access.permissions import PERMISSION_TENANT_ACCESS
from access.services import load_active_session_context, resolve_request_access, set_consolidated_context
from access.resolvers import RequestAccessResolver

from .models import Domain
from .request_context import reset_request_context, set_request_context


logger = logging.getLogger(__name__)
LOCAL_PREVIEW_SESSION_KEY = "tenant_preview_schema"


def _request_hostname(request) -> str:
    return request.get_host().split(":")[0].lower()


def _is_local_preview_host(request) -> bool:
    return _request_hostname(request) in {"localhost", "127.0.0.1"}


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
                "Intento de acceso a tenant desactivado.",
                extra={"tenant_schema": tenant.schema_name},
            )
            messages.error(request, "Este tenant esta desactivado.")
            target_view = "dashboard" if user is not None and user.is_authenticated else "login"
            return redirect(build_public_app_url(request, target_view))

        if user is None or not user.is_authenticated:
            return None

        if user.is_superuser:
            return None

        membership = get_tenant_membership(tenant=tenant, user=user)
        decision = resolve_request_access(request, PERMISSION_TENANT_ACCESS)
        if decision is None and membership is None:
            logger.warning(
                "Usuario sin membresia intento acceder a tenant.",
                extra={
                    "tenant_schema": tenant.schema_name,
                    "actor_id": getattr(user, "pk", "-") or "-",
                },
            )
            messages.error(request, "No tienes acceso a este tenant.")
            return redirect(build_public_app_url(request, "dashboard"))
        if decision is not None and not decision.allowed:
            logger.warning(
                "Acceso al tenant rechazado por scope activo o governance.",
                extra={
                    "tenant_schema": tenant.schema_name,
                    "actor_id": getattr(user, "pk", "-") or "-",
                },
            )
            messages.error(request, "Tu contexto activo no permite entrar a este tenant.")
            return redirect(build_public_app_url(request, "dashboard"))
        if (
            decision is not None
            and decision.allowed
            and getattr(decision.scope, "value", "") == "consolidated"
            and getattr(request, "active_session_context", None) is not None
            and request.active_session_context.corporate_group_id
            and request.active_session_context.tenant_id != tenant.pk
        ):
            from governance.models import CorporateGroup

            group = CorporateGroup.objects.filter(pk=request.active_session_context.corporate_group_id).first()
            if group is not None:
                set_consolidated_context(request, group=group, tenant=tenant, reason="tenant_context_handoff")

        request.tenant_membership = membership
        return None


class LocalTenantPreviewMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        self._activate_local_preview(request)
        return self.get_response(request)

    def _activate_local_preview(self, request):
        tenant = getattr(request, "tenant", None)
        if (
            not settings.DEBUG
            or tenant is None
            or tenant.schema_name != settings.PUBLIC_SCHEMA_NAME
            or not _is_local_preview_host(request)
        ):
            return

        requested_schema = (request.GET.get("_tenant") or "").strip().lower()
        if requested_schema == settings.PUBLIC_SCHEMA_NAME:
            request.session.pop(LOCAL_PREVIEW_SESSION_KEY, None)
            return
        if requested_schema:
            request.session[LOCAL_PREVIEW_SESSION_KEY] = requested_schema

        preview_schema = (request.session.get(LOCAL_PREVIEW_SESSION_KEY) or "").strip().lower()
        if not preview_schema:
            return

        preview_tenant = Domain.objects.select_related("tenant").filter(
            tenant__schema_name=preview_schema,
            tenant__is_active=True,
        ).first()
        if preview_tenant is None:
            request.session.pop(LOCAL_PREVIEW_SESSION_KEY, None)
            return

        resolved_tenant = preview_tenant.tenant
        user = getattr(request, "user", None)
        if (
            user is not None
            and user.is_authenticated
            and not user.is_superuser
        ):
            membership = get_tenant_membership(tenant=resolved_tenant, user=user)
            if membership is None:
                original_tenant = request.tenant
                request.tenant = resolved_tenant
                request.access_subject = build_access_subject(user)
                request.active_session_context = getattr(request, "active_session_context", None) or load_active_session_context(request)
                if request.active_session_context is None:
                    request.tenant = original_tenant
                    request.session.pop(LOCAL_PREVIEW_SESSION_KEY, None)
                    return
                decision = RequestAccessResolver(request).resolve(
                    subject=request.access_subject,
                    context=request.active_session_context,
                    target_tenant_id=resolved_tenant.pk,
                    permission_code=PERMISSION_TENANT_ACCESS,
                )
                request.tenant = original_tenant
                if not decision.allowed:
                    request.session.pop(LOCAL_PREVIEW_SESSION_KEY, None)
                    return

        request.tenant = resolved_tenant
        request.tenant.domain_url = preview_tenant.domain
        connection.set_tenant(resolved_tenant)
        request.urlconf = settings.ROOT_URLCONF
        set_urlconf(settings.ROOT_URLCONF)


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
