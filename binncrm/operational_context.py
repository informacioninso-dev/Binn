from __future__ import annotations

from datetime import timedelta

from django.utils import timezone

from tenants.operational_settings import COMMUNICATION_CHANNEL_LABELS

from .models import Activity, CollectionRecord

CHANNEL_ACTIVITY_TYPE_MAP = {
    "whatsapp": Activity.TYPE_WHATSAPP,
    "email": Activity.TYPE_EMAIL,
    "phone": Activity.TYPE_CALL,
}

ACTIVITY_TITLE_BY_TYPE = {
    Activity.TYPE_WHATSAPP: "Follow-up WhatsApp",
    Activity.TYPE_EMAIL: "Correo de seguimiento",
    Activity.TYPE_CALL: "Llamada de seguimiento",
}


def build_activity_operational_context(tenant) -> dict:
    settings = _as_dict(getattr(tenant, "communication_settings", {}))
    primary_channel = str(settings.get("primary_channel") or "whatsapp").strip().lower()
    channels = [str(item).strip().lower() for item in settings.get("channels", []) if str(item).strip()]
    default_activity_type = CHANNEL_ACTIVITY_TYPE_MAP.get(primary_channel, "")
    return {
        "primary_channel": primary_channel,
        "primary_channel_label": COMMUNICATION_CHANNEL_LABELS.get(primary_channel, primary_channel.title() or "Canal"),
        "channels": channels,
        "channels_label": ", ".join(COMMUNICATION_CHANNEL_LABELS.get(item, item.title()) for item in channels) or "Sin canales definidos",
        "default_activity_type": default_activity_type,
        "default_activity_title": ACTIVITY_TITLE_BY_TYPE.get(default_activity_type, ""),
        "broadcast_enabled": bool(settings.get("broadcast_enabled", False)),
        "consent_required": bool(settings.get("consent_required", True)),
    }


def build_proposal_operational_context(tenant, *, today=None) -> dict:
    settings = _as_dict(getattr(tenant, "quote_settings", {}))
    current_day = today or timezone.localdate()
    validity_days = max(int(settings.get("validity_days", 15) or 15), 0)
    default_currency = str(settings.get("default_currency") or "USD").strip().upper() or "USD"
    number_prefix = str(settings.get("number_prefix") or "PROP").strip().upper() or "PROP"
    approval_required_over = max(int(settings.get("approval_required_over", 0) or 0), 0)
    return {
        "default_currency": default_currency,
        "validity_days": validity_days,
        "default_valid_until": current_day + timedelta(days=validity_days),
        "number_prefix": number_prefix,
        "proposal_number_placeholder": f"{number_prefix}-{current_day.strftime('%Y%m%d')}",
        "approval_required_over": approval_required_over,
    }


def build_collection_operational_context(tenant) -> dict:
    settings = _as_dict(getattr(tenant, "collection_settings", {}))
    states = [str(item).strip().lower() for item in settings.get("states", []) if str(item).strip()]
    valid_statuses = {choice[0] for choice in CollectionRecord.STATUS_CHOICES}
    ordered_states = [state for state in states if state in valid_statuses]
    if not ordered_states:
        ordered_states = [CollectionRecord.STATUS_PENDING]
    choice_map = dict(CollectionRecord.STATUS_CHOICES)
    follow_up_days = [
        max(int(day or 0), 0)
        for day in settings.get("follow_up_days", [])
        if str(day).strip() != ""
    ]
    return {
        "default_currency": str(settings.get("default_currency") or "USD").strip().upper() or "USD",
        "risk_window_days": max(int(settings.get("risk_window_days", 5) or 5), 0),
        "follow_up_days": follow_up_days,
        "follow_up_label": ", ".join(str(day) for day in follow_up_days) if follow_up_days else "Sin cadencia sugerida",
        "states": ordered_states,
        "state_labels": [choice_map[state] for state in ordered_states if state in choice_map],
        "default_status": ordered_states[0],
    }


def _as_dict(value) -> dict:
    return value if isinstance(value, dict) else {}
