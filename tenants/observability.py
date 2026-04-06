import logging
from dataclasses import dataclass
from typing import Iterable

from django.db import connection

from .models import Client, Domain, TenantMembership, TenantOperationalEvent
from .plans import PlanDefinition, get_plan_definition


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TenantAlert:
    code: str
    severity: str
    title: str
    message: str


@dataclass(frozen=True)
class TenantDiagnostics:
    tenant: Client
    status: str
    alerts: tuple[TenantAlert, ...]
    plan_definition: PlanDefinition
    domain_count: int
    primary_domain: str
    active_members: int
    active_admins: int


def build_tenant_diagnostics(
    tenant: Client,
    *,
    domains: Iterable[Domain] | None = None,
    memberships: Iterable[TenantMembership] | None = None,
) -> TenantDiagnostics:
    domain_list = list(domains if domains is not None else tenant.domains.all())
    membership_list = list(memberships if memberships is not None else tenant.memberships.select_related("user"))
    active_memberships = [membership for membership in membership_list if membership.is_active]
    active_admins = [membership for membership in active_memberships if membership.is_admin]
    primary_domain = next((domain.domain for domain in domain_list if domain.is_primary), "")
    plan_definition = get_plan_definition(tenant.plan)

    alerts: list[TenantAlert] = []
    if not tenant.is_active:
        alerts.append(
            TenantAlert(
                code="tenant_inactive",
                severity=TenantOperationalEvent.SEVERITY_WARNING,
                title="Clinica desactivada",
                message="La clinica no acepta accesos de usuarios normales mientras este inactiva.",
            )
        )
    if not domain_list:
        alerts.append(
            TenantAlert(
                code="missing_domain",
                severity=TenantOperationalEvent.SEVERITY_ERROR,
                title="Sin dominio configurado",
                message="La clinica no tiene ningun dominio disponible para entrar.",
            )
        )
    elif not primary_domain:
        alerts.append(
            TenantAlert(
                code="missing_primary_domain",
                severity=TenantOperationalEvent.SEVERITY_WARNING,
                title="Sin dominio primario",
                message="La clinica tiene dominios, pero ninguno esta marcado como primario.",
            )
        )
        primary_domain = domain_list[0].domain

    if not active_admins:
        alerts.append(
            TenantAlert(
                code="missing_active_admin",
                severity=TenantOperationalEvent.SEVERITY_ERROR,
                title="Sin admin activo en la clinica",
                message="No hay ningun miembro activo con rol administrador para esta clinica.",
            )
        )

    if not active_memberships:
        alerts.append(
            TenantAlert(
                code="missing_active_members",
                severity=TenantOperationalEvent.SEVERITY_WARNING,
                title="Sin miembros activos",
                message="La clinica no tiene usuarios activos asignados en este momento.",
            )
        )

    if plan_definition.max_users is not None and len(active_memberships) > plan_definition.max_users:
        alerts.append(
            TenantAlert(
                code="plan_user_limit_exceeded",
                severity=TenantOperationalEvent.SEVERITY_WARNING,
                title="Limite de usuarios superado",
                message=(
                    f"El plan {plan_definition.label} soporta {plan_definition.max_users} usuarios activos "
                    f"y hoy la clinica tiene {len(active_memberships)}."
                ),
            )
        )

    if plan_definition.max_admins is not None and len(active_admins) > plan_definition.max_admins:
        alerts.append(
            TenantAlert(
                code="plan_admin_limit_exceeded",
                severity=TenantOperationalEvent.SEVERITY_WARNING,
                title="Limite de administradores superado",
                message=(
                    f"El plan {plan_definition.label} soporta {plan_definition.max_admins} administradores activos "
                    f"y hoy la clinica tiene {len(active_admins)}."
                ),
            )
        )

    if any(alert.severity == TenantOperationalEvent.SEVERITY_ERROR for alert in alerts):
        status = TenantOperationalEvent.SEVERITY_ERROR
    elif alerts:
        status = TenantOperationalEvent.SEVERITY_WARNING
    else:
        status = "ok"

    return TenantDiagnostics(
        tenant=tenant,
        status=status,
        alerts=tuple(alerts),
        plan_definition=plan_definition,
        domain_count=len(domain_list),
        primary_domain=primary_domain,
        active_members=len(active_memberships),
        active_admins=len(active_admins),
    )


def diagnostics_to_payload(diagnostics: TenantDiagnostics) -> dict:
    return {
        "status": diagnostics.status,
        "tenant": {
            "id": diagnostics.tenant.pk,
            "name": diagnostics.tenant.name,
            "schema_name": diagnostics.tenant.schema_name,
            "plan": diagnostics.tenant.plan,
            "is_active": diagnostics.tenant.is_active,
        },
        "plan": {
            "slug": diagnostics.plan_definition.slug,
            "label": diagnostics.plan_definition.label,
            "support_tier": diagnostics.plan_definition.support_tier,
            "max_users": diagnostics.plan_definition.max_users,
            "max_admins": diagnostics.plan_definition.max_admins,
            "storage_gb": diagnostics.plan_definition.storage_gb,
            "capabilities": sorted(diagnostics.plan_definition.capabilities),
            "features": list(diagnostics.plan_definition.features),
        },
        "operational": {
            "domain_count": diagnostics.domain_count,
            "primary_domain": diagnostics.primary_domain,
            "active_members": diagnostics.active_members,
            "active_admins": diagnostics.active_admins,
        },
        "alerts": [
            {
                "code": alert.code,
                "severity": alert.severity,
                "title": alert.title,
                "message": alert.message,
            }
            for alert in diagnostics.alerts
        ],
    }


def build_system_health_payload(*, tenant: Client | None = None) -> tuple[dict, int]:
    db_ok = True
    db_error = ""
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
    except Exception as exc:
        db_ok = False
        db_error = str(exc)

    payload: dict = {
        "service": "onne",
        "database": {"status": "ok" if db_ok else "error"},
    }
    if db_error:
        payload["database"]["error"] = db_error

    if tenant is not None:
        diagnostics = build_tenant_diagnostics(tenant)
        payload["tenant"] = {
            "schema_name": diagnostics.tenant.schema_name,
            "is_active": diagnostics.tenant.is_active,
        }
        payload["tenant_status"] = diagnostics.status
        payload["alerts_count"] = len(diagnostics.alerts)
        status_code = 503 if (not db_ok or diagnostics.status == TenantOperationalEvent.SEVERITY_ERROR) else 200
        payload["status"] = "degraded" if diagnostics.status == TenantOperationalEvent.SEVERITY_WARNING else diagnostics.status
        if payload["status"] == "ok" and not db_ok:
            payload["status"] = "error"
        return payload, status_code

    payload["status"] = "ok" if db_ok else "error"
    return payload, 200 if db_ok else 503


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
