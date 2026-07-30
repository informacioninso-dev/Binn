from __future__ import annotations

from copy import deepcopy

from .defaults import (
    PROFILE_BROKER,
    PROFILE_CONDOMINIO,
    PROFILE_GENERAL,
    PROFILE_MARKETING,
    PROFILE_RETAIL_MODA,
    PROFILE_SERVICIOS,
    VALID_ROLE_KEYS,
)

HOMEPAGE_LAYOUT_LABELS = {
    "operations": "Operacion diaria",
    "sales": "Mesa comercial",
    "collections": "Centro de cobranza",
    "relationships": "Relacion con clientes",
}

HOMEPAGE_DENSITY_LABELS = {
    "comfortable": "Comoda",
    "compact": "Compacta",
}

HOMEPAGE_HERO_METRIC_LABELS = {
    "activities_due": "Tareas por vencer",
    "open_deals": "Oportunidades abiertas",
    "open_collections": "Cobros abiertos",
    "recent_entities": "Clientes recientes",
    "unread_messages": "Mensajes sin leer",
}

COMMUNICATION_CHANNEL_LABELS = {
    "whatsapp": "WhatsApp",
    "email": "Email",
    "phone": "Llamada",
    "sms": "SMS",
    "instagram": "Instagram",
}

DEFAULT_TASK_PRESETS = [
    {
        "key": "primer_contacto",
        "label": "Primer contacto",
        "category": "followup",
        "due_in_days": 1,
        "priority": "medium",
        "owner_role": "operator",
    },
    {
        "key": "seguimiento_comercial",
        "label": "Seguimiento comercial",
        "category": "followup",
        "due_in_days": 3,
        "priority": "medium",
        "owner_role": "operator",
    },
    {
        "key": "cierre_documental",
        "label": "Cierre documental",
        "category": "ops",
        "due_in_days": 5,
        "priority": "high",
        "owner_role": "manager",
    },
]

DEFAULT_COLLECTION_SETTINGS = {
    "default_currency": "USD",
    "risk_window_days": 5,
    "follow_up_days": [3, 7, 15],
    "states": ["pending", "promised", "overdue", "paid"],
}

DEFAULT_COMMUNICATION_SETTINGS = {
    "primary_channel": "whatsapp",
    "channels": ["whatsapp", "email"],
    "broadcast_enabled": False,
    "consent_required": True,
}

DEFAULT_QUOTE_SETTINGS = {
    "default_currency": "USD",
    "validity_days": 15,
    "number_prefix": "PROP",
    "approval_required_over": 0,
}

DEFAULT_HOMEPAGE_LAYOUT = {
    "mode": "operations",
    "density": "comfortable",
    "hero_metric": "activities_due",
    "show_guided_steps": True,
}

