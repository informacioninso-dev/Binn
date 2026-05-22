# Fases 7 y 8: Reportes Corporativos y Hardening

## Fase 7

La capa de consolidacion ya no se queda solo en un dashboard unico.

Ahora existe una vista dedicada de reportes corporativos para holdings con:

- rankings por empresa visible
- radar de riesgo operativo
- lectura por vertical
- resumen de modos de visibilidad
- trazabilidad de corridas de consolidacion

Ruta principal:

- `consolidation:group_reports`

## Fase 8

El repo ya tiene una capa inicial de hardening operativo:

- preflight ejecutable por comando
- checks de configuracion estructural
- refuerzo de pruebas para consolidacion y configuracion
- auditoria de colaboracion tenant-local en eventos operativos

Comando:

```bash
python manage.py platform_preflight
python manage.py platform_preflight --strict
```

## Validacion

- `manage.py check`
- `manage.py test core.tests tenants.tests binncrm.tests governance.tests consolidation.tests collab.tests`

## Nota operativa

La base local vieja sigue afectada por la inconsistencia historica de migraciones tras el cambio a `AUTH_USER_MODEL`. El codigo nuevo esta validado sobre base fresca de pruebas; para aplicar migraciones reales sobre esa base antigua toca rebuild o runbook legado.
