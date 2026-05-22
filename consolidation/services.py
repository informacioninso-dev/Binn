from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from django.conf import settings
from django.utils import timezone
from django_tenants.utils import schema_context

from governance.models import CorporateGroup, GroupMembership
from governance.services import (
    record_governance_event,
    resolve_group_tenant_detail_access,
)
from tenants.workspace_packs import build_workspace_pack

from .models import ConsolidationRun, GroupMetricSnapshot, TenantMetricSnapshot


MONEY_QUANTIZER = Decimal("0.01")
SNAPSHOT_STALE_AFTER = timedelta(minutes=15)
VISIBLE_METRIC_KEYS = (
    "entity_count",
    "open_deals_count",
    "won_deals_count",
    "lost_deals_count",
    "pending_activities_count",
    "overdue_activities_count",
    "documents_count",
    "expiring_documents_count",
    "open_proposals_count",
    "open_collections_count",
    "overdue_collections_count",
)


@dataclass(frozen=True, slots=True)
class GroupDashboardAccess:
    allowed: bool
    membership: GroupMembership | None = None
    reason: str = ""


def get_group_dashboard_access(*, group, user) -> GroupDashboardAccess:
    if user is None or not getattr(user, "is_authenticated", False):
        return GroupDashboardAccess(allowed=False, reason="anonymous")
    if getattr(user, "is_superuser", False):
        return GroupDashboardAccess(allowed=True, reason="superuser")

    membership = (
        GroupMembership.objects.select_related("group")
        .filter(group=group, user=user, is_active=True, group__status=CorporateGroup.STATUS_ACTIVE)
        .first()
    )
    if membership is None or not membership.can_view_group_dashboard():
        return GroupDashboardAccess(allowed=False, reason="missing_group_membership")
    return GroupDashboardAccess(allowed=True, membership=membership, reason="group_membership")


def ensure_group_snapshot_fresh(*, group, actor=None, trigger: str = "dashboard", force: bool = False):
    snapshot = GroupMetricSnapshot.objects.filter(group=group).first()
    if not force and snapshot is not None and snapshot.last_synced_at >= timezone.now() - SNAPSHOT_STALE_AFTER:
        return snapshot
    if force or snapshot is None:
        return sync_group_snapshot(group=group, actor=actor, trigger=trigger)

    if _background_jobs_ready():
        from .tasks import sync_group_snapshot_task

        sync_group_snapshot_task.delay(group.pk, trigger=f"{trigger}:async")
    return snapshot


def sync_group_snapshot(*, group, actor=None, trigger: str = "manual"):
    run = ConsolidationRun.objects.create(
        target_type=ConsolidationRun.TARGET_GROUP,
        group=group,
        actor=actor,
        trigger=trigger,
        status=ConsolidationRun.STATUS_RUNNING,
    )
    try:
        snapshot = _sync_group_snapshot(group=group)
    except Exception as exc:
        run.status = ConsolidationRun.STATUS_FAILED
        run.error_message = str(exc)
        run.finished_at = timezone.now()
        run.save(update_fields=["status", "error_message", "finished_at"])
        raise

    run.status = ConsolidationRun.STATUS_SUCCEEDED
    run.snapshots_count = snapshot.included_tenants_count
    run.finished_at = timezone.now()
    run.metadata = {
        "group_mode": group.consolidation_mode,
        "blocked_tenants": str(snapshot.blocked_tenants_count),
        "full_detail_tenants": str(snapshot.full_detail_tenants_count),
        "aggregate_only_tenants": str(snapshot.aggregate_only_tenants_count),
    }
    run.save(update_fields=["status", "snapshots_count", "finished_at", "metadata"])
    record_governance_event(
        event_type="group_snapshot_synced",
        message=f"Se sincronizo el consolidado del grupo '{group.name}'.",
        actor=actor,
        group=group,
        metadata={
            "included_tenants_count": str(snapshot.included_tenants_count),
            "blocked_tenants_count": str(snapshot.blocked_tenants_count),
        },
    )
    return snapshot


