from __future__ import annotations

from core.tasking import shared_task
from governance.models import CorporateGroup
from tenants.models import Client

from .services import sync_group_snapshot, sync_tenant_snapshot


@shared_task(name="consolidation.sync_group_snapshot")
def sync_group_snapshot_task(group_id: int, *, trigger: str = "celery"):
    group = CorporateGroup.objects.filter(pk=group_id).first()
    if group is None:
        return {"status": "missing_group", "group_id": group_id}

    snapshot = sync_group_snapshot(group=group, trigger=trigger)
    return {
        "status": "ok",
        "group_id": group.pk,
        "included_tenants_count": snapshot.included_tenants_count,
        "blocked_tenants_count": snapshot.blocked_tenants_count,
        "snapshot_date": str(snapshot.snapshot_date),
    }


@shared_task(name="consolidation.sync_tenant_snapshot")
def sync_tenant_snapshot_task(tenant_id: int, *, trigger: str = "celery"):
    tenant = Client.objects.filter(pk=tenant_id).first()
    if tenant is None:
        return {"status": "missing_tenant", "tenant_id": tenant_id}

    snapshot = sync_tenant_snapshot(tenant=tenant, trigger=trigger)
    return {
        "status": "ok",
        "tenant_id": tenant.pk,
        "tenant_schema": tenant.schema_name,
        "snapshot_date": str(snapshot.snapshot_date),
    }


@shared_task(name="consolidation.sync_all_active_group_snapshots")
def sync_all_active_group_snapshots_task(*, trigger: str = "celery"):
    processed = []
    for group in CorporateGroup.objects.filter(status=CorporateGroup.STATUS_ACTIVE).order_by("name"):
        snapshot = sync_group_snapshot(group=group, trigger=trigger)
        processed.append(
            {
                "group_id": group.pk,
                "group_name": group.name,
                "included_tenants_count": snapshot.included_tenants_count,
                "snapshot_date": str(snapshot.snapshot_date),
            }
        )
    return {"status": "ok", "processed": processed, "count": len(processed)}
