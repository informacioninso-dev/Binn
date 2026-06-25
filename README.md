# Binn CRM

Base inicial de Binn sobre Django + PostgreSQL schemas + HTMX.

## Alcance actual

- Multitenencia por schemas con `django-tenants`
- `TenantConfig` en esquema publico para perfilar cada negocio
- App privada interna `binncrm` con prefijo publico `/crm/`:
  - `Entity`
  - `Pipeline`
  - `Deal`
  - `Activity`
  - `Document`
- Dashboard dinamico segun `feature_flags` y `labels`
- Perfiles iniciales:
  - `condominio`
  - `broker`
  - `marketing`

## Arranque local

```bash
py -3.12 -m venv .venv
.venv\Scripts\activate
Copy-Item .env.example .env
python -m pip install --upgrade pip
pip install -r requirements.lock.txt
python manage.py migrate_schemas --shared
python manage.py setup_public_tenant --domains localhost,127.0.0.1 --name "Binn Public"
python manage.py createsuperuser
python manage.py runserver
```

Referencia local:

- Python `3.12`
- dependencias instaladas desde `requirements.lock.txt`
- PostgreSQL requerido por `django-tenants`
- si todavia no existe `.env`, Binn cae en perfil local seguro (`DEBUG=True`, hosts locales unicamente)

## Static y media en produccion

`collectstatic` ya escribe en `STATIC_ROOT` y el repo ahora trae artefactos de despliegue para servir `static/` y `media/` desde Nginx con volumen compartido:

- `Dockerfile`
- `docker-compose.prod.yml`
- `deploy/entrypoint.sh`
- `deploy/nginx/binn.conf`

En produccion:

- `static/` sale por Nginx desde `STATIC_ROOT`
- `media/` sale por Nginx desde `MEDIA_ROOT`
- la app ASGI corre por `daphne`
- el worker corre por `celery`

Si necesitas paths distintos, define `STATIC_ROOT`, `MEDIA_ROOT`, `STATIC_URL` y `MEDIA_URL` por entorno.

## Realtime y workers

Para operar con realtime y colas reales:

```bash
daphne -b 0.0.0.0 -p 8007 config.asgi:application
celery -A config worker -l info
python manage.py platform_preflight --strict
python manage.py bootstrap_demo_stack --admin-user admin --admin-password "BinnAdmin2026!"
```

`Channels` usa Redis si `REDIS_URL` esta configurado. `Celery` usa `CELERY_BROKER_URL` o, si no existe, reutiliza `REDIS_URL`.

`/health/` queda como liveness publico minimo. El diagnostico operativo con base, cache, Redis, realtime y Celery vive en `/health/runtime/` y requiere superadmin autenticado.

## Release reproducible

El repo ahora fija dependencias operativas en `requirements.lock.txt` y trae CI en `.github/workflows/ci.yml`.

Flujo recomendado:

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml build
docker compose --env-file .env.production -f docker-compose.prod.yml up -d
./deploy/release.sh
python manage.py platform_preflight --strict
```

`docker-compose.prod.yml` espera que `DB_NAME`, `DB_USER` y `DB_PASSWORD` vengan del mismo `.env.production` para que Postgres y Django queden alineados.

Si quieres terminar TLS dentro del mismo stack Docker, usa tambien:

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml -f docker-compose.prod.tls.yml up -d
```

El override TLS espera certificados en `deploy/certs/fullchain.pem` y `deploy/certs/privkey.pem`.

## Observabilidad y operacion

Variables nuevas para operacion:

- `LOG_FORMAT=json|text`
- `LOG_TO_STDOUT=True`
- `LOG_FILE_ENABLED=True`
- `LOG_FILE_PATH=/ruta/al/log`
- `DJANGO_ADMINS=Ops:ops@binn.example,CTO:cto@binn.example`
- `EMAIL_BACKEND`
- `EMAIL_HOST`
- `EMAIL_PORT`
- `EMAIL_HOST_USER`
- `EMAIL_HOST_PASSWORD`
- `EMAIL_USE_TLS`
- `EMAIL_USE_SSL`
- `DEFAULT_FROM_EMAIL`
- `SERVER_EMAIL`
- `PASSWORD_RESET_TIMEOUT`

Comandos operativos:

```bash
python manage.py send_test_email ops@binn.example
python manage.py operational_smoke_test --tenant-schema public
./deploy/backup_db.sh
CONFIRM_RESTORE=yes ./deploy/restore_db.sh ./backups/binn-20260101T000000Z.dump
```

## Crear un tenant

```bash
python manage.py bootstrap_tenant condominios "Condominios Centro" condominios.localhost --profile condominio --admin-user admin --admin-email admin@binn.local --admin-password "BinnAdmin2026!"
```

## Base activa

La base vigente del proyecto se apoya en `tenants`, `core` y `binncrm`. El paquete Django y el namespace interno son `binncrm`; el prefijo visible para el usuario sigue siendo `/crm/`. Los modulos legacy del vertical clinico fueron retirados del repo para mantener el foco en el CRM multi-tenant de Binn.

## Arquitectura ejecutada

La base del proyecto ya quedo separada para evitar deuda estructural en identidad, switching y permisos:

- `identity`: identidad global y sesiones
- `tenants`: lifecycle y provisioning de empresas
- `governance`: holdings, consolidacion y kill switch
- `access`: resolucion central de permisos y scopes de sesion
- `consolidation`: snapshots y lectura corporativa
- `collab`: realtime, canales y notificaciones

Documentacion de referencia:

- [`docs/fase-0-arquitectura.md`](docs/fase-0-arquitectura.md)
- [`docs/fase-1-backlog.md`](docs/fase-1-backlog.md)
- [`docs/fase-1-migracion-identidad.md`](docs/fase-1-migracion-identidad.md)
- [`docs/fase-3-session-scopes.md`](docs/fase-3-session-scopes.md)
- [`docs/fase-4-core-crm.md`](docs/fase-4-core-crm.md)
- [`docs/fase-5-consolidacion.md`](docs/fase-5-consolidacion.md)
- [`docs/fase-4-a-6-operacion-collab-verticales.md`](docs/fase-4-a-6-operacion-collab-verticales.md)
- [`docs/fase-7-y-8-reportes-hardening.md`](docs/fase-7-y-8-reportes-hardening.md)
- [`docs/fase-11-realtime-workers.md`](docs/fase-11-realtime-workers.md)
- [`docs/fase-12-a-14-hardening-staging-release.md`](docs/fase-12-a-14-hardening-staging-release.md)
- [`docs/adr/0001-control-plane-y-boundaries.md`](docs/adr/0001-control-plane-y-boundaries.md)
- [`docs/adr/0002-access-resolver-y-session-scopes.md`](docs/adr/0002-access-resolver-y-session-scopes.md)

## Hoja de ruta de producto

La propuesta de MVP, competencia y plan por verticales esta documentada en [`docs/binn-mvp-prd.md`](docs/binn-mvp-prd.md).
