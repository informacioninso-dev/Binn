from datetime import timedelta

from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.db.models import Count, Max, Q, Sum
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone

from access.permissions import (
    PERMISSION_DASHBOARD_VIEW,
    PERMISSION_ACTIVITIES_EDIT,
    PERMISSION_ACTIVITIES_VIEW,
    PERMISSION_COLLECTIONS_EDIT,
    PERMISSION_COLLECTIONS_VIEW,
    PERMISSION_DEALS_EDIT,
    PERMISSION_DEALS_VIEW,
    PERMISSION_DOCUMENTS_EDIT,
    PERMISSION_DOCUMENTS_VIEW,
    PERMISSION_ENTITIES_EDIT,
    PERMISSION_ENTITIES_VIEW,
    PERMISSION_PROPOSALS_EDIT,
    PERMISSION_PROPOSALS_VIEW,
    PERMISSION_REPORTS_VIEW,
    request_has_tenant_permission,
)
from tenants.defaults import (
    PROFILE_BROKER,
    PROFILE_CONDOMINIO,
    PROFILE_GENERAL,
    PROFILE_MARKETING,
    PROFILE_RETAIL_MODA,
    PROFILE_SERVICIOS,
    resolve_dashboard_widgets,
    resolve_module_order,
)
from tenants.operational_settings import (
    HOMEPAGE_DENSITY_LABELS,
    HOMEPAGE_HERO_METRIC_LABELS,
    HOMEPAGE_LAYOUT_LABELS,
    resolve_homepage_layout,
)


def build_dashboard_experience(tenant, summary: dict, permissions: dict | None = None) -> dict:
    config = tenant.tenant_config
    labels = config.labels
    feature_flags = config.feature_flags or {}
    layout = resolve_homepage_layout(getattr(config, "homepage_layout", {}))
    copy = _dashboard_copy(config.profile, labels)
    module_order = _prioritize_dashboard_modules(resolve_module_order(getattr(config, "module_order", [])), hero_metric=layout["hero_metric"])
    dashboard_widgets = set(resolve_dashboard_widgets(getattr(config, "dashboard_widgets", [])))
    permissions = permissions or {
        PERMISSION_ENTITIES_VIEW: True,
        PERMISSION_ENTITIES_EDIT: True,
        PERMISSION_DEALS_VIEW: True,
        PERMISSION_DEALS_EDIT: True,
        PERMISSION_ACTIVITIES_VIEW: True,
        PERMISSION_ACTIVITIES_EDIT: True,
        PERMISSION_DOCUMENTS_VIEW: True,
        PERMISSION_DOCUMENTS_EDIT: True,
        PERMISSION_PROPOSALS_VIEW: True,
        PERMISSION_PROPOSALS_EDIT: True,
        PERMISSION_COLLECTIONS_VIEW: True,
        PERMISSION_COLLECTIONS_EDIT: True,
        PERMISSION_REPORTS_VIEW: True,
    }

    summary_card_map = {}
    if feature_flags.get("entities") and permissions.get(PERMISSION_ENTITIES_VIEW, False):
        summary_card_map["entities"] = {
            "title": labels.get("entity_plural", "Contactos"),
            "value": summary["entities"],
            "description": copy["entity_metric_caption"],
            "href": reverse("binncrm:entities"),
            "cta": copy["entity_metric_cta"],
        }
    if feature_flags.get("deals") and permissions.get(PERMISSION_DEALS_VIEW, False):
        card = {
            "title": labels.get("deal_plural", "Oportunidades"),
            "value": summary["open_deals"],
            "description": copy["deal_metric_caption"],
            "href": reverse("binncrm:index") if feature_flags.get("kanban", True) else "",
            "cta": copy["deal_metric_cta"],
        }
        if not feature_flags.get("kanban", True):
            card["description"] = copy["deal_metric_caption_without_kanban"]
            card["cta"] = ""
        summary_card_map["deals"] = card
    if feature_flags.get("activities") and permissions.get(PERMISSION_ACTIVITIES_VIEW, False):
        summary_card_map["activities"] = {
            "title": copy["activity_metric_title"],
            "value": summary["activities_due"],
            "description": copy["activity_metric_caption"],
            "href": reverse("binncrm:activities"),
            "cta": copy["activity_metric_cta"],
        }
    if feature_flags.get("documents") and permissions.get(PERMISSION_DOCUMENTS_VIEW, False):
        summary_card_map["documents"] = {
            "title": labels.get("document_plural", "Documentos"),
            "value": summary.get("documents", 0),
            "description": copy["document_metric_caption"],
            "href": reverse("binncrm:documents"),
            "cta": copy["document_metric_cta"],
        }
    if feature_flags.get("proposals") and permissions.get(PERMISSION_PROPOSALS_VIEW, False):
        summary_card_map["proposals"] = {
            "title": labels.get("proposal_plural", "Propuestas"),
            "value": summary.get("open_proposals", 0),
            "description": copy["proposal_metric_caption"],
            "href": reverse("binncrm:proposals"),
            "cta": copy["proposal_metric_cta"],
        }
    if feature_flags.get("collections") and permissions.get(PERMISSION_COLLECTIONS_VIEW, False):
        summary_card_map["collections"] = {
            "title": labels.get("collection_plural", "Cobranzas"),
            "value": summary.get("open_collections", 0),
            "description": copy["collection_metric_caption"],
            "href": reverse("binncrm:collections"),
            "cta": copy["collection_metric_cta"],
        }
    if feature_flags.get("reports") and permissions.get(PERMISSION_REPORTS_VIEW, False):
        summary_card_map["reports"] = {
            "title": copy["report_metric_title"],
            "value": summary.get("report_alerts", 0),
            "description": copy["report_metric_caption"],
            "href": reverse("binncrm:reports"),
            "cta": copy["report_metric_cta"],
        }

    guided_steps = []
    if layout["show_guided_steps"]:
        guided_steps = _resolve_guided_steps(
            copy,
            summary,
            feature_flags=feature_flags,
            permissions=permissions,
        )

    quick_action_limit = 6 if layout["density"] == "compact" else 4
    summary_card_limit = 6 if layout["density"] == "compact" else 4


    summary_cards = []
    if "summary_cards" in dashboard_widgets:
        summary_cards = [summary_card_map[key] for key in module_order if key in summary_card_map][:summary_card_limit]

    quick_action_map = {}
    if feature_flags.get("entities") and permissions.get(PERMISSION_ENTITIES_EDIT, False):
        quick_action_map["entities"] = {
            "label": copy["entity_action_label"],
            "compact_label": copy["entity_action_compact"],
            "href": reverse("binncrm:entity_create"),
            "primary": True,
            "help": copy["entity_action_help"],
        }
    if feature_flags.get("deals") and permissions.get(PERMISSION_DEALS_EDIT, False):
        quick_action_map["deals"] = {
            "label": copy["deal_action_label"],
            "compact_label": copy["deal_action_compact"],
            "href": reverse("binncrm:deal_create"),
            "primary": False,
            "help": copy["deal_action_help"],
        }
    if feature_flags.get("documents") and permissions.get(PERMISSION_DOCUMENTS_EDIT, False):
        quick_action_map["documents"] = {
            "label": copy["document_action_label"],
            "compact_label": copy["document_action_compact"],
            "href": reverse("binncrm:document_create"),
            "primary": False,
            "help": copy["document_action_help"],
        }
    if feature_flags.get("proposals") and permissions.get(PERMISSION_PROPOSALS_EDIT, False):
        quick_action_map["proposals"] = {
            "label": copy["proposal_action_label"],
            "compact_label": copy["proposal_action_compact"],
            "href": reverse("binncrm:proposal_create"),
            "primary": False,
            "help": copy["proposal_action_help"],
        }
    if feature_flags.get("collections") and permissions.get(PERMISSION_COLLECTIONS_EDIT, False):
        quick_action_map["collections"] = {
            "label": copy["collection_action_label"],
            "compact_label": copy["collection_action_compact"],
            "href": reverse("binncrm:collection_create"),
            "primary": False,
            "help": copy["collection_action_help"],
        }
    if feature_flags.get("activities") and permissions.get(PERMISSION_ACTIVITIES_EDIT, False):
        quick_action_map["activities"] = {
            "label": copy["activity_action_label"],
            "compact_label": copy["activity_action_compact"],
            "href": reverse("binncrm:activity_create"),
            "primary": False,
            "help": copy["activity_action_help"],
        }
    if feature_flags.get("reports") and permissions.get(PERMISSION_REPORTS_VIEW, False):
        quick_action_map["reports"] = {
            "label": copy["report_action_label"],
            "compact_label": copy["report_action_compact"],
            "href": reverse("binncrm:reports"),
            "primary": False,
            "help": copy["report_action_help"],
        }

    quick_actions = []
    if "quick_actions" in dashboard_widgets:
        quick_actions = [quick_action_map[key] for key in module_order if key in quick_action_map][:quick_action_limit]

    return {
        "kicker": copy["kicker"],
        "welcome_title": copy["welcome_title"],
        "welcome_copy": copy["welcome_copy"],
        "highlights": copy["highlights"] if "highlights" in dashboard_widgets else [],
        "guided_steps": guided_steps if "guided_steps" in dashboard_widgets else [],
        "guided_steps_title": "Para empezar rapido",
        "guided_steps_copy": "Pasos simples para dejar este espacio listo para trabajar.",
        "summary_cards": summary_cards,
        "summary_card_limit": summary_card_limit,
        "quick_actions": quick_actions,
        "quick_action_limit": quick_action_limit,
        "layout_mode": layout["mode"],
        "layout_mode_label": HOMEPAGE_LAYOUT_LABELS.get(layout["mode"], layout["mode"].title()),
        "layout_density": layout["density"],
        "layout_density_label": HOMEPAGE_DENSITY_LABELS.get(layout["density"], layout["density"].title()),
        "hero_metric": layout["hero_metric"],
        "hero_metric_label": HOMEPAGE_HERO_METRIC_LABELS.get(layout["hero_metric"], layout["hero_metric"].replace("_", " ").title()),
        "show_pipeline_panel": (
            feature_flags.get("deals")
            and permissions.get(PERMISSION_DEALS_VIEW, False)
            and feature_flags.get("kanban", True)
            and "pipeline_panel" in dashboard_widgets
        ),
        "show_entity_panel": (
            feature_flags.get("entities")
            and permissions.get(PERMISSION_ENTITIES_VIEW, False)
            and "entity_panel" in dashboard_widgets
        ),
        "show_activity_panel": (
            feature_flags.get("activities")
            and permissions.get(PERMISSION_ACTIVITIES_VIEW, False)
            and "activity_panel" in dashboard_widgets
        ),
        "can_create_deal": permissions.get(PERMISSION_DEALS_EDIT, False),
        "can_create_entity": permissions.get(PERMISSION_ENTITIES_EDIT, False),
        "can_create_activity": permissions.get(PERMISSION_ACTIVITIES_EDIT, False),
        "can_create_proposal": permissions.get(PERMISSION_PROPOSALS_EDIT, False),
        "can_create_collection": permissions.get(PERMISSION_COLLECTIONS_EDIT, False),
        "pipeline_subtitle": copy["pipeline_subtitle"],
        "pipeline_empty": copy["pipeline_empty"],
        "pipeline_cta": copy["pipeline_cta"],
        "entity_heading": copy["entity_heading"],
        "entity_empty": copy["entity_empty"],
        "entity_cta": copy["entity_cta"],
        "activity_heading": copy["activity_heading"],
        "activity_empty": copy["activity_empty"],
        "activity_cta": copy["activity_cta"],
    }


