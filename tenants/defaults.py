from __future__ import annotations

from copy import deepcopy


PROFILE_GENERAL = "general"
PROFILE_CONDOMINIO = "condominio"
PROFILE_BROKER = "broker"
PROFILE_MARKETING = "marketing"
PROFILE_SERVICIOS = "servicios"
PROFILE_RETAIL_MODA = "retail_moda"

PROFILE_CHOICES = [
    (PROFILE_GENERAL, "General"),
    (PROFILE_CONDOMINIO, "Operacion de condominios"),
    (PROFILE_BROKER, "Broker de seguros"),
    (PROFILE_SERVICIOS, "Servicios B2B"),
    (PROFILE_RETAIL_MODA, "Retail y clienteling"),
    (PROFILE_MARKETING, "Agencia comercial"),
]

DEFAULT_MODULE_ORDER = [
    "entities",
    "objects",
    "deals",
    "proposals",
    "collections",
    "activities",
    "collab",
    "documents",
    "reports",
    "assessments",
]

MODULE_ORDER_LABELS = {
    "entities": "Entidades",
    "objects": "Objetos",
    "deals": "Deals",
    "proposals": "Propuestas",
    "collections": "Cobranzas",
    "activities": "Actividades",
    "collab": "Colaboracion",
    "documents": "Documentos",
    "reports": "Reportes",
    "assessments": "Levantamientos",
}

DEFAULT_DASHBOARD_WIDGETS = [
    "highlights",
    "guided_steps",
    "quick_actions",
    "summary_cards",
    "pipeline_panel",
    "entity_panel",
    "activity_panel",
]

DASHBOARD_WIDGET_LABELS = {
    "highlights": "Pildoras de enfoque",
    "guided_steps": "Guia para empezar",
    "quick_actions": "Acciones rapidas",
    "summary_cards": "Tarjetas de resumen",
    "pipeline_panel": "Panel de pipeline",
    "entity_panel": "Panel de entidades",
    "activity_panel": "Panel de actividades",
}

VALID_ROLE_KEYS = ("owner", "manager", "operator", "analyst", "viewer")

ROLE_PERMISSION_LABELS = {
    "dashboard.view": "Ver dashboard",
    "entities.view": "Ver entidades",
    "entities.edit": "Crear y editar entidades",
    "objects.view": "Ver objetos custom",
    "objects.edit": "Crear y editar objetos custom",
    "deals.view": "Ver deals",
    "deals.edit": "Crear y editar deals",
    "deals.move": "Mover deals en kanban",
    "proposals.view": "Seguir propuestas",
    "proposals.edit": "Crear y editar propuestas",
    "collections.view": "Cobrar cartera",
    "collections.edit": "Crear y editar cobranzas",
    "activities.view": "Ver actividades",
    "activities.edit": "Crear y editar actividades",
    "activities.complete": "Completar tareas",
    "collab.view": "Ver conversacion interna",
    "collab.edit": "Escribir mensajes internos",
    "documents.view": "Operar documentos",
    "documents.edit": "Crear y editar documentos",
    "reports.view": "Ver reportes",
}

DEFAULT_ROLE_POLICIES = {
    "owner": ["*"],
    "manager": ["*"],
    "operator": [
        "dashboard.view",
        "entities.view",
        "entities.edit",
        "objects.view",
        "objects.edit",
        "deals.view",
        "deals.edit",
        "deals.move",
        "proposals.view",
        "proposals.edit",
        "collections.view",
        "collections.edit",
        "activities.view",
        "activities.edit",
        "activities.complete",
        "collab.view",
        "collab.edit",
        "documents.view",
        "documents.edit",
        "reports.view",
    ],
    "analyst": [
        "dashboard.view",
        "entities.view",
        "objects.view",
        "deals.view",
        "proposals.view",
        "collections.view",
        "activities.view",
        "collab.view",
        "documents.view",
        "reports.view",
    ],
    "viewer": [
        "dashboard.view",
        "entities.view",
        "objects.view",
        "deals.view",
        "proposals.view",
        "collections.view",
        "activities.view",
        "collab.view",
        "documents.view",
        "reports.view",
    ],
}

DEFAULT_FEATURE_FLAGS = {
    "entities": True,
    "objects": True,
    "deals": True,
    "activities": True,
    "collab": True,
    "documents": True,
    "proposals": True,
    "collections": False,
    "reports": True,
    "assessments": True,
    "fiscal_lookup": False,
    "kanban": True,
}

