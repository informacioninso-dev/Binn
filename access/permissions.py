from functools import wraps

from django.contrib import messages
from django.shortcuts import redirect

from .models import TenantMembership
from .runtime import get_request_membership
from .services import resolve_request_access


PERMISSION_TENANT_ACCESS = "tenant.access"
PERMISSION_DASHBOARD_VIEW = "dashboard.view"
PERMISSION_ENTITIES_VIEW = "entities.view"
PERMISSION_ENTITIES_EDIT = "entities.edit"
PERMISSION_OBJECTS_VIEW = "objects.view"
PERMISSION_OBJECTS_EDIT = "objects.edit"
PERMISSION_DEALS_VIEW = "deals.view"
PERMISSION_DEALS_EDIT = "deals.edit"
PERMISSION_DEALS_MOVE = "deals.move"
PERMISSION_PROPOSALS_VIEW = "proposals.view"
PERMISSION_PROPOSALS_EDIT = "proposals.edit"
PERMISSION_COLLECTIONS_VIEW = "collections.view"
PERMISSION_COLLECTIONS_EDIT = "collections.edit"
PERMISSION_ACTIVITIES_VIEW = "activities.view"
PERMISSION_ACTIVITIES_EDIT = "activities.edit"
PERMISSION_ACTIVITIES_COMPLETE = "activities.complete"
PERMISSION_COLLAB_VIEW = "collab.view"
PERMISSION_COLLAB_EDIT = "collab.edit"
PERMISSION_DOCUMENTS_VIEW = "documents.view"
PERMISSION_DOCUMENTS_EDIT = "documents.edit"
PERMISSION_REPORTS_VIEW = "reports.view"


def tenant_capability_required(capability):
    def decorator(view_func):
        @wraps(view_func)
        def wrapper(request, *args, **kwargs):
            tenant = getattr(request, "tenant", None)
            if tenant is None:
                messages.error(request, "No se encontro un tenant activo para esta solicitud.")
                return redirect("dashboard")

            if not tenant.has_capability(capability):
                messages.error(request, "Este modulo no esta habilitado para este tenant.")
                return redirect("dashboard")

            return view_func(request, *args, **kwargs)

        return wrapper

    return decorator


def tenant_permission_required(permission_code: str, *, capability: str | None = None):
    def decorator(view_func):
        @wraps(view_func)
        def wrapper(request, *args, **kwargs):
            tenant = getattr(request, "tenant", None)
            if tenant is None:
                messages.error(request, "No se encontro un tenant activo para esta solicitud.")
                return redirect("dashboard")

            if capability and not tenant.has_capability(capability):
                messages.error(request, "Este modulo no esta habilitado para este tenant.")
                return redirect("dashboard")

            membership = get_request_membership(request)
            if membership is not None:
                request.tenant_membership = membership

            if not request_has_tenant_permission(request, permission_code, membership=membership):
                messages.error(request, "Tu rol actual no tiene permisos para realizar esta accion.")
                return redirect("dashboard")

            return view_func(request, *args, **kwargs)

        return wrapper

    return decorator


def request_has_tenant_permission(request, permission_code: str, *, membership=None) -> bool:
    user = getattr(request, "user", None)
    if getattr(user, "is_superuser", False):
        return True

    tenant = getattr(request, "tenant", None)
    if tenant is None:
        return False

    decision = resolve_request_access(request, permission_code)
    if decision is not None:
        return decision.allowed

    membership = membership or getattr(request, "tenant_membership", None) or get_request_membership(request)
    if membership is None:
        return False
    request.tenant_membership = membership
    if permission_code == PERMISSION_TENANT_ACCESS:
        return True
    return membership_has_tenant_permission(membership, tenant, permission_code)


def membership_has_tenant_permission(membership, tenant, permission_code: str) -> bool:
    return role_has_tenant_permission(getattr(membership, "role", ""), tenant, permission_code)


def role_has_tenant_permission(role: str, tenant, permission_code: str) -> bool:
    from tenants.defaults import resolve_role_policies

    policies = resolve_role_policies(getattr(getattr(tenant, "tenant_config", tenant), "role_policies", {}))
    allowed_permissions = policies.get(role, [])
    return "*" in allowed_permissions or permission_code in allowed_permissions


def tenant_role_required(*allowed_roles):
    def decorator(view_func):
        @wraps(view_func)
        def wrapper(request, *args, **kwargs):
            user = getattr(request, "user", None)
            if user is not None and getattr(user, "is_superuser", False):
                return view_func(request, *args, **kwargs)

            membership = get_request_membership(request)
            if membership is None:
                messages.error(request, "No tienes una membresia activa para este tenant.")
                return redirect("dashboard")

            if allowed_roles and membership.role not in allowed_roles:
                messages.error(request, "Tu rol actual no tiene permisos para usar este modulo.")
                return redirect("dashboard")

            request.tenant_membership = membership
            return view_func(request, *args, **kwargs)

        return wrapper

    return decorator


CRM_ALLOWED_ROLES = (
    TenantMembership.ROLE_OWNER,
    TenantMembership.ROLE_MANAGER,
    TenantMembership.ROLE_OPERATOR,
    TenantMembership.ROLE_ANALYST,
    TenantMembership.ROLE_VIEWER,
)

CRM_EDIT_ALLOWED_ROLES = (
    TenantMembership.ROLE_OWNER,
    TenantMembership.ROLE_MANAGER,
    TenantMembership.ROLE_OPERATOR,
)

CRM_ADMIN_ALLOWED_ROLES = (
    TenantMembership.ROLE_OWNER,
    TenantMembership.ROLE_MANAGER,
)
