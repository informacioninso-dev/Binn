# Fase 1: migracion segura a identidad global

## Lo que ya quedo implementado

- app `identity`
- `AUTH_USER_MODEL = "identity.User"`
- modelo `User` global
- auditoria base de sesiones con `GlobalSession`
- middleware y signals para registrar login, logout y actividad
- capa transicional en `access` para empezar a sacar membresias de `tenants`

## Advertencia importante

Cambiar `AUTH_USER_MODEL` en Django despues de haber usado `auth_user` en una base ya poblada no es un cambio trivial.

Si tu base local ya tenia migraciones aplicadas antes de este cambio, es esperable que aparezcan errores de historial como `InconsistentMigrationHistory` hasta que reinicies la base o ejecutes un runbook legado.

En este proyecto la adopcion segura depende del estado real de la base:

### Escenario A: ambiente nuevo o reiniciable

Este es el camino recomendado.

1. crear una base limpia,
2. correr migraciones con `identity.User` ya activo,
3. recrear superusuarios y tenants bootstrap,
4. importar solo datos de negocio que realmente deban sobrevivir.

### Escenario B: base existente con datos que deben preservarse

No se debe correr este cambio a ciegas sobre esa base.

Hace falta un runbook dedicado para:

1. congelar escrituras,
2. inventariar referencias actuales a `auth_user`,
3. copiar usuarios hacia `identity_user`,
4. conservar ids o remapear foreign keys de forma controlada,
5. recrear constraints hacia la nueva tabla,
6. validar login, admin, memberships y auditoria,
7. abrir trafico solo despues de prueba completa.

## Regla operativa

Mientras no exista ese runbook de datos legado, esta fase se considera lista para:

- desarrollo nuevo,
- ambientes reiniciables,
- y despliegues donde todavia no exista una base productiva dependiente de `auth_user`.

## Implicacion para este repo hoy

El codigo ya quedo preparado para arrancar con identidad global.

Eso significa:

- en una base nueva, la cadena de migraciones queda consistente,
- en una base vieja del proyecto, primero hay que reconstruir o migrar el historial,
- y no conviene seguir desarrollando holdings o consolidacion sobre la identidad anterior.

## Siguiente paso

Fase 1 continua con:

1. mover `TenantMembership` hacia `access`,
2. introducir `ActiveSessionContext`,
3. reemplazar el switching actual por contexto activo formal,
4. preparar la base para `governance`.
