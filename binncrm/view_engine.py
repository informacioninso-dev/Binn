from __future__ import annotations

from datetime import timedelta

from django.db.models import Q
from django.utils import timezone

from .object_engine import get_object_views


def get_saved_views(*, object_key: str, tenant=None) -> list[dict]:
    return list(get_object_views(object_key=object_key, tenant=tenant))


def resolve_saved_view(*, object_key: str, tenant=None, view_key: str = "") -> dict:
    views = get_saved_views(object_key=object_key, tenant=tenant)
    if view_key:
        normalized_view_key = str(view_key).strip().lower()
        matched = next((view for view in views if view["key"] == normalized_view_key), None)
        if matched is not None:
            return matched
    default_view = next((view for view in views if view.get("is_default")), None)
    return default_view or (views[0] if views else {})


def apply_entity_saved_view(queryset, *, view: dict):
    filters = dict((view or {}).get("config", {})).get("filters", {})
    if filters.get("missing_contact"):
        queryset = queryset.filter(
            (Q(phone__isnull=True) | Q(phone=""))
            & (Q(email__isnull=True) | Q(email=""))
        )

    updated_within_days = _as_positive_int(filters.get("updated_within_days"))
    if updated_within_days:
        queryset = queryset.filter(updated_at__gte=timezone.now() - timedelta(days=updated_within_days))

    return _apply_ordering(queryset, config=(view or {}).get("config", {}), fallback=("full_name",))


def apply_deal_saved_view(queryset, *, view: dict):
    config = dict((view or {}).get("config", {}))
    filters = config.get("filters", {})
    today = timezone.localdate()
    now = timezone.now()

    expected_close_within_days = _as_positive_int(filters.get("expected_close_within_days"))
    if expected_close_within_days:
        queryset = queryset.filter(
            expected_close_on__isnull=False,
            expected_close_on__gte=today,
            expected_close_on__lte=today + timedelta(days=expected_close_within_days),
        )

    stale_days = _as_positive_int(filters.get("stale_days"))
    if stale_days:
        queryset = queryset.filter(updated_at__lt=now - timedelta(days=stale_days))

    return _apply_ordering(queryset, config=config, fallback=("sort_order", "-updated_at"))


def _apply_ordering(queryset, *, config: dict, fallback: tuple[str, ...]):
    raw_ordering = str(config.get("ordering", "")).strip()
    ordering = [part.strip() for part in raw_ordering.split(",") if part.strip()]
    if not ordering:
        ordering = list(fallback)
    return queryset.order_by(*ordering)


def _as_positive_int(value) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return 0
    return max(parsed, 0)