DEFAULT_LABELS = {
    "brand_name": "Binn",
    "dashboard_title": "Radar Binn",
    "dashboard_subtitle": "Operacion comercial sin ruido",
    "entity_singular": "Contacto",
    "entity_plural": "Contactos",
    "deal_singular": "Oportunidad",
    "deal_plural": "Oportunidades",
    "activity_singular": "Actividad",
    "activity_plural": "Actividades",
    "document_singular": "Documento",
    "document_plural": "Documentos",
    "proposal_singular": "Propuesta",
    "proposal_plural": "Propuestas",
    "collection_singular": "Cobranza",
    "collection_plural": "Cobranzas",
    "pipeline_label": "Pipeline",
    "search_placeholder": "Busca por nombre, identificacion o dato clave",
}

CAPABILITY_LABELS = {
    "entities": "Entidades",
    "objects": "Objetos",
    "deals": "Deals",
    "proposals": "Propuestas",
    "collections": "Cobranzas",
    "activities": "Actividades",
    "collab": "Colaboracion",
    "documents": "Documentos",
    "reports": "Reportes",
    "assessments": "Levantamientos",
    "fiscal_lookup": "Lookup fiscal",
    "kanban": "Kanban",
}

PROFILE_ONBOARDING = {
    PROFILE_GENERAL: {
        "headline": "CRM base listo para operar",
        "summary": "Activa el flujo comercial esencial sin cargar frentes que no hacen falta de entrada.",
        "next_steps": [
            "Importar tus primeros contactos y referencias comerciales.",
            "Ajustar labels si tu negocio usa otra nomenclatura.",
            "Validar el pipeline inicial antes de invitar al equipo.",
        ],
    },
    PROFILE_CONDOMINIO: {
        "headline": "Centro de recaudo listo para administracion residencial",
        "summary": "Prioriza residentes, cartera y seguimiento operativo sin mostrar un CRM comercial tradicional.",
        "next_steps": [
            "Cargar residentes y completar torre, departamento y alicuota.",
            "Ajustar el flujo de recaudacion segun tu proceso de cobro.",
            "Asignar al menos un operador para seguimiento diario.",
        ],
    },
    PROFILE_BROKER: {
        "headline": "Base documental preparada para renovaciones",
        "summary": "Deja visible el flujo de renovacion y documentacion pesada desde el primer dia.",
        "next_steps": [
            "Registrar asegurados con placa, aseguradora y numero de poliza.",
            "Confirmar buckets y convenciones de storage antes de subir archivos.",
            "Definir responsables para emision, inspeccion y cobranza.",
        ],
    },
    PROFILE_MARKETING: {
        "headline": "Pipeline visual listo para captacion de leads",
        "summary": "Enfoca al equipo en oportunidades, propuestas y campanas sin ruido operativo extra.",
        "next_steps": [
            "Cargar leads iniciales y etiquetar la fuente de campana.",
            "Ajustar el pipeline comercial con tus etapas reales.",
            "Definir un criterio comun para calificar oportunidades.",
        ],
    },
    PROFILE_SERVICIOS: {
        "headline": "Operacion comercial lista para servicios B2B",
        "summary": "Prioriza oportunidades, propuestas, reuniones y seguimiento postventa con lenguaje B2B sencillo.",
        "next_steps": [
            "Cargar clientes y prospectos con su empresa y servicio principal.",
            "Ajustar el pipeline de propuestas y cierres antes de invitar al equipo.",
            "Definir responsables para discovery, propuesta y cobranza.",
        ],
    },
    PROFILE_RETAIL_MODA: {
        "headline": "Clienteling listo para marcas de ropa y retail",
        "summary": "Clientes, recompra y listas VIP.",
        "next_steps": [
            "Cargar clientes frecuentes con talla, estilo y canal favorito.",
            "Definir un flujo simple para apartados, pedidos especiales y recompra.",
            "Separar listas activas, VIP e inactivas para reactivacion.",
        ],
    },
}