def _prioritize_dashboard_modules(module_order: list[str], *, hero_metric: str) -> list[str]:
    hero_module_map = {
        "activities_due": "activities",
        "open_deals": "deals",
        "open_collections": "collections",
        "recent_entities": "entities",
        "unread_messages": "reports",
    }
    prioritized_key = hero_module_map.get(str(hero_metric or "").strip().lower())
    if prioritized_key is None or prioritized_key not in module_order:
        return module_order
    return [prioritized_key] + [key for key in module_order if key != prioritized_key]


def _order_dashboard_priority_panels(panels: list[dict], *, hero_metric: str) -> list[dict]:
    hero_module_map = {
        "activities_due": "activities",
        "open_deals": "deals",
        "open_collections": "collections",
        "recent_entities": "entities",
    }
    prioritized_key = hero_module_map.get(str(hero_metric or "").strip().lower())
    if prioritized_key is None:
        return panels
    lead_panels = [panel for panel in panels if panel.get("key") == prioritized_key]
    trailing_panels = [panel for panel in panels if panel.get("key") != prioritized_key]
    return lead_panels + trailing_panels


def _dashboard_copy(profile: str, labels: dict) -> dict:
    entity_plural = labels.get("entity_plural", "Contactos")
    entity_singular = labels.get("entity_singular", "Contacto")
    deal_plural = labels.get("deal_plural", "Oportunidades")
    deal_singular = labels.get("deal_singular", "Oportunidad")
    document_singular = labels.get("document_singular", "Documento")
    proposal_singular = labels.get("proposal_singular", "Propuesta")
    collection_singular = labels.get("collection_singular", "Cobranza")

    shared = {
        "entity_metric_cta": "Operar fichas",
        "deal_metric_cta": "Mover pipeline",
        "deal_metric_caption_without_kanban": "El flujo esta activo, pero el tablero kanban todavia no sale a operar.",
        "activity_metric_cta": "Seguir agenda",
        "document_metric_cta": "Operar documentos",
        "proposal_metric_cta": "Seguir propuestas",
        "collection_metric_cta": "Cobrar cartera",
        "report_metric_cta": "Leer radar",
        "pipeline_cta": f"Abrir {deal_singular.lower()}",
        "entity_cta": "Abrir ficha",
        "activity_cta": "Abrir tarea",
        "entity_action_label": f"Abrir {entity_singular.lower()}",
        "entity_action_compact": "Abrir ficha",
        "entity_action_help": "Crea la ficha y deja el siguiente paso listo para operar.",
        "deal_action_label": f"Abrir {deal_singular.lower()}",
        "deal_action_compact": f"Abrir {deal_singular.lower()}",
        "deal_action_help": f"Abre el {deal_singular.lower()} y metelo al flujo comercial.",
        "activity_action_label": "Nueva actividad",
        "activity_action_compact": "Nueva actividad",
        "activity_action_help": "Deja llamada, tarea o recordatorio con fecha real.",
        "document_action_label": f"Cargar {document_singular.lower()}",
        "document_action_compact": "Cargar doc",
        "document_action_help": "Sube el soporte que puede destrabar el caso.",
        "proposal_action_label": f"Sacar {proposal_singular.lower()}",
        "proposal_action_compact": "Sacar propuesta",
        "proposal_action_help": "Deja la propuesta lista para enviar, negociar o cerrar.",
        "collection_action_label": f"Cargar {collection_singular.lower()}",
        "collection_action_compact": "Cargar cobro",
        "collection_action_help": "Carga saldo, promesa o pago y deja la cartera clara.",
        "report_action_label": "Leer radar",
        "report_action_compact": "Radar",
        "report_action_help": "Lee alertas y decide que frente mover primero.",
    }

    profiles = {
        PROFILE_GENERAL: {
            "kicker": "Radar de hoy",
            "welcome_title": "Que mover hoy",
            "welcome_copy": "Lee rapido que frente operar, seguir o cerrar antes de entrar al detalle.",
            "highlights": ["Contactos", "Seguimiento", "Pipeline"],
            "guided_steps": [
                f"Primero registra tus {entity_plural.lower()} o clientes.",
                f"Luego crea {deal_plural.lower()} para mover cada oportunidad.",
                "Finalmente agenda actividades para no olvidar el seguimiento.",
            ],
            "entity_metric_caption": "Base activa del tenant.",
            "deal_metric_caption": "Negocios abiertos en seguimiento.",
            "activity_metric_title": "Pendientes del dia",
            "activity_metric_caption": "Seguimientos y tareas por resolver.",
            "document_metric_caption": "Archivos y soportes disponibles.",
            "proposal_metric_caption": "Propuestas o cotizaciones activas.",
            "collection_metric_caption": "Cobros pendientes por resolver.",
            "report_metric_title": "Alertas clave",
            "report_metric_caption": "Senales operativas y comerciales que merecen atencion hoy.",
            "pipeline_subtitle": "Sigue el dinero en movimiento desde un solo tablero.",
            "pipeline_empty": "Todavia no hay un pipeline listo para mover negocio en este espacio.",
            "entity_heading": f"Ultimos {entity_plural.lower()}",
            "entity_empty": "Todavia no hay fichas activas para operar en este espacio.",
            "activity_heading": "Actividad reciente",
            "activity_empty": "Todavia no hay seguimiento registrado.",
        },
        PROFILE_CONDOMINIO: {
            "kicker": "Operacion de condominios",
            "welcome_title": "Residentes, cobro y novedades en una sola lectura.",
            "welcome_copy": "Este tablero esta pensado para saber rapido quien debe, que gestion toca hoy y que residente necesita atencion.",
            "highlights": ["Padron de residentes", "Recaudacion diaria", "Seguimiento de cartera"],
            "guided_steps": [
                "Carga o busca al residente que vas a gestionar.",
                "Registra el cobro o seguimiento que corresponda.",
                "Deja una actividad pendiente si necesitas volver a contactarlo.",
            ],
            "entity_metric_caption": "Padron activo del edificio.",
            "deal_metric_caption": "Cobros pendientes por cerrar.",
            "activity_metric_title": "Gestiones del dia",
            "activity_metric_caption": "Seguimientos y recordatorios de recaudacion.",
            "document_metric_caption": "Archivos del tenant disponibles.",
            "proposal_metric_caption": "Acuerdos o propuestas visibles para el equipo.",
            "collection_metric_caption": "Cartera con saldo pendiente o vencido.",
            "report_metric_title": "Alertas de cartera",
            "report_metric_caption": "Cartera, residentes sin contacto y gestiones que requieren atencion.",
            "pipeline_subtitle": "Prioriza notificaciones y pagos sin perder visibilidad de la cartera.",
            "pipeline_empty": "Todavia no hay un flujo de cobro listo para operar en este espacio.",
            "entity_heading": "Residentes recientes",
            "entity_empty": "Aun no hay residentes cargados para este condominio.",
            "activity_heading": "Actividad de recaudacion",
            "activity_empty": "Aun no hay gestiones de recaudacion registradas.",
        },
        PROFILE_BROKER: {
            "kicker": "Broker de seguros",
            "welcome_title": "Renovaciones, documentos y seguimiento en un solo lugar.",
            "welcome_copy": "Cuando abras el panel deberias poder saber de inmediato que asegurado revisar, que renovacion avanza y que documento falta.",
            "highlights": ["Asegurados al dia", "Renovaciones activas", "Documentos de emision"],
            "guided_steps": [
                "Busca al asegurado o crea uno nuevo si aun no existe.",
                "Registra la renovacion y muevela segun su etapa.",
                "Adjunta polizas, inspecciones o comprobantes para no perder contexto.",
            ],
            "entity_metric_caption": "Asegurados activos dentro del tenant.",
            "deal_metric_caption": "Renovaciones abiertas en seguimiento.",
            "activity_metric_title": "Seguimientos por vencer",
            "activity_metric_caption": "Llamadas y tareas para no perder renovaciones.",
            "document_metric_caption": "Polizas, inspecciones y soportes registrados.",
            "proposal_metric_caption": "Cotizaciones en borrador o enviadas.",
            "collection_metric_caption": "Cobros pendientes por renovar o recaudar.",
            "report_metric_title": "Riesgos de renovacion",
            "report_metric_caption": "Renovaciones, siniestros y documentos que necesitan reaccion.",
            "pipeline_subtitle": "Ordena renovaciones segun su etapa de emision y documentacion.",
            "pipeline_empty": "Aun no existe un flujo de renovaciones configurado para este tenant.",
            "entity_heading": "Asegurados recientes",
            "entity_empty": "Aun no hay asegurados registrados en este tenant.",
            "activity_heading": "Seguimiento comercial",
            "activity_empty": "Aun no hay seguimiento comercial registrado.",
        },
        PROFILE_MARKETING: {
            "kicker": "Agencia comercial",
            "welcome_title": "Todo el embudo comercial, claro y facil de seguir.",
            "welcome_copy": "El objetivo de esta pantalla es ayudarte a ver rapido cuantos leads entraron, en que etapa esta cada oportunidad y que seguimiento toca hoy.",
            "highlights": ["Captura de leads", "Embudo visual", "Seguimiento comercial"],
            "guided_steps": [
                "Carga un lead nuevo o busca uno existente.",
                "Crea la oportunidad para moverla por el embudo.",
                "Deja tareas y notas para que el equipo siga el hilo comercial.",
            ],
            "entity_metric_caption": "Leads activos listos para trabajar.",
            "deal_metric_caption": "Oportunidades en el embudo comercial.",
            "activity_metric_title": "Tareas de hoy",
            "activity_metric_caption": "Seguimientos pendientes para avanzar campanas.",
            "document_metric_caption": "Archivos comerciales disponibles.",
            "proposal_metric_caption": "Propuestas activas listas para enviar o cerrar.",
            "collection_metric_caption": "Cobros pendientes del flujo comercial.",
            "report_metric_title": "Alertas comerciales",
            "report_metric_caption": "Leads frios, propuestas por vencer y seguimientos atrasados.",
            "pipeline_subtitle": "Empuja leads por el embudo con una vista clara del avance comercial.",
            "pipeline_empty": "Aun no existe un pipeline comercial configurado para este tenant.",
            "entity_heading": "Leads recientes",
            "entity_empty": "Aun no hay leads registrados para esta agencia.",
            "activity_heading": "Actividad comercial",
            "activity_empty": "Aun no hay actividad comercial registrada.",
        },
        PROFILE_SERVICIOS: {
            "kicker": "Servicios B2B",
            "welcome_title": "Clientes, propuestas y seguimiento comercial sin enredos.",
            "welcome_copy": "Este panel esta pensado para saber rapido que oportunidad sigue viva, que propuesta se vence y que cliente necesita seguimiento hoy.",
            "highlights": ["Pipeline B2B", "Propuestas vigentes", "Cobros y renovaciones"],
            "guided_steps": [
                "Carga al cliente o prospecto con su empresa y servicio principal.",
                "Mueve la oportunidad por el pipeline y crea la propuesta cuando corresponda.",
                "Usa tareas y cobranzas para no perder el cierre ni la postventa.",
            ],
            "entity_metric_caption": "Clientes o prospectos activos del tenant.",
            "deal_metric_caption": "Oportunidades abiertas en seguimiento.",
            "activity_metric_title": "Pendientes comerciales",
            "activity_metric_caption": "Reuniones, llamadas y tareas por resolver.",
            "document_metric_caption": "Contratos, kickoff y entregables registrados.",
            "proposal_metric_caption": "Propuestas listas para negociar o cerrar.",
            "collection_metric_caption": "Cobros en seguimiento y renovaciones pendientes.",
            "report_metric_title": "Radar B2B",
            "report_metric_caption": "Propuestas, cobros y oportunidades que necesitan empuje.",
            "pipeline_subtitle": "Visualiza el avance comercial desde discovery hasta cierre sin salir del CRM.",
            "pipeline_empty": "Aun no existe un pipeline B2B configurado para este tenant.",
            "entity_heading": "Clientes recientes",
            "entity_empty": "Aun no hay clientes o prospectos registrados.",
            "activity_heading": "Seguimiento comercial",
            "activity_empty": "Aun no hay seguimiento comercial registrado.",
        },
        PROFILE_RETAIL_MODA: {
            "kicker": "Retail y clienteling",
            "welcome_title": "Clienteling claro para vender mejor y reactivar compras.",
            "welcome_copy": "Cuando abras el panel deberias ver que clientes volver a tocar, que pedidos especiales siguen abiertos y quien merece seguimiento por WhatsApp.",
            "highlights": ["Clientes VIP", "Pedidos especiales", "Recompra e inactividad"],
            "guided_steps": [
                "Busca al cliente o crea su ficha con talla y estilo favorito.",
                "Registra el pedido especial o seguimiento que quieres mover.",
                "Agenda una tarea de recompra para no dejar caer la relacion.",
            ],
            "entity_metric_caption": "Clientes activos listos para seguimiento.",
            "deal_metric_caption": "Pedidos especiales o ventas potenciales en curso.",
            "activity_metric_title": "Seguimientos de recompra",
            "activity_metric_caption": "Tareas de WhatsApp, apartados y clientes inactivos.",
            "document_metric_caption": "Soportes operativos del tenant disponibles.",
            "proposal_metric_caption": "Propuestas activas del tenant.",
            "collection_metric_caption": "Cobros o apartados pendientes del tenant.",
            "report_metric_title": "Radar de recompra",
            "report_metric_caption": "Clientes inactivos, pedidos abiertos y seguimientos de recompra.",
            "pipeline_subtitle": "Empuja la recompra con un flujo simple y entendible para el equipo de tienda.",
            "pipeline_empty": "Aun no existe un flujo de clienteling configurado para este tenant.",
            "entity_heading": "Clientes recientes",
            "entity_empty": "Aun no hay clientes registrados para esta marca.",
            "activity_heading": "Actividad de recompra",
            "activity_empty": "Aun no hay actividades de clienteling registradas.",
        },
    }

    return {**shared, **profiles.get(profile, profiles[PROFILE_GENERAL])}