PROFILE_OPERATIONAL_DEFAULTS = {
    PROFILE_GENERAL: {
        "task_presets": list(DEFAULT_TASK_PRESETS),
        "collection_settings": dict(DEFAULT_COLLECTION_SETTINGS),
        "communication_settings": dict(DEFAULT_COMMUNICATION_SETTINGS),
        "quote_settings": dict(DEFAULT_QUOTE_SETTINGS),
        "homepage_layout": dict(DEFAULT_HOMEPAGE_LAYOUT),
    },
    PROFILE_CONDOMINIO: {
        "task_presets": [
            {
                "key": "promesa_pago",
                "label": "Confirmar promesa de pago",
                "category": "collections",
                "due_in_days": 1,
                "priority": "high",
                "owner_role": "operator",
            },
            {
                "key": "cartera_vencida",
                "label": "Escalar cartera vencida",
                "category": "collections",
                "due_in_days": 3,
                "priority": "high",
                "owner_role": "manager",
            },
        ],
        "collection_settings": {
            "default_currency": "USD",
            "risk_window_days": 3,
            "follow_up_days": [1, 3, 7],
            "states": ["pending", "promised", "overdue", "paid"],
        },
        "communication_settings": {
            "primary_channel": "whatsapp",
            "channels": ["whatsapp", "email", "phone"],
        },
        "quote_settings": {
            "number_prefix": "CTA",
            "validity_days": 10,
        },
        "homepage_layout": {
            "mode": "collections",
            "hero_metric": "open_collections",
        },
    },
    PROFILE_BROKER: {
        "task_presets": [
            {
                "key": "pedir_documentos",
                "label": "Pedir documentos de emision",
                "category": "documents",
                "due_in_days": 1,
                "priority": "high",
                "owner_role": "operator",
            },
            {
                "key": "seguimiento_renovacion",
                "label": "Seguimiento de renovacion",
                "category": "renewal",
                "due_in_days": 5,
                "priority": "medium",
                "owner_role": "operator",
            },
        ],
        "collection_settings": {
            "default_currency": "USD",
            "risk_window_days": 5,
            "follow_up_days": [2, 5, 10],
        },
        "communication_settings": {
            "primary_channel": "whatsapp",
            "channels": ["whatsapp", "email", "phone"],
        },
        "quote_settings": {
            "number_prefix": "COT",
            "validity_days": 15,
        },
        "homepage_layout": {
            "mode": "sales",
            "hero_metric": "open_deals",
        },
    },
    PROFILE_MARKETING: {
        "task_presets": [
            {
                "key": "followup_lead",
                "label": "Follow-up de lead",
                "category": "lead",
                "due_in_days": 1,
                "priority": "medium",
                "owner_role": "operator",
            }
        ],
        "collection_settings": {
            "default_currency": "USD",
        },
        "communication_settings": {
            "primary_channel": "whatsapp",
            "channels": ["whatsapp", "email", "instagram"],
        },
        "quote_settings": {
            "number_prefix": "PROP",
            "validity_days": 14,
        },
        "homepage_layout": {
            "mode": "sales",
            "hero_metric": "open_deals",
        },
    },
    PROFILE_SERVICIOS: {
        "task_presets": [
            {
                "key": "reunion_discovery",
                "label": "Agendar reunion discovery",
                "category": "sales",
                "due_in_days": 2,
                "priority": "medium",
                "owner_role": "operator",
            },
            {
                "key": "enviar_propuesta",
                "label": "Enviar propuesta",
                "category": "quote",
                "due_in_days": 4,
                "priority": "high",
                "owner_role": "manager",
            },
        ],
        "collection_settings": {
            "default_currency": "USD",
            "risk_window_days": 7,
            "follow_up_days": [3, 7, 14],
        },
        "communication_settings": {
            "primary_channel": "email",
            "channels": ["email", "whatsapp", "phone"],
        },
        "quote_settings": {
            "number_prefix": "PROP",
            "validity_days": 21,
        },
        "homepage_layout": {
            "mode": "sales",
            "hero_metric": "open_deals",
        },
    },
    PROFILE_RETAIL_MODA: {
        "task_presets": [
            {
                "key": "followup_whatsapp",
                "label": "Follow-up por WhatsApp",
                "category": "clienteling",
                "due_in_days": 1,
                "priority": "medium",
                "owner_role": "operator",
            },
            {
                "key": "reactivar_inactiva",
                "label": "Reactivar clienta inactiva",
                "category": "reactivation",
                "due_in_days": 7,
                "priority": "medium",
                "owner_role": "operator",
            },
        ],
        "collection_settings": {
            "default_currency": "USD",
            "risk_window_days": 2,
            "follow_up_days": [1, 2, 5],
        },
        "communication_settings": {
            "primary_channel": "whatsapp",
            "channels": ["whatsapp", "instagram", "email"],
        },
        "quote_settings": {
            "number_prefix": "PED",
            "validity_days": 7,
        },
        "homepage_layout": {
            "mode": "relationships",
            "hero_metric": "recent_entities",
        },
    },
}


