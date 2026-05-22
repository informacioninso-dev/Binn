# Fase 5: consolidacion corporativa

## Objetivo

Habilitar lectura corporativa real para holdings sin perder el aislamiento legal y operativo entre empresas.

## Principios que quedan cerrados

- el holding puede existir aunque las empresas no se vean entre si
- `Client.allow_consolidation` es el kill switch maestro a nivel empresa
- `GroupTenantLink.consolidation_mode` define el alcance dentro del grupo
- los dashboards corporativos leen snapshots en `public`, no hacen fan-out cross-schema en vivo

## Modos efectivos

- `blocked`: la empresa pertenece al holding, pero no comparte datos
- `aggregate_only`: la empresa aporta KPIs agregados, sin drill-down operativo
- `full`: la empresa aporta KPIs y permite abrir el tenant desde el holding

## Lo que implementa este corte

- app `consolidation` en `SHARED_APPS`
- snapshots por tenant y por grupo
- corridas de sync auditables
- dashboard de holding con resumen y filas por empresa
- drill-down solo para empresas con `full`
- comando `sync_consolidation` para sincronizar manualmente

## Resultado operativo

El admin de Binn puede vincular empresas a un holding y, aun asi, dejar una o varias en modo hermetico. El admin general del holding solo vera lo que la politica efectiva permita.
