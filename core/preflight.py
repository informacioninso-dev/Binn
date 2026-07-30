from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from django.conf import settings
from config.env import DEFAULT_DEV_SECRET, is_strong_secret_key

from .runtime_services import get_runtime_services_status


@dataclass(frozen=True)
class PreflightCheck:
    code: str
    label: str
    status: str
    message: str

    @property
    def is_blocking(self) -> bool:
        return self.status == "fail"


def run_platform_preflight(*, settings_obj=None, logs_path: Path | None = None, probe_overrides: dict | None = None) -> list[PreflightCheck]:
    settings_obj = settings_obj or settings
    logs_path = logs_path or Path(settings_obj.BASE_DIR) / "logs"
    runtime_status = get_runtime_services_status(settings_obj=settings_obj, probe_overrides=probe_overrides)

    checks = [
        _check_auth_user_model(settings_obj),
        _check_control_plane_apps(settings_obj),
        _check_collab_app(settings_obj),
        _check_secret_key(settings_obj),
        _check_allowed_hosts(settings_obj),
        _check_ssl_cookies(settings_obj),
        _check_public_schema_urlconf(settings_obj),
        _check_logs_path(logs_path),
        _check_observability(settings_obj),
        _check_email_delivery(settings_obj),
        _check_database_runtime(runtime_status),
        _check_cache_runtime(runtime_status),
        _check_realtime_runtime(runtime_status),
        _check_background_jobs_runtime(runtime_status),
    ]
    return checks


def summarize_preflight(checks: list[PreflightCheck]) -> dict:
    return {
        "ok": sum(1 for check in checks if check.status == "ok"),
        "warn": sum(1 for check in checks if check.status == "warn"),
        "fail": sum(1 for check in checks if check.status == "fail"),
    }


def _check_auth_user_model(settings_obj) -> PreflightCheck:
    status = "ok" if getattr(settings_obj, "AUTH_USER_MODEL", "") == "identity.User" else "fail"
    return PreflightCheck(
        code="auth_user_model",
        label="Modelo global de usuario",
        status=status,
        message="AUTH_USER_MODEL apunta a identity.User." if status == "ok" else "AUTH_USER_MODEL no usa identity.User.",
    )


def _check_control_plane_apps(settings_obj) -> PreflightCheck:
    expected = {"identity", "governance", "access", "consolidation", "tenants"}
    shared_apps = set(getattr(settings_obj, "SHARED_APPS", []))
    missing = sorted(expected - shared_apps)
    status = "ok" if not missing else "fail"
    message = "Shared apps de control plane completas." if status == "ok" else f"Faltan apps shared: {', '.join(missing)}."
    return PreflightCheck(code="shared_apps", label="Control plane publico", status=status, message=message)


def _check_collab_app(settings_obj) -> PreflightCheck:
    tenant_apps = set(getattr(settings_obj, "TENANT_APPS", []))
    status = "ok" if "collab" in tenant_apps else "fail"
    message = "Collab vive en tenant apps y respeta aislamiento por schema." if status == "ok" else "Collab no esta habilitado como app tenant-local."
    return PreflightCheck(code="collab_tenant_app", label="Aislamiento de colaboracion", status=status, message=message)


def _check_secret_key(settings_obj) -> PreflightCheck:
    debug = bool(getattr(settings_obj, "DEBUG", False))
    secret_key = getattr(settings_obj, "SECRET_KEY", "")
    weak_secret_message = (
        "SECRET_KEY no cumple baseline de produccion: minimo 50 caracteres, sin placeholder y sin prefijo django-insecure-."
    )
    if not debug and secret_key == DEFAULT_DEV_SECRET:
        return PreflightCheck(
            code="secret_key",
            label="Secret key",
            status="fail",
            message="DEBUG esta apagado pero SECRET_KEY sigue en valor por defecto.",
        )
    if not is_strong_secret_key(secret_key):
        return PreflightCheck(
            code="secret_key",
            label="Secret key",
            status="warn" if debug else "fail",
            message=(
                "SECRET_KEY sigue en valor de desarrollo. Aceptable en prototipo local, no en salida real."
                if debug and secret_key == DEFAULT_DEV_SECRET
                else weak_secret_message
            ),
        )
    return PreflightCheck(code="secret_key", label="Secret key", status="ok", message="SECRET_KEY cumple baseline de salida real.")


def _check_allowed_hosts(settings_obj) -> PreflightCheck:
    allowed_hosts = [host for host in getattr(settings_obj, "ALLOWED_HOSTS", []) if str(host).strip()]
    status = "ok" if allowed_hosts else "fail"
    message = "ALLOWED_HOSTS configurado." if status == "ok" else "ALLOWED_HOSTS esta vacio."
    return PreflightCheck(code="allowed_hosts", label="Allowed hosts", status=status, message=message)


