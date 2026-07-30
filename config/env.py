from __future__ import annotations

from urllib.parse import urlparse

from django.core.exceptions import ImproperlyConfigured

DEFAULT_DEV_SECRET = "dev-key-CHANGE-IN-PRODUCTION-d8f9a7b6c5e4f3a2b1"
DEFAULT_LOCAL_ALLOWED_HOSTS = ("localhost", "127.0.0.1", ".localhost")
DEFAULT_LOCAL_CSRF_TRUSTED_ORIGINS = (
    "http://localhost",
    "http://127.0.0.1",
    "https://localhost",
    "https://127.0.0.1",
)
DEFAULT_LOCAL_TENANT_BASE_DOMAIN = "localhost"
_LOCAL_HOSTNAMES = {"localhost", "127.0.0.1", "::1", "[::1]"}
_PLACEHOLDER_SECRET_MARKERS = ("change-me", "replace-me", "example-secret", "sample-secret", "placeholder")


def split_csv(value: str | None) -> list[str]:
    if value is None:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def parse_admin_identities(value: str | None) -> list[tuple[str, str]]:
    admins: list[tuple[str, str]] = []
    for item in split_csv(value):
        if ":" in item:
            name, email = item.split(":", 1)
            admins.append((name.strip(), email.strip()))
        else:
            admins.append(("", item.strip()))
    return [(name, email) for name, email in admins if email]


def is_strong_secret_key(value: str | None) -> bool:
    secret_key = (value or "").strip()
    if len(secret_key) < 50:
        return False
    if len(set(secret_key)) < 5:
        return False
    if secret_key.startswith("django-insecure-"):
        return False
    lowered = secret_key.lower()
    return not any(marker in lowered for marker in _PLACEHOLDER_SECRET_MARKERS)


def resolve_allowed_hosts(*, debug: bool, env_value: str | None) -> list[str]:
    if env_value is None or not env_value.strip():
        return list(DEFAULT_LOCAL_ALLOWED_HOSTS if debug else [])
    return split_csv(env_value)


def resolve_csrf_trusted_origins(*, debug: bool, env_value: str | None) -> list[str]:
    if env_value is None or not env_value.strip():
        return list(DEFAULT_LOCAL_CSRF_TRUSTED_ORIGINS if debug else [])
    return split_csv(env_value)


def resolve_tenant_base_domain(*, debug: bool, env_value: str | None) -> str:
    candidate = (env_value or "").strip()
    if candidate:
        return candidate
    return DEFAULT_LOCAL_TENANT_BASE_DOMAIN if debug else ""


def is_local_host(value: str) -> bool:
    normalized = value.strip().lower().rstrip(".")
    if not normalized:
        return False
    if normalized.startswith("."):
        normalized = normalized[1:]
    return normalized in _LOCAL_HOSTNAMES or normalized.endswith(".localhost")


def is_local_origin(value: str) -> bool:
    parsed = urlparse(value.strip())
    if not parsed.scheme or not parsed.hostname:
        return False
    return is_local_host(parsed.hostname)


def validate_runtime_configuration(
    *,
    debug: bool,
    secret_key: str,
    allowed_hosts: list[str],
    csrf_trusted_origins: list[str],
    tenant_base_domain: str,
) -> None:
    if not debug and secret_key == DEFAULT_DEV_SECRET:
        raise ImproperlyConfigured(
            'SECRET_KEY debe estar configurada en produccion. '
            'Genera una con: python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"'
        )
    if not debug and not allowed_hosts:
        raise ImproperlyConfigured("ALLOWED_HOSTS debe estar configurado fuera de desarrollo local.")
    if not debug and not csrf_trusted_origins:
        raise ImproperlyConfigured("CSRF_TRUSTED_ORIGINS debe estar configurado fuera de desarrollo local.")
    if not debug and not tenant_base_domain:
        raise ImproperlyConfigured("TENANT_BASE_DOMAIN debe estar configurado fuera de desarrollo local.")

    public_hosts = [host for host in allowed_hosts if not is_local_host(host)]
    public_origins = [origin for origin in csrf_trusted_origins if not is_local_origin(origin)]
    public_base_domain = bool(tenant_base_domain and not is_local_host(tenant_base_domain))
    if debug and (public_hosts or public_origins or public_base_domain):
        problems = []
        if public_hosts:
            problems.append(f"ALLOWED_HOSTS={public_hosts}")
        if public_origins:
            problems.append(f"CSRF_TRUSTED_ORIGINS={public_origins}")
        if public_base_domain:
            problems.append(f"TENANT_BASE_DOMAIN={tenant_base_domain!r}")
        raise ImproperlyConfigured(
            "DEBUG=True solo se permite con configuracion local. Ajusta estas variables o apaga DEBUG: "
            + "; ".join(problems)
        )