def sync_tenant_snapshot(*, tenant, actor=None, trigger: str = "manual"):
    run = ConsolidationRun.objects.create(
        target_type=ConsolidationRun.TARGET_TENANT,
        tenant=tenant,
        actor=actor,
        trigger=trigger,
        status=ConsolidationRun.STATUS_RUNNING,
    )
    try:
        snapshot = _upsert_tenant_snapshot(tenant=tenant)
    except Exception as exc:
        run.status = ConsolidationRun.STATUS_FAILED
        run.error_message = str(exc)
        run.finished_at = timezone.now()
        run.save(update_fields=["status", "error_message", "finished_at"])
        raise

    run.status = ConsolidationRun.STATUS_SUCCEEDED
    run.snapshots_count = 1
    run.finished_at = timezone.now()
    run.metadata = {"tenant_schema": tenant.schema_name}
    run.save(update_fields=["status", "snapshots_count", "finished_at", "metadata"])
    return snapshot


def build_group_dashboard_rows(*, group, user=None):
    rows = []
    membership = None
    if user is not None and getattr(user, "is_authenticated", False) and not getattr(user, "is_superuser", False):
        membership = (
            GroupMembership.objects.select_related("group")
            .filter(group=group, user=user, is_active=True, group__status=CorporateGroup.STATUS_ACTIVE)
            .first()
        )

    links = (
        group.tenant_links.select_related("tenant", "tenant__consolidation_snapshot")
        .filter(tenant__is_active=True)
        .order_by("-is_primary", "tenant__name")
    )
    for link in links:
        snapshot = getattr(link.tenant, "consolidation_snapshot", None)
        rows.append(build_group_dashboard_row(link=link, snapshot=snapshot, user=user, membership=membership))
    return rows