def _check_ssl_cookies(settings_obj) -> PreflightCheck:
    debug = bool(getattr(settings_obj, "DEBUG", False))
    secure_session = bool(getattr(settings_obj, "SESSION_COOKIE_SECURE", False))
    secure_csrf = bool(getattr(settings_obj, "CSRF_COOKIE_SECURE", False))
    if debug:
        status = "warn" if not (secure_session and secure_csrf) else "ok"
        message = (
            "Entorno debug: cookies seguras no son obligatorias todavia."
            if status == "warn"
            else "Incluso en debug ya se usan cookies seguras."
        )
        return PreflightCheck(code="secure_cookies", label="Cookies seguras", status=status, message=message)

    status = "ok" if secure_session and secure_csrf else "fail"
    message = (
        "Cookies de sesion y CSRF marcadas como secure."
        if status == "ok"
        else "Produccion sin SESSION_COOKIE_SECURE o CSRF_COOKIE_SECURE."
    )
    return PreflightCheck(code="secure_cookies", label="Cookies seguras", status=status, message=message)


def _check_public_schema_urlconf(settings_obj) -> PreflightCheck:
    status = "ok" if getattr(settings_obj, "PUBLIC_SCHEMA_URLCONF", "") == "config.public_urls" else "fail"
    return PreflightCheck(
        code="public_urlconf",
        label="Public schema routing",
        status=status,
        message="PUBLIC_SCHEMA_URLCONF configurado a config.public_urls." if status == "ok" else "PUBLIC_SCHEMA_URLCONF no apunta a config.public_urls.",
    )


def _check_logs_path(logs_path: Path) -> PreflightCheck:
    if logs_path.exists() and logs_path.is_dir():
        return PreflightCheck(code="logs_path", label="Directorio de logs", status="ok", message=f"Directorio de logs listo en {logs_path}.")
    return PreflightCheck(
        code="logs_path",
        label="Directorio de logs",
        status="warn",
        message=f"No existe {logs_path}. En produccion conviene provisionarlo antes del despliegue.",
    )


def _check_observability(settings_obj) -> PreflightCheck:
    debug = bool(getattr(settings_obj, "DEBUG", False))
    log_to_stdout = bool(getattr(settings_obj, "LOG_TO_STDOUT", False))
    log_file_enabled = bool(getattr(settings_obj, "LOG_FILE_ENABLED", False))
    log_format = str(getattr(settings_obj, "LOG_FORMAT", "") or "").strip().lower()
    admins = getattr(settings_obj, "ADMINS", []) or []

    if not log_to_stdout and not log_file_enabled:
        return PreflightCheck(
            code="observability_runtime",
            label="Observabilidad",
            status="fail",
            message="No hay handlers operativos para logs; activa stdout o archivo rotativo.",
        )
    if not debug and log_to_stdout and log_format != "json":
        return PreflightCheck(
            code="observability_runtime",
            label="Observabilidad",
            status="warn",
            message="Produccion envia logs a stdout, pero no en formato JSON.",
        )
    if not debug and not admins:
        return PreflightCheck(
            code="observability_runtime",
            label="Observabilidad",
            status="warn",
            message="No hay DJANGO_ADMINS configurados para alertas por email.",
        )
    return PreflightCheck(
        code="observability_runtime",
        label="Observabilidad",
        status="ok",
        message="Logging y alertas base configuradas para operacion.",
    )


