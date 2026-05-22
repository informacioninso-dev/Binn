# Fase 4: core CRM sobre access

## Objetivo

Quitar el acople legacy entre `binncrm`, `core`, `tenants` y el modelo viejo de membresias para que el CRM opere sobre una sola capa de acceso.

## Cambios estructurales de este corte

- `TenantMembership` vive en `access`.
- `access.permissions` pasa a ser la fuente real para permisos del CRM.
- `tenants` deja de ser duenio de membresias y queda enfocado en lifecycle, provisioning y UI operativa del tenant.
- `RequestAccessResolver` reemplaza el nombre transicional del resolver anterior.

## Lo que se limpio

- formularios, vistas, middleware y backend de autenticacion dejaron de importar membresias desde `tenants.models`
- `core` y `binncrm` ya consumen permisos desde `access.permissions`
- se eliminaron wrappers de permisos y helpers que mantenian rutas legacy dentro de `tenants`
- las migraciones nuevas crean membresias desde `access`

## Resultado esperado

- una sola fuente de verdad para acceso tenant-local
- menos riesgo de reglas divergentes entre middleware, vistas y CRM
- base lista para consolidacion corporativa y reportes sin seguir arrastrando acoples

## Lo siguiente dentro de Fase 4

1. consolidar query helpers del CRM para que todo entrypoint mutador pase por el mismo patron de permisos
2. mover pruebas funcionales del CRM a escenarios con `ActiveAccessContext`
3. separar lectura consolidada futura del request path tenant-local
4. cerrar deuda visual y copy que todavia arrastra textos o labels legacy
