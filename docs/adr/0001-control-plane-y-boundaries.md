# ADR 0001: Control plane y boundaries de dominio

- Estado: aceptado
- Fecha: 2026-05-04

## Contexto

El proyecto actual ya usa `django-tenants` y el `public` schema concentra autenticacion compartida, creacion de tenants y acceso administrativo. Sin embargo, la identidad global, las membresias, el switching y parte del enforcement viven mezclados dentro de `tenants`.

Si seguimos construyendo asi, la evolucion hacia holdings, consolidacion, impersonacion y realtime quedara acoplada a una app que deberia encargarse principalmente del lifecycle del tenant.

## Decision

Se adopta la siguiente separacion:

- `identity`: identidad global y sesiones.
- `tenants`: tenants, dominios y provisioning.
- `governance`: holdings, kill switch y politicas de consolidacion.
- `access`: membresias, contextos activos y autorizacion.
- `consolidation`: snapshots y lectura corporativa.
- `collab`: mensajeria, notificaciones y realtime.

El `public` schema sera el control plane global del producto. No se introduce una base maestra separada en esta etapa.

## Consecuencias

### Positivas

- La identidad deja de depender del tenant activo.
- El switching deja de ser una combinacion de redirects y membership checks dispersos.
- Se vuelve posible modelar consolidacion y modo silo sin contaminar `binncrm`.
- La auditoria de acceso y revocacion gana un punto unico de control.

### Costos

- Habra una migracion de usuarios y membresias.
- Parte del codigo actual de `tenants` quedara transicionalmente duplicado.
- Fase 1 debe tocar autenticion y settings, no solo vistas.

## Reglas derivadas

1. Ninguna app de negocio decide permisos finales.
2. Ninguna lectura corporativa detallada se hace cross-schema en vivo.
3. El kill switch del Super Admin se modela como politica del control plane y no como simple condicion UI.