def _resolve_guided_steps(copy: dict, summary: dict, *, feature_flags: dict, permissions: dict) -> list[str]:
    base_steps = list(copy.get("guided_steps") or [])
    if len(base_steps) < 3:
        return base_steps

    missing_steps: list[str] = []
    has_entities = summary.get("entities", 0) > 0
    has_open_deals = summary.get("open_deals", 0) > 0
    has_activities = summary.get("activities_total", 0) > 0

    if (
        feature_flags.get("entities")
        and permissions.get(PERMISSION_ENTITIES_EDIT, False)
        and not has_entities
    ):
        missing_steps.append(base_steps[0])
    if (
        feature_flags.get("deals")
        and permissions.get(PERMISSION_DEALS_EDIT, False)
        and not has_open_deals
    ):
        missing_steps.append(base_steps[1])
    if (
        feature_flags.get("activities")
        and permissions.get(PERMISSION_ACTIVITIES_EDIT, False)
        and not has_activities
    ):
        missing_steps.append(base_steps[2])

    return missing_steps


def _format_dashboard_money(currency: str, amount) -> str:
    numeric = float(amount or 0)
    if numeric.is_integer():
        amount_label = f"{numeric:,.0f}"
    else:
        amount_label = f"{numeric:,.2f}"
    return f"{currency} {amount_label}"


