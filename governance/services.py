from __future__ import annotations

from dataclasses import dataclass

from django.utils import timezone
from django_tenants.utils import schema_context

from .models import BillingAccount, GovernanceEvent, GroupMembership, GroupTenantAccess, OperationalAccessGrant


@dataclass(frozen=True, slots=True)
class GroupTenantDetailDecision:
    allowed: bool
    reason: str
    grant: OperationalAccessGrant | None = None


def get_group_membership(*, group, user):
    if user is None or not getattr(user, "is_authenticated", False):
        return None
    if getattr(user, "is_superuser", False):
        return None
    return (
        GroupMembership.objects.select_related("group", "user")
        .filter(group=group, user=user, is_active=True)
        .first()
    )


def can_manage_group(*, group, user, membership=None) -> bool:
    if user is None or not getattr(user, "is_authenticated", False):
        return False
    if getattr(user, "is_superuser", False):
        return True
    membership = membership or get_group_membership(group=group, user=user)
    return bool(membership and membership.can_manage_group())


def can_manage_group_billing(*, group, user, membership=None) -> bool:
    if user is None or not getattr(user, "is_authenticated", False):
        return False
    if getattr(user, "is_superuser", False):
        return True
    membership = membership or get_group_membership(group=group, user=user)
    return bool(membership and membership.can_manage_billing())


def can_request_operational_access(*, group, user, membership=None) -> bool:
    if user is None or not getattr(user, "is_authenticated", False):
        return False
    if getattr(user, "is_superuser", False):
        return True
    membership = membership or get_group_membership(group=group, user=user)
    return bool(membership and membership.can_request_operational_access())


def can_manage_group_access(*, group, user, membership=None) -> bool:
    return can_manage_group(group=group, user=user, membership=membership)


def get_or_create_billing_account(*, group) -> BillingAccount:
    billing_account, _ = BillingAccount.objects.get_or_create(group=group)
    return billing_account


def build_group_usage_snapshot(*, group) -> dict:
    billing_account = get_or_create_billing_account(group=group)
    tenant_links = list(
        group.tenant_links.select_related("tenant")
        .filter(is_active=True, tenant__is_active=True)
        .order_by("-is_primary", "tenant__name")
    )
    active_memberships = list(group.memberships.select_related("user").filter(is_active=True))
    tenant_accesses = list(
        group.tenant_accesses.select_related("tenant", "user")
        .filter(is_active=True, tenant__in=[link.tenant for link in tenant_links])
    )
    tenant_accesses_by_tenant_id: dict[int, list] = {}
    for access in tenant_accesses:
        tenant_accesses_by_tenant_id.setdefault(access.tenant_id, []).append(access)

    tenant_rows = []
    total_storage_bytes = 0
    total_documents = 0
    total_object_records = 0
    total_local_users = 0
    total_group_assignments = 0
    total_manager_assignments = 0

    for link in tenant_links:
        tenant = link.tenant
        local_user_count = tenant.memberships.filter(is_active=True).count()
        access_rows = tenant_accesses_by_tenant_id.get(tenant.id, [])
        group_assignment_count = len(access_rows)
        manager_rows = [row for row in access_rows if row.role in {GroupTenantAccess.ROLE_OWNER, GroupTenantAccess.ROLE_MANAGER}]
        storage_stats = _read_tenant_storage_stats(tenant)

        total_local_users += local_user_count
        total_group_assignments += group_assignment_count
        total_manager_assignments += len(manager_rows)
        total_storage_bytes += storage_stats["storage_bytes"]
        total_documents += storage_stats["document_count"]
        total_object_records += storage_stats["object_record_count"]

        tenant_rows.append(
            {
                "tenant": tenant,
                "link": link,
                "local_user_count": local_user_count,
                "local_user_health": _compute_usage_health(local_user_count, tenant.max_users),
                "group_assignment_count": group_assignment_count,
                "manager_count": len(manager_rows),
                "manager_names": [row.user.username for row in manager_rows[:4]],
                "storage_bytes": storage_stats["storage_bytes"],
                "storage_label": _format_storage_label(storage_stats["storage_bytes"]),
                "storage_health": _compute_usage_health(
                    _bytes_to_megabytes(storage_stats["storage_bytes"]),
                    tenant.storage_quota_mb,
                ),
                "document_count": storage_stats["document_count"],
                "object_record_count": storage_stats["object_record_count"],
                "warning": storage_stats["warning"],
            }
        )

    return {
        "billing_account": billing_account,
        "seat_limit": billing_account.seat_limit,
        "seat_usage": len(active_memberships),
        "seat_health": _compute_usage_health(len(active_memberships), billing_account.seat_limit),
        "manager_limit": billing_account.manager_limit,
        "manager_usage": total_manager_assignments,
        "manager_health": _compute_usage_health(total_manager_assignments, billing_account.manager_limit),
        "storage_limit_mb": billing_account.storage_limit_mb,
        "storage_usage_bytes": total_storage_bytes,
        "storage_usage_mb": _bytes_to_megabytes(total_storage_bytes),
        "storage_label": _format_storage_label(total_storage_bytes),
        "storage_health": _compute_usage_health(_bytes_to_megabytes(total_storage_bytes), billing_account.storage_limit_mb),
        "tenant_count": len(tenant_rows),
        "local_user_count": total_local_users,
        "group_assignment_count": total_group_assignments,
        "document_count": total_documents,
        "object_record_count": total_object_records,
        "tenant_rows": tenant_rows,
    }


