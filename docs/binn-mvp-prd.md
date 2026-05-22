# Binn MVP 1.0

Fecha de referencia: 2026-04-25

## 1. Resumen ejecutivo

Binn no debe salir al mercado como "otro CRM general". Debe salir como un CRM operativo y configurable para pymes ecuatorianas, con foco en:

- simplicidad real para equipos con baja alfabetizacion digital,
- uso movil,
- flujo comercial visible,
- WhatsApp como accion natural,
- modulos que aparecen o desaparecen segun el tipo de negocio.

La mejor tesis de producto para Binn es:

> Un solo motor CRM multi-tenant, varias experiencias verticales.

Eso significa que el mismo codigo base debe poder verse como:

- un centro de recaudacion para condominios,
- un CRM de ventas, renovaciones y documentos para brokers de seguros,
- un CRM de clienteling y recompra para marcas de ropa,
- un CRM comercial y de propuestas para consultorias y servicios corporativos.

## 2. Diagnostico del producto actual

La base tecnica ya existe y es buena:

- multi-tenant por schemas con `django-tenants`,
- configuracion por tenant en `TenantConfig`,
- modelos base de CRM:
  - `Entity`
  - `Pipeline`
  - `Deal`
  - `Activity`
  - `Document`
- dashboard y labels dinamicos por perfil,
- experiencia visual mas clara para uso diario.

Lo que Binn ya resuelve:

- aislamiento por tenant,
- nomenclatura configurable,
- pipeline visual,
- ficha de cliente flexible,
- documentos,
- onboarding inicial por perfil.

Lo que todavia falta para que sea un MVP comercial vendible:

- permisos finos por modulo y accion,
- tareas y recordatorios como objeto de primer nivel,
- timeline 360 del cliente,
- captura real de leads,
- importacion CSV,
- propuestas/cotizaciones,
- cobranza ligera,
- comunicacion masiva y trazable,
- reportes realmente utiles por vertical,
- configuracion mas profunda desde admin.

Conclusion honesta:

- hoy Binn es un buen nucleo CRM multi-tenant,
- todavia no es un producto listo para competir de frente.

## 3. Competencia y lectura del mercado

### 3.1 CRMs horizontales

| Competidor | Lo que hace muy bien | Riesgo para Binn | Lo que aprendemos |
| --- | --- | --- | --- |
| HubSpot Sales | pipeline, automatizacion, cotizaciones, forecasting, ecosistema | muy fuerte en servicios B2B | el estandar de "CRM completo" ya incluye pipeline, actividades, docs y cobros/cotizaciones |
| Zoho Bigin | simplicidad, precio, foco en small business | compite directo por facilidad y costo | la simplicidad comercial es una ventaja real, no un detalle |
| Pipedrive | UX comercial, pipeline claro, seguimiento | benchmark de usabilidad en ventas | el pipeline debe sentirse rapido y obvio |
| Kommo | WhatsApp, bandeja unificada, mensajeria, embudos | amenaza fuerte en LatAm | WhatsApp no puede ser un boton suelto; debe sentirse parte del flujo |
| Bitrix24 | amplitud, precio por organizacion, CRM + tareas + pagos | gana por "todo en uno" | muchas pymes valoran amplitud aunque la UX sea pesada |
| Odoo | CRM + ventas + ERP + POS + facturacion | gana cuando el cliente quiere suite completa | no debemos prometer ERP en el MVP |

### 3.2 Competencia por vertical

| Vertical | Referentes | Lo que priorizan |
| --- | --- | --- |
| Condominios | VivoAdmin, ComunidadFeliz | pagos, estados de cuenta, comunicacion, portal de residentes |
| Seguros | Novux, Applied Epic | leads, renovaciones, polizas, cobranza, siniestros, documentos |
| Moda retail | Shopify POS y stacks retail | clientes, recompra, historial, campanas, POS, omnicanal |
| Consultorias / IA | HubSpot, Pipedrive, Odoo | cuentas, oportunidades, reuniones, propuestas, renovaciones |

### 3.3 Implicaciones para Binn

- En condominios, un "CRM de leads" no vende. Vende cobranza, seguimiento y comunicacion.
- En seguros, leads importan, pero renovaciones, documentos y cobranza importan mas.
- En moda retail, no conviene construir POS e inventario propio en el MVP; conviene atacar clienteling, recompra y WhatsApp.
- En consultoria/IA, la venta vive en pipeline, reuniones, propuestas y renovaciones.

