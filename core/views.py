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


def build_dashboard_experience(tenant, summary: dict, permissions: dict | None = None) -> dict:
    config = tenant.tenant_config
    labels = config.labels
    feature_flags = config.feature_flags or {}
    copy = _dashboard_copy(config.profile, labels)
    module_order = resolve_module_order(getattr(config, "module_order", []))
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

    guided_steps = _resolve_guided_steps(
        copy,
        summary,
        feature_flags=feature_flags,
        permissions=permissions,
    )

    summary_cards = []
    if "summary_cards" in dashboard_widgets:
        summary_cards = [summary_card_map[key] for key in module_order if key in summary_card_map]

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
        quick_actions = [quick_action_map[key] for key in module_order if key in quick_action_map]

    return {
        "kicker": copy["kicker"],
        "welcome_title": copy["welcome_title"],
        "welcome_copy": copy["welcome_copy"],
        "highlights": copy["highlights"] if "highlights" in dashboard_widgets else [],
        "guided_steps": guided_steps if "guided_steps" in dashboard_widgets else [],
        "guided_steps_title": "Para empezar rapido",
        "guided_steps_copy": "Pasos simples para dejar este espacio listo para trabajar.",
        "summary_cards": summary_cards,
        "quick_actions": quick_actions,
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


def _dashboard_copy(profile: str, labels: dict) -> dict:
    entity_plural = labels.get("entity_plural", "Contactos")
    entity_singular = labels.get("entity_singular", "Contacto")
    deal_plural = labels.get("deal_plural", "Oportunidades")
    deal_singular = labels.get("deal_singular", "Oportunidad")
    document_singular = labels.get("document_singular", "Documento")
    proposal_singular = labels.get("proposal_singular", "Propuesta")
    collection_singular = labels.get("collection_singular", "Cobranza")

    shared = {
        "entity_metric_cta": "Abrir modulo",
        "deal_metric_cta": "Abrir pipeline",
        "deal_metric_caption_without_kanban": "Modulo activo sin vista kanban publicada.",
        "activity_metric_cta": "Ver agenda",
        "document_metric_cta": "Ver documentos",
        "proposal_metric_cta": "Ver propuestas",
        "collection_metric_cta": "Ver cobranzas",
        "report_metric_cta": "Ver reportes",
        "pipeline_cta": f"Registrar {deal_singular.lower()}",
        "entity_cta": f"Registrar {entity_singular.lower()}",
        "activity_cta": "Nueva actividad",
        "entity_action_label": f"Registrar {entity_singular.lower()}",
        "entity_action_compact": f"Nuevo {entity_singular.lower()}",
        "entity_action_help": f"Crea la ficha y empieza a trabajar ese {entity_singular.lower()}.",
        "deal_action_label": f"Registrar {deal_singular.lower()}",
        "deal_action_compact": f"Nueva {deal_singular.lower()}",
        "deal_action_help": f"Abre un nuevo {deal_singular.lower()} y muevelo en el flujo.",
        "activity_action_label": "Nueva actividad",
        "activity_action_compact": "Nueva actividad",
        "activity_action_help": "Agenda una llamada, tarea o recordatorio.",
        "document_action_label": f"Registrar {document_singular.lower()}",
        "document_action_compact": f"Nuevo {document_singular.lower()}",
        "document_action_help": "Guarda el soporte clave del caso.",
        "proposal_action_label": f"Registrar {proposal_singular.lower()}",
        "proposal_action_compact": f"Nueva {proposal_singular.lower()}",
        "proposal_action_help": "Deja la propuesta o cotizacion trazable.",
        "collection_action_label": f"Registrar {collection_singular.lower()}",
        "collection_action_compact": f"Nueva {collection_singular.lower()}",
        "collection_action_help": "Registra el saldo y su fecha de vencimiento.",
        "report_action_label": "Abrir reportes",
        "report_action_compact": "Reportes",
        "report_action_help": "Mira alertas y pendientes del tenant.",
    }

    profiles = {
        PROFILE_GENERAL: {
            "kicker": "Panel de hoy",
            "welcome_title": "Resumen de hoy",
            "welcome_copy": "Revisa que atender primero y entra rapido a contactos, seguimiento o pipeline sin perder tiempo.",
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
            "pipeline_empty": "Todavia no existen pipelines configurados para este tenant.",
            "entity_heading": f"Ultimos {entity_plural.lower()}",
            "entity_empty": "Todavia no hay registros creados en este tenant.",
            "activity_heading": "Actividad reciente",
            "activity_empty": "Aun no hay actividad registrada.",
        },
        PROFILE_CONDOMINIO: {
            "kicker": "Administracion de condominios",
            "welcome_title": "Mira residentes, cobros y pendientes sin complicarte.",
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
            "pipeline_empty": "Aun no existe un flujo de recaudacion configurado para este tenant.",
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
            "kicker": "Agencia de marketing",
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
            "kicker": "Servicios y consultoria",
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
            "kicker": "Retail y moda",
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
        from binncrm.models import Activity, Entity
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
        recent_activities = (
            Activity.objects.select_related("entity", "deal").order_by("-created_at")[:5]
            if feature_flags.get("activities") and dashboard_permissions[PERMISSION_ACTIVITIES_VIEW]
            else []
        )
        recent_conversations = (
            list_inbox_summaries(tenant=tenant, user=request.user)[:4]
            if feature_flags.get("collab") and request_has_tenant_permission(request, "collab.view")
            else []
        )
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

        context.update(
            {
                "labels": labels,
                "summary": summary,
                "dashboard": build_dashboard_experience(tenant, summary, permissions=dashboard_permissions),
                "active_pipeline": active_pipeline,
                "pipeline_summary": metrics_bundle["pipeline_summary"] if feature_flags.get("deals") and dashboard_permissions[PERMISSION_DEALS_VIEW] and feature_flags.get("kanban", True) else [],
                "collection_summary": metrics_bundle["collection_summary"] if feature_flags.get("collections") and dashboard_permissions[PERMISSION_COLLECTIONS_VIEW] else [],
                "recent_entities": Entity.objects.filter(is_active=True).order_by("-updated_at")[:5]
                if feature_flags.get("entities") and dashboard_permissions[PERMISSION_ENTITIES_VIEW]
                else [],
                "recent_activities": recent_activities,
                "recent_conversations": recent_conversations,
                "today": today,
            }
        )

    return render(request, "pages/dashboard.html", context)
