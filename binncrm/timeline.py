from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Iterable

from django.utils import timezone

from .document_blueprints import get_document_type_label
from .models import Activity, CollectionRecord, Deal, Document, Entity, ObjectRecord, Proposal, TimelineEvent


def build_entity_timeline(
    entity: Entity,
    *,
    include_deals: bool = True,
    include_proposals: bool = True,
    include_collections: bool = True,
    include_activities: bool = True,
    include_documents: bool = True,
) -> list[dict]:
    allowed_categories = {TimelineEvent.CATEGORY_ENTITY}
    if include_deals:
        allowed_categories.add(TimelineEvent.CATEGORY_DEAL)
    if include_proposals:
        allowed_categories.add(TimelineEvent.CATEGORY_PROPOSAL)
    if include_collections:
        allowed_categories.add(TimelineEvent.CATEGORY_COLLECTION)
    if include_activities:
        allowed_categories.add(TimelineEvent.CATEGORY_ACTIVITY)
    if include_documents:
        allowed_categories.add(TimelineEvent.CATEGORY_DOCUMENT)

    event_source = getattr(entity, "timeline_events", None)
    if event_source is None:
        return []

    events = _resolve_event_source(event_source, allowed_categories=allowed_categories)
    return [_serialize_timeline_event(event) for event in events[:18]]


def record_timeline_event(
    *,
    category: str,
    event_key: str,
    kind_label: str,
    title: str,
    meta: str = "",
    description: str = "",
    accent: str = "",
    actor=None,
    entity: Entity | None = None,
    deal: Deal | None = None,
    proposal: Proposal | None = None,
    collection: CollectionRecord | None = None,
    activity: Activity | None = None,
    document: Document | None = None,
    object_record: ObjectRecord | None = None,
    occurred_at: datetime | None = None,
    payload: dict[str, Any] | None = None,
) -> TimelineEvent:
    return TimelineEvent.objects.create(
        actor=actor,
        entity=entity,
        deal=deal,
        proposal=proposal,
        collection=collection,
        activity=activity,
        document=document,
        object_record=object_record,
        category=category,
        event_key=event_key,
        kind_label=kind_label,
        title=title[:180],
        meta=(meta or "")[:180],
        description=description or "",
        accent=accent or _default_accent(category),
        payload=dict(payload or {}),
        occurred_at=occurred_at or timezone.now(),
    )


def log_entity_created(*, entity: Entity, actor=None, kind_label: str = "Ficha", origin: str = "runtime", occurred_at=None):
    return record_timeline_event(
        category=TimelineEvent.CATEGORY_ENTITY,
        event_key="entity.created",
        kind_label=kind_label,
        title=entity.full_name,
        meta="Ficha creada",
        description=entity.notes[:180] if entity.notes else "",
        actor=actor,
        entity=entity,
        occurred_at=occurred_at or entity.created_at,
        payload={"origin": origin},
    )


def log_entity_updated(
    *,
    entity: Entity,
    actor=None,
    kind_label: str = "Ficha",
    changed_fields: list[str] | None = None,
    origin: str = "runtime",
    occurred_at=None,
):
    return record_timeline_event(
        category=TimelineEvent.CATEGORY_ENTITY,
        event_key="entity.updated",
        kind_label=kind_label,
        title=entity.full_name,
        meta="Ficha actualizada",
        description=_build_changed_fields_copy(changed_fields),
        actor=actor,
        entity=entity,
        occurred_at=occurred_at or entity.updated_at,
        payload={"origin": origin, "changed_fields": list(changed_fields or [])},
    )


def log_deal_created(*, deal: Deal, actor=None, kind_label: str = "Deal", origin: str = "runtime", occurred_at=None):
    return record_timeline_event(
        category=TimelineEvent.CATEGORY_DEAL,
        event_key="deal.created",
        kind_label=kind_label,
        title=deal.title,
        meta=" | ".join(part for part in [deal.pipeline.name, deal.stage] if part),
        description=_format_currency_amount(deal.currency, deal.amount),
        actor=actor,
        entity=deal.entity,
        deal=deal,
        occurred_at=occurred_at or deal.created_at,
        payload={"origin": origin, "status": deal.status},
    )


