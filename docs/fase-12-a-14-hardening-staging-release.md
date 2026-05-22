# Fases 12 a 14 · Hardening, Staging y Salida

Estas fases cierran el salto entre demo funcional y operacion seria.

## Fase 12 · Hardening

### Ya resuelto en codigo

- throttle de login por cache con ventana y lockout
- `must_rotate_password` forzado por middleware
- cache operativo configurable por `CACHE_URL`
- `health/` y `platform_preflight` reportan cache, realtime y workers

### Variables nuevas

- `CACHE_URL`
- `LOGIN_RATE_LIMIT_ATTEMPTS`
- `LOGIN_RATE_LIMIT_WINDOW_SECONDS`
- `LOGIN_RATE_LIMIT_LOCKOUT_SECONDS`

## Fase 13 · Staging y demo comercial

### Comando unico

```bash
python manage.py bootstrap_demo_stack --admin-user admin --admin-password "BinnAdmin2026!"
```

Provisiona o refresca:

- `demo.localhost`
- `broker.localhost`
- `condominio.localhost`
- `marketing.localhost`

Y deja un holding demo con modos mixtos:

- `full`
- `aggregate_only`
- `blocked`

Eso permite mostrar:

- tenant solo
- grupo/holding
- consolidacion parcial
- bloqueo de visibilidad

## Fase 14 · Salida controlada

### Checklist minimo

1. `python manage.py platform_preflight --strict`
2. levantar `daphne`
3. levantar `celery`
4. verificar `/health/` y luego `/health/runtime/` con superadmin
5. correr suite principal de tests
6. refrescar stack demo
7. probar flujos con:
   - superadmin
   - group admin
   - tenant admin
   - usuario normal
8. validar kill switch y cambio de tenant

### Comandos recomendados

```bash
daphne -b 0.0.0.0 -p 8007 config.asgi:application
celery -A config worker -l info
python manage.py platform_preflight --strict
python manage.py bootstrap_demo_stack --admin-user admin --admin-password "BinnAdmin2026!"
```

## Nota operativa

Si `platform_preflight` te devuelve:

- `cache_runtime` en `warn`: sigues en cache local
- `realtime_runtime` en `warn`: sigues en `InMemoryChannelLayer`
- `background_jobs` en `warn`: Celery sigue deshabilitado o en modo no productivo

Mientras eso ocurra, el entorno sigue siendo apto para demo o staging ligero, no para carga seria.