PROFILE_DEFAULTS = {
    PROFILE_GENERAL: {
        "feature_flags": {
            **DEFAULT_FEATURE_FLAGS,
            "documents": False,
            "collections": False,
        },
        "labels": {
            **DEFAULT_LABELS,
        },
        "entity_fields": [
            {"key": "city", "label": "Ciudad", "type": "text"},
            {"key": "reference", "label": "Referencia", "type": "text"},
        ],
        "custom_objects": [],
        "module_order": list(DEFAULT_MODULE_ORDER),
        "dashboard_widgets": list(DEFAULT_DASHBOARD_WIDGETS),
        "role_policies": deepcopy(DEFAULT_ROLE_POLICIES),
        "document_blueprints": [],
        "pipeline_templates": [
            {
                "key": "ventas",
                "label": "Ventas",
                "stages": ["Nuevo", "Contactado", "Propuesta", "Ganado"],
            }
        ],
    },
    PROFILE_CONDOMINIO: {
        "feature_flags": {
            **DEFAULT_FEATURE_FLAGS,
            "documents": True,
            "proposals": False,
            "collections": True,
        },
        "labels": {
            **DEFAULT_LABELS,
            "dashboard_title": "Centro de recaudo",
            "dashboard_subtitle": "Cartera y residentes",
            "entity_singular": "Residente",
            "entity_plural": "Residentes",
            "deal_singular": "Cobro",
            "deal_plural": "Recaudaciones",
            "collection_singular": "Cuenta por cobrar",
            "collection_plural": "Cartera",
            "pipeline_label": "Estado de recaudacion",
        },
        "entity_fields": [
            {
                "key": "resident_status",
                "label": "Estado del residente",
                "type": "select",
                "choices": [
                    {"value": "al_dia", "label": "Al dia"},
                    {"value": "seguimiento", "label": "En seguimiento"},
                    {"value": "promesa_pago", "label": "Promesa de pago"},
                    {"value": "cartera_vencida", "label": "Cartera vencida"},
                ],
            },
            {"key": "departamento", "label": "Departamento", "type": "text"},
            {"key": "torre", "label": "Torre o bloque", "type": "text"},
            {"key": "alicuota", "label": "Alicuota", "type": "number"},
        ],
        "custom_objects": [
            {
                "key": "unidad",
                "label": "Unidades",
                "description": "Inventario flexible de departamentos, parqueos o bodegas sin tocar el esquema.",
                "settings": {"primary_field": "codigo_unidad", "subtitle_field": "residente_actual"},
                "fields": [
                    {"key": "codigo_unidad", "label": "Codigo de unidad", "type": "text", "required": True},
                    {"key": "torre", "label": "Torre", "type": "text"},
                    {"key": "propietario", "label": "Propietario", "type": "text"},
                    {"key": "residente_actual", "label": "Residente actual", "type": "text"},
                    {
                        "key": "estado_ocupacion",
                        "label": "Estado de ocupacion",
                        "type": "select",
                        "choices": [
                            {"value": "ocupada", "label": "Ocupada"},
                            {"value": "vacia", "label": "Vacia"},
                            {"value": "arriendo", "label": "Arriendo"},
                        ],
                    },
                    {"key": "metros_cuadrados", "label": "Metros cuadrados", "type": "number"},
                ],
            },
            {
                "key": "incidencia",
                "label": "Incidencias",
                "description": "Requerimientos, novedades o casos operativos del condominio ligados a residente o unidad.",
                "settings": {"primary_field": "asunto", "subtitle_field": "codigo_unidad"},
                "fields": [
                    {"key": "asunto", "label": "Asunto", "type": "text", "required": True},
                    {"key": "codigo_unidad", "label": "Codigo de unidad", "type": "text"},
                    {"key": "residente", "label": "Residente", "type": "text"},
                    {
                        "key": "tipo",
                        "label": "Tipo",
                        "type": "select",
                        "choices": [
                            {"value": "mantenimiento", "label": "Mantenimiento"},
                            {"value": "convivencia", "label": "Convivencia"},
                            {"value": "seguridad", "label": "Seguridad"},
                            {"value": "cartera", "label": "Cartera"},
                            {"value": "otro", "label": "Otro"},
                        ],
                    },
                    {
                        "key": "prioridad",
                        "label": "Prioridad",
                        "type": "select",
                        "choices": [
                            {"value": "alta", "label": "Alta"},
                            {"value": "media", "label": "Media"},
                            {"value": "baja", "label": "Baja"},
                        ],
                    },
                    {
                        "key": "estado",
                        "label": "Estado",
                        "type": "select",
                        "choices": [
                            {"value": "abierta", "label": "Abierta"},
                            {"value": "en_gestion", "label": "En gestion"},
                            {"value": "resuelta", "label": "Resuelta"},
                        ],
                    },
                    {"key": "reportada_en", "label": "Reportada en", "type": "date"},
                    {"key": "comentario", "label": "Comentario", "type": "textarea"},
                ],
            },
            {
                "key": "comunicado",
                "label": "Comunicados",
                "description": "Avisos y trazabilidad de mensajes enviados a residentes, bloques o unidades.",
                "settings": {"primary_field": "asunto", "subtitle_field": "fecha_envio"},
                "fields": [
                    {"key": "asunto", "label": "Asunto", "type": "text", "required": True},
                    {"key": "codigo_unidad", "label": "Codigo de unidad", "type": "text"},
                    {"key": "dirigido_a", "label": "Dirigido a", "type": "text"},
                    {
                        "key": "canal",
                        "label": "Canal",
                        "type": "select",
                        "choices": [
                            {"value": "whatsapp", "label": "WhatsApp"},
                            {"value": "email", "label": "Email"},
                            {"value": "cartelera", "label": "Cartelera"},
                        ],
                    },
                    {
                        "key": "estado",
                        "label": "Estado",
                        "type": "select",
                        "choices": [
                            {"value": "borrador", "label": "Borrador"},
                            {"value": "enviado", "label": "Enviado"},
                            {"value": "confirmado", "label": "Confirmado"},
                        ],
                    },
                    {"key": "fecha_envio", "label": "Fecha de envio", "type": "date"},
                    {"key": "comentario", "label": "Comentario", "type": "textarea"},
                ],
            }
        ],
        "module_order": ["entities", "objects", "collections", "activities", "documents", "deals", "reports", "proposals"],
        "dashboard_widgets": list(DEFAULT_DASHBOARD_WIDGETS),
        "role_policies": deepcopy(DEFAULT_ROLE_POLICIES),
        "document_blueprints": [],
        "pipeline_templates": [
            {
                "key": "recaudacion",
                "label": "Recaudacion",
                "stages": ["Pendiente", "Notificado", "Pagado"],
            }
        ],
    },
    PROFILE_BROKER: {
        "feature_flags": {
            **DEFAULT_FEATURE_FLAGS,
            "documents": True,
            "proposals": True,
            "collections": True,
        },
        "labels": {
            **DEFAULT_LABELS,
            "dashboard_title": "Centro de renovaciones",
            "dashboard_subtitle": "Asegurados y polizas",
            "entity_singular": "Asegurado",
            "entity_plural": "Asegurados",
            "deal_singular": "Renovacion",
            "deal_plural": "Renovaciones",
            "proposal_singular": "Cotizacion",
            "proposal_plural": "Cotizaciones",
            "collection_singular": "Cobro",
            "collection_plural": "Cobros",
            "pipeline_label": "Estado de emision",
        },
        "entity_fields": [
            {
                "key": "lifecycle_stage",
                "label": "Etapa broker",
                "type": "select",
                "default": "lead",
                "choices": [
                    {"value": "lead", "label": "Lead"},
                    {"value": "asegurado", "label": "Asegurado"},
                    {"value": "renovacion", "label": "Renovacion"},
                ],
            },
            {"key": "placa", "label": "Placa", "type": "text"},
            {"key": "aseguradora", "label": "Aseguradora", "type": "text"},
            {"key": "poliza", "label": "Numero de poliza", "type": "text"},
        ],
        "custom_objects": [
            {
                "key": "poliza_detalle",
                "label": "Polizas",
                "description": "Objeto flexible para documentar productos, vigencias y anexos sin una migracion por aseguradora.",
                "settings": {"primary_field": "numero_poliza", "subtitle_field": "producto"},
                "fields": [
                    {"key": "numero_poliza", "label": "Numero de poliza", "type": "text", "required": True},
                    {"key": "producto", "label": "Producto", "type": "text"},
                    {"key": "vigencia_hasta", "label": "Vigencia hasta", "type": "date"},
                    {"key": "prima", "label": "Prima", "type": "number"},
                ],
            }
        ],
        "module_order": ["entities", "deals", "proposals", "collections", "documents", "activities"],
        "dashboard_widgets": list(DEFAULT_DASHBOARD_WIDGETS),
        "role_policies": deepcopy(DEFAULT_ROLE_POLICIES),
        "document_blueprints": [],
        "pipeline_templates": [
            {
                "key": "renovaciones",
                "label": "Renovaciones",
                "stages": ["Cotizado", "Inspeccionado", "Emitido"],
            }
        ],
    },
    PROFILE_MARKETING: {
        "feature_flags": {
            **DEFAULT_FEATURE_FLAGS,
            "documents": False,
            "proposals": True,
            "collections": False,
        },
        "labels": {
            **DEFAULT_LABELS,
            "dashboard_title": "Centro de captacion",
            "dashboard_subtitle": "Leads y pipeline",
            "entity_singular": "Lead",
            "entity_plural": "Leads",
            "deal_singular": "Oportunidad",
            "deal_plural": "Oportunidades",
            "proposal_singular": "Propuesta",
            "proposal_plural": "Propuestas",
            "pipeline_label": "Pipeline comercial",
        },
        "entity_fields": [
            {"key": "empresa", "label": "Empresa", "type": "text"},
            {"key": "instagram", "label": "Instagram", "type": "text"},
            {"key": "campana", "label": "Campana", "type": "text"},
        ],
        "custom_objects": [],
        "module_order": ["entities", "deals", "proposals", "activities", "documents", "collections"],
        "dashboard_widgets": list(DEFAULT_DASHBOARD_WIDGETS),
        "role_policies": deepcopy(DEFAULT_ROLE_POLICIES),
        "document_blueprints": [],
        "pipeline_templates": [
            {
                "key": "captacion",
                "label": "Captacion",
                "stages": ["Nuevo", "Calificado", "Propuesta", "Ganado"],
            }
        ],
    },
    PROFILE_SERVICIOS: {
        "feature_flags": {
            **DEFAULT_FEATURE_FLAGS,
            "documents": True,
            "proposals": True,
            "collections": True,
        },
        "labels": {
            **DEFAULT_LABELS,
            "dashboard_title": "Centro comercial B2B",
            "dashboard_subtitle": "Cuentas y propuestas",
            "entity_singular": "Cliente",
            "entity_plural": "Clientes",
            "deal_singular": "Oportunidad",
            "deal_plural": "Oportunidades",
            "proposal_singular": "Propuesta",
            "proposal_plural": "Propuestas",
            "collection_singular": "Cobro",
            "collection_plural": "Cobros",
            "pipeline_label": "Pipeline comercial",
        },
        "entity_fields": [
            {
                "key": "service_stage",
                "label": "Etapa servicios",
                "type": "select",
                "default": "prospecto",
                "choices": [
                    {"value": "prospecto", "label": "Prospecto"},
                    {"value": "cliente_activo", "label": "Cliente activo"},
                    {"value": "renovacion_upsell", "label": "Renovacion / upsell"},
                ],
            },
            {"key": "empresa", "label": "Empresa", "type": "text"},
            {
                "key": "service_line",
                "label": "Linea de servicio",
                "type": "select",
                "choices": [
                    {"value": "consultoria", "label": "Consultoria"},
                    {"value": "implementacion", "label": "Implementacion"},
                    {"value": "automatizacion", "label": "Automatizacion"},
                    {"value": "capacitacion", "label": "Capacitacion"},
                    {"value": "soporte", "label": "Soporte"},
                ],
            },
            {"key": "servicio_principal", "label": "Servicio principal", "type": "text"},
            {"key": "cargo", "label": "Cargo del contacto", "type": "text"},
            {"key": "retainer_mensual", "label": "Retainer mensual", "type": "number"},
            {
                "key": "account_health",
                "label": "Salud de la cuenta",
                "type": "select",
                "choices": [
                    {"value": "estable", "label": "Estable"},
                    {"value": "seguimiento", "label": "Seguimiento"},
                    {"value": "riesgo", "label": "En riesgo"},
                    {"value": "expansion", "label": "Expansion"},
                ],
            },
            {"key": "started_on", "label": "Inicio de servicio", "type": "date"},
            {"key": "renewal_on", "label": "Fecha de renovacion", "type": "date"},
            {"key": "delivery_owner", "label": "Responsable delivery", "type": "text"},
        ],
        "custom_objects": [
            {
                "key": "proyecto",
                "label": "Proyectos",
                "description": "Seguimiento reusable de cuentas activas, implementaciones y consultorias sin meter una app de PM completa.",
                "settings": {"primary_field": "nombre", "subtitle_field": "cliente"},
                "fields": [
                    {"key": "nombre", "label": "Nombre", "type": "text", "required": True},
                    {"key": "cliente", "label": "Cliente", "type": "text", "required": True},
                    {"key": "linea_servicio", "label": "Linea de servicio", "type": "text"},
                    {
                        "key": "estado",
                        "label": "Estado",
                        "type": "select",
                        "choices": [
                            {"value": "kickoff", "label": "Kickoff"},
                            {"value": "en_ejecucion", "label": "En ejecucion"},
                            {"value": "en_revision", "label": "En revision"},
                            {"value": "cerrado", "label": "Cerrado"},
                        ],
                    },
                    {"key": "responsable", "label": "Responsable", "type": "text"},
                    {"key": "fecha_inicio", "label": "Fecha inicio", "type": "date"},
                    {"key": "fecha_cierre_objetivo", "label": "Fecha cierre objetivo", "type": "date"},
                    {
                        "key": "prioridad",
                        "label": "Prioridad",
                        "type": "select",
                        "choices": [
                            {"value": "alta", "label": "Alta"},
                            {"value": "media", "label": "Media"},
                            {"value": "baja", "label": "Baja"},
                        ],
                    },
                ],
            },
            {
                "key": "entregable",
                "label": "Entregables",
                "description": "Backlog flexible de entregables, workshops y activos del servicio sin meter otra app entera.",
                "settings": {"primary_field": "nombre", "subtitle_field": "cliente"},
                "fields": [
                    {"key": "nombre", "label": "Nombre", "type": "text", "required": True},
                    {"key": "cliente", "label": "Cliente", "type": "text", "required": True},
                    {"key": "proyecto", "label": "Proyecto", "type": "text"},
                    {"key": "tipo_entregable", "label": "Tipo", "type": "text"},
                    {
                        "key": "estado",
                        "label": "Estado",
                        "type": "select",
                        "choices": [
                            {"value": "por_iniciar", "label": "Por iniciar"},
                            {"value": "en_curso", "label": "En curso"},
                            {"value": "por_validar", "label": "Por validar"},
                            {"value": "entregado", "label": "Entregado"},
                            {"value": "bloqueado", "label": "Bloqueado"},
                        ],
                    },
                    {"key": "responsable", "label": "Responsable", "type": "text"},
                    {
                        "key": "prioridad",
                        "label": "Prioridad",
                        "type": "select",
                        "choices": [
                            {"value": "alta", "label": "Alta"},
                            {"value": "media", "label": "Media"},
                            {"value": "baja", "label": "Baja"},
                        ],
                    },
                    {"key": "fecha_entrega", "label": "Fecha de entrega", "type": "date"},
                    {"key": "fecha_revision", "label": "Fecha de revision", "type": "date"},
                ],
            }
        ],
        "module_order": ["entities", "objects", "deals", "proposals", "collections", "activities", "documents", "reports"],
        "dashboard_widgets": list(DEFAULT_DASHBOARD_WIDGETS),
        "role_policies": deepcopy(DEFAULT_ROLE_POLICIES),
        "document_blueprints": [],
        "pipeline_templates": [
            {
                "key": "servicios_b2b",
                "label": "Servicios B2B",
                "stages": ["Discovery", "Propuesta", "Negociacion", "Ganado"],
            }
        ],
    },
    PROFILE_RETAIL_MODA: {
        "feature_flags": {
            **DEFAULT_FEATURE_FLAGS,
            "documents": False,
            "proposals": False,
            "collections": False,
        },
        "labels": {
            **DEFAULT_LABELS,
            "dashboard_title": "Centro de clienteling",
            "dashboard_subtitle": "Clientes y recompra",
            "entity_singular": "Cliente",
            "entity_plural": "Clientes",
            "deal_singular": "Pedido especial",
            "deal_plural": "Pedidos especiales",
            "pipeline_label": "Flujo de recompra",
        },
        "entity_fields": [
            {
                "key": "client_segment",
                "label": "Segmento cliente",
                "type": "select",
                "choices": [
                    {"value": "vip", "label": "VIP"},
                    {"value": "frecuente", "label": "Frecuente"},
                    {"value": "ocasional", "label": "Ocasional"},
                    {"value": "inactiva", "label": "Inactiva"},
                ],
            },
            {"key": "talla", "label": "Talla preferida", "type": "text"},
            {"key": "estilo", "label": "Estilo favorito", "type": "text"},
            {
                "key": "canal_preferido",
                "label": "Canal preferido",
                "type": "select",
                "choices": [
                    {"value": "whatsapp", "label": "WhatsApp"},
                    {"value": "instagram", "label": "Instagram"},
                    {"value": "tienda", "label": "Tienda"},
                    {"value": "email", "label": "Email"},
                ],
            },
            {"key": "color_favorito", "label": "Color favorito", "type": "text"},
            {"key": "instagram", "label": "Instagram", "type": "text"},
            {"key": "ultima_compra", "label": "Ultima compra", "type": "date"},
        ],
        "custom_objects": [
            {
                "key": "wishlist",
                "label": "Wishlists",
                "description": "Objeto libre para registrar intereses, apartados y piezas por cliente.",
                "settings": {"primary_field": "cliente", "subtitle_field": "pieza"},
                "fields": [
                    {"key": "cliente", "label": "Cliente", "type": "text", "required": True},
                    {"key": "pieza", "label": "Pieza", "type": "text", "required": True},
                    {"key": "categoria", "label": "Categoria", "type": "text"},
                    {"key": "talla", "label": "Talla", "type": "text"},
                    {
                        "key": "prioridad",
                        "label": "Prioridad",
                        "type": "select",
                        "choices": [
                            {"value": "alta", "label": "Alta"},
                            {"value": "media", "label": "Media"},
                            {"value": "baja", "label": "Baja"},
                        ],
                    },
                    {"key": "fecha_followup", "label": "Fecha follow-up", "type": "date"},
                    {"key": "vigente", "label": "Vigente", "type": "boolean"},
                ],
            }
        ],
        "module_order": ["entities", "objects", "deals", "activities", "reports", "documents", "proposals", "collections"],
        "dashboard_widgets": list(DEFAULT_DASHBOARD_WIDGETS),
        "role_policies": deepcopy(DEFAULT_ROLE_POLICIES),
        "document_blueprints": [],
        "pipeline_templates": [
            {
                "key": "clienteling",
                "label": "Clienteling",
                "stages": ["Interes", "Separado", "Comprado", "Recompra"],
            }
        ],
    },
}


