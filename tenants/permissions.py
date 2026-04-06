from functools import wraps

from django.contrib import messages
from django.shortcuts import redirect

from .models import TenantMembership
from .utils import get_request_membership


def tenant_capability_required(capability):
    def decorator(view_func):
        @wraps(view_func)
        def wrapper(request, *args, **kwargs):
            tenant = getattr(request, "tenant", None)
            if tenant is None:
                messages.error(request, "No se encontro la clinica activa para esta solicitud.")
                return redirect("dashboard")

            if not tenant.has_capability(capability):
                messages.error(
                    request,
                    "Este modulo no esta disponible para el plan actual de la clinica.",
                )
                return redirect("dashboard")

            return view_func(request, *args, **kwargs)

        return wrapper

    return decorator


def tenant_role_required(*allowed_roles):
    def decorator(view_func):
        @wraps(view_func)
        def wrapper(request, *args, **kwargs):
            user = getattr(request, "user", None)
            if user is not None and getattr(user, "is_superuser", False):
                return view_func(request, *args, **kwargs)

            membership = get_request_membership(request)
            if membership is None:
                messages.error(request, "No tienes una membresia activa para esta clinica.")
                return redirect("dashboard")

            if membership.is_admin:
                request.tenant_membership = membership
                return view_func(request, *args, **kwargs)

            if allowed_roles and membership.role not in allowed_roles:
                messages.error(request, "Tu rol actual no tiene permisos para usar este modulo.")
                return redirect("dashboard")

            request.tenant_membership = membership
            return view_func(request, *args, **kwargs)

        return wrapper

    return decorator


CRM_ALLOWED_ROLES = (
    TenantMembership.ROLE_RECEPTION,
    TenantMembership.ROLE_ASSISTANT,
    TenantMembership.ROLE_CLINIC_ADMIN,
)

BILLING_ALLOWED_ROLES = (
    TenantMembership.ROLE_RECEPTION,
    TenantMembership.ROLE_CASHIER,
    TenantMembership.ROLE_CLINIC_ADMIN,
)

CLINICAL_ALLOWED_ROLES = (
    TenantMembership.ROLE_DOCTOR,
    TenantMembership.ROLE_ASSISTANT,
    TenantMembership.ROLE_CLINIC_ADMIN,
)

INVENTORY_ALLOWED_ROLES = (
    TenantMembership.ROLE_ASSISTANT,
    TenantMembership.ROLE_CASHIER,
    TenantMembership.ROLE_CLINIC_ADMIN,
)

OPERATIONS_REPORT_ALLOWED_ROLES = (
    TenantMembership.ROLE_ASSISTANT,
    TenantMembership.ROLE_CASHIER,
    TenantMembership.ROLE_CLINIC_ADMIN,
)

OPERATIONS_COMMISSION_ALLOWED_ROLES = (
    TenantMembership.ROLE_CASHIER,
    TenantMembership.ROLE_CLINIC_ADMIN,
)

OPERATIONS_ADMIN_ALLOWED_ROLES = (
    TenantMembership.ROLE_CLINIC_ADMIN,
)