def log_deal_updated(
    *,
    deal: Deal,
    actor=None,
    kind_label: str = "Deal",
    changed_fields: list[str] | None = None,
    origin: str = "runtime",
    occurred_at=None,
):
    return record_timeline_event(
        category=TimelineEvent.CATEGORY_DEAL,
        event_key="deal.updated",
        kind_label=kind_label,
        title=deal.title,
        meta=" | ".join(part for part in [deal.pipeline.name, deal.stage] if part),
        description=_build_changed_fields_copy(changed_fields) or _format_currency_amount(deal.currency, deal.amount),
        actor=actor,
        entity=deal.entity,
        deal=deal,
        occurred_at=occurred_at or deal.updated_at,
        payload={"origin": origin, "changed_fields": list(changed_fields or [])},
    )


def log_deal_stage_changed(
    *,
    deal: Deal,
    actor=None,
    kind_label: str = "Deal",
    previous_stage: str = "",
    previous_pipeline_name: str = "",
    origin: str = "runtime",
    occurred_at=None,
):
    description = f"Paso de {previous_stage} a {deal.stage}." if previous_stage and previous_stage != deal.stage else "Etapa reorganizada."
    if previous_pipeline_name and previous_pipeline_name != deal.pipeline.name:
        description = f"Se movio de {previous_pipeline_name}/{previous_stage or '-'} a {deal.pipeline.name}/{deal.stage}."
    return record_timeline_event(
        category=TimelineEvent.CATEGORY_DEAL,
        event_key="deal.stage_changed",
        kind_label=kind_label,
        title=deal.title,
        meta=" | ".join(part for part in [deal.pipeline.name, deal.stage] if part),
        description=description,
        actor=actor,
        entity=deal.entity,
        deal=deal,
        occurred_at=occurred_at or deal.updated_at,
        payload={
            "origin": origin,
            "previous_stage": previous_stage,
            "previous_pipeline_name": previous_pipeline_name,
            "current_stage": deal.stage,
            "current_pipeline_name": deal.pipeline.name,
        },
    )


def log_proposal_created(
    *,
    proposal: Proposal,
    actor=None,
    kind_label: str = "Propuesta",
    origin: str = "runtime",
    occurred_at=None,
):
    return record_timeline_event(
        category=TimelineEvent.CATEGORY_PROPOSAL,
        event_key="proposal.created",
        kind_label=kind_label,
        title=proposal.title,
        meta=proposal.get_status_display(),
        description=_format_currency_amount(proposal.currency, proposal.amount),
        actor=actor,
        entity=proposal.entity,
        deal=proposal.deal,
        proposal=proposal,
        occurred_at=occurred_at or proposal.created_at,
        payload={"origin": origin, "status": proposal.status},
    )


def log_proposal_updated(
    *,
    proposal: Proposal,
    actor=None,
    kind_label: str = "Propuesta",
    changed_fields: list[str] | None = None,
    previous_status: str = "",
    origin: str = "runtime",
    occurred_at=None,
):
    event_key = "proposal.status_changed" if previous_status and previous_status != proposal.status else "proposal.updated"
    description = _build_changed_fields_copy(changed_fields) or _format_currency_amount(proposal.currency, proposal.amount)
    if previous_status and previous_status != proposal.status:
        description = f"Paso de {previous_status} a {proposal.status}."
    return record_timeline_event(
        category=TimelineEvent.CATEGORY_PROPOSAL,
        event_key=event_key,
        kind_label=kind_label,
        title=proposal.title,
        meta=proposal.get_status_display(),
        description=description,
        actor=actor,
        entity=proposal.entity,
        deal=proposal.deal,
        proposal=proposal,
        occurred_at=occurred_at or proposal.updated_at,
        payload={"origin": origin, "changed_fields": list(changed_fields or []), "previous_status": previous_status},
    )


def log_collection_created(
    *,
    collection: CollectionRecord,
    actor=None,
    kind_label: str = "Cobranza",
    origin: str = "runtime",
    occurred_at=None,
):
    return record_timeline_event(
        category=TimelineEvent.CATEGORY_COLLECTION,
        event_key="collection.created",
        kind_label=kind_label,
        title=collection.title,
        meta=collection.get_status_display(),
        description=f"Saldo {_format_currency_amount(collection.currency, collection.balance)}",
        actor=actor,
        entity=collection.entity,
        deal=collection.deal,
        collection=collection,
        occurred_at=occurred_at or collection.created_at,
        payload={"origin": origin, "status": collection.status},
    )


