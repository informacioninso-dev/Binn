from __future__ import annotations

from typing import Any

from django.utils import timezone

from .models import GlobalSession, User


def _ensure_session_key(request) -> str:
    session_key = getattr(getattr(request, "session", None), "session_key", None)
    if session_key:
        return session_key

    session = getattr(request, "session", None)
    if session is None:
        return ""
    session.create()
    return session.session_key or ""


def register_authenticated_session(request, user: User) -> GlobalSession | None:
    session_key = _ensure_session_key(request)
    if not session_key:
        return None

    tenant = getattr(request, "tenant", None)
    defaults = {
        "auth_backend": getattr(user, "backend", "") or "",
        "state": GlobalSession.STATE_ACTIVE,
        "scope": GlobalSession.SCOPE_STRICT_ISOLATION,
        "ip_address": _extract_client_ip(request),
        "user_agent": request.META.get("HTTP_USER_AGENT", "")[:2000],
        "request_id": getattr(request, "request_id", "")[:64],
        "active_tenant_schema": getattr(tenant, "schema_name", "")[:63],
        "last_seen_at": timezone.now(),
    }
    session, created = GlobalSession.objects.get_or_create(
        session_key=session_key,
        defaults={"user": user, **defaults},
    )
    if not created:
        session.user = user
        session.auth_backend = defaults["auth_backend"]
        session.state = GlobalSession.STATE_ACTIVE
        session.ip_address = defaults["ip_address"]
        session.user_agent = defaults["user_agent"]
        session.request_id = defaults["request_id"]
        session.active_tenant_schema = defaults["active_tenant_schema"]
        session.last_seen_at = defaults["last_seen_at"]
        session.ended_at = None
        session.revoked_at = None
        session.ended_reason = ""
        session.save(
            update_fields=[
                "user",
                "auth_backend",
                "state",
                "ip_address",
                "user_agent",
                "request_id",
                "active_tenant_schema",
                "last_seen_at",
                "ended_at",
                "revoked_at",
                "ended_reason",
            ]
        )

    user.last_global_login_at = timezone.now()
    user.save(update_fields=["last_global_login_at"])
    return session


def close_authenticated_session(request, user: User | None, *, reason: str = "logout") -> None:
    session_key = getattr(getattr(request, "session", None), "session_key", None)
    if not session_key:
        return

    queryset = GlobalSession.objects.filter(session_key=session_key)
    if user is not None:
        queryset = queryset.filter(user=user)
    session = queryset.first()
    if session is None:
        return

    session.state = GlobalSession.STATE_ENDED
    session.ended_at = timezone.now()
    session.ended_reason = reason[:120]
    session.last_seen_at = timezone.now()
    session.save(update_fields=["state", "ended_at", "ended_reason", "last_seen_at"])


def touch_authenticated_session(request) -> None:
    session_key = getattr(getattr(request, "session", None), "session_key", None)
    user = getattr(request, "user", None)
    if not session_key or user is None or not getattr(user, "is_authenticated", False):
        return

    tenant = getattr(request, "tenant", None)
    tenant_schema = getattr(tenant, "schema_name", "")[:63]
    now = timezone.now()
    touch_interval_seconds = 60
    try:
        last_touch = float(request.session.get("_global_session_touched_at", 0) or 0)
    except (TypeError, ValueError):
        last_touch = 0
    previous_schema = request.session.get("_global_session_tenant_schema", "")
    if previous_schema == tenant_schema and (now.timestamp() - last_touch) < touch_interval_seconds:
        return

    GlobalSession.objects.filter(session_key=session_key, user=user).update(
        last_seen_at=now,
        active_tenant_schema=tenant_schema,
        request_id=getattr(request, "request_id", "")[:64],
    )
    # Keep audit freshness without making every module click a database write.
    request.session["_global_session_touched_at"] = now.timestamp()
    request.session["_global_session_tenant_schema"] = tenant_schema


def _extract_client_ip(request) -> str | None:
    forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    remote_addr = request.META.get("REMOTE_ADDR", "").strip()
    return remote_addr or None