def get_profile_defaults(profile: str) -> dict:
    return deepcopy(PROFILE_DEFAULTS.get(profile or "", PROFILE_DEFAULTS[PROFILE_GENERAL]))


def resolve_module_order(module_order=None) -> list[str]:
    cleaned: list[str] = []
    for key in module_order or []:
        normalized = str(key).strip().lower()
        if normalized in MODULE_ORDER_LABELS and normalized not in cleaned:
            cleaned.append(normalized)
    for key in DEFAULT_MODULE_ORDER:
        if key not in cleaned:
            cleaned.append(key)
    return cleaned


def resolve_dashboard_widgets(widget_keys=None) -> list[str]:
    cleaned: list[str] = []
    for key in widget_keys or []:
        normalized = str(key).strip().lower()
        if normalized in DASHBOARD_WIDGET_LABELS and normalized not in cleaned:
            cleaned.append(normalized)
    return cleaned or list(DEFAULT_DASHBOARD_WIDGETS)


def resolve_role_policies(role_policies=None) -> dict[str, list[str]]:
    cleaned: dict[str, list[str]] = {}
    raw_policies = role_policies if isinstance(role_policies, dict) else {}

    for role_key in VALID_ROLE_KEYS:
        raw_permissions = raw_policies.get(role_key, DEFAULT_ROLE_POLICIES[role_key])
        resolved_permissions: list[str] = []
        for permission_code in raw_permissions or []:
            normalized = str(permission_code).strip().lower()
            if normalized == "*":
                resolved_permissions = ["*"]
                break
            if normalized in ROLE_PERMISSION_LABELS and normalized not in resolved_permissions:
                resolved_permissions.append(normalized)
        cleaned[role_key] = resolved_permissions or list(DEFAULT_ROLE_POLICIES[role_key])
    return cleaned