def _build_pipeline_summary(*, active_pipeline, open_deals_qs):
    if active_pipeline is None:
        return []

    stage_rows = {
        row["stage"]: row
        for row in (
            open_deals_qs.filter(pipeline=active_pipeline)
            .values("stage")
            .annotate(
                count=Count("id"),
                total=Sum("amount"),
                currency=Max("currency"),
            )
        )
    }
    summary = []
    for stage in active_pipeline.stage_choices:
        row = stage_rows.get(stage, {})
        summary.append(
            {
                "stage": stage,
                "count": row.get("count", 0),
                "amount_label": _format_dashboard_money(row.get("currency") or "USD", row.get("total") or 0),
            }
        )
    return summary


def _build_collection_summary(*, collections_qs):
    collection_tones = {
        "pending": {"accent": "#f59e0b", "alt": "#fbbf24", "soft": "rgba(245, 158, 11, 0.12)"},
        "promised": {"accent": "#2563eb", "alt": "#60a5fa", "soft": "rgba(37, 99, 235, 0.12)"},
        "overdue": {"accent": "#dc2626", "alt": "#f97316", "soft": "rgba(220, 38, 38, 0.12)"},
        "disputed": {"accent": "#7c3aed", "alt": "#a78bfa", "soft": "rgba(124, 58, 237, 0.12)"},
        "paid": {"accent": "#059669", "alt": "#34d399", "soft": "rgba(5, 150, 105, 0.12)"},
    }
    status_rows = {
        row["status"]: row
        for row in (
            collections_qs.values("status")
            .annotate(
                count=Count("id"),
                total_due=Sum("amount_due"),
                total_paid=Sum("amount_paid"),
                currency=Max("currency"),
            )
        )
    }
    summary = []
    status_choices = (
        ("pending", "Pendiente"),
        ("promised", "Promesa de pago"),
        ("paid", "Pagada"),
        ("overdue", "Vencida"),
        ("disputed", "En revision"),
    )
    for status_key, status_label in status_choices:
        row = status_rows.get(status_key, {})
        total_due = row.get("total_due") or 0
        total_paid = row.get("total_paid") or 0
        summary.append(
            {
                "status": status_key,
                "label": status_label,
                "count": row.get("count", 0),
                "amount_label": _format_dashboard_money(
                    row.get("currency") or "USD",
                    max(total_due - total_paid, 0),
                ),
                "tone": collection_tones[status_key],
            }
        )
    return summary


