from django.contrib.auth import get_user_model

from .models import TenantMembership


def get_request_membership(request):
    tenant = getattr(request, "tenant", None)
    user = getattr(request, "user", None)
    if tenant is None or user is None or not getattr(user, "is_authenticated", False):
        return None
    if getattr(user, "is_superuser", False):
        return None
    return (
        TenantMembership.objects.select_related("tenant", "user")
        .filter(tenant=tenant, user=user, is_active=True)
        .first()
    )


def get_tenant_user_queryset(tenant, *, roles=None, include_admins=True):
    user_model = get_user_model()
    membership_filters = {
        "tenant_memberships__tenant": tenant,
        "tenant_memberships__is_active": True,
    }
    if roles:
        membership_filters["tenant_memberships__role__in"] = list(roles)
    queryset = user_model._default_manager.filter(**membership_filters)
    if roles and include_admins:
        queryset = queryset | user_model._default_manager.filter(
            tenant_memberships__tenant=tenant,
            tenant_memberships__is_active=True,
            tenant_memberships__is_admin=True,
        )
    return queryset.distinct().order_by("username")
