# Fase 3: session scopes y switching formal

## Objetivo

Reemplazar el modelo implicito de acceso por un contexto activo persistido y auditable.

## Lo que queda cubierto en este corte

- modelos base de `governance`
- `ActiveAccessContext` persistido por sesion
- carga del contexto activo en middleware
- resolver de acceso con soporte para:
  - acceso directo por membresia local
  - acceso consolidado por grupo
  - bloqueo por politica corporativa
- switching formal de tenant usando contexto activo

## Alcance real

Este corte no cierra toda la UI de holdings ni la consolidacion corporativa.

Si deja listo:

- el contrato de session scope,
- el lugar donde vive el contexto activo,
- y el camino para que el kill switch de gobernanza impacte el acceso.

## Scope modes

- `strict_isolation`: acceso normal al tenant activo
- `consolidated`: acceso derivado por grupo corporativo
- `impersonated`: reservado para la siguiente iteracion

## Regla importante

El acceso consolidado no se concede solo por cambiar el scope. Tambien depende de:

1. membresia activa del usuario en el grupo,
2. vinculo activo entre grupo y tenant,
3. politica efectiva de consolidacion,
4. permiso solicitado.