def build_group_dashboard_row(*, link, snapshot, user=None, membership=None):
    mode = link.effective_mode
    tenant_config = getattr(link.tenant, "tenant_config", None)
    tenant_labels = getattr(tenant_config, "labels", {})
    tenant_feature_flags = getattr(tenant_config, "feature_flags", {})
    workspace_pack = build_workspace_pack(
        profile=getattr(tenant_config, "profile", ""),
        labels=tenant_labels,
        feature_flags=tenant_feature_flags,
    )
    metrics_visible = mode in {CorporateGroup.MODE_AGGREGATE_ONLY, CorporateGroup.MODE_FULL}
    detail_allowed = mode == CorporateGroup.MODE_FULL
    detail_decision = None

    if user is not None and getattr(user, "is_authenticated", False) and mode == CorporateGroup.MODE_FULL:
        detail_decision = resolve_group_tenant_detail_access(
            group=link.group,
            link=link,
            user=user,
            membership=membership,
        )
        detail_allowed = detail_decision.allowed

    metric_values = {
        "entity_count": getattr(snapshot, "entity_count", 0) if metrics_visible and snapshot is not None else None,
        "open_deals_count": getattr(snapshot, "open_deals_count", 0) if metrics_visible and snapshot is not None else None,
        "won_deals_count": getattr(snapshot, "won_deals_count", 0) if metrics_visible and snapshot is not None else None,
        "lost_deals_count": getattr(snapshot, "lost_deals_count", 0) if metrics_visible and snapshot is not None else None,
        "pending_activities_count": getattr(snapshot, "pending_activities_count", 0) if metrics_visible and snapshot is not None else None,
        "overdue_activities_count": getattr(snapshot, "overdue_activities_count", 0) if metrics_visible and snapshot is not None else None,
        "expiring_documents_count": getattr(snapshot, "expiring_documents_count", 0) if metrics_visible and snapshot is not None else None,
        "open_proposals_count": getattr(snapshot, "open_proposals_count", 0) if metrics_visible and snapshot is not None else None,
        "open_collections_count": getattr(snapshot, "open_collections_count", 0) if metrics_visible and snapshot is not None else None,
        "overdue_collections_count": getattr(snapshot, "overdue_collections_count", 0) if metrics_visible and snapshot is not None else None,
    }
    return {
        "tenant": link.tenant,
        "profile_label": workspace_pack["profile_label"],
        "pack_title": workspace_pack["title"],
        "effective_mode": mode,
        "mode_label": _mode_label(mode),
        "mode_tone": _mode_tone(mode),
        "metrics_visible": metrics_visible,
        "detail_allowed": detail_allowed,
        "tenant_allows_consolidation": getattr(link.tenant, "allow_consolidation", True),
        "detail_reason": getattr(detail_decision, "reason", ""),
        "entity_count": metric_values["entity_count"],
        "open_deals_count": metric_values["open_deals_count"],
        "won_deals_count": metric_values["won_deals_count"],
        "lost_deals_count": metric_values["lost_deals_count"],
        "pending_activities_count": metric_values["pending_activities_count"],
        "overdue_activities_count": metric_values["overdue_activities_count"],
        "expiring_documents_count": metric_values["expiring_documents_count"],
        "open_proposals_count": metric_values["open_proposals_count"],
        "open_collections_count": metric_values["open_collections_count"],
        "overdue_collections_count": metric_values["overdue_collections_count"],
        "open_deal_amounts_display": _format_amounts_for_display(getattr(snapshot, "open_deal_amounts", {})) if metrics_visible and snapshot is not None else "",
        "outstanding_balance_amounts_display": _format_amounts_for_display(getattr(snapshot, "outstanding_balance_amounts", {})) if metrics_visible and snapshot is not None else "",
        "last_synced_at": getattr(snapshot, "last_synced_at", None),
        "status_copy": _status_copy(link=link, mode=mode, detail_decision=detail_decision),
        "risk_score": calculate_tenant_risk_score(
            {
                "overdue_activities_count": metric_values["overdue_activities_count"],
                "overdue_collections_count": metric_values["overdue_collections_count"],
                "expiring_documents_count": metric_values["expiring_documents_count"],
                "open_deals_count": metric_values["open_deals_count"],
            }
        )
        if metrics_visible
        else 0,
    }


def calculate_tenant_risk_score(row: dict) -> int:
    return (
        int(row.get("overdue_activities_count") or 0) * 4
        + int(row.get("overdue_collections_count") or 0) * 5
        + int(row.get("expiring_documents_count") or 0) * 3
        + int(row.get("open_deals_count") or 0)
    )


def build_group_report_sections(*, tenant_rows: list[dict]) -> dict:
    visible_rows = [row for row in tenant_rows if row.get("metrics_visible")]
    visible_rows = sorted(visible_rows, key=lambda row: row["tenant"].name)

    return {
        "leaderboards": [
            {
                "title": "Empresas con mayor base visible",
                "metric_label": "Contactos visibles",
                "rows": _top_rows(visible_rows, metric_key="entity_count"),
            },
            {
                "title": "Empresas con mayor pipeline abierto",
                "metric_label": "Deals abiertos",
                "rows": _top_rows(visible_rows, metric_key="open_deals_count"),
            },
            {
                "title": "Empresas con mayor carga de cobranza",
                "metric_label": "Cobros abiertos",
                "rows": _top_rows(visible_rows, metric_key="open_collections_count"),
            },
        ],
        "risk_rows": sorted(
            (
                {
                    "tenant_name": row["tenant"].name,
                    "profile_label": row.get("profile_label", ""),
                    "risk_score": row.get("risk_score", 0),
                    "overdue_activities_count": row.get("overdue_activities_count", 0),
                    "overdue_collections_count": row.get("overdue_collections_count", 0),
                    "expiring_documents_count": row.get("expiring_documents_count", 0),
                    "detail_allowed": row.get("detail_allowed", False),
                    "tenant": row["tenant"],
                }
                for row in visible_rows
                if row.get("risk_score", 0) > 0
            ),
            key=lambda item: (-item["risk_score"], item["tenant_name"]),
        )[:6],
        "mode_summary": _build_mode_summary(tenant_rows),
    }