def _load_dashboard_metrics_bundle(*, tenant, today, now):
    cache_key = f"dashboard:metrics:{tenant.schema_name}:{today.isoformat()}"
    cached_bundle = cache.get(cache_key)
    if cached_bundle is not None:
        return cached_bundle

    from binncrm.models import Activity, CollectionRecord, Deal, Document, Entity, Pipeline, Proposal

    pipelines = list(Pipeline.objects.filter(is_active=True).order_by("position", "name"))
    active_pipeline = pipelines[0] if pipelines else None

    open_deals_qs = Deal.objects.filter(is_active=True, status=Deal.STATUS_OPEN)
    collections_base_qs = CollectionRecord.objects.filter(is_active=True)

    activity_stats = Activity.objects.aggregate(
        total=Count("id"),
        due=Count("id", filter=Q(completed_at__isnull=True, due_at__date__lte=today)),
        overdue_tasks=Count("id", filter=Q(activity_type=Activity.TYPE_TASK, completed_at__isnull=True, due_at__lt=now)),
    )
    document_stats = Document.objects.filter(is_active=True).aggregate(
        total=Count("id"),
        expiring=Count("id", filter=Q(expires_on__isnull=False, expires_on__lte=today + timedelta(days=30))),
    )
    proposal_stats = Proposal.objects.filter(
        is_active=True,
        status__in=[Proposal.STATUS_DRAFT, Proposal.STATUS_SENT],
    ).aggregate(total=Count("id"))
    collection_stats = collections_base_qs.aggregate(
        open_total=Count("id", filter=~Q(status=CollectionRecord.STATUS_PAID)),
        overdue_total=Count("id", filter=Q(due_on__lt=today) & ~Q(status=CollectionRecord.STATUS_PAID)),
    )
    deal_stats = Deal.objects.filter(is_active=True).aggregate(
        open_total=Count("id", filter=Q(status=Deal.STATUS_OPEN)),
        stale_open_total=Count("id", filter=Q(status=Deal.STATUS_OPEN, updated_at__lt=now - timedelta(days=14))),
    )

    bundle = {
        "pipelines": pipelines,
        "active_pipeline_id": active_pipeline.pk if active_pipeline else None,
        "entity_count": Entity.objects.filter(is_active=True).count(),
        "open_deals": deal_stats["open_total"] or 0,
        "activities_due": activity_stats["due"] or 0,
        "activities_total": activity_stats["total"] or 0,
        "documents": document_stats["total"] or 0,
        "open_proposals": proposal_stats["total"] or 0,
        "open_collections": collection_stats["open_total"] or 0,
        "report_alerts": (
            (deal_stats["stale_open_total"] or 0)
            + (activity_stats["overdue_tasks"] or 0)
            + (collection_stats["overdue_total"] or 0)
            + (document_stats["expiring"] or 0)
        ),
        "pipeline_summary": _build_pipeline_summary(active_pipeline=active_pipeline, open_deals_qs=open_deals_qs),
        "collection_summary": _build_collection_summary(collections_qs=collections_base_qs),
    }
    cache.set(cache_key, bundle, 30)
    return bundle


def _dashboard_module_enabled(feature_flags: dict, permissions: dict, feature_key: str, permission_key: str) -> bool:
    return bool(feature_flags.get(feature_key) and permissions.get(permission_key, False))