def _check_email_delivery(settings_obj) -> PreflightCheck:
    debug = bool(getattr(settings_obj, "DEBUG", False))
    email_backend = str(getattr(settings_obj, "EMAIL_BACKEND", "") or "").strip()
    default_from = str(getattr(settings_obj, "DEFAULT_FROM_EMAIL", "") or "").strip()
    email_host = str(getattr(settings_obj, "EMAIL_HOST", "") or "").strip()
    email_use_tls = bool(getattr(settings_obj, "EMAIL_USE_TLS", False))
    email_use_ssl = bool(getattr(settings_obj, "EMAIL_USE_SSL", False))
    non_production_backends = {
        "django.core.mail.backends.console.EmailBackend",
        "django.core.mail.backends.locmem.EmailBackend",
        "django.core.mail.backends.filebased.EmailBackend",
        "django.core.mail.backends.dummy.EmailBackend",
    }

    if email_use_tls and email_use_ssl:
        return PreflightCheck(
            code="email_delivery",
            label="Email transaccional",
            status="fail",
            message="EMAIL_USE_TLS y EMAIL_USE_SSL no pueden estar activos al mismo tiempo.",
        )
    if debug:
        return PreflightCheck(
            code="email_delivery",
            label="Email transaccional",
            status="warn" if email_backend in non_production_backends else "ok",
            message=(
                "Entorno debug usa backend de email local; suficiente para desarrollo."
                if email_backend in non_production_backends
                else "Entorno debug ya usa backend de email externo."
            ),
        )
    if email_backend in non_production_backends:
        return PreflightCheck(
            code="email_delivery",
            label="Email transaccional",
            status="fail",
            message="Produccion no puede usar backend de email local/dummy.",
        )
    if not default_from:
        return PreflightCheck(
            code="email_delivery",
            label="Email transaccional",
            status="fail",
            message="DEFAULT_FROM_EMAIL debe estar configurado para reset y alertas.",
        )
    if email_backend == "django.core.mail.backends.smtp.EmailBackend" and not email_host:
        return PreflightCheck(
            code="email_delivery",
            label="Email transaccional",
            status="fail",
            message="EMAIL_HOST debe estar configurado cuando usas SMTP.",
        )
    return PreflightCheck(
        code="email_delivery",
        label="Email transaccional",
        status="ok",
        message="Email de produccion configurado para password reset y alertas.",
    )


def _check_database_runtime(runtime_status: dict[str, object]) -> PreflightCheck:
    database_status = runtime_status["database"]
    if not database_status.healthy:
        return PreflightCheck(
            code="database_runtime",
            label="Base de datos",
            status="fail",
            message=database_status.message,
        )
    return PreflightCheck(
        code="database_runtime",
        label="Base de datos",
        status="ok",
        message=database_status.message,
    )


def _check_realtime_runtime(runtime_status: dict[str, object]) -> PreflightCheck:
    channels_status = runtime_status["channels"]
    redis_status = runtime_status["redis"]
    if not channels_status.enabled:
        return PreflightCheck(
            code="realtime_runtime",
            label="Realtime",
            status="warn",
            message="Realtime deshabilitado. El chat seguira sin stream vivo hasta habilitarlo.",
        )
    if not channels_status.healthy:
        return PreflightCheck(
            code="realtime_runtime",
            label="Realtime",
            status="fail",
            message=channels_status.message,
        )
    if channels_status.mode == "memory":
        return PreflightCheck(
            code="realtime_runtime",
            label="Realtime",
            status="warn",
            message=f"{channels_status.message} {redis_status.message}",
        )
    return PreflightCheck(
        code="realtime_runtime",
        label="Realtime",
        status="ok",
        message=channels_status.message,
    )


def _check_cache_runtime(runtime_status: dict[str, object]) -> PreflightCheck:
    cache_status = runtime_status["cache"]
    if not cache_status.healthy:
        return PreflightCheck(
            code="cache_runtime",
            label="Cache operativo",
            status="fail",
            message=cache_status.message,
        )
    if cache_status.mode == "memory":
        return PreflightCheck(
            code="cache_runtime",
            label="Cache operativo",
            status="warn",
            message=cache_status.message,
        )
    return PreflightCheck(
        code="cache_runtime",
        label="Cache operativo",
        status="ok",
        message=cache_status.message,
    )


def _check_background_jobs_runtime(runtime_status: dict[str, object]) -> PreflightCheck:
    celery_status = runtime_status["celery"]
    result_backend_status = runtime_status["celery_result_backend"]
    if not celery_status.enabled:
        return PreflightCheck(
            code="background_jobs",
            label="Background jobs",
            status="warn",
            message="Background jobs deshabilitados. Activalos cuando montes workers de produccion.",
        )
    if not celery_status.healthy:
        return PreflightCheck(
            code="background_jobs",
            label="Background jobs",
            status="fail",
            message=celery_status.message,
        )
    if celery_status.mode == "eager":
        return PreflightCheck(
            code="background_jobs",
            label="Background jobs",
            status="warn",
            message=f"{celery_status.message} {result_backend_status.message}",
        )
    if result_backend_status.configured and not result_backend_status.healthy:
        return PreflightCheck(
            code="background_jobs",
            label="Background jobs",
            status="fail",
            message=f"{celery_status.message} {result_backend_status.message}",
        )
    if not result_backend_status.configured:
        return PreflightCheck(
            code="background_jobs",
            label="Background jobs",
            status="warn",
            message=f"{celery_status.message} {result_backend_status.message}",
        )
    return PreflightCheck(
        code="background_jobs",
        label="Background jobs",
        status="ok",
        message=f"{celery_status.message} {result_backend_status.message}",
    )