def _sync_group_snapshot(*, group):
    totals = empty_metric_bucket()
    included_tenants = 0
    full_detail_tenants = 0
    aggregate_only_tenants = 0
    blocked_tenants = 0

    links = list(
        group.tenant_links.select_related("tenant")
        .filter(is_active=True, tenant__is_active=True)
        .order_by("-is_primary", "tenant__name")
    )
    for link in links:
        mode = link.effective_mode
        if mode == CorporateGroup.MODE_BLOCKED:
            blocked_tenants += 1
            continue

        tenant_snapshot = _upsert_tenant_snapshot(tenant=link.tenant)
        merge_metric_buckets(totals, tenant_snapshot.metrics)
        included_tenants += 1
        if mode == CorporateGroup.MODE_FULL:
            full_detail_tenants += 1
        else:
            aggregate_only_tenants += 1

    snapshot_date = timezone.localdate()
    snapshot, _ = GroupMetricSnapshot.objects.update_or_create(
        group=group,
        defaults={
            "snapshot_date": snapshot_date,
            "included_tenants_count": included_tenants,
            "full_detail_tenants_count": full_detail_tenants,
            "aggregate_only_tenants_count": aggregate_only_tenants,
            "blocked_tenants_count": blocked_tenants,
            **_snapshot_defaults_from_bucket(totals),
        },
    )
    return snapshot


def _upsert_tenant_snapshot(*, tenant):
    bucket = compute_tenant_metrics(tenant=tenant)
    snapshot, _ = TenantMetricSnapshot.objects.update_or_create(
        tenant=tenant,
        defaults={
            "snapshot_date": timezone.localdate(),
            **_snapshot_defaults_from_bucket(bucket),
        },
    )
    return snapshot


def compute_tenant_metrics(*, tenant):
    bucket = empty_metric_bucket()
    now = timezone.now()
    today = timezone.localdate()

    with schema_context(tenant.schema_name):
        from binncrm.models import Activity, CollectionRecord, Deal, Document, Entity, Proposal

        bucket["entity_count"] = Entity.objects.filter(is_active=True).count()

        open_deals = Deal.objects.filter(is_active=True, status=Deal.STATUS_OPEN)
        bucket["open_deals_count"] = open_deals.count()
        bucket["won_deals_count"] = Deal.objects.filter(is_active=True, status=Deal.STATUS_WON).count()
        bucket["lost_deals_count"] = Deal.objects.filter(is_active=True, status=Deal.STATUS_LOST).count()
        for currency, amount in open_deals.values_list("currency", "amount"):
            add_amount(bucket["open_deal_amounts"], currency, amount)

        pending_activities = Activity.objects.filter(completed_at__isnull=True)
        bucket["pending_activities_count"] = pending_activities.count()
        bucket["overdue_activities_count"] = pending_activities.filter(due_at__isnull=False, due_at__lt=now).count()

        active_documents = Document.objects.filter(is_active=True)
        bucket["documents_count"] = active_documents.count()
        bucket["expiring_documents_count"] = active_documents.filter(
            expires_on__isnull=False,
            expires_on__lte=today + timedelta(days=30),
        ).count()

        open_proposals = Proposal.objects.filter(
            is_active=True,
            status__in=[Proposal.STATUS_DRAFT, Proposal.STATUS_SENT],
        )
        bucket["open_proposals_count"] = open_proposals.count()

        open_collections = CollectionRecord.objects.filter(is_active=True).exclude(status=CollectionRecord.STATUS_PAID)
        bucket["open_collections_count"] = open_collections.count()
        bucket["overdue_collections_count"] = open_collections.filter(due_on__lt=today).count()
        for currency, amount_due, amount_paid in open_collections.values_list("currency", "amount_due", "amount_paid"):
            balance = max((amount_due or Decimal("0")) - (amount_paid or Decimal("0")), Decimal("0"))
            add_amount(bucket["outstanding_balance_amounts"], currency, balance)

    bucket["open_deal_amounts"] = serialize_amounts(bucket["open_deal_amounts"])
    bucket["outstanding_balance_amounts"] = serialize_amounts(bucket["outstanding_balance_amounts"])
    return bucket


