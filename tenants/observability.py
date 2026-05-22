import logging

from .models import Client, TenantOperationalEvent


logger = logging.getLogger(__name__)


def record_tenant_event(
    *,
    tenant: Client,
    title: str,
    message: str = "",
    actor=None,
    kind: str = TenantOperationalEvent.KIND_AUDIT,
    severity: str = TenantOperationalEvent.SEVERITY_INFO,
    status: str = TenantOperationalEvent.STATUS_RECORDED,
    code: str = "",
    metadata: dict | None = None,
) -> TenantOperationalEvent:
    event = TenantOperationalEvent.objects.create(
        tenant=tenant,
        actor=actor,
        kind=kind,
        severity=severity,
        status=status,
        code=code,
        title=title,
        message=message,
        metadata=metadata or {},
    )

    log_method = {
        TenantOperationalEvent.SEVERITY_INFO: logger.info,
        TenantOperationalEvent.SEVERITY_WARNING: logger.warning,
        TenantOperationalEvent.SEVERITY_ERROR: logger.error,
    }.get(severity, logger.info)
    log_method(
        "%s | %s",
        title,
        message or "sin detalle adicional",
        extra={
            "tenant_schema": tenant.schema_name,
            "actor_id": getattr(actor, "pk", "-") or "-",
        },
    )
    return event
