from __future__ import annotations

from dataclasses import dataclass
from typing import Callable
from urllib.parse import urlparse
from uuid import uuid4

from django.conf import settings
from django.core.cache import caches
from django.db import connection


@dataclass(frozen=True)
class ServiceRuntimeStatus:
    enabled: bool
    available: bool
    configured: bool
    healthy: bool
    mode: str
    message: str


@dataclass(frozen=True)
class RuntimeProbeResult:
    healthy: bool
    message: str


ProbeCallable = Callable[..., RuntimeProbeResult]


def _execute_probe(*, label: str, probe: ProbeCallable, settings_obj) -> RuntimeProbeResult:
    try:
        return probe(settings_obj=settings_obj)
    except Exception as exc:  # pragma: no cover - exercised by integration/runtime failures
        return RuntimeProbeResult(healthy=False, message=f"{label} fallo: {exc}")


def _probe_database(*, settings_obj=None) -> RuntimeProbeResult:
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1")
        cursor.fetchone()
    return RuntimeProbeResult(healthy=True, message="Base de datos responde a SELECT 1.")


def _probe_redis_url(redis_url: str, *, label: str) -> RuntimeProbeResult:
    from redis import Redis

    client = Redis.from_url(
        redis_url,
        socket_connect_timeout=1,
        socket_timeout=1,
    )
    try:
        if not client.ping():
            raise RuntimeError("PING no devolvio respuesta valida.")
    finally:
        client.close()
    return RuntimeProbeResult(healthy=True, message=f"{label} responde a PING.")


def _probe_redis(*, settings_obj=None) -> RuntimeProbeResult:
    redis_url = str(getattr(settings_obj, "REDIS_URL", "") or "").strip()
    return _probe_redis_url(redis_url, label="Redis")


def _probe_cache(*, settings_obj=None) -> RuntimeProbeResult:
    cache = caches["default"]
    key = f"binn:health:{uuid4().hex}"
    value = uuid4().hex
    cache.set(key, value, timeout=15)
    cached = cache.get(key)
    cache.delete(key)
    if cached != value:
        raise RuntimeError("La cache no devolvio el valor recien escrito.")
    return RuntimeProbeResult(healthy=True, message="Cache default responde a set/get.")


def _probe_celery_broker(*, settings_obj=None) -> RuntimeProbeResult:
    from kombu import Connection

    broker_url = str(getattr(settings_obj, "CELERY_BROKER_URL", "") or "").strip()
    conn = Connection(broker_url, connect_timeout=2)
    try:
        conn.ensure_connection(max_retries=1)
    finally:
        conn.release()
    return RuntimeProbeResult(healthy=True, message="Broker de Celery acepta conexiones.")


def _probe_celery_workers(*, settings_obj=None) -> RuntimeProbeResult:
    from config.celery import app as celery_app

    replies = celery_app.control.inspect(timeout=1).ping() or {}
    if not replies:
        raise RuntimeError("No hay workers de Celery respondiendo al ping.")
    return RuntimeProbeResult(healthy=True, message=f"{len(replies)} worker(s) de Celery responden al ping.")


def _probe_celery_result_backend(*, settings_obj=None) -> RuntimeProbeResult:
    result_backend = str(getattr(settings_obj, "CELERY_RESULT_BACKEND", "") or "").strip()
    if not result_backend:
        return RuntimeProbeResult(
            healthy=True,
            message="Celery result backend no configurado; aceptable si no necesitas resultados persistidos.",
        )

    scheme = urlparse(result_backend).scheme.lower()
    if scheme.startswith("redis"):
        return _probe_redis_url(result_backend, label="Celery result backend")

    return RuntimeProbeResult(
        healthy=True,
        message="Celery result backend configurado; no existe sonda activa para este backend.",
    )


def is_runtime_healthy(runtime_status: dict[str, ServiceRuntimeStatus]) -> bool:
    return all(service.healthy for service in runtime_status.values())


def serialize_runtime_status(runtime_status: dict[str, ServiceRuntimeStatus]) -> dict[str, dict[str, object]]:
    return {
        key: {
            "enabled": value.enabled,
            "available": value.available,
            "configured": value.configured,
            "healthy": value.healthy,
            "mode": value.mode,
            "message": value.message,
        }
        for key, value in runtime_status.items()
    }


