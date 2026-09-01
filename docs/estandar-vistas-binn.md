# Estandar de vistas Binn

Las vistas de Binn son herramientas de trabajo, no tableros decorativos. Cada pantalla debe responder primero que requiere accion y despues ofrecer el lugar para ejecutarla.

## Anatomia obligatoria

1. **Barra operativa:** contexto, busqueda, cortes, filtros secundarios y accion principal en una fila compacta.
2. **Superficie de trabajo:** kanban, tabla, formulario o conversacion. Debe dominar la pantalla desde el primer pantallazo.
3. **Foco:** una alerta o estado solo cuando cambia la prioridad del usuario. No repetirlo en otra tarjeta.
4. **Senales de apoyo:** metricas o accesos secundarios, solo cuando ayudan a decidir sobre la superficie principal.

## Reglas de densidad

- Maximo tres acciones visibles en el encabezado. El resto pertenece al modulo o a la busqueda global.
- Un numero solo aparece una vez como KPI principal. Si reaparece, debe aportar un desglose accionable.
- No usar tarjetas para texto que puede ser una etiqueta, una frase o un estado en la propia superficie.
- Las vistas operativas priorizan el trabajo sobre los reportes; los reportes viven en `Reportes`.
- En pantalla reducida, las columnas se apilan sin ocultar la accion principal ni crear desplazamiento horizontal.
- Las vistas de lista no llevan una cabecera editorial grande. Usan la barra operativa y reservan el alto para los registros.
- El orden fijo de la barra es: contexto, busqueda, cortes, filtros, accion secundaria y accion primaria.

## Primitivas compartidas

Usar `binn-view-standard` como contenedor, `binn-workspace-bar` para vistas operativas, `binn-workspace-bar-controls` para contexto y busqueda, `binn-workspace-bar-cuts` para cortes y `binn-workspace-bar-actions` para acciones. `binn-module-header` queda reservado para inicio, formularios y vistas de detalle. Las clases viven en `templates/base.html` para mantener la misma jerarquia visual entre modulos.
