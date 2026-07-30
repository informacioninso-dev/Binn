# Backlog consolidado activo de Binn

Fecha de consolidacion: 2026-07-30

## Objetivo

Unificar en un solo archivo los cambios pendientes que siguen abiertos en la documentacion del repo para arrancar desarrollo con una sola fuente de verdad operativa.

## Criterio de consolidacion

- Se incluyeron pendientes explicitos, siguientes pasos, deuda abierta y backlog de producto.
- Se deduplicaron items repetidos entre PRD, docs de fases y notas de UI.
- No se reabren tareas que documentos posteriores ya describen como implementadas.
- Este backlog nace desde la documentacion; antes de cerrar cada bloque conviene validarlo contra el codigo y las pruebas actuales.

## Fuentes usadas

- `README.md`
- `docs/binn-mvp-prd.md`
- `docs/fase-1-backlog.md`
- `docs/fase-1-migracion-identidad.md`
- `docs/fase-4-core-crm.md`
- `docs/fase-4-a-6-operacion-collab-verticales.md`
- `docs/fase-7-y-8-reportes-hardening.md`
- `docs/fase-11-realtime-workers.md`
- `docs/fase-12-a-14-hardening-staging-release.md`
- `docs/runbook-migracion-identidad-legado.md`
- `pendiente_ui.md`

## Base que ya se considera ejecutada segun docs

Esta seccion existe para no volver a planear trabajo que la documentacion mas nueva ya da por cerrado:

- identidad global con `identity.User` y auditoria base de sesion
- `access` como fuente principal de permisos tenant-locales
- `governance`, `consolidation` y `collab` ya separados como apps
- reportes corporativos iniciales para holdings
- hardening operativo base con `platform_preflight`
- runtime base con `health/runtime/`, `Channels` y `Celery` documentado
- runbook legado de identidad y auditoria `audit_identity_cutover` ya documentados
- packs operativos por vertical en tenants
- sidebar y navegacion base de UI marcadas como implementadas

## Decision operativa previa

### 1. Bases viejas previas a `AUTH_USER_MODEL`

Estado consolidado:

- En bases nuevas o reiniciables, la ruta recomendada es rebuild limpio.
- En bases existentes con datos reales, ya existe un runbook legado para migrar desde `auth_user` a `identity_user`.
- El comando `audit_identity_cutover` permite decidir si la base esta lista, si conviene bootstrap limpio o si hace falta el runbook.
- Mientras no se ensaye ese runbook sobre la base historica concreta, no conviene usar una base vieja como punto de partida para trabajo sensible de migraciones.

Ruta recomendada:

1. congelar escrituras
2. inventariar referencias actuales a `auth_user`
3. copiar usuarios hacia `identity_user`
4. conservar ids o remapear foreign keys de forma controlada
5. recrear constraints hacia la nueva tabla
6. validar login, admin, memberships y auditoria
7. abrir trafico solo despues de prueba completa

Decision practica para comenzar desarrollo:

- Si vamos a trabajar sobre entorno local reiniciable, usar base fresca.
- Si vamos a tocar una base historica, primero correr `audit_identity_cutover` y ensayar el runbook legado completo.

## Backlog activo priorizado

### P0. Fundacion configurable y core CRM vendible

#### Control plane y configuracion por tenant

- Extender `TenantConfig` para controlar modulos visibles por tenant.
- Permitir orden de modulos por tenant.
- Agregar widgets de dashboard configurables.
- Implementar `role_policies`.
- Implementar `document_blueprints`.
- Implementar `task_presets`.
- Implementar `collection_settings`.
- Implementar `communication_settings`.
- Implementar `quote_settings`.
- Implementar `module_order`.
- Implementar `homepage_layout`.
- Separar el perfil `marketing` en perfiles `servicios` y `retail_moda`.

#### Roles, permisos y auditoria

- Crear roles efectivos por tenant.
- Implementar permisos basicos por rol y modulo.
- Consolidar los entrypoints mutadores del CRM bajo un solo patron de permisos.
- Cerrar auditoria minima de acciones del CRM, no solo login o eventos tecnicos.

#### Core CRM vendible

- Implementar timeline 360 en la ficha.
- Implementar tareas con fecha, responsable y recordatorios.
- Mostrar tablero o dashboard con pendientes reales.
- Agregar importacion CSV.
- Agregar busqueda global.
- Hacer notas y actividades mas rapidas de registrar.
- Crear estados vacios guiados.
- Agregar filtros guardados.

#### Deuda tecnica para cerrar esta etapa

- Mover pruebas funcionales del CRM a escenarios con `ActiveAccessContext`.
- Separar la futura lectura consolidada del request path tenant-local.

### P1. Vertical broker