def merge_with_profile_defaults(
    profile: str,
    *,
    feature_flags=None,
    labels=None,
    entity_fields=None,
    custom_objects=None,
    module_order=None,
    dashboard_widgets=None,
    role_policies=None,
    document_blueprints=None,
    pipeline_templates=None,
) -> dict:
    defaults = get_profile_defaults(profile)
    return {
        "feature_flags": {**defaults["feature_flags"], **(feature_flags or {})},
        "labels": {**defaults["labels"], **(labels or {})},
        "entity_fields": deepcopy(entity_fields) if entity_fields else defaults["entity_fields"],
        "custom_objects": deepcopy(custom_objects) if custom_objects else defaults["custom_objects"],
        "module_order": resolve_module_order(module_order if module_order is not None else defaults["module_order"]),
        "dashboard_widgets": resolve_dashboard_widgets(
            dashboard_widgets if dashboard_widgets is not None else defaults["dashboard_widgets"]
        ),
        "role_policies": resolve_role_policies(role_policies if role_policies is not None else defaults["role_policies"]),
        "document_blueprints": deepcopy(document_blueprints) if document_blueprints else defaults["document_blueprints"],
        "pipeline_templates": deepcopy(pipeline_templates) if pipeline_templates else defaults["pipeline_templates"],
    }


