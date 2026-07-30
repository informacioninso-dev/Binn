# Runbook de migracion de identidad legado

Fecha de referencia: 2026-07-30

## Objetivo

Dar una ruta controlada para bases viejas que todavia arrastran `auth_user` o referencias historicas previas al cambio hacia `identity.User`.

## Cuando usar este runbook

Usalo si se cumple al menos una de estas condiciones:

- `python manage.py audit_identity_cutover` reporta `legacy_runbook_required`
- `python manage.py audit_identity_cutover` reporta `manual_review`
- la base tiene datos reales que deben conservarse
- la base vieja dispara errores como `InconsistentMigrationHistory`

## Cuando no usar este runbook

No lo uses si el entorno es reiniciable y puedes rebuildar sin costo real. En ese caso la ruta recomendada sigue siendo base fresca.

## Paso 0. Auditar la base antes de tocarla

Ejecuta primero:

```bash
python manage.py audit_identity_cutover
```

Lectura rapida del resultado:

- `fresh_ready`: la base actual puede seguir usandose
- `empty_bootstrap`: conviene bootstrap limpio
- `legacy_runbook_required`: no sigas sin migracion controlada
- `manual_review`: no hay FKs activas a `auth_user`, pero siguen quedando residuos historicos

Si quieres bloquear pipelines o despliegues cuando el estado sea riesgoso:

```bash
python manage.py audit_identity_cutover --strict
```

## Paso 1. Congelar escrituras

Antes de migrar:

1. detener workers y procesos batch
2. cerrar accesos de escritura desde la app
3. pausar tareas operativas que creen usuarios, membresias o sesiones
4. anunciar ventana de mantenimiento

## Paso 2. Respaldar y ensayar

Antes de cambiar tablas reales:

1. tomar backup completo de la base
2. restaurar ese backup en una base de ensayo
3. correr el runbook completo primero en ensayo
4. validar login, admin, memberships y switching antes de tocar produccion

## Paso 3. Inventariar referencias actuales a `auth_user`

El comando `audit_identity_cutover` ya te dira si existen FKs activas hacia `auth_user`.

Si necesitas detalle adicional en PostgreSQL, usa una consulta de inventario como esta:

```sql
SELECT
    conrelid::regclass AS source_table,
    conname AS constraint_name,
    pg_get_constraintdef(c.oid) AS definition
FROM pg_constraint c
JOIN pg_class target ON target.oid = c.confrelid
WHERE c.contype = 'f'
  AND target.relname = 'auth_user'
ORDER BY 1, 2;
```

Checkpoint:

- lista cerrada de tablas que apuntan a `auth_user`
- decision explicita sobre conservar IDs o remapearlos
- ambiente de ensayo con resultados consistentes

## Paso 4. Definir estrategia de IDs

Hay dos rutas validas:

- `preservar IDs`: copiar filas de `auth_user` hacia `identity_user` conservando PK. Esta es la ruta mas simple si puedes hacerlo sin colisiones.
- `remapear IDs`: crear tabla temporal de mapeo `old_user_id -> new_user_id` y actualizar todas las FKs detectadas.

Recomendacion:

- si la base es tuya y controlada, intenta preservar IDs
- si existen colisiones o historia irregular, usa mapeo explicito

## Paso 5. Copiar usuarios a `identity_user`

Durante la copia:

1. mover `username`, `email`, nombres, flags de staff y superuser
2. conservar hashes de password existentes
3. poblar campos nuevos de `identity.User` con defaults seguros
4. registrar cualquier fila conflictiva en un reporte de migracion

Checkpoint:

- cantidad de usuarios en `auth_user` y `identity_user` alineada
- usuarios administrativos validos
- hashes de password preservados

## Paso 6. Recrear referencias y constraints

Despues de copiar usuarios:

1. actualizar FKs para apuntar a `identity_user`
2. recrear constraints que antes apuntaban a `auth_user`
3. validar integridad referencial completa
4. volver a correr `python manage.py audit_identity_cutover`

La auditoria debe dejar de reportar referencias activas a `auth_user`.

## Paso 7. Validacion funcional

Validaciones minimas:

1. login con usuario normal
2. login con superadmin
3. acceso a lista de tenants
4. switching de tenant
5. admin de accesos por tenant
6. auditoria de `GlobalSession`
7. `python manage.py check`
8. `python manage.py platform_preflight --strict`

Si el repo y el entorno lo permiten, suma tambien:

```bash
python manage.py test core.tests tenants.tests binncrm.tests governance.tests consolidation.tests collab.tests identity.tests
```

## Paso 8. Cerrar cutover

Solo despues de validar todo:

1. reabrir trafico
2. reactivar workers
3. monitorear login, errores 500 y sesiones
4. dejar evidencia del resultado final del comando `audit_identity_cutover`

## Criterio de salida

El runbook se considera exitoso cuando:

- `audit_identity_cutover` ya no reporta `legacy_runbook_required`
- no quedan FKs activas hacia `auth_user`
- login y switching funcionan
- auditoria de sesiones sigue registrando eventos
- la base queda lista para seguir desarrollo sin depender de la identidad antigua

## Notas para Binn

- Este runbook existe porque la documentacion del repo ya advertia deuda historica alrededor de `AUTH_USER_MODEL`.
- Para desarrollo nuevo, Binn sigue prefiriendo base fresca antes que migracion sobre una base vieja.
- Este documento no reemplaza ensayo previo; lo hace obligatorio.