def _build_dashboard_action_lanes(*, feature_flags, permissions):
    lanes = []

    consultation_items = []
    if _dashboard_module_enabled(feature_flags, permissions, "deals", PERMISSION_DEALS_VIEW):
        consultation_items.append(
            {
                "label": "Mover pipeline",
                "help": "Lee volumen, etapas y monto antes de tocar una oportunidad.",
                "href": reverse("binncrm:index"),
            }
        )
    if _dashboard_module_enabled(feature_flags, permissions, "entities", PERMISSION_ENTITIES_VIEW):
        consultation_items.append(
            {
                "label": "Operar fichas",
                "help": "Entra a clientes y valida contexto, contacto y negocio abierto.",
                "href": reverse("binncrm:entities"),
            }
        )
    if _dashboard_module_enabled(feature_flags, permissions, "reports", PERMISSION_REPORTS_VIEW):
        consultation_items.append(
            {
                "label": "Leer radar",
                "help": "Usa el radar para detectar atrasos, huecos y focos del dia.",
                "href": reverse("binncrm:reports"),
            }
        )
    if consultation_items:
        lanes.append(
            {
                "title": "Consulta",
                "subtitle": "Lectura rapida para decidir donde meter energia primero.",
                "tone": {"accent": "#0f766e", "soft": "rgba(15, 118, 110, 0.10)"},
                "items": consultation_items[:3],
            }
        )

    follow_up_items = []
    if _dashboard_module_enabled(feature_flags, permissions, "activities", PERMISSION_ACTIVITIES_VIEW):
        follow_up_items.append(
            {
                "label": "Seguir agenda",
                "help": "Revisa tareas vencidas y compromisos de hoy en una sola vista.",
                "href": reverse("binncrm:activities"),
            }
        )
    if _dashboard_module_enabled(feature_flags, permissions, "activities", PERMISSION_ACTIVITIES_EDIT):
        follow_up_items.append(
            {
                "label": "Nueva actividad",
                "help": "Deja proximo paso, responsable y fecha cerrados al instante.",
                "href": reverse("binncrm:activity_create"),
            }
        )
    if _dashboard_module_enabled(feature_flags, permissions, "documents", PERMISSION_DOCUMENTS_VIEW):
        follow_up_items.append(
            {
                "label": "Operar documentos",
                "help": "Confirma vencimientos, faltantes y piezas sin verificar.",
                "href": reverse("binncrm:documents"),
            }
        )
    if follow_up_items:
        lanes.append(
            {
                "title": "Seguimiento",
                "subtitle": "Acciones para empujar respuesta, dejar huella y no soltar nada vivo.",
                "tone": {"accent": "#2563eb", "soft": "rgba(37, 99, 235, 0.10)"},
                "items": follow_up_items[:3],
            }
        )

    closing_items = []
    if _dashboard_module_enabled(feature_flags, permissions, "proposals", PERMISSION_PROPOSALS_VIEW):
        closing_items.append(
            {
                "label": "Seguir propuestas",
                "help": "Chequea vigencia y respuestas pendientes antes de que se enfrien.",
                "href": reverse("binncrm:proposals"),
            }
        )
    if _dashboard_module_enabled(feature_flags, permissions, "collections", PERMISSION_COLLECTIONS_VIEW):
        closing_items.append(
            {
                "label": "Cobrar cartera",
                "help": "Ve promesas, vencidos y caja por recuperar sin salir del CRM.",
                "href": reverse("binncrm:collections"),
            }
        )
    if _dashboard_module_enabled(feature_flags, permissions, "collections", PERMISSION_COLLECTIONS_EDIT):
        closing_items.append(
            {
                "label": "Cargar cobro",
                "help": "Carga compromisos o pagos apenas se confirme el siguiente paso.",
                "href": reverse("binncrm:collection_create"),
            }
        )
    elif _dashboard_module_enabled(feature_flags, permissions, "proposals", PERMISSION_PROPOSALS_EDIT):
        closing_items.append(
            {
                "label": "Sacar propuesta",
                "help": "Formaliza el cierre con una propuesta lista para enviar hoy.",
                "href": reverse("binncrm:proposal_create"),
            }
        )
    if closing_items:
        lanes.append(
            {
                "title": "Cierre",
                "subtitle": "Todo lo necesario para convertir intencion en firma o recaudo.",
                "tone": {"accent": "#b45309", "soft": "rgba(180, 83, 9, 0.10)"},
                "items": closing_items[:3],
            }
        )

    return lanes