def log_collection_updated(
    *,
    collection: CollectionRecord,
    actor=None,
    kind_label: str = "Cobranza",
    changed_fields: list[str] | None = None,
    previous_status: str = "",
    origin: str = "runtime",
    occurred_at=None,
):
    event_key = "collection.status_changed" if previous_status and previous_status != collection.status else "collection.updated"
    description = _build_changed_fields_copy(changed_fields) or f"Saldo {_format_currency_amount(collection.currency, collection.balance)}"
    if previous_status and previous_status != collection.status:
        description = f"Paso de {previous_status} a {collection.status}."
    return record_timeline_event(
        category=TimelineEvent.CATEGORY_COLLECTION,
        event_key=event_key,
        kind_label=kind_label,
        title=collection.title,
        meta=collection.get_status_display(),
        description=description,
        actor=actor,
        entity=collection.entity,
        deal=collection.deal,
        collection=collection,
        occurred_at=occurred_at or collection.updated_at,
        payload={"origin": origin, "changed_fields": list(changed_fields or []), "previous_status": previous_status},
    )


def log_activity_created(
    *,
    activity: Activity,
    actor=None,
    origin: str = "runtime",
    occurred_at=None,
):
    return record_timeline_event(
        category=TimelineEvent.CATEGORY_ACTIVITY,
        event_key="activity.created",
        kind_label=activity.get_activity_type_display(),
        title=activity.title,
        meta=getattr(activity.deal, "title", "") or getattr(activity.assigned_to, "username", "") or "",
        description=_build_activity_description(activity),
        actor=actor,
        entity=activity.entity,
        deal=activity.deal,
        activity=activity,
        occurred_at=occurred_at or activity.created_at,
        payload={"origin": origin, "activity_type": activity.activity_type},
    )


def log_activity_completion_changed(
    *,
    activity: Activity,
    actor=None,
    origin: str = "runtime",
    occurred_at=None,
):
    event_key = "activity.completed" if activity.completed_at else "activity.reopened"
    description = "Tarea marcada como completada." if activity.completed_at else "Tarea reabierta para seguimiento."
    return record_timeline_event(
        category=TimelineEvent.CATEGORY_ACTIVITY,
        event_key=event_key,
        kind_label=activity.get_activity_type_display(),
        title=activity.title,
        meta=getattr(activity.deal, "title", "") or getattr(activity.assigned_to, "username", "") or "",
        description=description,
        actor=actor,
        entity=activity.entity,
        deal=activity.deal,
        activity=activity,
        occurred_at=occurred_at or activity.updated_at,
        payload={"origin": origin, "activity_type": activity.activity_type, "is_complete": bool(activity.completed_at)},
    )


def log_document_created(
    *,
    document: Document,
    profile: str,
    custom_blueprints: list[dict] | None = None,
    actor=None,
    kind_label: str = "Documento",
    origin: str = "runtime",
    occurred_at=None,
):
    return record_timeline_event(
        category=TimelineEvent.CATEGORY_DOCUMENT,
        event_key="document.created",
        kind_label=kind_label,
        title=document.title,
        meta=get_document_type_label(profile, document.document_type, custom_blueprints=custom_blueprints),
        description=getattr(document.deal, "title", "") or document.storage_key,
        actor=actor,
        entity=document.entity,
        deal=document.deal,
        document=document,
        occurred_at=occurred_at or document.created_at,
        payload={"origin": origin, "document_type": document.document_type},
    )


def log_document_updated(
    *,
    document: Document,
    profile: str,
    custom_blueprints: list[dict] | None = None,
    actor=None,
    kind_label: str = "Documento",
    changed_fields: list[str] | None = None,
    origin: str = "runtime",
    occurred_at=None,
):
    return record_timeline_event(
        category=TimelineEvent.CATEGORY_DOCUMENT,
        event_key="document.updated",
        kind_label=kind_label,
        title=document.title,
        meta=get_document_type_label(profile, document.document_type, custom_blueprints=custom_blueprints),
        description=_build_changed_fields_copy(changed_fields) or getattr(document.deal, "title", "") or document.storage_key,
        actor=actor,
        entity=document.entity,
        deal=document.deal,
        document=document,
        occurred_at=occurred_at or document.updated_at,
        payload={"origin": origin, "changed_fields": list(changed_fields or []), "document_type": document.document_type},
    )


