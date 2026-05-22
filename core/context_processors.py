from __future__ import annotations


def collab_badge(request):
    """Inject collab_enabled and collab_unread_total into every template context."""
    user = getattr(request, "user", None)
    tenant = getattr(request, "tenant", None)
    empty = {"collab_enabled": False, "collab_unread_total": 0}
    if (
        not getattr(user, "is_authenticated", False)
        or tenant is None
        or getattr(tenant, "schema_name", "") == "public"
        or not tenant.has_capability("collab")
    ):
        return empty
    try:
        from collab.services import get_unread_notification_count
        return {
            "collab_enabled": True,
            "collab_unread_total": get_unread_notification_count(user=user),
        }
    except Exception:
        return empty
