# Fase 11 · Realtime y Workers

La Fase 11 aterriza la capa operativa para que Binn no dependa solo del proceso web:

- `Channels` ya puede correr en modo real con Redis si `REDIS_URL` esta configurado.
- `Celery` queda cableado para workers y tareas asincronas.
- `health/` y `platform_preflight` ahora exponen el estado de Redis, Channels y Celery.

## Variables nuevas

- `ENABLE_REALTIME`
- `REQUIRE_REDIS_FOR_REALTIME`
- `REDIS_URL`
- `ENABLE_BACKGROUND_JOBS`
- `CELERY_BROKER_URL`
- `CELERY_RESULT_BACKEND`
- `CELERY_TASK_ALWAYS_EAGER`
- `CELERY_TASK_EAGER_PROPAGATES`
- `CELERY_TASK_DEFAULT_QUEUE`
- `CELERY_TASK_TIME_LIMIT`
- `CELERY_TASK_SOFT_TIME_LIMIT`
- `CELERY_WORKER_PREFETCH_MULTIPLIER`

## Modos de runtime

### Local simple

- `ENABLE_REALTIME=True`
- `REQUIRE_REDIS_FOR_REALTIME=False`
- `ENABLE_BACKGROUND_JOBS=False`

Con eso:

- WebSockets usan `InMemoryChannelLayer`
- no hace falta Redis
- no hace falta levantar workers

### Staging / Produccion

- `ENABLE_REALTIME=True`
- `REQUIRE_REDIS_FOR_REALTIME=True`
- `REDIS_URL=redis://...`
- `ENABLE_BACKGROUND_JOBS=True`
- `CELERY_BROKER_URL=redis://...`

Con eso:

- WebSockets salen por Redis
- Celery deja de correr inline
- el preflight falla si falta Redis o Celery

## Tareas asincronas habilitadas

- `consolidation.sync_group_snapshot`
- `consolidation.sync_tenant_snapshot`
- `consolidation.sync_all_active_group_snapshots`
- `core.platform_preflight_snapshot`

## Comandos operativos

```bash
python manage.py platform_preflight
python manage.py platform_preflight --strict
```

```bash
daphne -b 0.0.0.0 -p 8007 config.asgi:application
```

```bash
celery -A config worker -l info
```

## Lectura de salud

`/health/` ahora queda como liveness publico minimo y `/health/runtime/` expone el diagnostico operativo autenticado.

`/health/runtime/` devuelve:

- estado de base
- tenant actual
- estado de Redis
- backend realtime (`redis` o `memory`)
- modo de Celery (`worker`, `eager`, `disabled`)

Eso permite revisar de un vistazo si el entorno corre de verdad como SaaS con realtime y workers, o solo como demo local.
