from __future__ import annotations

from .contracts import (
    AccessDecision,
    AccessResolver,
    AccessSource,
)
from governance.services import resolve_group_tenant_detail_access
from .runtime import (
    get_active_group_membership,
    get_group_tenant_link,
    get_tenant_membership,
)


def _membership_has_tenant_permission(membership, tenant, permission_code: str) -> bool:
    from .permissions import membership_has_tenant_permission

    return membership_has_tenant_permission(membership, tenant, permission_code)


class RequestAccessResolver(AccessResolver):
    def __init__(self, request):
        self.request = request

    def resolve(
        self,
        *,
        subject,
        context,
        target_tenant_id: int,
        permission_code: str,
    ) -> AccessDecision:
        if not subject.active:
            return AccessDecision(
                allowed=False,
                scope=context.scope,
                reason="inactive_subject",
                tenant_id=target_tenant_id,
            )

        if subject.is_superuser:
            return AccessDecision(
                allowed=True,
                scope=context.scope,
                source=AccessSource.SUPERADMIN,
                tenant_id=target_tenant_id,
                reason="superadmin_bypass",
            )

        if context.scope.value == "consolidated":
            group_membership = get_active_group_membership(
                group_id=context.corporate_group_id,
                user=getattr(self.request, "user", None),
            )
            link = get_group_tenant_link(
                group_id=context.corporate_group_id,
                tenant_id=target_tenant_id,
            )
            if group_membership is None or link is None:
                return AccessDecision(
                    allowed=False,
                    scope=context.scope,
                    reason="missing_group_access",
                    tenant_id=target_tenant_id,
                    corporate_group_id=context.corporate_group_id,
                )
            effective_mode = link.effective_mode
            detail_decision = resolve_group_tenant_detail_access(
                group=link.group,
                link=link,
                user=getattr(self.request, "user", None),
                membership=group_membership,
                permission_code=permission_code,
            )
            if not detail_decision.allowed:
                return AccessDecision(
                    allowed=False,
                    scope=context.scope,
                    reason=detail_decision.reason,
                    tenant_id=target_tenant_id,
                    corporate_group_id=context.corporate_group_id,
                    metadata={"effective_mode": effective_mode, "role": group_membership.role},
                )
            return AccessDecision(
                allowed=True,
                scope=context.scope,
                source=AccessSource.GROUP_MEMBERSHIP,
                tenant_id=target_tenant_id,
                corporate_group_id=context.corporate_group_id,
                reason="group_membership",
                metadata={"effective_mode": effective_mode, "role": group_membership.role},
            )

        if context.scope.value == "strict_isolation" and context.tenant_id is not None and context.tenant_id != target_tenant_id:
            return AccessDecision(
                allowed=False,
                scope=context.scope,
                tenant_id=target_tenant_id,
                reason="strict_context_tenant_mismatch",
                metadata={"active_tenant_id": str(context.tenant_id)},
            )

        tenant = getattr(self.request, "tenant", None)
        user = getattr(self.request, "user", None)
        membership = get_tenant_membership(tenant=tenant, user=user)
        if membership is None or membership.tenant_id != target_tenant_id:
            return AccessDecision(
                allowed=False,
                scope=context.scope,
                reason="missing_membership",
                tenant_id=target_tenant_id,
            )
        if permission_code == "tenant.access":
            return AccessDecision(
                allowed=True,
                scope=context.scope,
                source=AccessSource.DIRECT_MEMBERSHIP,
                tenant_id=target_tenant_id,
                reason="direct_membership",
            )

        allowed = _membership_has_tenant_permission(membership, tenant, permission_code)
        return AccessDecision(
            allowed=allowed,
            scope=context.scope,
            source=AccessSource.DIRECT_MEMBERSHIP if allowed else None,
            tenant_id=target_tenant_id,
            reason="direct_membership" if allowed else "permission_denied",
        )