def empty_metric_bucket():
    return {
        "entity_count": 0,
        "open_deals_count": 0,
        "won_deals_count": 0,
        "lost_deals_count": 0,
        "pending_activities_count": 0,
        "overdue_activities_count": 0,
        "documents_count": 0,
        "expiring_documents_count": 0,
        "open_proposals_count": 0,
        "open_collections_count": 0,
        "overdue_collections_count": 0,
        "open_deal_amounts": {},
        "outstanding_balance_amounts": {},
    }


def merge_metric_buckets(target: dict, incoming: dict):
    for key in VISIBLE_METRIC_KEYS:
        target[key] = int(target.get(key, 0)) + int(incoming.get(key, 0))

    for key in ("open_deal_amounts", "outstanding_balance_amounts"):
        target_amounts = deserialize_amounts(target.get(key, {}))
        incoming_amounts = deserialize_amounts(incoming.get(key, {}))
        for currency, amount in incoming_amounts.items():
            target_amounts[currency] = target_amounts.get(currency, Decimal("0")) + amount
        target[key] = serialize_amounts(target_amounts)
    return target


def add_amount(target: dict[str, Decimal], currency: str, amount) -> None:
    if amount in (None, ""):
        return
    normalized_currency = (currency or "USD").strip().upper()
    decimal_amount = Decimal(str(amount))
    target[normalized_currency] = target.get(normalized_currency, Decimal("0")) + decimal_amount


def deserialize_amounts(raw: dict) -> dict[str, Decimal]:
    amounts = {}
    for currency, amount in (raw or {}).items():
        amounts[str(currency).upper()] = Decimal(str(amount))
    return amounts


def serialize_amounts(raw: dict[str, Decimal]) -> dict[str, str]:
    return {
        currency: str(amount.quantize(MONEY_QUANTIZER, rounding=ROUND_HALF_UP))
        for currency, amount in sorted(raw.items())
        if amount is not None
    }


def _snapshot_defaults_from_bucket(bucket: dict):
    return {
        "entity_count": bucket["entity_count"],
        "open_deals_count": bucket["open_deals_count"],
        "won_deals_count": bucket["won_deals_count"],
        "lost_deals_count": bucket["lost_deals_count"],
        "pending_activities_count": bucket["pending_activities_count"],
        "overdue_activities_count": bucket["overdue_activities_count"],
        "documents_count": bucket["documents_count"],
        "expiring_documents_count": bucket["expiring_documents_count"],
        "open_proposals_count": bucket["open_proposals_count"],
        "open_collections_count": bucket["open_collections_count"],
        "overdue_collections_count": bucket["overdue_collections_count"],
        "open_deal_amounts": bucket["open_deal_amounts"],
        "outstanding_balance_amounts": bucket["outstanding_balance_amounts"],
        "metrics": bucket,
    }


def _mode_label(mode: str) -> str:
    mapping = {
        CorporateGroup.MODE_BLOCKED: "Bloqueado",
        CorporateGroup.MODE_AGGREGATE_ONLY: "Solo agregados",
        CorporateGroup.MODE_FULL: "Detalle total",
    }
    return mapping.get(mode, mode)


def _mode_tone(mode: str) -> str:
    mapping = {
        CorporateGroup.MODE_BLOCKED: "bg-amber-50 text-amber-700",
        CorporateGroup.MODE_AGGREGATE_ONLY: "bg-sky-50 text-sky-700",
        CorporateGroup.MODE_FULL: "bg-emerald-50 text-emerald-700",
    }
    return mapping.get(mode, "bg-gray-100 text-gray-700")


