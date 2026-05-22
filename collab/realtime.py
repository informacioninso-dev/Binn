from __future__ import annotations

from typing import Any

try:
    from asgiref.sync import async_to_sync
    from channels.layers import get_channel_layer
except ImportError:  # pragma: no cover - graceful fallback until channels is installed
    async_to_sync = None
    get_channel_layer = None


def build_tenant_stream_group(schema_name: str) -> str:
    normalized = "".join(ch for ch in str(schema_name or "").lower() if ch.isalnum() or ch in {"-", "_", "."})
    normalized = normalized[:72] or "unknown"
    return f"collab.tenant.{normalized}"


def broadcast_tenant_collab_event(
    *,
    tenant,
    conversation_id: int,
    event_name: str,
    author_id: int | None = None,
    message_id: int | None = None,
    metadata: dict[str, Any] | None = None,
) -> bool:
    if get_channel_layer is None or async_to_sync is None:
        return False

    channel_layer = get_channel_layer()
    if channel_layer is None:
        return False

    async_to_sync(channel_layer.group_send)(
        build_tenant_stream_group(getattr(tenant, "schema_name", "")),
        {
            "type": "collab.event",
            "event_name": event_name,
            "conversation_id": int(conversation_id),
            "author_id": int(author_id) if author_id else None,
            "message_id": int(message_id) if message_id else None,
            "metadata": metadata or {},
        },
    )
    return True