### 3.4 Fuentes oficiales revisadas

- HubSpot Sales: <https://www.hubspot.com/products/sales>
- Zoho Bigin pricing: <https://www.bigin.com/pricing.html>
- Pipedrive pricing: <https://www.pipedrive.com/es/pricing>
- Kommo home: <https://www.kommo.com/>
- Kommo WhatsApp CRM: <https://www.kommo.com/es/whatsapp/>
- Bitrix24 pricing: <https://www.bitrix24.com/prices/>
- Odoo pricing: <https://www.odoo.com/pricing>
- Odoo CRM: <https://www.odoo.com/app/crm>
- VivoAdmin: <https://vivoadmin.com/>
- ComunidadFeliz: <https://www.comunidadfeliz.cl/funciones-admin-b>
- Novux: <https://novux.io/>
- Shopify POS: <https://www.shopify.com/pos>

## 4. Posicionamiento recomendado

### Lo que Binn si debe ser

- CRM vertical configurable para pymes de Ecuador y LatAm.
- Producto mobile-first con lenguaje simple.
- Centro de operacion comercial + seguimiento + documentos + cobranza ligera.
- Sistema camaleonico: cada tenant ve solo lo que le sirve.

### Lo que Binn no debe intentar ser en el MVP

- ERP completo,
- software contable,
- POS completo,
- software total de administracion de condominios,
- suite enterprise tipo HubSpot,
- call center omnicanal complejo.

## 5. Principios de UX para el usuario final

Binn debe optimizarse para usuarios que no usan CRM todo el dia.

Principios:

1. Una accion principal por pantalla.
2. Terminologia del negocio, no del software.
3. Cards y listas antes que tablas complejas.
4. Vacio guiado: siempre explicar que hacer despues.
5. WhatsApp visible en las fichas importantes.
6. Formularios cortos por defecto; extras bajo demanda.
7. Mobile-first real.
8. Nada importante escondido en menus confusos.
9. Colores y jerarquia visual para priorizar tareas pendientes.
10. El dashboard debe responder: que tengo que hacer hoy.

## 6. Arquitectura de producto recomendada

### 6.1 Motor comun

Todos los tenants comparten el mismo core:

- autenticacion,
- membresias,
- contactos,
- oportunidades/casos,
- actividades,
- documentos,
- dashboards,
- auditoria,
- configuracion por tenant.

### 6.2 Admin maestro

Desde el panel de administracion debes poder decidir que ve cada tenant.

Controles minimos:

- modulos visibles,
- labels visibles,
- campos por ficha,
- pipelines,
- tipos documentales,
- widgets del dashboard,
- quick actions,
- permisos por rol,
- automatizaciones simples,
- colores/logo/branding liviano.

### 6.3 Evolucion recomendada de `TenantConfig`

La estructura actual va bien, pero debe crecer.

Estado actual:

- `profile`
- `feature_flags`
- `labels`
- `entity_fields`
- `pipeline_templates`

Campos recomendados para la siguiente etapa:

- `role_policies`
- `dashboard_widgets`
- `document_blueprints`
- `task_presets`
- `automation_rules`
- `collection_settings`
- `communication_settings`
- `quote_settings`
- `module_order`
- `homepage_layout`

Ejemplo conceptual:

```json
{
  "profile": "broker",
  "feature_flags": {
    "leads": true,
    "renewals": true,
    "claims": true,
    "collections": true,
    "documents": true,
    "campaigns": false
  },
  "role_policies": {
    "owner": ["*"],
    "manager": ["entities.view", "entities.edit", "deals.*", "documents.*"],
    "operator": ["entities.view", "activities.*", "documents.view"],
    "viewer": ["dashboard.view", "entities.view"]
  },
  "dashboard_widgets": ["pending_tasks", "renewals_due", "collections_at_risk"],
  "module_order": ["dashboard", "entities", "deals", "documents", "collections"]
}
```

## 7. Verticales objetivo

## 7.1 Broker de seguros

### Trabajo que el cliente necesita resolver

- captar y calificar leads,
- convertir leads en asegurados,
- gestionar renovaciones,
- controlar documentos,
- hacer seguimiento de cobranza,
- registrar siniestros o al menos su seguimiento.