def get_group_tenant_access(*, group, tenant, user):
    if user is None or not getattr(user, "is_authenticated", False):
        return None
    return (
        GroupTenantAccess.objects.select_related("group", "tenant", "user", "granted_by")
        .filter(group=group, tenant=tenant, user=user, is_active=True)
        .first()
    )


def can_allocate_group_seat(*, group, current_membership=None) -> bool:
    billing_account = get_or_create_billing_account(group=group)
    if not billing_account.enforce_limits:
        return True
    if current_membership is not None and current_membership.is_active:
        return True
    active_members = group.memberships.filter(is_active=True).count()
    return active_members < billing_account.seat_limit


def can_allocate_manager_assignment(*, group, current_access=None, target_role: str = "") -> bool:
    billing_account = get_or_create_billing_account(group=group)
    manager_roles = {GroupTenantAccess.ROLE_OWNER, GroupTenantAccess.ROLE_MANAGER}
    if target_role not in manager_roles or not billing_account.enforce_limits:
        return True
    if current_access is not None and current_access.is_active and current_access.role in manager_roles:
        return True
    active_manager_assignments = group.tenant_accesses.filter(
        is_active=True,
        role__in=manager_roles,
    ).count()
    return active_manager_assignments < billing_account.manager_limit


def get_latest_operational_access_grant(*, group, tenant, user):
    if user is None or not getattr(user, "is_authenticated", False):
        return None
    return (
        OperationalAccessGrant.objects.select_related("group", "tenant", "user", "requested_by", "decided_by")
        .filter(group=group, tenant=tenant, user=user)
        .order_by("-created_at", "-id")
        .first()
    )


def get_active_operational_access_grant(*, group, tenant, user):
    grant = get_latest_operational_access_grant(group=group, tenant=tenant, user=user)
    if grant is None or not grant.is_active:
        return None
    return grant


def create_operational_access_request(*, group, tenant, user, requested_by=None, justification: str = "", expires_at=None):
    if not getattr(group, "requires_operational_grant", False):
        raise ValueError("Este holding no usa grants operativos porque no esta en modo Islas.")

    existing = get_latest_operational_access_grant(group=group, tenant=tenant, user=user)
    if existing is not None and existing.status in {
        OperationalAccessGrant.STATUS_PENDING,
        OperationalAccessGrant.STATUS_APPROVED,
    }:
        return existing, False

    grant = OperationalAccessGrant.objects.create(
        group=group,
        tenant=tenant,
        user=user,
        requested_by=requested_by,
        justification=justification,
        expires_at=expires_at,
        status=OperationalAccessGrant.STATUS_PENDING,
    )
    return grant, True