def _status_copy(*, link, mode: str, detail_decision=None) -> str:
    if not getattr(link.tenant, "allow_consolidation", True):
        return "Binn bloqueo la consolidacion de esta empresa desde el nivel del tenant."
    if mode == CorporateGroup.MODE_BLOCKED:
        return "La empresa pertenece al holding, pero no comparte visibilidad interempresa."
    if mode == CorporateGroup.MODE_AGGREGATE_ONLY:
        return "Solo se muestran KPIs agregados. No existe drill-down al detalle operativo."
    if detail_decision is not None and detail_decision.reason == "missing_group_tenant_access":
        return "Esta empresa permite detalle, pero tu usuario del holding todavia no tiene acceso asignado."
    if detail_decision is not None and detail_decision.reason == "tenant_role_denied":
        return "Tu usuario del holding entra a esta empresa, pero su rol actual no alcanza para esta accion."
    if detail_decision is not None and detail_decision.reason == "group_admin":
        return "El administrador del holding puede abrir esta empresa por control jerarquico del grupo."
    return "El holding puede abrir esta empresa y operar con detalle completo."


def _format_amounts_for_display(raw_amounts: dict) -> str:
    if not raw_amounts:
        return ""
    parts = [f"{currency} {amount}" for currency, amount in sorted((raw_amounts or {}).items())]
    return " | ".join(parts)


def _top_rows(rows: list[dict], *, metric_key: str, limit: int = 5) -> list[dict]:
    return [
        {
            "tenant_name": row["tenant"].name,
            "profile_label": row.get("profile_label", ""),
            "metric_value": int(row.get(metric_key) or 0),
            "detail_allowed": row.get("detail_allowed", False),
            "tenant": row["tenant"],
        }
        for row in sorted(rows, key=lambda item: (-int(item.get(metric_key) or 0), item["tenant"].name))[:limit]
    ]


def _build_mode_summary(tenant_rows: list[dict]) -> list[dict]:
    total = len(tenant_rows)
    buckets = {
        CorporateGroup.MODE_FULL: sum(1 for row in tenant_rows if row.get("effective_mode") == CorporateGroup.MODE_FULL),
        CorporateGroup.MODE_AGGREGATE_ONLY: sum(
            1 for row in tenant_rows if row.get("effective_mode") == CorporateGroup.MODE_AGGREGATE_ONLY
        ),
        CorporateGroup.MODE_BLOCKED: sum(1 for row in tenant_rows if row.get("effective_mode") == CorporateGroup.MODE_BLOCKED),
    }
    return [
        {
            "label": "Detalle total",
            "value": buckets[CorporateGroup.MODE_FULL],
            "share": _format_share(buckets[CorporateGroup.MODE_FULL], total),
            "tone": "bg-emerald-50 text-emerald-700",
        },
        {
            "label": "Solo agregados",
            "value": buckets[CorporateGroup.MODE_AGGREGATE_ONLY],
            "share": _format_share(buckets[CorporateGroup.MODE_AGGREGATE_ONLY], total),
            "tone": "bg-sky-50 text-sky-700",
        },
        {
            "label": "Bloqueadas",
            "value": buckets[CorporateGroup.MODE_BLOCKED],
            "share": _format_share(buckets[CorporateGroup.MODE_BLOCKED], total),
            "tone": "bg-amber-50 text-amber-700",
        },
    ]


def _format_share(value: int, total: int) -> str:
    if total <= 0:
        return "0%"
    return f"{round((value / total) * 100):.0f}%"


def _background_jobs_ready() -> bool:
    return bool(
        getattr(settings, "ENABLE_BACKGROUND_JOBS", False)
        and getattr(settings, "CELERY_AVAILABLE", False)
        and getattr(settings, "CELERY_BROKER_URL", "")
    )