### Modulos MVP visibles

- leads / asegurados,
- renovaciones,
- actividades,
- documentos,
- cobranza,
- tablero de pendientes.

### Modulos que pueden esperar

- bot de WhatsApp avanzado,
- cotizador conectado a aseguradoras,
- siniestros complejos,
- firmas avanzadas.

## 7.2 Administracion de condominios

### Trabajo que el cliente necesita resolver

- base de residentes,
- cartera y pagos,
- estados de cuenta,
- comunicacion,
- seguimiento a incidencias o requerimientos.

### Modulos MVP visibles

- residentes,
- unidades,
- recaudacion/cobranza,
- comunicados,
- incidencias,
- documentos clave.

### Lo que debe ocultarse

- scoring de leads,
- pipeline comercial clasico,
- terminologia de ventas.

## 7.3 Marcas de ropa

### Trabajo que el cliente necesita resolver

- conocer clientes frecuentes,
- dar seguimiento por WhatsApp,
- activar recompra,
- guardar preferencias y tallas,
- coordinar ventas especiales y pedidos apartados.

### Modulos MVP visibles

- clientes,
- oportunidades/pedidos especiales,
- campanas ligeras,
- historial de contacto,
- listas VIP,
- acciones rapidas por WhatsApp.

### Lo que no debemos construir de entrada

- POS propio,
- inventario completo,
- ecommerce propio.

## 7.4 Consultorias y servicios corporativos / IA

### Trabajo que el cliente necesita resolver

- gestionar cuentas y contactos,
- mover oportunidades en pipeline,
- registrar reuniones,
- enviar propuestas,
- cerrar contratos,
- hacer seguimiento postventa y renovaciones.

### Modulos MVP visibles

- cuentas/contactos,
- pipeline comercial,
- actividades y tareas,
- propuestas,
- documentos,
- renovaciones.

## 8. Alcance del MVP

### 8.1 Core comun obligatorio

1. Dashboard claro y accionable.
2. Ficha 360 de cliente con timeline.
3. Pipeline con kanban y etapas configurables.
4. Actividades y tareas con vencimiento.
5. Documentos por ficha y por oportunidad.
6. Busqueda global.
7. Importacion CSV.
8. Quick actions de WhatsApp.
9. Roles y permisos basicos.
10. Configuracion por tenant desde admin.

### 8.2 Extras verticales de MVP

Broker:

- renovaciones,
- cobranza ligera,
- checklist documental,
- vista de vencimientos.

Condominios:

- unidades,
- estado de cuenta basico,
- comunicados,
- cartera vencida.

Moda:

- preferencias/tallas,
- ultimos contactos,
- clientes inactivos,
- campana o motivo de recompra.

Consultoria:

- propuestas,
- reuniones,
- monto esperado,
- fecha estimada de cierre,
- handoff a entrega.

## 9. Lo que NO entra en MVP 1.0

- facturacion electronica completa,
- contabilidad,
- conciliacion bancaria avanzada,
- app movil nativa,
- inbox omnicanal completo,
- IA compleja,
- integraciones profundas con terceros,
- motor de reporteria enterprise,
- portal completo de residentes,
- ERP retail.

## 10. Orden de construccion recomendado

### Fase 1. Admin configurable

Objetivo: controlar que ve cada empresa sin tocar codigo.

Entregables:

- visibilidad de modulos por tenant,
- orden de modulos,
- widgets de dashboard configurables,
- permisos por rol,
- blueprints documentales,
- perfiles nuevos:
  - `retail_moda`
  - `servicios`

Nota:

El perfil actual `marketing` puede sobrevivir temporalmente como perfil comercial general, pero no deberia ser el nombre final para tus primeros clientes.

### Fase 2. Core CRM vendible

Objetivo: que cualquier pyme pueda operar su dia a dia comercial.

Entregables:

- timeline 360,
- tareas con vencimiento,
- importacion CSV,
- busqueda global,
- notas y actividades mas rapidas,
- dashboard con pendientes reales,
- estados vacios guiados,
- filtros guardados.

### Fase 3. Vertical broker

Objetivo: cerrar el primer vertical mas natural para Binn.

Entregables:

- lead -> asegurado -> renovacion,
- vencimientos,
- checklist documental por tipo de poliza,
- cobranza ligera,
- seguimiento de siniestros lite.

### Fase 4. Vertical servicios / consultoria

Objetivo: vender a consultorias, agencias y servicios corporativos.

Entregables:

- oportunidades B2B,
- propuestas,
- reuniones,
- handoff comercial -> servicio,
- renovaciones y upsell.

### Fase 5. Vertical condominio

Objetivo: entrar por administradores que hoy viven en Excel + WhatsApp.

Entregables:

- residentes y unidades,
- cartera,
- seguimiento de cobro,
- comunicados,
- incidencias simples,
- adjuntos.

### Fase 6. Vertical moda

Objetivo: resolver relacion con clientes y recompra.

Entregables:

- ficha de cliente retail,
- preferencias,
- WhatsApp follow-up,
- listas por segmento,
- recompra e inactividad.

## 11. Backlog priorizado

### P0 - obligatorios antes de vender

- permisos basicos por rol y modulo,
- timeline 360 en la ficha,
- tareas con fecha y responsable,
- importacion CSV,
- dashboard con pendientes,
- busqueda global,
- configuracion de modulos visibles,
- auditoria minima.

### P1 - hacen que el producto se sienta serio

- propuestas/cotizaciones,
- cobranza ligera,
- widgets por vertical,
- mas filtros,
- plantillas de documentos,
- reportes simples por tenant,
- datos iniciales de demo por perfil.

### P2 - crecimiento comercial

- formularios web para captacion,
- difusiones por WhatsApp o email,
- integraciones ligeras,
- health checks operativos,
- onboarding guiado.

### P3 - diferenciacion futura

- automatizaciones por reglas,
- bandeja unificada,
- S3 completo con previews,
- IA utilitaria,
- reportes avanzados.

## 12. Metricas de exito del MVP

Metricas transversales:

- tiempo a primer valor: crear primer contacto + primer seguimiento + primer pipeline en menos de 20 minutos,
- porcentaje de usuarios activos por semana,
- numero de actividades registradas por usuario,
- porcentaje de fichas con telefono valido,
- tiempo promedio para registrar un seguimiento.

Metricas por vertical:

Broker:

- renovaciones vencidas sin seguimiento,
- porcentaje de documentos completos,
- cobranza pendiente por vencer.

Condominio:

- cartera recuperada,
- residentes contactados,
- comunicados enviados,
- incidencias cerradas.

Moda:

- clientes reactivados,
- recompra en 30/60/90 dias,
- listas de clientes accionadas.

Consultoria:

- tasa de avance entre etapas,
- propuestas enviadas,
- tiempo desde primer contacto hasta propuesta.

## 13. Recomendacion comercial

El mejor orden para salir al mercado es:

1. Broker de seguros.
2. Consultorias y servicios corporativos / IA.
3. Administracion de condominios.
4. Marcas de ropa.

Razon:

- broker y servicios dependen mas del CRM central,
- condominios empuja mas rapido hacia software operativo especializado,
- moda reta por integraciones retail si se intenta abarcar demasiado.

## 14. Propuesta concreta para Binn 1.0

### Producto base

`Binn Core`

- contactos,
- pipeline,
- actividades,
- tareas,
- documentos,
- dashboard,
- WhatsApp,
- roles,
- configuracion.

### Paquetes verticales

`Binn Broker`

- leads,
- renovaciones,
- polizas,
- cobranza,
- documentos.

`Binn Servicios`

- cuentas,
- oportunidades,
- reuniones,
- propuestas,
- renovaciones.

`Binn Condominios`

- residentes,
- unidades,
- cartera,
- comunicados,
- incidencias.

`Binn Moda`

- clientes,
- preferencias,
- follow-up,
- listas,
- recompra.

## 15. Siguiente paso recomendado dentro del codigo

Si el objetivo es convertir Binn en un MVP real, el siguiente bloque de trabajo deberia ser:

1. Extender `TenantConfig` para controlar modulos, widgets y permisos.
2. Crear roles efectivos por tenant.
3. Implementar timeline + tareas.
4. Agregar importacion CSV.
5. Separar `marketing` en perfiles `servicios` y `retail_moda`.
6. Construir primero el pack `broker`.

Con eso Binn deja de ser solo un framework CRM bonito y empieza a verse como producto.