def get_runtime_services_status(*, settings_obj=None, probe_overrides: dict[str, ProbeCallable] | None = None) -> dict[str, ServiceRuntimeStatus]:
    settings_obj = settings_obj or settings
    probe_overrides = probe_overrides or {}

    database_probe = probe_overrides.get("database", _probe_database)
    redis_probe = probe_overrides.get("redis", _probe_redis)
    cache_probe = probe_overrides.get("cache", _probe_cache)
    celery_broker_probe = probe_overrides.get("celery_broker", _probe_celery_broker)
    celery_workers_probe = probe_overrides.get("celery_workers", _probe_celery_workers)
    celery_result_backend_probe = probe_overrides.get("celery_result_backend", _probe_celery_result_backend)

    database_result = _execute_probe(label="Base de datos", probe=database_probe, settings_obj=settings_obj)
    database_status = ServiceRuntimeStatus(
        enabled=True,
        available=True,
        configured=True,
        healthy=database_result.healthy,
        mode="sql",
        message=database_result.message,
    )

    redis_url = str(getattr(settings_obj, "REDIS_URL", "") or "").strip()
    channels_available = bool(getattr(settings_obj, "CHANNELS_AVAILABLE", False))
    channels_redis_available = bool(getattr(settings_obj, "CHANNELS_REDIS_AVAILABLE", False))
    enable_realtime = bool(getattr(settings_obj, "ENABLE_REALTIME", False))
    require_redis_for_realtime = bool(getattr(settings_obj, "REQUIRE_REDIS_FOR_REALTIME", False))
    channel_backend = (
        getattr(settings_obj, "CHANNEL_LAYERS", {})
        .get("default", {})
        .get("BACKEND", "")
    )
    channel_uses_redis = channel_backend == "channels_redis.core.RedisChannelLayer"
    channel_uses_memory = channel_backend == "channels.layers.InMemoryChannelLayer"

    celery_available = bool(getattr(settings_obj, "CELERY_AVAILABLE", False))
    enable_background_jobs = bool(getattr(settings_obj, "ENABLE_BACKGROUND_JOBS", False))
    celery_broker_url = str(getattr(settings_obj, "CELERY_BROKER_URL", "") or "").strip()
    celery_result_backend = str(getattr(settings_obj, "CELERY_RESULT_BACKEND", "") or "").strip()
    celery_always_eager = bool(getattr(settings_obj, "CELERY_TASK_ALWAYS_EAGER", False))
    cache_backend = getattr(settings_obj, "CACHES", {}).get("default", {}).get("BACKEND", "")

    redis_required = require_redis_for_realtime or enable_background_jobs
    redis_configured = bool(redis_url)

    if redis_required and not redis_configured:
        redis_status = ServiceRuntimeStatus(
            enabled=True,
            available=True,
            configured=False,
            healthy=False,
            mode="missing",
            message="Redis es requerido por el modo actual, pero REDIS_URL no esta configurado.",
        )
    elif redis_configured:
        redis_result = _execute_probe(label="Redis", probe=redis_probe, settings_obj=settings_obj)
        redis_status = ServiceRuntimeStatus(
            enabled=True,
            available=True,
            configured=True,
            healthy=redis_result.healthy,
            mode="configured",
            message=redis_result.message,
        )
    else:
        redis_status = ServiceRuntimeStatus(
            enabled=False,
            available=True,
            configured=False,
            healthy=True,
            mode="disabled",
            message="Redis no esta configurado; se usa solo para entornos locales sin cola real.",
        )

    if not enable_realtime:
        channels_status = ServiceRuntimeStatus(
            enabled=False,
            available=channels_available,
            configured=False,
            healthy=True,
            mode="disabled",
            message="Realtime deshabilitado por configuracion.",
        )
    elif not channels_available:
        channels_status = ServiceRuntimeStatus(
            enabled=True,
            available=False,
            configured=False,
            healthy=False,
            mode="missing_dependency",
            message="ENABLE_REALTIME esta activo pero Channels no esta instalado.",
        )
    elif channel_uses_redis:
        channels_healthy = redis_status.healthy and channels_redis_available
        channels_status = ServiceRuntimeStatus(
            enabled=True,
            available=True,
            configured=redis_configured and channels_redis_available,
            healthy=channels_healthy,
            mode="redis",
            message=(
                "Realtime opera sobre Redis y la sonda de Redis responde."
                if channels_healthy
                else f"Realtime usa Redis pero la base realtime no esta sana. {redis_status.message}"
            ),
        )
    elif channel_uses_memory:
        channels_status = ServiceRuntimeStatus(
            enabled=True,
            available=True,
            configured=True,
            healthy=not require_redis_for_realtime,
            mode="memory",
            message=(
                "Realtime usa InMemoryChannelLayer; aceptable en local."
                if not require_redis_for_realtime
                else "Realtime quedo en InMemoryChannelLayer y el entorno exige Redis."
            ),
        )
    else:
        channels_status = ServiceRuntimeStatus(
            enabled=True,
            available=True,
            configured=bool(channel_backend),
            healthy=bool(channel_backend),
            mode="custom" if channel_backend else "unconfigured",
            message="Channels usa un backend personalizado." if channel_backend else "Channels no tiene CHANNEL_LAYERS configurado.",
        )

    if cache_backend:
        cache_result = _execute_probe(label="Cache", probe=cache_probe, settings_obj=settings_obj)
    else:
        cache_result = RuntimeProbeResult(healthy=False, message="No existe cache default configurado.")

    if cache_backend == "django.core.cache.backends.redis.RedisCache":
        cache_status = ServiceRuntimeStatus(
            enabled=True,
            available=True,
            configured=True,
            healthy=cache_result.healthy,
            mode="redis",
            message=cache_result.message,
        )
    elif cache_backend == "django.core.cache.backends.locmem.LocMemCache":
        cache_status = ServiceRuntimeStatus(
            enabled=True,
            available=True,
            configured=True,
            healthy=cache_result.healthy,
            mode="memory",
            message=cache_result.message if cache_result.healthy else "Cache local fallo en la sonda set/get.",
        )
    else:
        cache_status = ServiceRuntimeStatus(
            enabled=bool(cache_backend),
            available=True,
            configured=bool(cache_backend),
            healthy=cache_result.healthy,
            mode="custom" if cache_backend else "unconfigured",
            message=cache_result.message,
        )

    if not enable_background_jobs:
        celery_status = ServiceRuntimeStatus(
            enabled=False,
            available=celery_available,
            configured=bool(celery_broker_url),
            healthy=True,
            mode="disabled",
            message="Workers de background deshabilitados por configuracion.",
        )
    elif not celery_available:
        celery_status = ServiceRuntimeStatus(
            enabled=True,
            available=False,
            configured=False,
            healthy=False,
            mode="missing_dependency",
            message="ENABLE_BACKGROUND_JOBS esta activo pero Celery no esta instalado.",
        )
    elif celery_always_eager:
        celery_status = ServiceRuntimeStatus(
            enabled=True,
            available=True,
            configured=True,
            healthy=True,
            mode="eager",
            message="Celery corre en modo eager dentro del proceso web.",
        )
    elif not celery_broker_url:
        celery_status = ServiceRuntimeStatus(
            enabled=True,
            available=True,
            configured=False,
            healthy=False,
            mode="missing_broker",
            message="Celery esta habilitado pero CELERY_BROKER_URL no esta configurado.",
        )
    else:
        broker_result = _execute_probe(label="Broker de Celery", probe=celery_broker_probe, settings_obj=settings_obj)
        worker_result = _execute_probe(label="Worker de Celery", probe=celery_workers_probe, settings_obj=settings_obj)
        celery_status = ServiceRuntimeStatus(
            enabled=True,
            available=True,
            configured=True,
            healthy=broker_result.healthy and worker_result.healthy,
            mode="worker",
            message=(
                f"{broker_result.message} {worker_result.message}"
                if broker_result.healthy and worker_result.healthy
                else (
                    broker_result.message
                    if not broker_result.healthy
                    else worker_result.message
                )
            ),
        )

    if not enable_background_jobs:
        result_backend_status = ServiceRuntimeStatus(
            enabled=False,
            available=True,
            configured=bool(celery_result_backend),
            healthy=True,
            mode="disabled",
            message="Celery result backend deshabilitado junto con los workers.",
        )
    elif not celery_result_backend:
        result_backend_status = ServiceRuntimeStatus(
            enabled=True,
            available=True,
            configured=False,
            healthy=True,
            mode="disabled",
            message="Celery result backend no configurado; aceptable si no necesitas resultados persistidos.",
        )
    else:
        result_backend_result = _execute_probe(
            label="Celery result backend",
            probe=celery_result_backend_probe,
            settings_obj=settings_obj,
        )
        result_backend_status = ServiceRuntimeStatus(
            enabled=True,
            available=True,
            configured=True,
            healthy=result_backend_result.healthy,
            mode="configured",
            message=result_backend_result.message,
        )

    return {
        "database": database_status,
        "redis": redis_status,
        "cache": cache_status,
        "channels": channels_status,
        "celery": celery_status,
        "celery_result_backend": result_backend_status,
    }
