from __future__ import annotations

from django.utils import timezone

from governance.models import CorporateGroup
from identity.models import GlobalSession

from .contracts import ActiveSessionContext, SessionScope
from .models import ActiveAccessContext
from .resolvers import RequestAccessResolver

ACTIVE_ACCESS_CONTEXT_SESSION_KEY = "active_access_context_id"


def get_global_session_for_request(request):
    session_key = getattr(getattr(request, "session", None), "session_key", None)
    user = getattr(request, "user", None)
    if not session_key or user is None or not getattr(user, "is_authenticated", False):
        return None
    return GlobalSession.objects.filter(session_key=session_key, user=user).first()


def ensure_active_access_context(request) -> ActiveAccessContext | None:
    global_session = get_global_session_for_request(request)
    user = getattr(request, "user", None)
    if global_session is None or user is None or not getattr(user, "is_authenticated", False):
        return None

    tenant = getattr(request, "tenant", None)
    defaults = {
        "user": user,
        "scope": SessionScope.STRICT_ISOLATION.value,
        "active_tenant": tenant if getattr(tenant, "schema_name", "") not in {"", "public"} else None,
        "reason": "request_bootstrap",
    }
    context, created = ActiveAccessContext.objects.get_or_create(global_session=global_session, defaults=defaults)
    if created:
        _sync_global_session_from_context(global_session, context)
    return context


def load_active_session_context(request) -> ActiveSessionContext | None:
    context_record = ensure_active_access_context(request)
    if context_record is None:
        return None
    return ActiveSessionContext(
        scope=SessionScope(context_record.scope),
        tenant_id=context_record.active_tenant_id,
        corporate_group_id=context_record.corporate_group_id,
        impersonator_user_id=context_record.impersonator_id,
        reason=context_record.reason,
    )


def resolve_request_access(request, permission_code: str):
    cache = getattr(request, "_access_decisions", None)
    if cache is None:
        cache = {}
        request._access_decisions = cache
    if permission_code in cache:
        return cache[permission_code]

    subject = getattr(request, "access_subject", None)
    context = getattr(request, "active_session_context", None) or load_active_session_context(request)
    tenant = getattr(request, "tenant", None)
    if subject is None or context is None or tenant is None:
        return None

    decision = RequestAccessResolver(request).resolve(
        subject=subject,
        context=context,
        target_tenant_id=tenant.pk,
        permission_code=permission_code,
    )
    cache[permission_code] = decision
    return decision


def set_strict_tenant_context(request, *, tenant, reason: str = "tenant_switch") -> ActiveAccessContext | None:
    context_record = ensure_active_access_context(request)
    global_session = get_global_session_for_request(request)
    if context_record is None or global_session is None:
        return None

    context_record.scope = SessionScope.STRICT_ISOLATION.value
    context_record.active_tenant = tenant
    context_record.corporate_group = None
    context_record.impersonator = None
    context_record.reason = reason[:160]
    context_record.last_resolved_at = timezone.now()
    context_record.save(
        update_fields=[
            "scope",
            "active_tenant",
            "corporate_group",
            "impersonator",
            "reason",
            "last_resolved_at",
        ]
    )
    _sync_global_session_from_context(global_session, context_record)
    request.session[ACTIVE_ACCESS_CONTEXT_SESSION_KEY] = context_record.pk
    return context_record


def set_consolidated_context(
    request,
    *,
    group: CorporateGroup,
    tenant=None,
    reason: str = "group_switch",
) -> ActiveAccessContext | None:
    context_record = ensure_active_access_context(request)
    global_session = get_global_session_for_request(request)
    if context_record is None or global_session is None:
        return None

    context_record.scope = SessionScope.CONSOLIDATED.value
    context_record.active_tenant = tenant
    context_record.corporate_group = group
    context_record.impersonator = None
    context_record.reason = reason[:160]
    context_record.last_resolved_at = timezone.now()
    context_record.save(
        update_fields=[
            "scope",
            "active_tenant",
            "corporate_group",
            "impersonator",
            "reason",
            "last_resolved_at",
        ]
    )
    _sync_global_session_from_context(global_session, context_record)
    request.session[ACTIVE_ACCESS_CONTEXT_SESSION_KEY] = context_record.pk
    return context_record


def clear_active_access_context(request, *, reason: str = "return_to_platform") -> None:
    context_record = ensure_active_access_context(request)
    global_session = get_global_session_for_request(request)
    if context_record is None or global_session is None:
        return

    context_record.scope = SessionScope.STRICT_ISOLATION.value
    context_record.active_tenant = None
    context_record.corporate_group = None
    context_record.impersonator = None
    context_record.reason = reason[:160]
    context_record.last_resolved_at = timezone.now()
    context_record.save(
        update_fields=[
            "scope",
            "active_tenant",
            "corporate_group",
            "impersonator",
            "reason",
            "last_resolved_at",
        ]
    )
    _sync_global_session_from_context(global_session, context_record)
    request.session.pop(ACTIVE_ACCESS_CONTEXT_SESSION_KEY, None)


def _sync_global_session_from_context(global_session: GlobalSession, context_record: ActiveAccessContext) -> None:
    global_session.scope = context_record.scope
    global_session.active_tenant_schema = getattr(context_record.active_tenant, "schema_name", "")[:63]
    global_session.impersonator_user_id = context_record.impersonator_id
    global_session.last_seen_at = timezone.now()
    global_session.save(update_fields=["scope", "active_tenant_schema", "impersonator_user_id", "last_seen_at"])
