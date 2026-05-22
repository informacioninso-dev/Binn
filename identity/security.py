from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256

from django.conf import settings
from django.core.cache import cache


@dataclass(frozen=True)
class LoginThrottleDecision:
    allowed: bool
    retry_after_seconds: int = 0
    failure_count: int = 0


def evaluate_login_throttle(*, request, login_value: str) -> LoginThrottleDecision:
    if not _throttle_enabled():
        return LoginThrottleDecision(allowed=True)

    identity = _build_login_identity(request=request, login_value=login_value)
    lock_key = _lock_cache_key(identity)
    lock_value = cache.get(lock_key)
    if not lock_value:
        return LoginThrottleDecision(allowed=True)
    return LoginThrottleDecision(
        allowed=False,
        retry_after_seconds=int(lock_value.get("retry_after_seconds", settings.LOGIN_RATE_LIMIT_LOCKOUT_SECONDS)),
        failure_count=int(lock_value.get("failure_count", settings.LOGIN_RATE_LIMIT_ATTEMPTS)),
    )


def register_login_failure(*, request, login_value: str) -> LoginThrottleDecision:
    if not _throttle_enabled():
        return LoginThrottleDecision(allowed=True)

    identity = _build_login_identity(request=request, login_value=login_value)
    attempts_key = _attempts_cache_key(identity)
    failure_count = int(cache.get(attempts_key, 0)) + 1
    cache.set(attempts_key, failure_count, timeout=settings.LOGIN_RATE_LIMIT_WINDOW_SECONDS)

    if failure_count < settings.LOGIN_RATE_LIMIT_ATTEMPTS:
        return LoginThrottleDecision(allowed=True, failure_count=failure_count)

    retry_after_seconds = settings.LOGIN_RATE_LIMIT_LOCKOUT_SECONDS
    cache.set(
        _lock_cache_key(identity),
        {"failure_count": failure_count, "retry_after_seconds": retry_after_seconds},
        timeout=retry_after_seconds,
    )
    return LoginThrottleDecision(
        allowed=False,
        retry_after_seconds=retry_after_seconds,
        failure_count=failure_count,
    )


def reset_login_throttle(*, request, login_value: str) -> None:
    if not _throttle_enabled():
        return
    identity = _build_login_identity(request=request, login_value=login_value)
    cache.delete_many([_attempts_cache_key(identity), _lock_cache_key(identity)])


def _throttle_enabled() -> bool:
    return all(
        int(value) > 0
        for value in (
            getattr(settings, "LOGIN_RATE_LIMIT_ATTEMPTS", 0),
            getattr(settings, "LOGIN_RATE_LIMIT_WINDOW_SECONDS", 0),
            getattr(settings, "LOGIN_RATE_LIMIT_LOCKOUT_SECONDS", 0),
        )
    )


def _build_login_identity(*, request, login_value: str) -> str:
    remote_addr = (
        request.META.get("HTTP_X_FORWARDED_FOR", "").split(",")[0].strip()
        or request.META.get("REMOTE_ADDR", "").strip()
        or "unknown"
    )
    tenant_schema = getattr(getattr(request, "tenant", None), "schema_name", "public")
    raw_identity = f"{tenant_schema}|{remote_addr}|{(login_value or '').strip().lower()}"
    return sha256(raw_identity.encode("utf-8")).hexdigest()


def _attempts_cache_key(identity: str) -> str:
    return f"security.login.attempts.{identity}"


def _lock_cache_key(identity: str) -> str:
    return f"security.login.lock.{identity}"
