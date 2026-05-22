# Fase 1: Backlog ejecutable

## Objetivo

Implementar la capa de identidad global y preparar el reemplazo ordenado de la mezcla actual entre autenticacion, membresias y switching.

## Epica 1: `identity`

### Tareas

1. Crear app `identity`.
2. Definir `CustomUser`.
3. Declarar `AUTH_USER_MODEL`.
4. Disenar estrategia de migracion desde `auth_user`.
5. Crear modelo de sesion global auditable.
6. Registrar eventos de login, logout y bloqueo.

### Definiciones tecnicas

- El usuario existe una sola vez en Binn.
- Ningun tenant sera duenio del usuario.
- El estado de cuenta no dependera del schema activo.

## Epica 2: separacion de `TenantMembership`

### Tareas

1. Mover membresias hacia `access`.
2. Mantener compatibilidad temporal con el runtime actual.
3. Crear adaptador para leer membresias mientras dure la transicion.
4. Reescribir helpers para que dependan del contrato de acceso y no del ORM directo.

## Epica 3: contrato del `AccessResolver`

### Tareas

1. Definir sujeto, contexto, decision y errores.
2. Resolver acceso directo por tenant.
3. Reservar modos para acceso por grupo e impersonacion.
4. Integrar request context y auditoria.
5. Escribir pruebas unitarias puras para resolucion y rechazo.

## Epica 4: migracion del switching

### Tareas

1. Inventariar el flujo actual de `TenantSwitchView`.
2. Disenar `ActiveSessionContext`.
3. Resolver el tenant activo solo en servidor.
4. Eliminar dependencia de preview local como mecanismo principal.
5. Registrar cada cambio de contexto activo.

## Epica 5: admin y operaciones

### Tareas

1. Inventariar formularios y vistas que dependen del usuario actual.
2. Preparar ajustes para `createsuperuser`, bootstrap y seed.
3. Definir eventos de auditoria obligatorios.
4. Alinear logs con `request_id`, `actor_id`, `tenant_schema` y `scope`.

## Done de Fase 1

- `AUTH_USER_MODEL` propio activo.
- login unico global funcionando.
- contrato de acceso central listo para adoption.
- switching preparado para salir del modelo actual.
- sin perdida de aislamiento tenant-local.
