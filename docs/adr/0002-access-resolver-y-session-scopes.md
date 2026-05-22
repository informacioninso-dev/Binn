# ADR 0002: AccessResolver y session scopes

- Estado: aceptado
- Fecha: 2026-05-04

## Contexto

El proyecto actual valida acceso usando una mezcla de backend de autenticacion, middleware y checks directos sobre `TenantMembership`. Ese enfoque funciona para acceso tenant-local basico, pero no soporta de forma limpia:

- acceso consolidado por grupo,
- modo silo,
- impersonacion,
- revocacion inmediata,
- ACL consistente entre HTTP, workers y websocket.

## Decision

Toda autorizacion se centralizara en un `AccessResolver`.

El resolver trabajara con:

- un sujeto autenticado global,
- un contexto de sesion activo,
- un tenant objetivo,
- y un scope explicito.

Los scopes iniciales seran:

- `strict_isolation`
- `consolidated`
- `impersonated`

El resultado de resolucion debe ser una decision estructurada y auditable, no un booleano suelto.

## Consecuencias

### Positivas

- Las reglas de acceso se vuelven trazables.
- Se puede invalidar acceso derivado sin barrer el codigo.
- HTTP, Celery y websocket pueden compartir la misma fuente de verdad.

### Costos

- Habra que introducir contratos y excepciones nuevas.
- Las vistas actuales deberan migrar hacia decorators o servicios nuevos.
- El switching del tenant activo ya no podra depender solo del dominio o de params locales.

## Reglas derivadas

1. Toda decision debe incluir motivo y origen del acceso.
2. El frontend nunca decide el scope real.
3. El kill switch puede degradar un contexto consolidado a rechazo total o a modo silo.