- Flujo `lead -> asegurado -> renovacion`.
- Vencimientos.
- Checklist documental por tipo de poliza.
- Cobranza ligera.
- Seguimiento de siniestros lite.

### P2. Vertical servicios / consultoria

- Oportunidades B2B.
- Propuestas y cotizaciones.
- Reuniones.
- Handoff comercial -> servicio.
- Renovaciones y upsell.

### P3. Vertical condominio

- Residentes y unidades.
- Cartera.
- Seguimiento de cobro.
- Comunicados.
- Incidencias simples.
- Adjuntos.

### P4. Vertical retail moda

- Ficha de cliente retail.
- Preferencias.
- WhatsApp follow-up.
- Listas por segmento.
- Recompra e inactividad.

### P5. Capa de producto para que Binn se sienta serio

- Widgets por vertical.
- Mas filtros.
- Plantillas de documentos.
- Reportes simples por tenant.
- Datos demo iniciales por perfil.

### P6. Crecimiento comercial

- Formularios web para captacion.
- Difusiones por WhatsApp o email.
- Integraciones ligeras.
- Onboarding guiado.

### P7. Diferenciacion futura

- Automatizaciones por reglas.
- Bandeja unificada.
- S3 completo con previews.
- IA utilitaria.
- Reportes avanzados.

## Pendientes de UI y UX

### Fase UI-2. Dashboard operativo

- Priorizar tareas de hoy, oportunidades activas, clientes pendientes y cobros o documentos en riesgo.
- Reducir tarjetas decorativas o repetidas.
- Separar acciones de consulta, seguimiento y cierre.
- Mejorar estados vacios con mensajes utiles.
- Revisar jerarquia visual para lectura rapida.

### Fase UI-3. Lenguaje comercial

- Revisar microcopy en botones, CTAs, labels, estados vacios y ayudas.
- Usar verbos de trabajo: operar, seguir, cobrar, cerrar, resolver.
- Evitar textos demasiado administrativos cuando la accion es comercial.
- Alinear nombres de modulos por vertical: broker, servicios, condominios y retail.
- Cerrar deuda visual y copy que todavia arrastra textos o labels legacy.

### Fase UI-4. Pantallas internas

- Revisar listados, filtros, detalles y formularios.
- Normalizar espaciados, botones, badges, iconos y estados activos.
- Mejorar densidad de informacion sin volver pesada la interfaz.
- Validar que las acciones primarias sean claras en cada pantalla.

### Fase UI-5. Responsive y QA visual

- Probar sidebar abierto y contraido en desktop.
- Probar navegacion horizontal en tablet y movil.
- Verificar que no haya textos cortados ni solapados.
- Revisar foco, hover, `aria-labels` y tooltips.
- Ejecutar checks y pruebas automatizadas antes de cerrar UI.

## Orden recomendado para arrancar desarrollo

1. Resolver si trabajaremos con base fresca o si hace falta ejecutar y validar el runbook legado.
2. Extender `TenantConfig` y cerrar roles y permisos por tenant.
3. Construir el bloque de core vendible: timeline, tareas, CSV, busqueda global y dashboard con pendientes.
4. Cerrar auditoria funcional y pruebas con `ActiveAccessContext`.
5. Construir primero el pack `broker` como vertical comercial inicial.
6. Seguir con `servicios`, luego `condominio`, luego `retail_moda`.
7. Dejar crecimiento comercial y diferenciacion para despues del primer MVP vendible.

## Traduccion a primeras epicas de desarrollo

### Epica 1. Base operativa

- Estrategia de base fresca o validacion del runbook legado.
- Cierre de deuda de migracion historica solo si se usara una base vieja con datos reales.

### Epica 2. Admin configurable

- `TenantConfig` extendido.
- Roles por tenant.
- Modulos, widgets y blueprints configurables.

### Epica 3. Core CRM vendible

- Timeline.
- Tareas.
- CSV.
- Busqueda.
- Dashboard operativo.

### Epica 4. Vertical broker

- Renovaciones.
- Vencimientos.
- Documentos.
- Cobranza ligera.

### Epica 5. UX transversal

- Copy comercial.
- Pantallas internas.
- Responsive y QA visual.

## Notas de lectura

- `docs/fase-1-backlog.md` queda como backlog historico de una fase ya absorbida por docs posteriores.
- `pendiente_ui.md` sigue siendo la fuente mas directa de deuda visual, pero Fase 1 de sidebar aparece como implementada y por eso no se trae como pendiente activo.
- Los items de health checks operativos no se traen como pendiente principal porque docs posteriores ya marcan una capa inicial de hardening y `platform_preflight` como existentes.
- El backlog consolidado debe revisarse cada vez que aparezca un doc posterior que cambie un item de `pendiente` a `documentado` o `ejecutado`.