# Fases 4 a 6: Operacion, Colaboracion y Verticales

## Fase 4

El CRM ya opera sobre vistas guardadas reales del `ObjectView` engine:

- presets de entidades y deals en `binncrm.object_engine`
- aplicacion de filtros desde `binncrm.view_engine`
- chips de vistas en entidades y kanban
- paleta `Command K` para navegar y crear registros sin perder contexto

## Fase 5

`collab` ya vive como app tenant-local para no romper aislamiento por schema:

- conversaciones por equipo y por ficha
- mensajes internos y notificaciones dentro del tenant
- panel contextual en ficha de entidad
- inbox de colaboracion en `/crm/collab/`
- refresco liviano por HTMX polling, sin depender todavia de Channels

El cambio importante aqui es estructural: el modelo y los permisos de colaboracion ya quedaron separados. Si luego se enchufa Channels/Redis, el transporte cambia, no el dominio.

## Fase 6

Los perfiles del tenant ahora tambien son packs operativos visibles:

- `workspace_pack` por vertical
- rituales y focos de reporte por perfil
- lectura del pack en detalle de tenant y reportes del CRM
- comparativo por vertical en el dashboard consolidado del holding

## Validacion

- `manage.py check`
- `manage.py test core.tests tenants.tests binncrm.tests governance.tests consolidation.tests collab.tests`

Ambos pasan sobre una base fresca de pruebas. La base local vieja sigue arrastrando el problema historico de migraciones desde el cambio a `AUTH_USER_MODEL`, asi que para aplicar migraciones reales conviene rebuild o runbook legado.
