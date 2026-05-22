# Fase 0: Arquitectura base de Binn

## Objetivo

Fijar la arquitectura que soportara un CRM multi-tenant con gobernanza corporativa sin seguir acumulando logica de identidad, permisos y switching dentro de `tenants`.

La salida de esta fase no es un feature comercial. La salida de esta fase es una base estructural que permita construir el resto del producto sin deuda critica ni parches peligrosos.

## Estado actual del repo

- `public` schema ya actua como control plane parcial.
- `TenantMembership`, autenticacion tenant-aware y switching viven mezclados dentro de `tenants`.
- El usuario actual depende todavia del modelo por defecto de Django.
- `binncrm` ya funciona como app tenant-local y debe preservarse como modulo de dominio, no como lugar de gobernanza.

## Decisiones cerradas

1. `public` schema sera el control plane global.
2. Se migrara a `AUTH_USER_MODEL` propio antes de construir holdings, impersonacion o realtime.
3. Toda autorizacion pasara por un `AccessResolver`.
4. `tenants` conservara solo lifecycle de tenant, dominios y aprovisionamiento.
5. La consolidacion corporativa no consultara datos cross-schema en vivo para dashboards.
6. El kill switch del Super Admin debe revocar acceso inter-tenant en tiempo real.
7. Chat, websockets y workers distribuidos entran solo despues de cerrar scopes y ACL.

## Arquitectura objetivo

```text
config/
core/
identity/
tenants/
governance/
access/
binncrm/
consolidation/
collab/
docs/
```

## Responsabilidad por app

### `identity`

- `CustomUser`
- sesiones globales
- politicas de autenticacion
- MFA y estados de cuenta
- auditoria de login

### `tenants`

- `Client`
- `Domain`
- provisioning
- lifecycle del tenant
- utilidades de bootstrap

### `governance`

- `CorporateGroup`
- vinculos tenant <-> grupo
- politicas de consolidacion
- kill switch corporativo
- impersonacion administrativa

### `access`

- `TenantMembership`
- `AccessResolver`
- `ActiveSessionContext`
- permisos por scope
- middleware y decorators de enforcement

### `binncrm`

- entidades CRM tenant-locales
- pipelines
- actividades
- documentos
- vistas de operacion del negocio

### `consolidation`

- snapshots corporativos
- KPI agregados
- jobs de sincronizacion
- reportes comparativos

### `collab`

- canales
- mensajes
- notificaciones
- realtime y websocket ACL

## Flujos que deben quedar soportados

### 1. Login global

El usuario autentica una sola vez y luego el sistema resuelve a que tenants o grupos puede entrar.

### 2. Switching de tenant

El cambio de empresa ocurre por request y depende de un contexto activo validado server-side.

### 3. Modo silo

El usuario solo puede operar dentro del tenant activo. No existe detalle cross-tenant aunque pertenezca a un holding.

### 4. Modo consolidado

El usuario puede navegar entre tenants autorizados del mismo holding solo si la politica corporativa y el kill switch lo permiten.

### 5. Revocacion inmediata

Si el Super Admin apaga consolidacion para un tenant o grupo, el acceso derivado deja de existir sin redeploy.

## Antipatrones prohibidos

- Checks de permisos repartidos entre vistas, forms, templates y helpers.
- Consultas cross-schema en el request path de dashboards corporativos.
- Confiar en `tenant_id` o `group_id` enviados por frontend sin resolver contexto.
- Workers sin `tenant_id`, `actor_id`, `scope` y `request_id`.
- WebSockets sin ACL equivalente a HTTP.
- Mas booleans sueltos cuando en realidad hay politicas o estados versionables.

## Entregables de Fase 0

1. ADR de control plane y boundaries.
2. ADR de session scopes y `AccessResolver`.
3. Backlog ejecutable de Fase 1.
4. Scaffolding de apps nuevas.
5. Contratos base en codigo para acceso y resolucion de contexto.

## Criterio de salida

La fase termina cuando:

- la arquitectura queda documentada,
- las fronteras entre apps quedan fijadas,
- el contrato de acceso deja de ser implicito,
- y Fase 1 puede empezar con migracion real de identidad sin redefinir decisiones base.