def _build_dashboard_priority_panels(*, feature_flags, permissions, today, now):
    from binncrm.models import Activity, CollectionRecord, Deal, Document, Entity

    panels = []

    if _dashboard_module_enabled(feature_flags, permissions, "activities", PERMISSION_ACTIVITIES_VIEW):
        due_tasks_qs = Activity.objects.select_related("entity", "assigned_to").filter(
            activity_type=Activity.TYPE_TASK,
            completed_at__isnull=True,
            due_at__isnull=False,
            due_at__date__lte=today,
        )
        due_total = due_tasks_qs.count()
        overdue_total = due_tasks_qs.filter(due_at__lt=now).count()
        due_today_total = due_tasks_qs.filter(due_at__date=today).count()
        task_items = []
        for task in due_tasks_qs.order_by("due_at", "-created_at")[:5]:
            due_at = timezone.localtime(task.due_at) if timezone.is_aware(task.due_at) else task.due_at
            owner = ""
            if task.assigned_to:
                owner = task.assigned_to.get_full_name() or task.assigned_to.username
            meta_parts = [task.entity.full_name]
            if owner:
                meta_parts.append(owner)
            if due_at and due_at < now:
                status = due_at.strftime("Vencio %d/%m %H:%M")
            elif due_at and due_at.date() == today:
                status = due_at.strftime("Hoy %H:%M")
            else:
                status = due_at.strftime("Programada %d/%m %H:%M") if due_at else "Sin fecha"
            task_items.append(
                {
                    "badge": "Tarea",
                    "title": task.title,
                    "meta": " | ".join(part for part in meta_parts if part),
                    "status": status,
                    "href": reverse("binncrm:entity_detail", kwargs={"pk": task.entity_id}),
                }
            )
        panels.append(
            {
                "key": "activities",
                "glance_label": "tareas por mover",
                "title": "Agenda de seguimiento",
                "value": due_total,
                "value_caption": "vencidas y para hoy",
                "hint": f"{overdue_total} vencidas y {due_today_total} programadas para hoy.",
                "href": reverse("binncrm:activities"),
                "cta": "Seguir agenda",
                "items": task_items,
                "empty_message": "Agenda limpia por ahora. Cuando entre una tarea con fecha, la veras primero aqui.",
                "tone": {"accent": "#2563eb", "soft": "rgba(37, 99, 235, 0.10)"},
            }
        )

    if _dashboard_module_enabled(feature_flags, permissions, "deals", PERMISSION_DEALS_VIEW):
        open_deals_qs = Deal.objects.select_related("entity", "pipeline").filter(is_active=True, status=Deal.STATUS_OPEN)
        open_total = open_deals_qs.count()
        closing_soon_qs = open_deals_qs.filter(expected_close_on__isnull=False, expected_close_on__lte=today + timedelta(days=14))
        closing_soon_total = closing_soon_qs.count()
        focus_deals = list(closing_soon_qs.order_by("expected_close_on", "-updated_at")[:3])
        focus_ids = {deal.pk for deal in focus_deals}
        if len(focus_deals) < 5:
            focus_deals.extend(
                list(open_deals_qs.exclude(pk__in=focus_ids).order_by("updated_at")[: 5 - len(focus_deals)])
            )
        deal_items = []
        for deal in focus_deals:
            if deal.expected_close_on:
                if deal.expected_close_on < today:
                    status = deal.expected_close_on.strftime("Debio cerrar %d/%m/%Y")
                elif deal.expected_close_on == today:
                    status = "Cierra hoy"
                else:
                    status = deal.expected_close_on.strftime("Cierra %d/%m/%Y")
            else:
                last_movement = timezone.localtime(deal.updated_at) if timezone.is_aware(deal.updated_at) else deal.updated_at
                status = last_movement.strftime("Ultimo movimiento %d/%m/%Y")
            deal_items.append(
                {
                    "badge": "Deal",
                    "title": deal.title,
                    "meta": f"{deal.entity.full_name} | {deal.pipeline.name} | {deal.stage}",
                    "status": status,
                    "href": reverse("binncrm:deal_edit", kwargs={"pk": deal.pk}),
                }
            )
        panels.append(
            {
                "key": "deals",
                "glance_label": "oportunidades abiertas",
                "title": "Oportunidades activas",
                "value": open_total,
                "value_caption": "todavia vivas",
                "hint": (
                    f"{closing_soon_total} por cerrar en los proximos 14 dias."
                    if closing_soon_total
                    else "No hay cierres inmediatos, pero si oportunidades abiertas para seguir moviendo."
                ),
                "href": reverse("binncrm:index"),
                "cta": "Mover pipeline",
                "items": deal_items,
                "empty_message": "Todavia no hay oportunidades abiertas. Cuando entren, este panel te mostrara las que piden accion primero.",
                "tone": {"accent": "#0f766e", "soft": "rgba(15, 118, 110, 0.10)"},
            }
        )

    if _dashboard_module_enabled(feature_flags, permissions, "entities", PERMISSION_ENTITIES_VIEW):
        pending_entities_qs = (
            Entity.objects.filter(is_active=True)
            .annotate(
                last_touch_at=Max("activities__created_at"),
                open_deals_count=Count(
                    "deals",
                    filter=Q(deals__is_active=True, deals__status=Deal.STATUS_OPEN),
                    distinct=True,
                ),
                open_collections_count=Count(
                    "collections",
                    filter=Q(collections__is_active=True) & ~Q(collections__status=CollectionRecord.STATUS_PAID),
                    distinct=True,
                ),
            )
            .filter(Q(open_deals_count__gt=0) | Q(open_collections_count__gt=0))
            .filter(Q(last_touch_at__isnull=True) | Q(last_touch_at__lt=now - timedelta(days=10)))
            .order_by("last_touch_at", "-updated_at")
        )
        pending_total = pending_entities_qs.count()
        entity_items = []
        for entity in pending_entities_qs[:5]:
            meta_parts = []
            if entity.open_deals_count:
                meta_parts.append(f"{entity.open_deals_count} oportunidades")
            if entity.open_collections_count:
                meta_parts.append(f"{entity.open_collections_count} cobros")
            if entity.phone:
                meta_parts.append(entity.phone)
            elif entity.email:
                meta_parts.append(entity.email)
            if entity.last_touch_at:
                last_touch = timezone.localtime(entity.last_touch_at) if timezone.is_aware(entity.last_touch_at) else entity.last_touch_at
                status = last_touch.strftime("Ultimo toque %d/%m %H:%M")
            else:
                status = "Sin seguimiento registrado todavia"
            entity_items.append(
                {
                    "badge": "Cliente",
                    "title": entity.full_name,
                    "meta": " | ".join(meta_parts) if meta_parts else "Negocio abierto sin contexto extra cargado.",
                    "status": status,
                    "href": reverse("binncrm:entity_detail", kwargs={"pk": entity.pk}),
                }
            )
        panels.append(
            {
                "key": "entities",
                "glance_label": "clientes pendientes",
                "title": "Clientes pendientes",
                "value": pending_total,
                "value_caption": "sin toque reciente",
                "hint": "Contactos con negocio abierto que ya piden llamada, nota o siguiente paso claro.",
                "href": reverse("binncrm:entities"),
                "cta": "Operar fichas",
                "items": entity_items,
                "empty_message": "Buen ritmo: no aparecen clientes abiertos sin seguimiento reciente en este momento.",
                "tone": {"accent": "#475467", "soft": "rgba(71, 84, 103, 0.10)"},
            }
        )

    can_view_collections = _dashboard_module_enabled(feature_flags, permissions, "collections", PERMISSION_COLLECTIONS_VIEW)
    can_view_documents = _dashboard_module_enabled(feature_flags, permissions, "documents", PERMISSION_DOCUMENTS_VIEW)
    if can_view_collections or can_view_documents:
        risk_items = []
        collection_risk_total = 0
        document_risk_total = 0

        if can_view_collections:
            urgent_collections_qs = (
                CollectionRecord.objects.select_related("entity")
                .filter(is_active=True)
                .exclude(status=CollectionRecord.STATUS_PAID)
                .filter(Q(due_on__lt=today) | Q(promised_for__lte=today))
                .order_by("due_on", "promised_for", "-updated_at")
            )
            collection_risk_total = urgent_collections_qs.count()
            for collection in urgent_collections_qs[:3]:
                risk_date = collection.due_on or collection.promised_for
                if collection.due_on and collection.due_on < today:
                    status = collection.due_on.strftime("Vencio %d/%m/%Y")
                elif collection.promised_for and collection.promised_for == today:
                    status = "Promesa para hoy"
                elif collection.promised_for:
                    status = collection.promised_for.strftime("Prometida %d/%m/%Y")
                else:
                    status = "Cobranza abierta"
                risk_items.append(
                    {
                        "badge": "Cobro",
                        "title": collection.title,
                        "meta": f"{collection.entity.full_name} | {collection.get_status_display()}",
                        "status": status,
                        "href": reverse("binncrm:collection_edit", kwargs={"pk": collection.pk}),
                        "sort_date": risk_date,
                    }
                )

        if can_view_documents:
            expiring_documents_qs = (
                Document.objects.select_related("entity", "deal")
                .filter(is_active=True, expires_on__isnull=False, expires_on__lte=today + timedelta(days=15))
                .order_by("expires_on", "is_verified", "-updated_at")
            )
            document_risk_total = expiring_documents_qs.count()
            for document in expiring_documents_qs[:3]:
                if document.entity_id:
                    owner_label = document.entity.full_name
                elif document.deal_id:
                    owner_label = document.deal.title
                else:
                    owner_label = document.document_type or "Documento operativo"
                meta_parts = [owner_label]
                if not document.is_verified:
                    meta_parts.append("sin verificar")
                if document.expires_on < today:
                    status = document.expires_on.strftime("Vencio %d/%m/%Y")
                elif document.expires_on == today:
                    status = "Vence hoy"
                else:
                    status = document.expires_on.strftime("Vence %d/%m/%Y")
                risk_items.append(
                    {
                        "badge": "Documento",
                        "title": document.title,
                        "meta": " | ".join(meta_parts),
                        "status": status,
                        "href": reverse("binncrm:document_edit", kwargs={"pk": document.pk}),
                        "sort_date": document.expires_on,
                    }
                )

        risk_items = sorted(
            risk_items,
            key=lambda item: (item.get("sort_date") is None, item.get("sort_date") or today, item["badge"]),
        )
        normalized_risk_items = []
        for item in risk_items[:5]:
            normalized_risk_items.append(
                {
                    "badge": item["badge"],
                    "title": item["title"],
                    "meta": item["meta"],
                    "status": item["status"],
                    "href": item["href"],
                }
            )

        if collection_risk_total:
            risk_href = reverse("binncrm:collections")
            risk_cta = "Cobrar cartera"
        elif document_risk_total:
            risk_href = reverse("binncrm:documents")
            risk_cta = "Operar documentos"
        elif can_view_collections:
            risk_href = reverse("binncrm:collections")
            risk_cta = "Cobrar cartera"
        else:
            risk_href = reverse("binncrm:documents")
            risk_cta = "Operar documentos"

        panels.append(
            {
                "key": "collections" if can_view_collections else "documents",
                "glance_label": "riesgos operativos",
                "title": "Cobros y documentos en riesgo",
                "value": collection_risk_total + document_risk_total,
                "value_caption": "por resolver pronto",
                "hint": f"{collection_risk_total} cobros y {document_risk_total} documentos piden una decision o gestion hoy.",
                "href": risk_href,
                "cta": risk_cta,
                "items": normalized_risk_items,
                "empty_message": "Sin alertas rojas ahora mismo. Cuando un cobro o documento se acerque al borde, aparecera aqui.",
                "tone": {"accent": "#b42318", "soft": "rgba(180, 35, 24, 0.10)"},
            }
        )

    return panels


