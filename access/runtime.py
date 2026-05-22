from __future__ import annotations

from django.contrib.auth import get_user_model

from governance.models import CorporateGroup, GroupMembership, GroupTenantAccess, GroupTenantLink

from .contracts import AccessSubject
from .models import TenantMembership


def build_access_subject(user) -> AccessSubject | None:
    if user is None or not getattr(user, "is_authenticated", False):
        return None
    return AccessSubject(
        user_id=user.pk,
        is_superuser=bool(getattr(user, "is_superuser", False)),
        active=bool(getattr(user, "is_active", False)),
    )


def get_tenant_membership(*, tenant, user) -> TenantMembership | None:
    if tenant is None or user is None or not getattr(user, "is_authenticated", False):
        return None
    if getattr(user, "is_superuser", False):
        return None
    return (
        TenantMembership.objects.select_related("tenant", "user")
        .filter(tenant=tenant, user=user, is_active=True)
        .first()
    )


def count_case_insensitive_usernames(username: str) -> int:
    user_model = get_user_model()
    return user_model._default_manager.filter(username__iexact=username).count()


def get_request_membership(request) -> TenantMembership | None:
    tenant = getattr(request, "tenant", None)
    user = getattr(request, "user", None)
    return get_tenant_membership(tenant=tenant, user=user)


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


def get_active_group_membership(*, group_id: int | None, user):
    if group_id is None or user is None or not getattr(user, "is_authenticated", False):
        return None
    return (
        GroupMembership.objects.select_related("group", "user")
        .filter(group_id=group_id, user=user, is_active=True, group__status=CorporateGroup.STATUS_ACTIVE)
        .first()
    )


def get_group_tenant_link(*, group_id: int | None, tenant_id: int | None):
    if group_id is None or tenant_id is None:
        return None
    return (
        GroupTenantLink.objects.select_related("group", "tenant")
        .filter(group_id=group_id, tenant_id=tenant_id, is_active=True, tenant__is_active=True)
        .first()
    )


def get_group_tenant_access(*, group_id: int | None, tenant_id: int | None, user):
    if group_id is None or tenant_id is None or user is None or not getattr(user, "is_authenticated", False):
        return None
    return (
        GroupTenantAccess.objects.select_related("group", "tenant", "user")
        .filter(
            group_id=group_id,
            tenant_id=tenant_id,
            user=user,
            is_active=True,
            group__status=CorporateGroup.STATUS_ACTIVE,
            tenant__is_active=True,
        )
        .first()
    )