def _coerce_non_negative_int(value, default: int, *, minimum: int = 0) -> int:
    try:
        resolved = int(value)
    except (TypeError, ValueError):
        return default
    return resolved if resolved >= minimum else default


def resolve_task_presets(task_presets=None) -> list[dict]:
    cleaned: list[dict] = []
    seen_keys: set[str] = set()
    for item in task_presets or []:
        if not isinstance(item, dict):
            continue
        key = str(item.get("key", "")).strip().lower()
        label = str(item.get("label", "")).strip()
        if not key or not label or key in seen_keys:
            continue
        priority = str(item.get("priority", "medium")).strip().lower()
        if priority not in {"low", "medium", "high"}:
            priority = "medium"
        owner_role = str(item.get("owner_role", "operator")).strip().lower()
        if owner_role not in VALID_ROLE_KEYS:
            owner_role = "operator"
        cleaned.append(
            {
                "key": key,
                "label": label,
                "category": str(item.get("category", "general")).strip().lower() or "general",
                "description": str(item.get("description", "")).strip(),
                "due_in_days": _coerce_non_negative_int(item.get("due_in_days", 0), 0),
                "priority": priority,
                "owner_role": owner_role,
            }
        )
        seen_keys.add(key)
    return cleaned


def resolve_collection_settings(collection_settings=None) -> dict:
    settings = dict(DEFAULT_COLLECTION_SETTINGS)
    raw_settings = collection_settings if isinstance(collection_settings, dict) else {}
    currency = str(raw_settings.get("default_currency", settings["default_currency"]) or settings["default_currency"]).strip().upper()
    follow_up_days: list[int] = []
    for day in raw_settings.get("follow_up_days", settings["follow_up_days"]) or []:
        try:
            normalized = int(day)
        except (TypeError, ValueError):
            continue
        if normalized >= 0 and normalized not in follow_up_days:
            follow_up_days.append(normalized)
    states: list[str] = []
    for state in raw_settings.get("states", settings["states"]) or []:
        normalized = str(state).strip().lower()
        if normalized and normalized not in states:
            states.append(normalized)
    settings.update(
        {
            "default_currency": currency or settings["default_currency"],
            "risk_window_days": _coerce_non_negative_int(
                raw_settings.get("risk_window_days", settings["risk_window_days"]),
                settings["risk_window_days"],
            ),
            "follow_up_days": follow_up_days or list(DEFAULT_COLLECTION_SETTINGS["follow_up_days"]),
            "states": states or list(DEFAULT_COLLECTION_SETTINGS["states"]),
        }
    )
    return settings


def resolve_communication_settings(communication_settings=None) -> dict:
    settings = dict(DEFAULT_COMMUNICATION_SETTINGS)
    raw_settings = communication_settings if isinstance(communication_settings, dict) else {}
    primary_channel = str(raw_settings.get("primary_channel", settings["primary_channel"]) or settings["primary_channel"]).strip().lower()
    if primary_channel not in COMMUNICATION_CHANNEL_LABELS:
        primary_channel = settings["primary_channel"]
    channels: list[str] = []
    for channel in raw_settings.get("channels", settings["channels"]) or []:
        normalized = str(channel).strip().lower()
        if normalized in COMMUNICATION_CHANNEL_LABELS and normalized not in channels:
            channels.append(normalized)
    if primary_channel not in channels:
        channels.insert(0, primary_channel)
    settings.update(
        {
            "primary_channel": primary_channel,
            "channels": channels or list(DEFAULT_COMMUNICATION_SETTINGS["channels"]),
            "broadcast_enabled": bool(raw_settings.get("broadcast_enabled", settings["broadcast_enabled"])),
            "consent_required": bool(raw_settings.get("consent_required", settings["consent_required"])),
        }
    )
    return settings