def build_profile_launchpad(
    profile: str,
    *,
    feature_flags=None,
    labels=None,
    entity_fields=None,
    custom_objects=None,
    module_order=None,
    dashboard_widgets=None,
    role_policies=None,
    document_blueprints=None,
    pipeline_templates=None,
) -> dict:
    merged = merge_with_profile_defaults(
        profile,
        feature_flags=feature_flags,
        labels=labels,
        entity_fields=entity_fields,
        custom_objects=custom_objects,
        module_order=module_order,
        dashboard_widgets=dashboard_widgets,
        role_policies=role_policies,
        document_blueprints=document_blueprints,
        pipeline_templates=pipeline_templates,
    )
    blueprint = PROFILE_ONBOARDING.get(profile or "", PROFILE_ONBOARDING[PROFILE_GENERAL])
    resolved_labels = merged["labels"]
    module_labels = {
        "entities": resolved_labels.get("entity_plural", CAPABILITY_LABELS["entities"]),
        "deals": resolved_labels.get("deal_plural", CAPABILITY_LABELS["deals"]),
        "proposals": resolved_labels.get("proposal_plural", CAPABILITY_LABELS["proposals"]),
        "collections": resolved_labels.get("collection_plural", CAPABILITY_LABELS["collections"]),
        "activities": resolved_labels.get("activity_plural", CAPABILITY_LABELS["activities"]),
        "documents": resolved_labels.get("document_plural", CAPABILITY_LABELS["documents"]),
        "reports": CAPABILITY_LABELS["reports"],
        "kanban": resolved_labels.get("pipeline_label", CAPABILITY_LABELS["kanban"]),
        "fiscal_lookup": CAPABILITY_LABELS["fiscal_lookup"],
    }

    enabled_capabilities = [
        {
            "key": key,
            "label": module_labels.get(key, CAPABILITY_LABELS.get(key, key.replace("_", " ").title())),
        }
        for key, is_enabled in merged["feature_flags"].items()
        if is_enabled
    ]
    hidden_capabilities = [
        {
            "key": key,
            "label": module_labels.get(key, CAPABILITY_LABELS.get(key, key.replace("_", " ").title())),
        }
        for key, is_enabled in merged["feature_flags"].items()
        if not is_enabled
    ]

    return {
        "headline": blueprint["headline"],
        "summary": blueprint["summary"],
        "next_steps": list(blueprint["next_steps"]),
        "labels": resolved_labels,
        "enabled_capabilities": enabled_capabilities,
        "hidden_capabilities": hidden_capabilities,
        "entity_fields": [deepcopy(field) for field in merged["entity_fields"]],
        "custom_objects": [deepcopy(item) for item in merged["custom_objects"]],
        "module_order": [
            {
                "key": key,
                "label": module_labels.get(key, MODULE_ORDER_LABELS.get(key, key.replace("_", " ").title())),
            }
            for key in resolve_module_order(merged["module_order"])
        ],
        "dashboard_widgets": [
            {
                "key": key,
                "label": DASHBOARD_WIDGET_LABELS.get(key, key.replace("_", " ").title()),
            }
            for key in resolve_dashboard_widgets(merged["dashboard_widgets"])
        ],
        "role_policies": [
            {
                "role": role_key,
                "permissions": [
                    ROLE_PERMISSION_LABELS.get(permission_code, permission_code)
                    for permission_code in permissions
                ],
                "is_full_access": permissions == ["*"],
            }
            for role_key, permissions in resolve_role_policies(merged["role_policies"]).items()
        ],
        "document_blueprint_count": len(merged["document_blueprints"] or []),
        "pipelines": [
            {
                "key": pipeline["key"],
                "label": pipeline["label"],
                "stages": list(pipeline["stages"]),
                "stage_count": len(pipeline["stages"]),
                "summary": " | ".join(pipeline["stages"]),
            }
            for pipeline in merged["pipeline_templates"]
        ],
    }

