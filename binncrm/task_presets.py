from __future__ import annotations

from datetime import datetime, time, timedelta
from urllib.parse import urlencode

from django.urls import reverse
from django.utils import timezone

from access.runtime import get_tenant_user_queryset

from .models import Activity

TASK_PRESET_PRIORITY_LABELS = {
    "low": "Baja",
    "medium": "Media",
    "high": "Alta",
}

TASK_PRESET_PRIORITY_TONES = {
    "low": "bg-slate-100 text-slate-700",
    "medium": "bg-amber-50 text-amber-700",
    "high": "bg-red-50 text-red-700",
}

TASK_PRESET_ROLE_LABELS = {
    "owner": "Owner",
    "manager": "Manager",
    "operator": "Operacion",
    "analyst": "Analisis",
    "viewer": "Consulta",
}


def get_task_preset(tenant, preset_key: str):
    normalized_key = str(preset_key or "").strip().lower()
    if not normalized_key:
        return None
    for preset in getattr(tenant, "task_presets", []) or []:
        if str(preset.get("key", "")).strip().lower() == normalized_key:
            return dict(preset)
    return None


def build_task_preset_due_at(task_preset: dict, *, now=None):
    current = now or timezone.now()
    local_now = timezone.localtime(current)
    due_in_days = max(int(task_preset.get("due_in_days", 0) or 0), 0)
    due_date = local_now.date() + timedelta(days=due_in_days)
    if due_in_days == 0:
        due_hour = min(max(local_now.hour + 2, 9), 18)
        due_minute = 0 if local_now.minute < 30 else 30
    else:
        due_hour = 9
        due_minute = 0
    due_local = timezone.make_aware(
        datetime.combine(due_date, time(hour=due_hour, minute=due_minute)),
        timezone.get_current_timezone(),
    )
    if due_local <= current:
        return current + timedelta(hours=2)
    return due_local


def resolve_task_preset_assignee(tenant, *, task_preset: dict, current_user=None):
    if current_user is not None and getattr(current_user, "is_superuser", False):
        return current_user
    owner_role = str(task_preset.get("owner_role", "")).strip().lower()
    queryset = get_tenant_user_queryset(
        tenant,
        roles=[owner_role] if owner_role else None,
        include_admins=True,
    )
    if current_user is not None and getattr(current_user, "is_authenticated", False):
        current_match = queryset.filter(pk=getattr(current_user, "pk", None)).first()
        if current_match is not None:
            return current_user
    return queryset.first() or (current_user if getattr(current_user, "is_authenticated", False) else None)


def build_task_preset_form_initial(
    tenant,
    preset_key: str,
    *,
    entity_id: int | None = None,
    deal_id: int | None = None,
    current_user=None,
    now=None,
) -> dict:
    task_preset = get_task_preset(tenant, preset_key)
    if task_preset is None:
        return {}
    assignee = resolve_task_preset_assignee(tenant, task_preset=task_preset, current_user=current_user)
    due_at = build_task_preset_due_at(task_preset, now=now)
    initial = {
        "activity_type": Activity.TYPE_TASK,
        "title": task_preset["label"],
        "description": task_preset.get("description", ""),
        "due_at": timezone.localtime(due_at).strftime("%Y-%m-%dT%H:%M"),
    }
    if entity_id:
        initial["entity"] = entity_id
    if deal_id:
        initial["deal"] = deal_id
    if assignee is not None and getattr(assignee, "pk", None):
        initial["assigned_to"] = assignee.pk
    return initial


def build_task_preset_form_href(*, preset_key: str, entity_id: int | None = None, deal_id: int | None = None) -> str:
    params = {
        "preset": preset_key,
        "activity_type": Activity.TYPE_TASK,
    }
    if entity_id:
        params["entity"] = str(entity_id)
    if deal_id:
        params["deal"] = str(deal_id)
    return f"{reverse('binncrm:activity_create')}?{urlencode(params)}"


def build_task_preset_cards(
    tenant,
    *,
    entity_id: int | None = None,
    deal_id: int | None = None,
    next_url: str = "",
    selected_key: str = "",
    limit: int | None = None,
    now=None,
) -> list[dict]:
    cards = []
    presets = list(getattr(tenant, "task_presets", []) or [])
    if limit is not None:
        presets = presets[:limit]
    for task_preset in presets:
        preset_key = str(task_preset.get("key", "")).strip().lower()
        if not preset_key:
            continue
        due_at = build_task_preset_due_at(task_preset, now=now)
        owner_role = str(task_preset.get("owner_role", "operator")).strip().lower()
        priority = str(task_preset.get("priority", "medium")).strip().lower()
        cards.append(
            {
                "key": preset_key,
                "label": task_preset.get("label", preset_key),
                "description": task_preset.get("description", ""),
                "category_label": _humanize_task_preset_category(task_preset.get("category", "general")),
                "priority_label": TASK_PRESET_PRIORITY_LABELS.get(priority, TASK_PRESET_PRIORITY_LABELS["medium"]),
                "priority_tone": TASK_PRESET_PRIORITY_TONES.get(priority, TASK_PRESET_PRIORITY_TONES["medium"]),
                "owner_role_label": TASK_PRESET_ROLE_LABELS.get(owner_role, TASK_PRESET_ROLE_LABELS["operator"]),
                "due_label": _format_task_preset_due_label(due_at, now=now),
                "href": build_task_preset_form_href(
                    preset_key=preset_key,
                    entity_id=entity_id,
                    deal_id=deal_id,
                ),
                "quick_create_fields": [
                    ("preset", preset_key),
                    ("entity", str(entity_id or "")),
                    ("deal", str(deal_id or "")),
                    ("next", next_url),
                ],
                "can_quick_create": bool(entity_id or deal_id),
                "is_selected": preset_key == str(selected_key or "").strip().lower(),
            }
        )
    return cards


def _format_task_preset_due_label(due_at, *, now=None) -> str:
    local_due = timezone.localtime(due_at)
    local_now = timezone.localtime(now or timezone.now())
    delta_days = (local_due.date() - local_now.date()).days
    if delta_days <= 0:
        prefix = "Hoy"
    elif delta_days == 1:
        prefix = "Manana"
    else:
        prefix = f"{delta_days}d"
    return f"{prefix} · {local_due.strftime('%H:%M')}"


def _humanize_task_preset_category(value) -> str:
    normalized = str(value or "").strip().replace("_", " ")
    return normalized.title() if normalized else "General"