def decide_operational_access_request(*, grant, actor, status: str, decision_note: str = ""):
    allowed_statuses = {
        OperationalAccessGrant.STATUS_APPROVED,
        OperationalAccessGrant.STATUS_REJECTED,
        OperationalAccessGrant.STATUS_REVOKED,
    }
    if status not in allowed_statuses:
        raise ValueError("Estado de decision invalido para el grant operativo.")
    grant.status = status
    grant.decision_note = decision_note
    grant.decided_by = actor
    grant.decided_at = timezone.now()
    grant.save(update_fields=["status", "decision_note", "decided_by", "decided_at", "updated_at"])
    return grant


def resolve_group_tenant_detail_access(*, group, link, user, membership=None, permission_code: str = "tenant.access"):
    if user is None or not getattr(user, "is_authenticated", False):
        return GroupTenantDetailDecision(allowed=False, reason="anonymous")
    if getattr(user, "is_superuser", False):
        return GroupTenantDetailDecision(allowed=True, reason="superuser")

    membership = membership or get_group_membership(group=group, user=user)
    if membership is None or not membership.is_active:
        return GroupTenantDetailDecision(allowed=False, reason="missing_group_membership")

    effective_mode = link.effective_mode
    if effective_mode != group.MODE_FULL:
        return GroupTenantDetailDecision(allowed=False, reason=f"effective_mode_{effective_mode}")

    if membership.can_manage_group():
        return GroupTenantDetailDecision(allowed=True, reason="group_admin")

    tenant_access = get_group_tenant_access(group=group, tenant=link.tenant, user=user)
    if tenant_access is None:
        return GroupTenantDetailDecision(allowed=False, reason="missing_group_tenant_access")

    if permission_code == "tenant.access":
        return GroupTenantDetailDecision(allowed=True, reason="group_tenant_access")

    from access.permissions import role_has_tenant_permission

    if not role_has_tenant_permission(tenant_access.role, link.tenant, permission_code):
        return GroupTenantDetailDecision(allowed=False, reason="tenant_role_denied")

    return GroupTenantDetailDecision(allowed=True, reason="group_tenant_access")


def record_governance_event(
    *,
    event_type: str,
    message: str = "",
    actor=None,
    group=None,
    tenant=None,
    metadata: dict | None = None,
):
    return GovernanceEvent.objects.create(
        event_type=event_type,
        message=message,
        actor=actor,
        group=group,
        tenant=tenant,
        metadata=metadata or {},
    )


def _read_tenant_storage_stats(tenant) -> dict:
    try:
        with schema_context(tenant.schema_name):
            from binncrm.models import Document, ObjectRecord

            document_rows = list(Document.objects.filter(is_active=True).values_list("file_size", flat=True))
            storage_bytes = sum(int(value or 0) for value in document_rows)
            return {
                "storage_bytes": storage_bytes,
                "document_count": len(document_rows),
                "object_record_count": ObjectRecord.objects.filter(is_active=True).count(),
                "warning": "",
            }
    except Exception as exc:
        return {
            "storage_bytes": 0,
            "document_count": 0,
            "object_record_count": 0,
            "warning": str(exc),
        }


def _format_storage_label(storage_bytes: int) -> str:
    if storage_bytes <= 0:
        return "0 MB"
    if storage_bytes >= 1024 * 1024 * 1024:
        return f"{storage_bytes / (1024 * 1024 * 1024):,.2f} GB"
    return f"{storage_bytes / (1024 * 1024):,.2f} MB"


def _bytes_to_megabytes(storage_bytes: int) -> int:
    if storage_bytes <= 0:
        return 0
    return int(round(storage_bytes / (1024 * 1024)))


def _compute_usage_health(used: int, limit: int) -> dict:
    if limit <= 0:
        return {"used": used, "limit": limit, "remaining": 0, "is_over": used > 0, "ratio": 1}
    remaining = max(limit - used, 0)
    ratio = min((used / limit), 1)
    return {
        "used": used,
        "limit": limit,
        "remaining": remaining,
        "is_over": used > limit,
        "ratio": ratio,
    }
