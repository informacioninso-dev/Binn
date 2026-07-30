from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Mapping

from django_tenants.utils import get_public_schema_name, schema_context

from tenants.observability import record_tenant_event


def record_crm_audit_event(
    *,
    tenant,
    actor=None,
    action: str,
    object_type: str,
    title: str,
    message: str = "",
    metadata: Mapping[str, Any] | None = None,
    code: str = "",
):
    payload = {
        "scope": "crm",
        "object_type": object_type,
        "action": action,
        **_normalize_metadata_dict(metadata or {}),
    }
    with schema_context(get_public_schema_name()):
        return record_tenant_event(
            tenant=tenant,
            actor=actor,
            title=title[:160],
            message=message,
            code=code or f"crm_{object_type}_{action}",
            metadata=payload,
        )


def _normalize_metadata_dict(metadata: Mapping[str, Any]) -> dict[str, Any]:
    normalized = {}
    for key, value in metadata.items():
        if key is None:
            continue
        normalized[str(key)] = _normalize_metadata_value(value)
    return normalized


def _normalize_metadata_value(value: Any):
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Mapping):
        return _normalize_metadata_dict(value)
    if isinstance(value, set):
        return [_normalize_metadata_value(item) for item in sorted(value, key=str)]
    if isinstance(value, (list, tuple)):
        return [_normalize_metadata_value(item) for item in value]
    return str(value)