@login_required
def dashboard(request):
    tenant = getattr(request, "tenant", None)
    if tenant and tenant.schema_name == "public":
        if request.user.is_superuser:
            return redirect("tenants:list")
        return redirect("tenants:access_list")

    context = {
        "tenant_name": getattr(tenant, "name", ""),
        "tenant_schema": getattr(tenant, "schema_name", ""),
    }

    if tenant and tenant.schema_name != "public":
        from collab.services import list_inbox_summaries

        labels = tenant.tenant_config.labels
        if not request_has_tenant_permission(request, PERMISSION_DASHBOARD_VIEW):
            context.update(
                {
                    "labels": labels,
                    "dashboard_access_denied": True,
                    "dashboard": {
                        "kicker": "Acceso restringido",
                        "welcome_title": "Tu rol no puede abrir este panel.",
                        "welcome_copy": "Pide a un owner o manager que ajuste los permisos de este tenant si necesitas ver el dashboard.",
                        "highlights": [],
                        "guided_steps": [],
                        "quick_actions": [],
                        "summary_cards": [],
                        "show_pipeline_panel": False,
                        "show_entity_panel": False,
                        "show_activity_panel": False,
                        "can_create_deal": False,
                        "can_create_entity": False,
                        "can_create_activity": False,
                        "can_create_proposal": False,
                        "can_create_collection": False,
                    },
                }
            )
            return render(request, "pages/dashboard.html", context)

        feature_flags = tenant.tenant_config.feature_flags or {}
        dashboard_permissions = {
            PERMISSION_DASHBOARD_VIEW: True,
            PERMISSION_ENTITIES_VIEW: request_has_tenant_permission(request, PERMISSION_ENTITIES_VIEW),
            PERMISSION_ENTITIES_EDIT: request_has_tenant_permission(request, PERMISSION_ENTITIES_EDIT),
            PERMISSION_DEALS_VIEW: request_has_tenant_permission(request, PERMISSION_DEALS_VIEW),
            PERMISSION_DEALS_EDIT: request_has_tenant_permission(request, PERMISSION_DEALS_EDIT),
            PERMISSION_ACTIVITIES_VIEW: request_has_tenant_permission(request, PERMISSION_ACTIVITIES_VIEW),
            PERMISSION_ACTIVITIES_EDIT: request_has_tenant_permission(request, PERMISSION_ACTIVITIES_EDIT),
            PERMISSION_DOCUMENTS_VIEW: request_has_tenant_permission(request, PERMISSION_DOCUMENTS_VIEW),
            PERMISSION_DOCUMENTS_EDIT: request_has_tenant_permission(request, PERMISSION_DOCUMENTS_EDIT),
            PERMISSION_PROPOSALS_VIEW: request_has_tenant_permission(request, PERMISSION_PROPOSALS_VIEW),
            PERMISSION_PROPOSALS_EDIT: request_has_tenant_permission(request, PERMISSION_PROPOSALS_EDIT),
            PERMISSION_COLLECTIONS_VIEW: request_has_tenant_permission(request, PERMISSION_COLLECTIONS_VIEW),
            PERMISSION_COLLECTIONS_EDIT: request_has_tenant_permission(request, PERMISSION_COLLECTIONS_EDIT),
            PERMISSION_REPORTS_VIEW: request_has_tenant_permission(request, PERMISSION_REPORTS_VIEW),
        }
        today = timezone.localdate()
        now = timezone.now()
        metrics_bundle = _load_dashboard_metrics_bundle(tenant=tenant, today=today, now=now)
        pipelines = metrics_bundle["pipelines"] if feature_flags.get("deals") and dashboard_permissions[PERMISSION_DEALS_VIEW] else []
        active_pipeline = next(
            (pipeline for pipeline in pipelines if pipeline.pk == metrics_bundle["active_pipeline_id"]),
            pipelines[0] if pipelines else None,
        )
        show_conversation_panel = feature_flags.get("collab") and request_has_tenant_permission(request, "collab.view")
        recent_conversations = list_inbox_summaries(tenant=tenant, user=request.user)[:4] if show_conversation_panel else []
        unread_messages = sum(summary.unread_count for summary in recent_conversations)
        summary = {
            "entities": metrics_bundle["entity_count"] if feature_flags.get("entities") and dashboard_permissions[PERMISSION_ENTITIES_VIEW] else 0,
            "open_deals": metrics_bundle["open_deals"] if feature_flags.get("deals") and dashboard_permissions[PERMISSION_DEALS_VIEW] else 0,
            "activities_due": metrics_bundle["activities_due"] if feature_flags.get("activities") and dashboard_permissions[PERMISSION_ACTIVITIES_VIEW] else 0,
            "activities_total": metrics_bundle["activities_total"] if feature_flags.get("activities") and dashboard_permissions[PERMISSION_ACTIVITIES_VIEW] else 0,
            "documents": metrics_bundle["documents"] if feature_flags.get("documents") and dashboard_permissions[PERMISSION_DOCUMENTS_VIEW] else 0,
            "open_proposals": metrics_bundle["open_proposals"] if feature_flags.get("proposals") and dashboard_permissions[PERMISSION_PROPOSALS_VIEW] else 0,
            "open_collections": metrics_bundle["open_collections"] if feature_flags.get("collections") and dashboard_permissions[PERMISSION_COLLECTIONS_VIEW] else 0,
            "report_alerts": metrics_bundle["report_alerts"],
            "unread_messages": unread_messages,
        }

        dashboard_experience = build_dashboard_experience(tenant, summary, permissions=dashboard_permissions)
        priority_panels = _order_dashboard_priority_panels(
            _build_dashboard_priority_panels(
                feature_flags=feature_flags,
                permissions=dashboard_permissions,
                today=today,
                now=now,
            ),
            hero_metric=dashboard_experience["hero_metric"],
        )
        context.update(
            {
                "labels": labels,
                "summary": summary,
                "dashboard": dashboard_experience,
                "active_pipeline": active_pipeline,
                "pipeline_summary": metrics_bundle["pipeline_summary"] if feature_flags.get("deals") and dashboard_permissions[PERMISSION_DEALS_VIEW] else [],
                "collection_summary": metrics_bundle["collection_summary"] if feature_flags.get("collections") and dashboard_permissions[PERMISSION_COLLECTIONS_VIEW] else [],
                "recent_conversations": recent_conversations,
                "action_lanes": _build_dashboard_action_lanes(feature_flags=feature_flags, permissions=dashboard_permissions),
                "priority_panels": priority_panels,
                "show_pipeline_pulse": feature_flags.get("deals") and dashboard_permissions[PERMISSION_DEALS_VIEW],
                "show_collection_pulse": feature_flags.get("collections") and dashboard_permissions[PERMISSION_COLLECTIONS_VIEW],
                "show_conversation_panel": show_conversation_panel,
                "today": today,
            }
        )

    return render(request, "pages/dashboard.html", context)