def resolve_quote_settings(quote_settings=None) -> dict:
    settings = dict(DEFAULT_QUOTE_SETTINGS)
    raw_settings = quote_settings if isinstance(quote_settings, dict) else {}
    settings.update(
        {
            "default_currency": str(raw_settings.get("default_currency", settings["default_currency"]) or settings["default_currency"]).strip().upper() or settings["default_currency"],
            "validity_days": _coerce_non_negative_int(raw_settings.get("validity_days", settings["validity_days"]), settings["validity_days"], minimum=1),
            "number_prefix": str(raw_settings.get("number_prefix", settings["number_prefix"]) or settings["number_prefix"]).strip().upper()[:12] or settings["number_prefix"],
            "approval_required_over": _coerce_non_negative_int(
                raw_settings.get("approval_required_over", settings["approval_required_over"]),
                settings["approval_required_over"],
            ),
        }
    )
    return settings


def resolve_homepage_layout(homepage_layout=None) -> dict:
    layout = dict(DEFAULT_HOMEPAGE_LAYOUT)
    raw_layout = homepage_layout if isinstance(homepage_layout, dict) else {}
    mode = str(raw_layout.get("mode", layout["mode"]) or layout["mode"]).strip().lower()
    density = str(raw_layout.get("density", layout["density"]) or layout["density"]).strip().lower()
    hero_metric = str(raw_layout.get("hero_metric", layout["hero_metric"]) or layout["hero_metric"]).strip().lower()
    if mode not in HOMEPAGE_LAYOUT_LABELS:
        mode = layout["mode"]
    if density not in HOMEPAGE_DENSITY_LABELS:
        density = layout["density"]
    if hero_metric not in HOMEPAGE_HERO_METRIC_LABELS:
        hero_metric = layout["hero_metric"]
    layout.update(
        {
            "mode": mode,
            "density": density,
            "hero_metric": hero_metric,
            "show_guided_steps": bool(raw_layout.get("show_guided_steps", layout["show_guided_steps"])),
        }
    )
    return layout


def get_operational_defaults(profile: str) -> dict:
    defaults = PROFILE_OPERATIONAL_DEFAULTS.get(profile or "", PROFILE_OPERATIONAL_DEFAULTS[PROFILE_GENERAL])
    return {
        "task_presets": resolve_task_presets(deepcopy(defaults.get("task_presets", DEFAULT_TASK_PRESETS))),
        "collection_settings": resolve_collection_settings(deepcopy(defaults.get("collection_settings", DEFAULT_COLLECTION_SETTINGS))),
        "communication_settings": resolve_communication_settings(
            deepcopy(defaults.get("communication_settings", DEFAULT_COMMUNICATION_SETTINGS))
        ),
        "quote_settings": resolve_quote_settings(deepcopy(defaults.get("quote_settings", DEFAULT_QUOTE_SETTINGS))),
        "homepage_layout": resolve_homepage_layout(deepcopy(defaults.get("homepage_layout", DEFAULT_HOMEPAGE_LAYOUT))),
    }


def merge_operational_defaults(
    profile: str,
    *,
    task_presets=None,
    collection_settings=None,
    communication_settings=None,
    quote_settings=None,
    homepage_layout=None,
) -> dict:
    defaults = get_operational_defaults(profile)
    return {
        "task_presets": resolve_task_presets(
            deepcopy(task_presets) if task_presets is not None else defaults["task_presets"]
        ),
        "collection_settings": resolve_collection_settings(
            collection_settings if collection_settings is not None else defaults["collection_settings"]
        ),
        "communication_settings": resolve_communication_settings(
            communication_settings if communication_settings is not None else defaults["communication_settings"]
        ),
        "quote_settings": resolve_quote_settings(
            quote_settings if quote_settings is not None else defaults["quote_settings"]
        ),
        "homepage_layout": resolve_homepage_layout(
            homepage_layout if homepage_layout is not None else defaults["homepage_layout"]
        ),
    }

