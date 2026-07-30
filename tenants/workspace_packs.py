from __future__ import annotations

from collections import defaultdict

from .defaults import (
    PROFILE_BROKER,
    PROFILE_CHOICES,
    PROFILE_CONDOMINIO,
    PROFILE_GENERAL,
    PROFILE_MARKETING,
    PROFILE_RETAIL_MODA,
    PROFILE_SERVICIOS,
)


PROFILE_LABEL_MAP = dict(PROFILE_CHOICES)

WORKSPACE_PACKS = {
    PROFILE_GENERAL: {
        "title": "Operacion base Binn",
        "subtitle": "Fichas, pipeline y seguimiento con criterio comercial y sin ruido extra.",
        "pillars": ["Base de contactos limpia", "Pipeline simple", "Seguimiento diario"],
        "rituals": [
            "Seguir fichas sin contexto claro cada semana.",
            "Cerrar tareas vencidas antes de abrir frente nuevo.",
            "Mover deals quietos antes de fin de mes.",
        ],
        "report_focus": ["Seguimiento en riesgo", "Deals sin movimiento", "Base incompleta"],
    },
    PROFILE_CONDOMINIO: {
        "title": "Operacion condominio",
        "subtitle": "Cobro, residentes y novedades con lenguaje de operacion diaria.",
        "pillars": ["Residentes claros", "Cartera visible", "Gestiones repetibles"],
        "rituals": [
            "Separar cartera vencida, prometida y cobrada por semana.",
            "Registrar cada gestion dentro de la ficha del residente.",
            "Usar el canal interno para novedades de torre o bloque.",
        ],
        "report_focus": ["Cartera vencida", "Residentes sin seguimiento", "Cobros por promesa"],
    },
    PROFILE_BROKER: {
        "title": "Operacion broker",
        "subtitle": "Renovaciones, checklist documental y cobro con criterio comercial.",
        "pillars": ["Asegurados completos", "Renovaciones vivas", "Docs bajo control"],
        "rituals": [
            "Seguir renovaciones proximas todos los lunes.",
            "Cerrar checklist documental antes de emitir.",
            "Escalar siniestros abiertos desde la ficha del asegurado.",
        ],
        "report_focus": ["Renovaciones proximas", "Checklist incompleto", "Documentos por vencer"],
    },
    PROFILE_MARKETING: {
        "title": "Operacion captacion",
        "subtitle": "Leads, propuestas y oportunidades con ritmo comercial y sin burocracia.",
        "pillars": ["Leads calificados", "Pipeline visible", "Propuestas vigentes"],
        "rituals": [
            "Mover leads frios antes de que se pierda el contexto.",
            "Mantener una fuente de campana consistente.",
            "Seguir propuestas por vencer dos veces por semana.",
        ],
        "report_focus": ["Leads sin seguimiento", "Embudo enfriandose", "Propuestas vigentes"],
    },
    PROFILE_SERVICIOS: {
        "title": "Operacion servicios B2B",
        "subtitle": "Clientes, propuestas y follow-up en una sola cadencia de cierre.",
        "pillars": ["Cuentas activas", "Propuestas ordenadas", "Cobro disciplinado"],
        "rituals": [
            "Validar siguiente paso por cuenta cada viernes.",
            "Separar discovery, propuesta y negociacion sin mezclar etapas.",
            "Atacar primero las cuentas sin responsable claro.",
        ],
        "report_focus": ["Deals quietos", "Cobros por empujar", "Clientes sin siguiente paso"],
    },
    PROFILE_RETAIL_MODA: {
        "title": "Operacion retail",
        "subtitle": "Clienteling, recompra y listas VIP sin ruido de ERP.",
        "pillars": ["Clientes activos", "Recompra visible", "Pedidos especiales"],
        "rituals": [
            "Reactivar clientes frios con cadencia semanal.",
            "Separar VIP, activos e inactivos en la base.",
            "Usar conversaciones internas para apartados sensibles.",
        ],
        "report_focus": ["Clientes inactivos", "Pedidos especiales", "Seguimientos de recompra"],
    },
}


def build_workspace_pack(*, profile: str, labels: dict | None = None, feature_flags: dict | None = None) -> dict:
    pack = dict(WORKSPACE_PACKS.get(profile or "", WORKSPACE_PACKS[PROFILE_GENERAL]))
    labels = labels or {}
    feature_flags = feature_flags or {}
    pack["profile"] = profile or PROFILE_GENERAL
    pack["profile_label"] = PROFILE_LABEL_MAP.get(profile or "", PROFILE_LABEL_MAP[PROFILE_GENERAL])
    pack["entity_label"] = labels.get("entity_plural", "Entidades")
    pack["deal_label"] = labels.get("deal_plural", "Deals")
    pack["collab_enabled"] = bool(feature_flags.get("collab", False))
    pack["documents_enabled"] = bool(feature_flags.get("documents", False))
    pack["collections_enabled"] = bool(feature_flags.get("collections", False))
    return pack


def build_group_pack_mix(*, tenant_rows: list[dict]) -> list[dict]:
    buckets: dict[str, dict] = defaultdict(
        lambda: {
            "profile": PROFILE_GENERAL,
            "profile_label": PROFILE_LABEL_MAP[PROFILE_GENERAL],
            "tenant_count": 0,
            "visible_tenant_count": 0,
            "entity_count": 0,
            "open_deals_count": 0,
            "overdue_activities_count": 0,
        }
    )
    for row in tenant_rows:
        tenant = row["tenant"]
        profile = getattr(getattr(tenant, "tenant_config", None), "profile", PROFILE_GENERAL) or PROFILE_GENERAL
        bucket = buckets[profile]
        bucket["profile"] = profile
        bucket["profile_label"] = PROFILE_LABEL_MAP.get(profile, profile.replace("_", " ").title())
        bucket["tenant_count"] += 1
        if row.get("metrics_visible"):
            bucket["visible_tenant_count"] += 1
            bucket["entity_count"] += int(row.get("entity_count") or 0)
            bucket["open_deals_count"] += int(row.get("open_deals_count") or 0)
            bucket["overdue_activities_count"] += int(row.get("overdue_activities_count") or 0)

    return sorted(
        buckets.values(),
        key=lambda item: (-item["visible_tenant_count"], -item["entity_count"], item["profile_label"]),
    )
