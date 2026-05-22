from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol


class SessionScope(StrEnum):
    STRICT_ISOLATION = "strict_isolation"
    CONSOLIDATED = "consolidated"
    IMPERSONATED = "impersonated"


class AccessSource(StrEnum):
    DIRECT_MEMBERSHIP = "direct_membership"
    GROUP_MEMBERSHIP = "group_membership"
    IMPERSONATION = "impersonation"
    SUPERADMIN = "superadmin"


@dataclass(slots=True, frozen=True)
class AccessSubject:
    user_id: int
    is_superuser: bool = False
    active: bool = True


@dataclass(slots=True, frozen=True)
class ActiveSessionContext:
    scope: SessionScope
    tenant_id: int | None = None
    corporate_group_id: int | None = None
    impersonator_user_id: int | None = None
    reason: str = ""


@dataclass(slots=True, frozen=True)
class AccessDecision:
    allowed: bool
    scope: SessionScope
    source: AccessSource | None = None
    tenant_id: int | None = None
    corporate_group_id: int | None = None
    reason: str = ""
    metadata: dict[str, str] = field(default_factory=dict)


class AccessResolver(Protocol):
    def resolve(
        self,
        *,
        subject: AccessSubject,
        context: ActiveSessionContext,
        target_tenant_id: int,
        permission_code: str,
    ) -> AccessDecision:
        """Return the final access decision for the requested tenant and permission."""