def log_object_record_created(
    *,
    record: ObjectRecord,
    actor=None,
    origin: str = "runtime",
    occurred_at=None,
):
    return record_timeline_event(
        category=TimelineEvent.CATEGORY_OBJECT_RECORD,
        event_key="object_record.created",
        kind_label=record.object_schema.label,
        title=record.title or record.object_schema.label,
        meta="Registro custom creado",
        actor=actor,
        object_record=record,
        occurred_at=occurred_at or record.created_at,
        payload={"origin": origin, "object_key": record.object_schema.key},
    )


def log_object_record_updated(
    *,
    record: ObjectRecord,
    actor=None,
    changed_fields: list[str] | None = None,
    origin: str = "runtime",
    occurred_at=None,
):
    return record_timeline_event(
        category=TimelineEvent.CATEGORY_OBJECT_RECORD,
        event_key="object_record.updated",
        kind_label=record.object_schema.label,
        title=record.title or record.object_schema.label,
        meta="Registro custom actualizado",
        description=_build_changed_fields_copy(changed_fields),
        actor=actor,
        object_record=record,
        occurred_at=occurred_at or record.updated_at,
        payload={"origin": origin, "object_key": record.object_schema.key, "changed_fields": list(changed_fields or [])},
    )


def _resolve_event_source(event_source, *, allowed_categories: set[str]) -> list:
    if hasattr(event_source, "filter"):
        return list(
            event_source.filter(category__in=allowed_categories).order_by("-occurred_at", "-id")[:18]
        )
    events = [event for event in list(event_source) if getattr(event, "category", "") in allowed_categories]
    events.sort(
        key=lambda event: (
            getattr(event, "occurred_at", timezone.now()),
            getattr(event, "id", 0),
        ),
        reverse=True,
    )
    return events


def _serialize_timeline_event(event) -> dict[str, Any]:
    return {
        "kind": getattr(event, "category", ""),
        "kind_label": getattr(event, "kind_label", ""),
        "title": getattr(event, "title", ""),
        "meta": getattr(event, "meta", ""),
        "description": getattr(event, "description", ""),
        "timestamp": getattr(event, "occurred_at", timezone.now()),
        "accent": getattr(event, "accent", "") or _default_accent(getattr(event, "category", "")),
    }


def _build_activity_description(activity: Activity) -> str:
    if activity.completed_at:
        return f"Completada {timezone.localtime(activity.completed_at).strftime('%d/%m/%Y %H:%M')}"
    if activity.due_at:
        return f"Vence {timezone.localtime(activity.due_at).strftime('%d/%m/%Y %H:%M')}"
    return (activity.description or "")[:180]


def _build_changed_fields_copy(changed_fields: list[str] | None) -> str:
    cleaned = [_humanize_changed_field(field_name) for field_name in (changed_fields or []) if field_name]
    if not cleaned:
        return ""
    return "Actualizado: " + ", ".join(cleaned[:4])


def _humanize_changed_field(field_name: str) -> str:
    raw_value = field_name.split("__", 1)[1] if "__" in field_name else field_name
    return raw_value.replace("_", " ")


def _format_currency_amount(currency: str, amount: Decimal | int | float | None) -> str:
    numeric = float(amount or 0)
    decimals = 0 if numeric.is_integer() else 2
    return f"{currency} {numeric:,.{decimals}f}"


def _default_accent(category: str) -> str:
    return {
        TimelineEvent.CATEGORY_ENTITY: "bg-slate-100 text-slate-700",
        TimelineEvent.CATEGORY_DEAL: "bg-blue-50 text-blue-700",
        TimelineEvent.CATEGORY_PROPOSAL: "bg-violet-50 text-violet-700",
        TimelineEvent.CATEGORY_COLLECTION: "bg-amber-50 text-amber-700",
        TimelineEvent.CATEGORY_ACTIVITY: "bg-gray-100 text-gray-700",
        TimelineEvent.CATEGORY_DOCUMENT: "bg-green-50 text-green-700",
        TimelineEvent.CATEGORY_OBJECT_RECORD: "bg-indigo-50 text-indigo-700",
    }.get(category, "bg-gray-100 text-gray-700")
