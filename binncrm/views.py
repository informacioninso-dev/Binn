import json
from urllib.parse import urlencode
from datetime import date, datetime, timedelta

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Count, Max, Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST
from django_tenants.utils import get_public_schema_name, schema_context

from access.permissions import (
    CRM_ADMIN_ALLOWED_ROLES,
    PERMISSION_ACTIVITIES_COMPLETE,
    PERMISSION_ACTIVITIES_EDIT,
    PERMISSION_ACTIVITIES_VIEW,
    PERMISSION_COLLAB_VIEW,
    PERMISSION_COLLECTIONS_EDIT,
    PERMISSION_COLLECTIONS_VIEW,
    PERMISSION_DEALS_EDIT,
    PERMISSION_DEALS_MOVE,
    PERMISSION_DEALS_VIEW,
    PERMISSION_DOCUMENTS_EDIT,
    PERMISSION_DOCUMENTS_VIEW,
    PERMISSION_ENTITIES_EDIT,
    PERMISSION_ENTITIES_VIEW,
    PERMISSION_OBJECTS_EDIT,
    PERMISSION_OBJECTS_VIEW,
    PERMISSION_PROPOSALS_EDIT,
    PERMISSION_PROPOSALS_VIEW,
    PERMISSION_REPORTS_VIEW,
    request_has_tenant_permission,
    tenant_role_required,
    tenant_permission_required,
)
from access.runtime import get_request_membership
from tenants.workspace_packs import build_workspace_pack
from tenants.models import Client
from tenants.observability import record_tenant_event
from tenants.services import sync_tenant_pipelines

from .importers import import_entities_from_csv
from .document_blueprints import (
    build_document_metadata_summary,
    get_document_blueprint_map,
    get_document_blueprints,
    get_document_type_label,
)
from .forms import (
    ActivityForm,
    CollectionRecordForm,
    DealForm,
    DocumentForm,
    EntityForm,
    EntityImportForm,
    ObjectRecordForm,
    PipelineTemplateEditorForm,
    ProposalForm,
    SavedWorkspaceFilterForm,
)
from .models import Activity, CollectionRecord, Deal, Document, Entity, ObjectRecord, ObjectSchema, Pipeline, Proposal, SavedWorkspaceFilter
from .object_engine import (
    build_object_record_preview,
    get_custom_object_schemas,
    get_entity_field_definitions,
    get_object_record_field_definitions,
    get_object_schema_definition,
)
from .timeline import (
    build_entity_timeline as build_recorded_entity_timeline,
    log_activity_completion_changed,
    log_activity_created,
    log_collection_created,
    log_collection_updated,
    log_deal_created,
    log_deal_stage_changed,
    log_deal_updated,
    log_document_created,
    log_document_updated,
    log_entity_created,
    log_entity_updated,
    log_object_record_created,
    log_object_record_updated,
    log_proposal_created,
    log_proposal_updated,
)
from .view_engine import apply_deal_saved_view, apply_entity_saved_view, get_saved_views, resolve_saved_view


def _is_htmx(request) -> bool:
    return request.headers.get("HX-Request") == "true"


def _can(request, permission_code: str) -> bool:
    return request_has_tenant_permission(request, permission_code)


def _can_manage_pipeline_settings(request) -> bool:
    user = getattr(request, "user", None)
    if getattr(user, "is_superuser", False):
        return True
    membership = getattr(request, "tenant_membership", None) or get_request_membership(request)
    if membership is None or not membership.is_active:
        return False
    return membership.role in CRM_ADMIN_ALLOWED_ROLES


def _saved_filter_allowed_keys(object_type: str) -> tuple[str, ...]:
    if object_type == SavedWorkspaceFilter.OBJECT_DEAL:
        return ("q", "view", "pipeline")
    return ("q", "view")


def _normalize_saved_filter_params(*, object_type: str, raw_params: dict | None) -> dict[str, str]:
    normalized = {}
    for key in _saved_filter_allowed_keys(object_type):
        value = str((raw_params or {}).get(key, "") or "").strip()
        if value:
            normalized[key] = value
    return normalized


def _resolve_active_saved_filter(request, *, object_type: str) -> tuple[SavedWorkspaceFilter | None, dict[str, str]]:
    raw_filter_id = (request.GET.get("saved_filter") or "").strip()
    if not raw_filter_id.isdigit():
        return None, {}
    saved_filter = (
        SavedWorkspaceFilter.objects.filter(
            pk=int(raw_filter_id),
            owner=request.user,
            object_type=object_type,
        )
        .only("id", "label", "params", "object_type")
        .first()
    )
    if saved_filter is None:
        return None, {}
    return saved_filter, _normalize_saved_filter_params(object_type=object_type, raw_params=saved_filter.params)


def _resolve_filter_value(request, *, key: str, defaults: dict[str, str]) -> str:
    return str(request.GET.get(key, defaults.get(key, "")) or "").strip()


def _build_saved_filter_redirect(route_name: str, *, params: dict[str, str], saved_filter_id: int | None = None) -> str:
    query_params = dict(params)
    if saved_filter_id is not None:
        query_params["saved_filter"] = str(saved_filter_id)
    base_url = reverse(route_name)
    if not query_params:
        return base_url
    return f"{base_url}?{urlencode(query_params)}"


def _build_saved_filter_items(request, *, object_type: str, route_name: str, active_filter: SavedWorkspaceFilter | None) -> list[dict]:
    filters = SavedWorkspaceFilter.objects.filter(owner=request.user, object_type=object_type).order_by("label", "id")
    items = []
    active_filter_id = getattr(active_filter, "pk", None)
    for saved_filter in filters:
        params = _normalize_saved_filter_params(object_type=object_type, raw_params=saved_filter.params)
        items.append(
            {
                "pk": saved_filter.pk,
                "label": saved_filter.label,
                "href": _build_saved_filter_redirect(route_name, params=params, saved_filter_id=saved_filter.pk),
                "is_active": saved_filter.pk == active_filter_id,
            }
        )
    return items


def _replace_pipeline_template(templates: list[dict], pipeline_key: str, replacement: dict) -> list[dict]:
    updated = []
    replaced = False
    for item in templates:
        if item.get("key") == pipeline_key:
            updated.append(replacement)
            replaced = True
        else:
            updated.append(dict(item))
    if not replaced:
        updated.append(replacement)
    return updated


def _move_pipeline_template(templates: list[dict], pipeline_key: str, direction: int) -> list[dict]:
    index = next((idx for idx, item in enumerate(templates) if item.get("key") == pipeline_key), None)
    if index is None:
        return list(templates)
    target = index + direction
    if target < 0 or target >= len(templates):
        return list(templates)
    updated = list(templates)
    updated[index], updated[target] = updated[target], updated[index]
    return updated


def _set_default_pipeline_template(templates: list[dict], pipeline_key: str) -> list[dict]:
    selected = None
    remainder = []
    for item in templates:
        if item.get("key") == pipeline_key:
            selected = dict(item)
        else:
            remainder.append(dict(item))
    if selected is None:
        return list(templates)
    return [selected, *remainder]


def _remove_pipeline_template(templates: list[dict], pipeline_key: str) -> list[dict]:
    return [dict(item) for item in templates if item.get("key") != pipeline_key]


def _persist_tenant_pipeline_templates(
    request,
    *,
    templates: list[dict],
    event_title: str,
    event_message: str,
    event_code: str,
    metadata: dict | None = None,
) -> list[str]:
    with schema_context(get_public_schema_name()):
        tenant = Client.objects.select_related("config").get(schema_name=request.tenant.schema_name)
        config = tenant.tenant_config
        config.pipeline_templates = templates
        config.save(update_fields=["pipeline_templates", "updated_at"])
        notices = sync_tenant_pipelines(tenant)
        record_tenant_event(
            tenant=tenant,
            actor=request.user,
            title=event_title,
            message=event_message,
            code=event_code,
            metadata=metadata or {},
        )
    return notices


def _build_pipeline_admin_rows(request) -> tuple[list[dict], list[dict]]:
    configured_templates = list(getattr(request.tenant.tenant_config, "pipeline_templates", []) or [])
    actual_pipeline_map = {
        pipeline.key: pipeline
        for pipeline in Pipeline.objects.annotate(deal_count=Count("deals", distinct=True)).order_by("position", "name")
    }

    rows = []
    for index, template in enumerate(configured_templates):
        actual = actual_pipeline_map.get(template["key"])
        rows.append(
            {
                "key": template["key"],
                "label": template["label"],
                "stages": list(template.get("stages", [])),
                "position": index,
                "is_default": index == 0,
                "deal_count": getattr(actual, "deal_count", 0) if actual is not None else 0,
                "is_active": getattr(actual, "is_active", True) if actual is not None else True,
            }
        )

    stale_rows = []
    for pipeline in actual_pipeline_map.values():
        if any(item["key"] == pipeline.key for item in configured_templates):
            continue
        stale_rows.append(
            {
                "key": pipeline.key,
                "label": pipeline.name,
                "stages": list(pipeline.stage_choices),
                "deal_count": getattr(pipeline, "deal_count", 0),
                "is_active": pipeline.is_active,
            }
        )
    return rows, stale_rows


def _task_status(activity: Activity, *, now=None) -> dict:
    now = now or timezone.now()
    if activity.completed_at:
        return {
            "label": f"Completada {timezone.localtime(activity.completed_at).strftime('%d/%m/%Y %H:%M')}",
            "tone": "bg-green-50 text-green-700",
            "is_complete": True,
            "is_overdue": False,
        }
    if activity.due_at and activity.due_at < now:
        return {
            "label": f"Vencida {timezone.localtime(activity.due_at).strftime('%d/%m/%Y %H:%M')}",
            "tone": "bg-red-50 text-red-700",
            "is_complete": False,
            "is_overdue": True,
        }
    if activity.due_at:
        return {
            "label": f"Vence {timezone.localtime(activity.due_at).strftime('%d/%m/%Y %H:%M')}",
            "tone": "bg-amber-50 text-amber-700",
            "is_complete": False,
            "is_overdue": False,
        }
    return {
        "label": "Sin vencimiento",
        "tone": "bg-gray-100 text-gray-600",
        "is_complete": False,
        "is_overdue": False,
    }


def _tenant_profile(tenant) -> str:
    return getattr(getattr(tenant, "tenant_config", tenant), "profile", "general")


def _build_task_card(activity: Activity, *, now=None) -> dict:
    status = _task_status(activity, now=now)
    return {
        "activity": activity,
        "status": status,
        "assignee_label": getattr(activity.assigned_to, "username", "") or "Sin responsable",
    }


def _format_extra_value(value, field_definition: dict) -> str:
    if value in (None, "", []):
        return ""

    field_type = field_definition.get("type", "text")
    if field_type == "boolean":
        return "Si" if value else "No"
    if field_type == "date":
        if isinstance(value, datetime):
            return value.strftime("%d/%m/%Y")
        if isinstance(value, date):
            return value.strftime("%d/%m/%Y")
        try:
            parsed = datetime.fromisoformat(str(value))
        except ValueError:
            return str(value)
        return parsed.strftime("%d/%m/%Y")
    return str(value)


def _build_extra_values(entity: Entity, field_definitions: list[dict], *, limit: int | None = None) -> list[dict]:
    values = []
    for field_definition in field_definitions[:limit] if limit else field_definitions:
        raw_value = entity.data_extra.get(field_definition["key"])
        values.append(
            {
                "key": field_definition["key"],
                "label": field_definition["label"],
                "value": _format_extra_value(raw_value, field_definition),
                "has_value": raw_value not in (None, "", []),
            }
        )
    return values


def _build_entity_search_query(query: str, field_definitions: list[dict], *, prefix: str = "") -> Q:
    terms = [part.strip() for part in query.split() if part.strip()]
    if not terms:
        return Q()

    combined_query = Q()
    for term in terms:
        term_query = (
            Q(**{f"{prefix}full_name__icontains": term})
            | Q(**{f"{prefix}legal_id__icontains": term})
            | Q(**{f"{prefix}phone__icontains": term})
            | Q(**{f"{prefix}email__icontains": term})
        )
        for field_definition in field_definitions:
            term_query |= Q(**{f"{prefix}data_extra__{field_definition['key']}__icontains": term})
        combined_query &= term_query
    return combined_query


def _build_object_record_search_query(query: str, field_definitions: list[dict]) -> Q:
    terms = [part.strip() for part in query.split() if part.strip()]
    if not terms:
        return Q()

    searchable_keys = [
        field_definition["key"]
        for field_definition in field_definitions
        if field_definition.get("type") in {"text", "textarea", "email"}
    ]
    combined_query = Q()
    for term in terms:
        term_query = Q(title__icontains=term)
        for key in searchable_keys:
            term_query |= Q(**{f"data__{key}__icontains": term})
        combined_query &= term_query
    return combined_query


def _serialize_object_value(value, field_definition: dict) -> str:
    if value in (None, "", []):
        return "-"
    if field_definition.get("type") == "boolean":
        return "Si" if bool(value) else "No"
    if field_definition.get("type") == "date" and value:
        try:
            return date.fromisoformat(str(value)[:10]).strftime("%d/%m/%Y")
        except ValueError:
            return str(value)
    return str(value)


def _get_custom_object_schema_or_404(object_key: str) -> ObjectSchema:
    object_schema = get_object_schema_definition(object_key=object_key)
    if object_schema is None or object_schema.source != ObjectSchema.SOURCE_CUSTOM:
        raise ObjectSchema.DoesNotExist()
    return object_schema


def _format_file_size(value: int) -> str:
    if not value:
        return "0 B"

    size = float(value)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{int(size)} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{value} B"


def _build_document_access_url(document: Document) -> str:
    if document.external_url:
        return document.external_url

    if document.storage_provider == Document.STORAGE_S3 and document.bucket_name and document.storage_key:
        configured_base = getattr(settings, "DOCUMENT_PUBLIC_BASE_URL", "").rstrip("/")
        if configured_base:
            return f"{configured_base}/{document.storage_key.lstrip('/')}"
        region = getattr(settings, "AWS_S3_REGION_NAME", "").strip()
        if region:
            return f"https://{document.bucket_name}.s3.{region}.amazonaws.com/{document.storage_key.lstrip('/')}"
        return f"https://{document.bucket_name}.s3.amazonaws.com/{document.storage_key.lstrip('/')}"

    return ""


def _document_expiry_status(document: Document, *, today=None) -> dict:
    today = today or timezone.localdate()
    if not document.expires_on:
        return {
            "label": "Sin vencimiento",
            "tone": "bg-gray-100 text-gray-600",
            "is_expired": False,
            "is_expiring_soon": False,
        }
    if document.expires_on < today:
        return {
            "label": f"Vencio {document.expires_on.strftime('%d/%m/%Y')}",
            "tone": "bg-red-50 text-red-700",
            "is_expired": True,
            "is_expiring_soon": False,
        }
    if document.expires_on <= today + timedelta(days=30):
        return {
            "label": f"Vence {document.expires_on.strftime('%d/%m/%Y')}",
            "tone": "bg-amber-50 text-amber-700",
            "is_expired": False,
            "is_expiring_soon": True,
        }
    return {
        "label": f"Vigente hasta {document.expires_on.strftime('%d/%m/%Y')}",
        "tone": "bg-green-50 text-green-700",
        "is_expired": False,
        "is_expiring_soon": False,
    }


def _build_broker_document_checklist(entity: Entity, documents: list[Document], *, blueprint_map: dict[str, dict]) -> list[dict]:
    required_keys = ["poliza", "cedula"]
    if entity.data_extra.get("placa"):
        required_keys.extend(["matricula", "inspeccion"])

    available_types = {document.document_type for document in documents}
    checklist = []
    for document_key in required_keys:
        label = blueprint_map.get(document_key, {}).get("label", document_key.replace("_", " ").title())
        is_present = document_key in available_types
        checklist.append(
            {
                "key": document_key,
                "label": label,
                "is_present": is_present,
                "tone": "bg-green-50 text-green-700" if is_present else "bg-red-50 text-red-700",
                "status": "Completo" if is_present else "Falta",
            }
        )
    return checklist


def _broker_snapshot(
    *,
    entities,
    deals,
    activities,
    documents,
    collections,
    today=None,
) -> dict:
    today = today or timezone.localdate()
    renewals_due = deals.filter(status=Deal.STATUS_OPEN, expected_close_on__isnull=False, expected_close_on__lte=today + timedelta(days=30))
    open_claims = activities.filter(activity_type=Activity.TYPE_CLAIM, completed_at__isnull=True)
    overdue_collections = collections.exclude(status=CollectionRecord.STATUS_PAID).filter(due_on__lt=today)
    expiring_documents = documents.filter(expires_on__isnull=False, expires_on__lte=today + timedelta(days=30))

    missing_checklist_entities = 0
    # We compute the checklist with the already loaded document set to avoid another layer of infra.
    entity_documents: dict[int, list[Document]] = {}
    for document in documents:
        if document.entity_id is None:
            continue
        entity_documents.setdefault(document.entity_id, []).append(document)
    broker_blueprint_map = get_document_blueprint_map("broker")
    for entity in entities:
        checklist = _build_broker_document_checklist(entity, entity_documents.get(entity.id, []), blueprint_map=broker_blueprint_map)
        if any(not item["is_present"] for item in checklist):
            missing_checklist_entities += 1

    return {
        "renewals_due_count": renewals_due.count() if hasattr(renewals_due, "count") else len(list(renewals_due)),
        "open_claims_count": open_claims.count() if hasattr(open_claims, "count") else len(list(open_claims)),
        "overdue_collections_count": overdue_collections.count() if hasattr(overdue_collections, "count") else len(list(overdue_collections)),
        "expiring_documents_count": expiring_documents.count() if hasattr(expiring_documents, "count") else len(list(expiring_documents)),
        "missing_checklist_entities_count": missing_checklist_entities,
    }


def _parse_extra_date(raw_value):
    if not raw_value:
        return None
    if isinstance(raw_value, datetime):
        return raw_value.date()
    if isinstance(raw_value, date):
        return raw_value
    try:
        return date.fromisoformat(str(raw_value)[:10])
    except ValueError:
        return None


def _build_search_section(*, key: str, title: str, empty_message: str, items: list[dict], href: str = "") -> dict:
    return {
        "key": key,
        "title": title,
        "empty_message": empty_message,
        "count": len(items),
        "items": items,
        "href": href,
    }


def _build_global_search_sections(request, *, query: str) -> list[dict]:
    query = (query or "").strip()
    if not query:
        return []

    labels = request.tenant.tenant_config.labels
    entity_fields = get_entity_field_definitions(tenant=request.tenant)
    sections = []

    if _can(request, PERMISSION_ENTITIES_VIEW):
        entity_items = [
            {
                "title": entity.full_name,
                "meta": entity.legal_id or entity.phone or entity.email or "Sin dato principal",
                "caption": entity.notes[:120] if entity.notes else "Ficha del contacto.",
                "href": reverse("binncrm:entity_detail", kwargs={"pk": entity.pk}),
                "link_label": "Abrir ficha",
            }
            for entity in Entity.objects.filter(is_active=True)
            .filter(_build_entity_search_query(query, entity_fields))
            .order_by("full_name")[:6]
        ]
        sections.append(
            _build_search_section(
                key="entities",
                title=labels.get("entity_plural", "Contactos"),
                empty_message="No hubo coincidencias en contactos.",
                items=entity_items,
                href=f"{reverse('binncrm:entities')}?{urlencode({'q': query})}",
            )
        )

    if _can(request, PERMISSION_DEALS_VIEW):
        deal_items = []
        deals = (
            Deal.objects.select_related("entity", "pipeline")
            .filter(is_active=True)
            .filter(Q(title__icontains=query) | _build_entity_search_query(query, entity_fields, prefix="entity__"))
            .order_by("-updated_at")[:6]
        )
        for deal in deals:
            deal_items.append(
                {
                    "title": deal.title,
                    "meta": f"{deal.entity.full_name} | {deal.pipeline.name} | {deal.stage}",
                    "caption": deal.notes[:120] if deal.notes else _format_currency_amount(deal.currency, deal.amount),
                    "href": reverse("binncrm:deal_edit", kwargs={"pk": deal.pk}),
                    "link_label": "Abrir deal",
                }
            )
        sections.append(
            _build_search_section(
                key="deals",
                title=labels.get("deal_plural", "Deals"),
                empty_message="No hubo coincidencias en deals.",
                items=deal_items,
                href=f"{reverse('binncrm:index')}?{urlencode({'q': query})}",
            )
        )

    if _can(request, PERMISSION_ACTIVITIES_VIEW):
        activity_items = []
        activities = (
            Activity.objects.select_related("entity", "deal", "assigned_to")
            .filter(
                Q(title__icontains=query)
                | Q(description__icontains=query)
                | Q(entity__full_name__icontains=query)
            )
            .order_by("-created_at")[:6]
        )
        for activity in activities:
            status_copy = _task_status(activity)["label"] if activity.activity_type == Activity.TYPE_TASK else activity.get_activity_type_display()
            activity_items.append(
                {
                    "title": activity.title,
                    "meta": f"{activity.entity.full_name} | {activity.get_activity_type_display()}",
                    "caption": status_copy,
                    "href": reverse("binncrm:entity_detail", kwargs={"pk": activity.entity_id}),
                    "link_label": "Abrir ficha",
                }
            )
        sections.append(
            _build_search_section(
                key="activities",
                title=labels.get("activity_plural", "Actividades"),
                empty_message="No hubo coincidencias en actividades.",
                items=activity_items,
                href=f"{reverse('binncrm:activities')}?{urlencode({'q': query})}",
            )
        )

    if _can(request, PERMISSION_PROPOSALS_VIEW):
        proposal_items = []
        proposals = (
            Proposal.objects.select_related("entity", "deal")
            .filter(is_active=True)
            .filter(
                Q(title__icontains=query)
                | Q(proposal_number__icontains=query)
                | Q(entity__full_name__icontains=query)
            )
            .order_by("-updated_at")[:6]
        )
        for proposal in proposals:
            proposal_items.append(
                {
                    "title": proposal.title,
                    "meta": f"{proposal.entity.full_name} | {proposal.get_status_display()}",
                    "caption": proposal.summary[:120] if proposal.summary else _format_currency_amount(proposal.currency, proposal.amount),
                    "href": reverse("binncrm:proposal_edit", kwargs={"pk": proposal.pk}),
                    "link_label": "Abrir propuesta",
                }
            )
        sections.append(
            _build_search_section(
                key="proposals",
                title=labels.get("proposal_plural", "Propuestas"),
                empty_message="No hubo coincidencias en propuestas.",
                items=proposal_items,
                href=f"{reverse('binncrm:proposals')}?{urlencode({'q': query})}",
            )
        )

    if _can(request, PERMISSION_COLLECTIONS_VIEW):
        collection_items = []
        collections = (
            CollectionRecord.objects.select_related("entity", "deal")
            .filter(is_active=True)
            .filter(
                Q(title__icontains=query)
                | Q(reference__icontains=query)
                | Q(entity__full_name__icontains=query)
            )
            .order_by("due_on", "-updated_at")[:6]
        )
        for collection in collections:
            collection_items.append(
                {
                    "title": collection.title,
                    "meta": f"{collection.entity.full_name} | {collection.get_status_display()}",
                    "caption": f"Saldo {_format_currency_amount(collection.currency, collection.balance)}",
                    "href": reverse("binncrm:collection_edit", kwargs={"pk": collection.pk}),
                    "link_label": "Abrir cobranza",
                }
            )
        sections.append(
            _build_search_section(
                key="collections",
                title=labels.get("collection_plural", "Cobranzas"),
                empty_message="No hubo coincidencias en cobranzas.",
                items=collection_items,
                href=f"{reverse('binncrm:collections')}?{urlencode({'q': query})}",
            )
        )

    if _can(request, PERMISSION_DOCUMENTS_VIEW):
        document_items = []
        documents = (
            Document.objects.select_related("entity", "deal")
            .filter(is_active=True)
            .filter(
                Q(title__icontains=query)
                | Q(document_type__icontains=query)
                | Q(storage_key__icontains=query)
                | Q(entity__full_name__icontains=query)
            )
            .order_by("-created_at")[:6]
        )
        for document in documents:
            document_items.append(
                {
                    "title": document.title,
                    "meta": getattr(document.entity, "full_name", "") or document.document_type,
                    "caption": document.storage_key or document.external_url or "Documento registrado.",
                    "href": reverse("binncrm:document_edit", kwargs={"pk": document.pk}),
                    "link_label": "Abrir documento",
                }
            )
        sections.append(
            _build_search_section(
                key="documents",
                title=labels.get("document_plural", "Documentos"),
                empty_message="No hubo coincidencias en documentos.",
                items=document_items,
                href=f"{reverse('binncrm:documents')}?{urlencode({'q': query})}",
            )
        )

    return sections


def _build_report_item(*, title: str, meta: str = "", caption: str = "", status: str = "", tone: str = "bg-gray-100 text-gray-700") -> dict:
    return {
        "title": title,
        "meta": meta,
        "caption": caption,
        "status": status,
        "tone": tone,
    }


def _build_reports_copy(profile: str, labels: dict) -> dict:
    entity_plural = labels.get("entity_plural", "Contactos")
    deal_plural = labels.get("deal_plural", "Oportunidades")
    profiles = {
        "broker": {
            "kicker": "Reportes broker",
            "title": "Renovaciones, siniestros y documentos bajo control.",
            "subtitle": "Este radar junta lo que se enfria, vence o queda incompleto para que el equipo reaccione antes de perder una renovacion.",
            "highlights": ["Renovaciones proximas", "Siniestros abiertos", "Checklist documental"],
        },
        "condominio": {
            "kicker": "Reportes de recaudo",
            "title": "Cartera, residentes y seguimiento en una sola lectura.",
            "subtitle": "Aqui ves rapido que cuentas siguen vencidas, que residente lleva tiempo sin gestion y donde toca insistir hoy.",
            "highlights": ["Cartera vencida", "Residentes sin contacto", "Gestiones atrasadas"],
        },
        "servicios": {
            "kicker": "Radar comercial B2B",
            "title": "Propuestas, cobros y oportunidades que piden seguimiento.",
            "subtitle": "Usa este panel para detectar deals quietos, propuestas a punto de vencer y clientes que quedaron sin siguiente paso claro.",
            "highlights": ["Deals quietos", "Propuestas por vencer", "Cobros por empujar"],
        },
        "retail_moda": {
            "kicker": "Radar de recompra",
            "title": "Clienteling simple para no dejar enfriar clientes valiosos.",
            "subtitle": "La idea es identificar clientes inactivos, pedidos abiertos y seguimientos de WhatsApp que conviene mover hoy.",
            "highlights": ["Clientes inactivos", "Pedidos especiales", "Seguimientos de recompra"],
        },
        "marketing": {
            "kicker": "Radar comercial",
            "title": "Leads y oportunidades con senales claras de prioridad.",
            "subtitle": "Este panel sirve para descubrir oportunidades frias, tareas vencidas y propuestas que pueden escaparse si nadie actua.",
            "highlights": ["Embudo enfriandose", "Propuestas vigentes", "Seguimiento atrasado"],
        },
    }
    shared = {
        "kicker": "Reportes",
        "title": f"Salud operativa de {entity_plural.lower()} y {deal_plural.lower()}.",
        "subtitle": "Este radar prioriza seguimiento, vencimientos y dinero pendiente para que el equipo actue sin perderse en tablas largas.",
        "highlights": ["Seguimiento", "Vencimientos", "Alertas del negocio"],
    }
    return {**shared, **profiles.get(profile, {})}


def _build_document_card(
    document: Document,
    *,
    profile: str,
    blueprint_map: dict[str, dict],
    custom_blueprints: list[dict] | None = None,
) -> dict:
    blueprint = blueprint_map.get(document.document_type, {})
    expiry_status = _document_expiry_status(document)
    return {
        "document": document,
        "type_label": blueprint.get(
            "label",
            get_document_type_label(profile, document.document_type, custom_blueprints=custom_blueprints),
        ),
        "category": blueprint.get("category", "Soporte"),
        "description": blueprint.get("description", ""),
        "storage_hint": blueprint.get("storage_hint", ""),
        "access_url": _build_document_access_url(document),
        "storage_provider_label": document.get_storage_provider_display(),
        "storage_label": " / ".join(part for part in [document.bucket_name, document.storage_key] if part) or "Sin storage",
        "content_type": document.content_type or "No definido",
        "size_label": _format_file_size(document.file_size),
        "expiry_status": expiry_status,
        "verification_label": "Verificado" if document.is_verified else "Pendiente de verificacion",
        "verification_tone": "bg-green-50 text-green-700" if document.is_verified else "bg-gray-100 text-gray-600",
        "metadata_items": build_document_metadata_summary(
            document.metadata,
            profile=profile,
            document_type=document.document_type,
            limit=3,
            custom_blueprints=custom_blueprints,
        ),
    }


def _proposal_status(proposal: Proposal, *, now=None) -> dict:
    now = now or timezone.localdate()
    tone_map = {
        Proposal.STATUS_DRAFT: "bg-gray-100 text-gray-700",
        Proposal.STATUS_SENT: "bg-blue-50 text-blue-700",
        Proposal.STATUS_ACCEPTED: "bg-green-50 text-green-700",
        Proposal.STATUS_REJECTED: "bg-red-50 text-red-700",
        Proposal.STATUS_EXPIRED: "bg-amber-50 text-amber-700",
    }
    status_label = proposal.get_status_display()
    if proposal.valid_until and proposal.valid_until < now and proposal.status in {Proposal.STATUS_DRAFT, Proposal.STATUS_SENT}:
        status_label = f"Vencio {proposal.valid_until.strftime('%d/%m/%Y')}"
    elif proposal.valid_until and proposal.status in {Proposal.STATUS_DRAFT, Proposal.STATUS_SENT}:
        status_label = f"{proposal.get_status_display()} hasta {proposal.valid_until.strftime('%d/%m/%Y')}"
    return {
        "label": status_label,
        "tone": tone_map.get(proposal.status, "bg-gray-100 text-gray-700"),
    }


def _build_proposal_card(proposal: Proposal, *, now=None) -> dict:
    return {
        "proposal": proposal,
        "status": _proposal_status(proposal, now=now),
        "amount_label": f"{proposal.currency} {proposal.amount}",
    }


def _collection_status(collection: CollectionRecord, *, now=None) -> dict:
    now = now or timezone.localdate()
    if collection.status == CollectionRecord.STATUS_PAID:
        return {
            "label": "Pagada",
            "tone": "bg-green-50 text-green-700",
            "is_overdue": False,
        }
    if collection.due_on and collection.due_on < now:
        return {
            "label": f"Vencida {collection.due_on.strftime('%d/%m/%Y')}",
            "tone": "bg-red-50 text-red-700",
            "is_overdue": True,
        }
    if collection.status == CollectionRecord.STATUS_PROMISED and collection.promised_for:
        return {
            "label": f"Promesa para {collection.promised_for.strftime('%d/%m/%Y')}",
            "tone": "bg-blue-50 text-blue-700",
            "is_overdue": False,
        }
    if collection.due_on:
        return {
            "label": f"Vence {collection.due_on.strftime('%d/%m/%Y')}",
            "tone": "bg-amber-50 text-amber-700",
            "is_overdue": False,
        }
    return {
        "label": collection.get_status_display(),
        "tone": "bg-gray-100 text-gray-700",
        "is_overdue": False,
    }


def _build_collection_card(collection: CollectionRecord, *, now=None) -> dict:
    return {
        "collection": collection,
        "status": _collection_status(collection, now=now),
        "balance_label": f"{collection.currency} {collection.balance}",
        "paid_label": f"{collection.currency} {collection.amount_paid}",
    }


def _build_collection_board_card(collection: CollectionRecord, *, now=None) -> dict:
    status = _collection_status(collection, now=now)
    due_label = collection.due_on.strftime("%d/%m/%Y") if collection.due_on else ""
    promise_label = collection.promised_for.strftime("%d/%m/%Y") if collection.promised_for else ""
    last_touch_label = (
        f"Ultimo toque {timezone.localtime(collection.last_contacted_at).strftime('%d/%m %H:%M')}"
        if collection.last_contacted_at
        else "Sin toque reciente"
    )
    return {
        "collection": collection,
        "status": status,
        "balance_label": f"{collection.currency} {collection.balance}",
        "paid_label": f"{collection.currency} {collection.amount_paid}",
        "due_label": due_label,
        "promise_label": promise_label,
        "last_touch_label": last_touch_label,
        "health_badge": {
            "label": "Vencida" if status["is_overdue"] else ("Promesa" if collection.status == CollectionRecord.STATUS_PROMISED else "Al dia"),
            "tone": "danger" if status["is_overdue"] else ("info" if collection.status == CollectionRecord.STATUS_PROMISED else "success"),
        },
    }


def _format_currency_amount(currency: str, amount) -> str:
    numeric = float(amount or 0)
    decimals = 0 if numeric.is_integer() else 2
    return f"{currency} {numeric:,.{decimals}f}"


def _truncate_inline(text: str, limit: int = 88) -> str:
    value = " ".join((text or "").split())
    if len(value) <= limit:
        return value
    return f"{value[: limit - 1].rstrip()}…"


def _deal_health_badge(deal: Deal, *, today=None) -> dict:
    today = today or timezone.localdate()
    if deal.expected_close_on and deal.expected_close_on < today:
        return {"label": "Atrasado", "tone": "danger"}
    if deal.expected_close_on and deal.expected_close_on <= today + timedelta(days=7):
        return {"label": f"Cierra {deal.expected_close_on.strftime('%d/%m')}", "tone": "warn"}

    last_touch_at = getattr(deal, "last_activity_at", None) or deal.updated_at
    if last_touch_at:
        last_touch_date = timezone.localtime(last_touch_at).date()
        days_without_touch = max((today - last_touch_date).days, 0)
        if days_without_touch >= 10:
            return {"label": "Sin toque", "tone": "danger"}
        if days_without_touch >= 5:
            return {"label": "Frio", "tone": "warn"}

    return {"label": "Activo", "tone": "good"}


def _build_deal_board_card(deal: Deal, *, today=None) -> dict:
    today = today or timezone.localdate()
    last_touch_at = getattr(deal, "last_activity_at", None) or deal.updated_at
    last_touch_label = "Sin toque"
    if last_touch_at:
        last_touch_local = timezone.localtime(last_touch_at)
        days_without_touch = max((today - last_touch_local.date()).days, 0)
        if days_without_touch == 0:
            last_touch_label = "Toque hoy"
        elif days_without_touch == 1:
            last_touch_label = "Toque ayer"
        else:
            last_touch_label = f"{days_without_touch}d sin toque"

    contact_hint = " | ".join(
        part
        for part in [
            deal.entity.legal_id,
            deal.entity.phone or deal.entity.email,
        ]
        if part
    ) or "Sin dato rapido"
    note_source = deal.notes or deal.entity.notes or ""

    return {
        "deal": deal,
        "amount_label": _format_currency_amount(deal.currency, deal.amount),
        "contact_hint": contact_hint,
        "summary": _truncate_inline(note_source, 96) if note_source else "",
        "health_badge": _deal_health_badge(deal, today=today),
        "last_touch_label": last_touch_label,
        "proposal_count": getattr(deal, "proposal_count", 0),
        "activity_count": getattr(deal, "activity_count", 0),
        "document_count": getattr(deal, "document_count", 0),
        "close_label": (
            deal.expected_close_on.strftime("%d/%m/%Y")
            if deal.expected_close_on
            else ""
        ),
    }


def _build_entity_timeline(
    entity: Entity,
    *,
    profile: str,
    blueprint_map: dict[str, dict],
    custom_blueprints=None,
    include_deals: bool = True,
    include_proposals: bool = True,
    include_collections: bool = True,
    include_activities: bool = True,
    include_documents: bool = True,
) -> list[dict]:
    return build_recorded_entity_timeline(
        entity,
        include_deals=include_deals,
        include_proposals=include_proposals,
        include_collections=include_collections,
        include_activities=include_activities,
        include_documents=include_documents,
    )


def _build_document_filters(documents_qs, *, document_blueprints: list[dict], selected_type: str) -> list[dict]:
    count_rows = documents_qs.values("document_type").annotate(total=Count("id"))
    totals = {row["document_type"]: row["total"] for row in count_rows}
    filters = [
        {
            "key": "",
            "label": "Todos",
            "count": sum(totals.values()),
            "active": selected_type == "",
        }
    ]
    for blueprint in document_blueprints:
        filters.append(
            {
                "key": blueprint["key"],
                "label": blueprint["label"],
                "count": totals.get(blueprint["key"], 0),
                "active": selected_type == blueprint["key"],
            }
        )
    return filters


def _append_deal_to_stage_end(deal: Deal) -> None:
    existing_orders = list(
        Deal.objects.filter(
            pipeline=deal.pipeline,
            stage=deal.stage,
            is_active=True,
        )
        .exclude(pk=deal.pk)
        .values_list("sort_order", flat=True)
        .order_by("sort_order", "id")
    )
    deal.sort_order = (max(existing_orders) + 100) if existing_orders else 100


def _append_collection_to_status_end(collection: CollectionRecord) -> None:
    existing_orders = list(
        CollectionRecord.objects.filter(
            status=collection.status,
            is_active=True,
        )
        .exclude(pk=collection.pk)
        .values_list("sort_order", flat=True)
        .order_by("sort_order", "id")
    )
    collection.sort_order = (max(existing_orders) + 100) if existing_orders else 100


def _resequence_stage(pipeline: Pipeline, stage: str, *, moving_deal=None, position: int | None = None) -> int | None:
    stage_deals = list(
        Deal.objects.filter(pipeline=pipeline, stage=stage, is_active=True)
        .exclude(pk=getattr(moving_deal, "pk", None))
        .order_by("sort_order", "id")
    )
    inserted_index = None
    if moving_deal is not None:
        bounded_position = max(0, min(position or 0, len(stage_deals)))
        stage_deals.insert(bounded_position, moving_deal)
        inserted_index = bounded_position

    changed_deals = []
    for index, stage_deal in enumerate(stage_deals, start=1):
        new_sort_order = index * 100
        if stage_deal.sort_order != new_sort_order:
            stage_deal.sort_order = new_sort_order
            changed_deals.append(stage_deal)

    if changed_deals:
        Deal.objects.bulk_update(changed_deals, ["sort_order"])
    return inserted_index


def _resequence_collection_status(status: str, *, moving_collection=None, position: int | None = None) -> int | None:
    status_collections = list(
        CollectionRecord.objects.filter(status=status, is_active=True)
        .exclude(pk=getattr(moving_collection, "pk", None))
        .order_by("sort_order", "due_on", "-updated_at", "id")
    )
    inserted_index = None
    if moving_collection is not None:
        bounded_position = max(0, min(position or 0, len(status_collections)))
        status_collections.insert(bounded_position, moving_collection)
        inserted_index = bounded_position

    changed_collections = []
    for index, record in enumerate(status_collections, start=1):
        new_sort_order = index * 100
        if record.sort_order != new_sort_order:
            record.sort_order = new_sort_order
            changed_collections.append(record)

    if changed_collections:
        CollectionRecord.objects.bulk_update(changed_collections, ["sort_order"])
    return inserted_index


def _render_entity_form(request, form, *, page_title: str, submit_label: str, entity=None):
    return render(
        request,
        "binncrm/entity_form.html",
        {
            "form": form,
            "entity": entity,
            "page_title": page_title,
            "submit_label": submit_label,
            "labels": request.tenant.tenant_config.labels,
        },
    )


def _render_deal_form(request, form, *, page_title: str, submit_label: str, deal=None):
    return render(
        request,
        "binncrm/deal_form.html",
        {
            "form": form,
            "deal": deal,
            "page_title": page_title,
            "submit_label": submit_label,
            "labels": request.tenant.tenant_config.labels,
            "pipeline_stage_map_json": json.dumps(form.pipeline_stage_map, ensure_ascii=True),
            "can_view_collab": request.tenant.has_capability("collab") and _can(request, PERMISSION_COLLAB_VIEW),
        },
    )


def _render_proposal_form(request, form, *, page_title: str, submit_label: str, proposal=None):
    return render(
        request,
        "binncrm/proposal_form.html",
        {
            "form": form,
            "proposal": proposal,
            "page_title": page_title,
            "submit_label": submit_label,
            "labels": request.tenant.tenant_config.labels,
        },
    )


def _render_collection_form(request, form, *, page_title: str, submit_label: str, collection=None):
    return render(
        request,
        "binncrm/collection_form.html",
        {
            "form": form,
            "collection": collection,
            "page_title": page_title,
            "submit_label": submit_label,
            "labels": request.tenant.tenant_config.labels,
        },
    )


def _render_document_form(request, form, *, page_title: str, submit_label: str, document=None):
    profile = _tenant_profile(request.tenant)
    custom_blueprints = request.tenant.document_blueprints
    return render(
        request,
        "binncrm/document_form.html",
        {
            "labels": request.tenant.tenant_config.labels,
            "form": form,
            "document": document,
            "page_title": page_title,
            "submit_label": submit_label,
            "document_blueprints": get_document_blueprints(profile, custom_blueprints=custom_blueprints),
        },
    )


def _sync_proposal_timestamps(proposal: Proposal, *, previous_status: str | None = None) -> None:
    now = timezone.now()
    if proposal.status == Proposal.STATUS_SENT and proposal.sent_at is None:
        proposal.sent_at = now
    if proposal.status in {Proposal.STATUS_ACCEPTED, Proposal.STATUS_REJECTED, Proposal.STATUS_EXPIRED} and proposal.responded_at is None:
        proposal.responded_at = now
    if proposal.status == Proposal.STATUS_DRAFT and previous_status != Proposal.STATUS_DRAFT:
        proposal.responded_at = None


@login_required
@tenant_permission_required(PERMISSION_DEALS_VIEW, capability="deals")
def index(request):
    labels = request.tenant.tenant_config.labels
    entity_fields = get_entity_field_definitions(tenant=request.tenant)
    active_saved_filter, saved_filter_defaults = _resolve_active_saved_filter(
        request,
        object_type=SavedWorkspaceFilter.OBJECT_DEAL,
    )
    saved_views = get_saved_views(object_key="deal", tenant=request.tenant)
    current_view = resolve_saved_view(
        object_key="deal",
        tenant=request.tenant,
        view_key=_resolve_filter_value(request, key="view", defaults=saved_filter_defaults),
    )
    pipelines = list(Pipeline.objects.filter(is_active=True).order_by("position", "name"))
    current_pipeline = None
    pipeline_id = _resolve_filter_value(request, key="pipeline", defaults=saved_filter_defaults)
    if pipeline_id:
        current_pipeline = next((pipeline for pipeline in pipelines if str(pipeline.pk) == pipeline_id), None)
    if current_pipeline is None and pipelines:
        current_pipeline = pipelines[0]

    q = _resolve_filter_value(request, key="q", defaults=saved_filter_defaults)
    deals = (
        Deal.objects.select_related("entity", "pipeline")
        .annotate(
            activity_count=Count("activities", distinct=True),
            proposal_count=Count("proposals", distinct=True),
            document_count=Count("documents", distinct=True),
            last_activity_at=Max("activities__created_at"),
        )
        .filter(is_active=True)
    )
    if current_pipeline:
        deals = deals.filter(pipeline=current_pipeline)
    deals = apply_deal_saved_view(deals, view=current_view)
    if q:
        deals = deals.filter(Q(title__icontains=q) | _build_entity_search_query(q, entity_fields, prefix="entity__"))

    stage_tones = [
        {"accent": "#16a34a", "alt": "#65a30d", "soft": "rgba(22, 163, 74, 0.08)"},
        {"accent": "#0284c7", "alt": "#0ea5e9", "soft": "rgba(14, 165, 233, 0.08)"},
        {"accent": "#7c3aed", "alt": "#c026d3", "soft": "rgba(168, 85, 247, 0.08)"},
        {"accent": "#ea580c", "alt": "#f59e0b", "soft": "rgba(249, 115, 22, 0.08)"},
        {"accent": "#0f766e", "alt": "#14b8a6", "soft": "rgba(20, 184, 166, 0.08)"},
    ]
    today = timezone.localdate()
    grouped_deals = []
    stages = current_pipeline.stage_choices if current_pipeline else []
    raw_deals = list(deals.order_by("sort_order", "-updated_at", "id"))
    deals_by_stage = {stage: [] for stage in stages}
    for deal in raw_deals:
        deals_by_stage.setdefault(deal.stage, []).append(deal)
    for index, stage in enumerate(stages):
        raw_stage_deals = deals_by_stage.get(stage, [])
        stage_cards = [_build_deal_board_card(deal, today=today) for deal in raw_stage_deals]
        stage_currency = raw_stage_deals[0].currency if raw_stage_deals else "USD"
        tone = stage_tones[index % len(stage_tones)]
        grouped_deals.append(
            {
                "stage": stage,
                "deals": stage_cards,
                "count": len(stage_cards),
                "total_amount_label": _format_currency_amount(
                    stage_currency,
                    sum(deal.amount for deal in raw_stage_deals),
                ),
                "tone": tone,
            }
        )

    context = {
        "labels": labels,
        "pipelines": pipelines,
        "current_pipeline": current_pipeline,
        "saved_views": saved_views,
        "current_view": current_view,
        "saved_filters": _build_saved_filter_items(
            request,
            object_type=SavedWorkspaceFilter.OBJECT_DEAL,
            route_name="binncrm:index",
            active_filter=active_saved_filter,
        ),
        "active_saved_filter_id": getattr(active_saved_filter, "pk", None),
        "saved_filter_form": SavedWorkspaceFilterForm(
            object_type=SavedWorkspaceFilter.OBJECT_DEAL,
            initial={
                "q": q,
                "view": current_view.get("key", ""),
                "pipeline": str(current_pipeline.pk) if current_pipeline else "",
            },
        ),
        "grouped_deals": grouped_deals,
        "q": q,
        "can_create_deal": _can(request, PERMISSION_DEALS_EDIT),
        "can_edit_deal": _can(request, PERMISSION_DEALS_EDIT),
        "can_move_deals": _can(request, PERMISSION_DEALS_MOVE),
        "can_manage_pipelines": _can_manage_pipeline_settings(request),
        "can_view_collab": request.tenant.has_capability("collab") and _can(request, PERMISSION_COLLAB_VIEW),
    }
    template_name = "binncrm/_kanban_board.html" if _is_htmx(request) else "binncrm/index.html"
    return render(request, template_name, context)


@login_required
@tenant_permission_required(PERMISSION_DEALS_VIEW, capability="deals")
@require_POST
def deal_filter_save(request):
    form = SavedWorkspaceFilterForm(
        request.POST,
        object_type=SavedWorkspaceFilter.OBJECT_DEAL,
    )
    params = _normalize_saved_filter_params(
        object_type=SavedWorkspaceFilter.OBJECT_DEAL,
        raw_params=request.POST,
    )
    if form.is_valid():
        saved_filter, created = SavedWorkspaceFilter.objects.update_or_create(
            owner=request.user,
            object_type=SavedWorkspaceFilter.OBJECT_DEAL,
            label=form.cleaned_data["label"],
            defaults={
                "params": form.cleaned_data["normalized_params"],
                "created_by": request.user,
                "updated_by": request.user,
            },
        )
        if not created:
            saved_filter.updated_by = request.user
            saved_filter.params = form.cleaned_data["normalized_params"]
            saved_filter.save(update_fields=["params", "updated_by", "updated_at"])
        messages.success(request, f"Filtro '{saved_filter.label}' guardado para deals.")
        return redirect(
            _build_saved_filter_redirect(
                "binncrm:index",
                params=form.cleaned_data["normalized_params"],
                saved_filter_id=saved_filter.pk,
            )
        )
    messages.error(request, next(iter(form.errors.get("label", [])), "No pude guardar ese filtro."))
    return redirect(_build_saved_filter_redirect("binncrm:index", params=params))


@login_required
@tenant_permission_required(PERMISSION_DEALS_VIEW, capability="deals")
@require_POST
def deal_filter_delete(request, pk):
    saved_filter = get_object_or_404(
        SavedWorkspaceFilter,
        pk=pk,
        owner=request.user,
        object_type=SavedWorkspaceFilter.OBJECT_DEAL,
    )
    filter_label = saved_filter.label
    saved_filter.delete()
    messages.success(request, f"Filtro '{filter_label}' eliminado.")
    return redirect("binncrm:index")


@login_required
@tenant_permission_required(PERMISSION_DEALS_VIEW, capability="deals")
@tenant_role_required(*CRM_ADMIN_ALLOWED_ROLES)
def pipeline_settings(request):
    tenant = request.tenant
    rows, stale_rows = _build_pipeline_admin_rows(request)
    selected_key = (request.GET.get("pipeline") or request.POST.get("pipeline_key") or "").strip().lower()
    selected_row = next((row for row in rows if row["key"] == selected_key), rows[0] if rows else None)

    if request.method == "POST":
        action = (request.POST.get("action") or "save").strip().lower()
        if action == "save":
            form = PipelineTemplateEditorForm(
                request.POST,
                existing_keys=[row["key"] for row in rows],
                current_key=selected_row["key"] if selected_row and selected_row["key"] == selected_key else selected_key,
            )
            if form.is_valid():
                payload = {
                    "key": form.cleaned_data["pipeline_key"],
                    "label": form.cleaned_data["label"],
                    "stages": form.cleaned_data["stages"],
                }
                templates = list(getattr(tenant.tenant_config, "pipeline_templates", []) or [])
                is_edit = any(item.get("key") == payload["key"] for item in templates)
                templates = _replace_pipeline_template(templates, payload["key"], payload)
                if form.cleaned_data.get("make_default") or len(templates) == 1:
                    templates = _set_default_pipeline_template(templates, payload["key"])

                notices = _persist_tenant_pipeline_templates(
                    request,
                    templates=templates,
                    event_title="Pipeline comercial actualizado",
                    event_message=(
                        f"Se {'edito' if is_edit else 'creo'} el pipeline '{payload['label']}' desde la empresa."
                    ),
                    event_code="tenant_pipeline_upserted",
                    metadata={"pipeline_key": payload["key"], "stages": payload["stages"]},
                )
                for notice in notices:
                    messages.info(request, notice)
                messages.success(
                    request,
                    f"Pipeline '{payload['label']}' {'actualizado' if is_edit else 'creado'} correctamente.",
                )
                return redirect(f"{reverse('binncrm:pipeline_settings')}?pipeline={payload['key']}")
            selected_key = (form.data.get("pipeline_key") or "").strip().lower()
        else:
            pipeline_key = (request.POST.get("pipeline_key") or "").strip().lower()
            templates = list(getattr(tenant.tenant_config, "pipeline_templates", []) or [])
            pipeline_label = next((item.get("label", pipeline_key) for item in templates if item.get("key") == pipeline_key), pipeline_key)

            if action == "remove":
                if len(templates) <= 1:
                    messages.error(request, "Debes dejar al menos un pipeline activo para esta empresa.")
                    return redirect(reverse("binncrm:pipeline_settings"))
                templates = _remove_pipeline_template(templates, pipeline_key)
                notices = _persist_tenant_pipeline_templates(
                    request,
                    templates=templates,
                    event_title="Pipeline removido de configuracion",
                    event_message=f"Se saco el pipeline '{pipeline_label}' de la configuracion principal de la empresa.",
                    event_code="tenant_pipeline_removed",
                    metadata={"pipeline_key": pipeline_key},
                )
                for notice in notices:
                    messages.info(request, notice)
                messages.success(request, f"Pipeline '{pipeline_label}' removido de la configuracion activa.")
                return redirect(reverse("binncrm:pipeline_settings"))

            if action == "set_default":
                templates = _set_default_pipeline_template(templates, pipeline_key)
                notices = _persist_tenant_pipeline_templates(
                    request,
                    templates=templates,
                    event_title="Pipeline principal cambiado",
                    event_message=f"El pipeline '{pipeline_label}' quedo como flujo principal de oportunidades.",
                    event_code="tenant_pipeline_default_changed",
                    metadata={"pipeline_key": pipeline_key},
                )
                for notice in notices:
                    messages.info(request, notice)
                messages.success(request, f"'{pipeline_label}' ahora es el pipeline principal.")
                return redirect(f"{reverse('binncrm:pipeline_settings')}?pipeline={pipeline_key}")

            if action in {"move_up", "move_down"}:
                direction = -1 if action == "move_up" else 1
                templates = _move_pipeline_template(templates, pipeline_key, direction)
                notices = _persist_tenant_pipeline_templates(
                    request,
                    templates=templates,
                    event_title="Orden de pipelines actualizado",
                    event_message=f"Se movio el pipeline '{pipeline_label}' dentro del orden comercial.",
                    event_code="tenant_pipeline_reordered",
                    metadata={"pipeline_key": pipeline_key, "direction": action},
                )
                for notice in notices:
                    messages.info(request, notice)
                messages.success(request, f"Orden de '{pipeline_label}' actualizado.")
                return redirect(f"{reverse('binncrm:pipeline_settings')}?pipeline={pipeline_key}")

            form = PipelineTemplateEditorForm()
    else:
        form = None

    rows, stale_rows = _build_pipeline_admin_rows(request)
    selected_row = next((row for row in rows if row["key"] == selected_key), rows[0] if rows else None)
    if form is None:
        initial = {}
        if selected_row is not None:
            initial = {
                "pipeline_key": selected_row["key"],
                "label": selected_row["label"],
                "stages_text": "\n".join(selected_row["stages"]),
                "make_default": selected_row["is_default"],
            }
        form = PipelineTemplateEditorForm(
            initial=initial,
            existing_keys=[row["key"] for row in rows],
            current_key=selected_row["key"] if selected_row else "",
        )

    context = {
        "labels": tenant.tenant_config.labels,
        "pipeline_rows": rows,
        "stale_pipeline_rows": stale_rows,
        "selected_pipeline": selected_row,
        "form": form,
    }
    return render(request, "binncrm/pipeline_settings.html", context)


@login_required
@tenant_permission_required(PERMISSION_ENTITIES_VIEW, capability="entities")
def entities(request):
    labels = request.tenant.tenant_config.labels
    entity_fields = get_entity_field_definitions(tenant=request.tenant)
    active_saved_filter, saved_filter_defaults = _resolve_active_saved_filter(
        request,
        object_type=SavedWorkspaceFilter.OBJECT_ENTITY,
    )
    q = _resolve_filter_value(request, key="q", defaults=saved_filter_defaults)
    saved_views = get_saved_views(object_key="entity", tenant=request.tenant)
    current_view = resolve_saved_view(
        object_key="entity",
        tenant=request.tenant,
        view_key=_resolve_filter_value(request, key="view", defaults=saved_filter_defaults),
    )
    queryset = Entity.objects.filter(is_active=True)
    queryset = apply_entity_saved_view(queryset, view=current_view)
    if q:
        queryset = queryset.filter(_build_entity_search_query(q, entity_fields))

    entity_list = list(queryset[:100])
    column_definitions = entity_fields[:2]
    entity_rows = [
        {
            "instance": entity,
            "extra_values": _build_extra_values(entity, column_definitions),
        }
        for entity in entity_list
    ]

    context = {
        "labels": labels,
        "entities": entity_rows,
        "entity_field_columns": column_definitions,
        "entity_table_colspan": 5 + len(column_definitions),
        "searchable_fields": [field["label"] for field in entity_fields],
        "saved_views": saved_views,
        "current_view": current_view,
        "saved_filters": _build_saved_filter_items(
            request,
            object_type=SavedWorkspaceFilter.OBJECT_ENTITY,
            route_name="binncrm:entities",
            active_filter=active_saved_filter,
        ),
        "active_saved_filter_id": getattr(active_saved_filter, "pk", None),
        "saved_filter_form": SavedWorkspaceFilterForm(
            object_type=SavedWorkspaceFilter.OBJECT_ENTITY,
            initial={
                "q": q,
                "view": current_view.get("key", ""),
            },
        ),
        "q": q,
        "can_create_entity": _can(request, PERMISSION_ENTITIES_EDIT),
        "can_import_entities": _can(request, PERMISSION_ENTITIES_EDIT),
        "can_manage_related": {
            "deals": _can(request, PERMISSION_DEALS_EDIT),
            "proposals": _can(request, PERMISSION_PROPOSALS_EDIT),
            "collections": _can(request, PERMISSION_COLLECTIONS_EDIT),
            "activities": _can(request, PERMISSION_ACTIVITIES_EDIT),
            "documents": _can(request, PERMISSION_DOCUMENTS_EDIT),
        },
    }
    template_name = "binncrm/_entity_table.html" if _is_htmx(request) else "binncrm/entities.html"
    return render(request, template_name, context)


@login_required
@tenant_permission_required(PERMISSION_ENTITIES_VIEW, capability="entities")
@require_POST
def entity_filter_save(request):
    form = SavedWorkspaceFilterForm(
        request.POST,
        object_type=SavedWorkspaceFilter.OBJECT_ENTITY,
    )
    params = _normalize_saved_filter_params(
        object_type=SavedWorkspaceFilter.OBJECT_ENTITY,
        raw_params=request.POST,
    )
    if form.is_valid():
        saved_filter, created = SavedWorkspaceFilter.objects.update_or_create(
            owner=request.user,
            object_type=SavedWorkspaceFilter.OBJECT_ENTITY,
            label=form.cleaned_data["label"],
            defaults={
                "params": form.cleaned_data["normalized_params"],
                "created_by": request.user,
                "updated_by": request.user,
            },
        )
        if not created:
            saved_filter.updated_by = request.user
            saved_filter.params = form.cleaned_data["normalized_params"]
            saved_filter.save(update_fields=["params", "updated_by", "updated_at"])
        messages.success(request, f"Filtro '{saved_filter.label}' guardado para contactos.")
        return redirect(
            _build_saved_filter_redirect(
                "binncrm:entities",
                params=form.cleaned_data["normalized_params"],
                saved_filter_id=saved_filter.pk,
            )
        )
    messages.error(request, next(iter(form.errors.get("label", [])), "No pude guardar ese filtro."))
    return redirect(_build_saved_filter_redirect("binncrm:entities", params=params))


@login_required
@tenant_permission_required(PERMISSION_ENTITIES_VIEW, capability="entities")
@require_POST
def entity_filter_delete(request, pk):
    saved_filter = get_object_or_404(
        SavedWorkspaceFilter,
        pk=pk,
        owner=request.user,
        object_type=SavedWorkspaceFilter.OBJECT_ENTITY,
    )
    filter_label = saved_filter.label
    saved_filter.delete()
    messages.success(request, f"Filtro '{filter_label}' eliminado.")
    return redirect("binncrm:entities")


@login_required
def global_search(request):
    if request.tenant.schema_name == "public":
        return redirect("dashboard")
    labels = request.tenant.tenant_config.labels
    q = (request.GET.get("q") or "").strip()
    sections = _build_global_search_sections(request, query=q)
    total_results = sum(section["count"] for section in sections)
    return render(
        request,
        "binncrm/global_search.html",
        {
            "labels": labels,
            "q": q,
            "result_sections": sections,
            "total_results": total_results,
            "has_query": bool(q),
        },
    )


@login_required
@tenant_permission_required(PERMISSION_ENTITIES_EDIT, capability="entities")
def entity_import(request):
    import_summary = None
    if request.method == "POST":
        form = EntityImportForm(request.POST, request.FILES)
        if form.is_valid():
            try:
                import_summary = import_entities_from_csv(
                    form.cleaned_data["csv_file"],
                    tenant=request.tenant,
                    actor=request.user,
                    update_existing=form.cleaned_data["update_existing"],
                )
            except ValueError as exc:
                form.add_error("csv_file", str(exc))
            else:
                messages.success(
                    request,
                    f"Importacion completada: {import_summary['created']} creadas, {import_summary['updated']} actualizadas.",
                )
    else:
        form = EntityImportForm()

    return render(
        request,
        "binncrm/entity_import.html",
        {
            "labels": request.tenant.tenant_config.labels,
            "form": form,
            "import_summary": import_summary,
            "sample_columns": [
                "nombre",
                "cedula",
                "telefono",
                "correo",
                "notas",
                *[field["key"] for field in get_entity_field_definitions(tenant=request.tenant)],
            ],
        },
    )


@login_required
@tenant_permission_required(PERMISSION_ENTITIES_EDIT, capability="entities")
def entity_create(request):
    if request.method == "POST":
        form = EntityForm(request.POST, tenant=request.tenant)
        if form.is_valid():
            entity = form.save(commit=False)
            entity.created_by = request.user
            entity.updated_by = request.user
            entity.save()
            log_entity_created(
                entity=entity,
                actor=request.user,
                kind_label=request.tenant.get_label("entity_singular", "Contacto"),
            )
            messages.success(request, "Entidad creada correctamente.")
            return redirect("binncrm:entity_detail", pk=entity.pk)
    else:
        form = EntityForm(tenant=request.tenant, initial={"is_active": True})

    return _render_entity_form(
        request,
        form,
        page_title=f"Nuevo {request.tenant.get_label('entity_singular', 'Contacto')}",
        submit_label="Guardar",
    )


@login_required
@tenant_permission_required(PERMISSION_ENTITIES_VIEW, capability="entities")
def entity_detail(request, pk):
    entity = get_object_or_404(Entity, pk=pk)
    extra_values = _build_extra_values(entity, get_entity_field_definitions(tenant=request.tenant))
    profile = _tenant_profile(request.tenant)
    custom_blueprints = request.tenant.document_blueprints
    blueprint_map = get_document_blueprint_map(profile, custom_blueprints=custom_blueprints)
    can_view_deals = _can(request, PERMISSION_DEALS_VIEW)
    can_view_proposals = _can(request, PERMISSION_PROPOSALS_VIEW)
    can_view_collections = _can(request, PERMISSION_COLLECTIONS_VIEW)
    can_view_activities = _can(request, PERMISSION_ACTIVITIES_VIEW)
    can_view_collab = request.tenant.has_capability("collab") and _can(request, PERMISSION_COLLAB_VIEW)
    can_view_documents = _can(request, PERMISSION_DOCUMENTS_VIEW)
    all_documents = (
        list(entity.documents.select_related("deal").order_by("-created_at"))
        if can_view_documents
        else []
    )
    recent_documents = all_documents[:6]
    open_tasks = (
        list(
            entity.activities.select_related("deal", "assigned_to")
            .filter(activity_type=Activity.TYPE_TASK, completed_at__isnull=True)
            .order_by("due_at", "-created_at")[:6]
        )
        if can_view_activities
        else []
    )
    recent_proposals = (
        list(entity.proposals.select_related("deal").order_by("-updated_at")[:5])
        if can_view_proposals
        else []
    )
    recent_collections = (
        list(entity.collections.select_related("deal").order_by("due_on", "-updated_at")[:5])
        if can_view_collections
        else []
    )
    context = {
        "labels": request.tenant.tenant_config.labels,
        "entity": entity,
        "recent_deals": entity.deals.select_related("pipeline").order_by("-updated_at")[:5] if can_view_deals else [],
        "recent_proposal_cards": [_build_proposal_card(proposal) for proposal in recent_proposals],
        "recent_collection_cards": [_build_collection_card(collection) for collection in recent_collections],
        "recent_activities": (
            entity.activities.select_related("deal", "assigned_to").order_by("-created_at")[:6]
            if can_view_activities
            else []
        ),
        "recent_document_cards": [
            _build_document_card(
                document,
                profile=profile,
                blueprint_map=blueprint_map,
                custom_blueprints=custom_blueprints,
            )
            for document in recent_documents
        ],
        "filled_extra_values": [item for item in extra_values if item["has_value"]],
        "empty_extra_values": [item for item in extra_values if not item["has_value"]],
        "extra_values": extra_values,
        "open_task_cards": [_build_task_card(activity) for activity in open_tasks],
        "broker_document_checklist": (
            _build_broker_document_checklist(entity, all_documents, blueprint_map=blueprint_map)
            if profile == "broker"
            else []
        ),
        "timeline_items": _build_entity_timeline(
            entity,
            profile=profile,
            blueprint_map=blueprint_map,
            custom_blueprints=custom_blueprints,
            include_deals=can_view_deals,
            include_proposals=can_view_proposals,
            include_collections=can_view_collections,
            include_activities=can_view_activities,
            include_documents=can_view_documents,
        ),
        "can_view_deals": can_view_deals,
        "can_view_proposals": can_view_proposals,
        "can_view_collections": can_view_collections,
        "can_view_activities": can_view_activities,
        "can_view_collab": can_view_collab,
        "can_view_documents": can_view_documents,
        "can_edit_entity": _can(request, PERMISSION_ENTITIES_EDIT),
        "can_create_deal": _can(request, PERMISSION_DEALS_EDIT),
        "can_create_proposal": _can(request, PERMISSION_PROPOSALS_EDIT),
        "can_create_collection": _can(request, PERMISSION_COLLECTIONS_EDIT),
        "can_create_activity": _can(request, PERMISSION_ACTIVITIES_EDIT),
        "can_create_document": _can(request, PERMISSION_DOCUMENTS_EDIT),
        "can_complete_tasks": _can(request, PERMISSION_ACTIVITIES_COMPLETE),
    }
    return render(request, "binncrm/entity_detail.html", context)


@login_required
@tenant_permission_required(PERMISSION_ENTITIES_EDIT, capability="entities")
def entity_edit(request, pk):
    entity = get_object_or_404(Entity, pk=pk)
    if request.method == "POST":
        form = EntityForm(request.POST, instance=entity, tenant=request.tenant)
        if form.is_valid():
            changed_fields = list(form.changed_data)
            entity = form.save(commit=False)
            entity.updated_by = request.user
            entity.save()
            if changed_fields:
                log_entity_updated(
                    entity=entity,
                    actor=request.user,
                    kind_label=request.tenant.get_label("entity_singular", "Contacto"),
                    changed_fields=changed_fields,
                )
            messages.success(request, "Entidad actualizada correctamente.")
            return redirect("binncrm:entity_detail", pk=entity.pk)
    else:
        form = EntityForm(instance=entity, tenant=request.tenant)

    return _render_entity_form(
        request,
        form,
        entity=entity,
        page_title=f"Editar {request.tenant.get_label('entity_singular', 'Contacto')}",
        submit_label="Guardar cambios",
    )


@login_required
@tenant_permission_required(PERMISSION_DEALS_EDIT, capability="deals")
def deal_create(request):
    initial = {"is_active": True, "status": Deal.STATUS_OPEN}
    entity_id = (request.GET.get("entity") or "").strip()
    if entity_id.isdigit():
        initial["entity"] = entity_id
    if request.method == "POST":
        form = DealForm(request.POST, tenant=request.tenant)
        if form.is_valid():
            deal = form.save(commit=False)
            deal.created_by = request.user
            deal.updated_by = request.user
            _append_deal_to_stage_end(deal)
            deal.save()
            log_deal_created(
                deal=deal,
                actor=request.user,
                kind_label=request.tenant.get_label("deal_singular", "Deal"),
            )
            messages.success(request, "Deal creado correctamente.")
            return redirect("binncrm:index")
    else:
        form = DealForm(tenant=request.tenant, initial=initial)

    return _render_deal_form(
        request,
        form,
        page_title=f"Nuevo {request.tenant.get_label('deal_singular', 'Deal')}",
        submit_label="Guardar",
    )


@login_required
@tenant_permission_required(PERMISSION_DEALS_EDIT, capability="deals")
def deal_edit(request, pk):
    deal = get_object_or_404(Deal, pk=pk)
    original_pipeline_id = deal.pipeline_id
    original_pipeline_name = getattr(deal.pipeline, "name", "")
    original_stage = deal.stage
    if request.method == "POST":
        form = DealForm(request.POST, instance=deal, tenant=request.tenant)
        if form.is_valid():
            changed_fields = list(form.changed_data)
            deal = form.save(commit=False)
            deal.updated_by = request.user
            moved_stage = deal.pipeline_id != original_pipeline_id or deal.stage != original_stage
            if moved_stage:
                _append_deal_to_stage_end(deal)
            deal.save()
            if moved_stage:
                _resequence_stage(deal.pipeline, deal.stage)
                if original_pipeline_id and original_stage:
                    previous_pipeline = Pipeline.objects.filter(pk=original_pipeline_id).first()
                    if previous_pipeline is not None:
                        _resequence_stage(previous_pipeline, original_stage)
                log_deal_stage_changed(
                    deal=deal,
                    actor=request.user,
                    kind_label=request.tenant.get_label("deal_singular", "Deal"),
                    previous_stage=original_stage,
                    previous_pipeline_name=original_pipeline_name,
                )
            elif changed_fields:
                log_deal_updated(
                    deal=deal,
                    actor=request.user,
                    kind_label=request.tenant.get_label("deal_singular", "Deal"),
                    changed_fields=changed_fields,
                )
            messages.success(request, "Deal actualizado correctamente.")
            return redirect("binncrm:index")
    else:
        form = DealForm(instance=deal, tenant=request.tenant)

    return _render_deal_form(
        request,
        form,
        deal=deal,
        page_title=f"Editar {request.tenant.get_label('deal_singular', 'Deal')}",
        submit_label="Guardar cambios",
    )


@login_required
@tenant_permission_required(PERMISSION_PROPOSALS_VIEW, capability="proposals")
def proposals(request):
    labels = request.tenant.tenant_config.labels
    q = (request.GET.get("q") or "").strip()
    selected_status = (request.GET.get("status") or "").strip()
    proposals_qs = Proposal.objects.select_related("entity", "deal").filter(is_active=True)
    if q:
        proposals_qs = proposals_qs.filter(
            Q(title__icontains=q)
            | Q(proposal_number__icontains=q)
            | Q(entity__full_name__icontains=q)
            | Q(deal__title__icontains=q)
        )
    if selected_status in {choice[0] for choice in Proposal.STATUS_CHOICES}:
        proposals_qs = proposals_qs.filter(status=selected_status)

    return render(
        request,
        "binncrm/proposals.html",
        {
            "labels": labels,
            "proposal_cards": [_build_proposal_card(proposal) for proposal in proposals_qs.order_by("-updated_at")[:100]],
            "proposal_statuses": Proposal.STATUS_CHOICES,
            "selected_status": selected_status,
            "q": q,
            "can_create_proposal": _can(request, PERMISSION_PROPOSALS_EDIT),
            "can_edit_proposal": _can(request, PERMISSION_PROPOSALS_EDIT),
        },
    )


@login_required
@tenant_permission_required(PERMISSION_PROPOSALS_EDIT, capability="proposals")
def proposal_create(request):
    initial = {"is_active": True, "status": Proposal.STATUS_DRAFT}
    entity_id = (request.GET.get("entity") or "").strip()
    deal_id = (request.GET.get("deal") or "").strip()
    if entity_id.isdigit():
        initial["entity"] = entity_id
    if deal_id.isdigit():
        initial["deal"] = deal_id
    if request.method == "POST":
        form = ProposalForm(request.POST, tenant=request.tenant)
        if form.is_valid():
            proposal = form.save(commit=False)
            proposal.created_by = request.user
            proposal.updated_by = request.user
            _sync_proposal_timestamps(proposal)
            proposal.save()
            log_proposal_created(
                proposal=proposal,
                actor=request.user,
                kind_label=request.tenant.get_label("proposal_singular", "Propuesta"),
            )
            messages.success(request, "Propuesta registrada correctamente.")
            return redirect("binncrm:proposals")
    else:
        form = ProposalForm(initial=initial, tenant=request.tenant)

    return _render_proposal_form(
        request,
        form,
        page_title=f"Nueva {request.tenant.get_label('proposal_singular', 'Propuesta')}",
        submit_label="Guardar propuesta",
    )


@login_required
@tenant_permission_required(PERMISSION_PROPOSALS_EDIT, capability="proposals")
def proposal_edit(request, pk):
    proposal = get_object_or_404(Proposal, pk=pk)
    original_status = proposal.status
    if request.method == "POST":
        form = ProposalForm(request.POST, instance=proposal, tenant=request.tenant)
        if form.is_valid():
            changed_fields = list(form.changed_data)
            proposal = form.save(commit=False)
            proposal.updated_by = request.user
            _sync_proposal_timestamps(proposal, previous_status=original_status)
            proposal.save()
            if changed_fields:
                log_proposal_updated(
                    proposal=proposal,
                    actor=request.user,
                    kind_label=request.tenant.get_label("proposal_singular", "Propuesta"),
                    changed_fields=changed_fields,
                    previous_status=original_status,
                )
            messages.success(request, "Propuesta actualizada correctamente.")
            return redirect("binncrm:proposals")
    else:
        form = ProposalForm(instance=proposal, tenant=request.tenant)

    return _render_proposal_form(
        request,
        form,
        proposal=proposal,
        page_title=f"Editar {request.tenant.get_label('proposal_singular', 'Propuesta')}",
        submit_label="Guardar cambios",
    )


@login_required
@tenant_permission_required(PERMISSION_COLLECTIONS_VIEW, capability="collections")
def collections(request):
    labels = request.tenant.tenant_config.labels
    q = (request.GET.get("q") or "").strip()
    selected_status = (request.GET.get("status") or "").strip()
    today = timezone.localdate()
    collections_qs = CollectionRecord.objects.select_related("entity", "deal").filter(is_active=True)
    if q:
        collections_qs = collections_qs.filter(
            Q(title__icontains=q)
            | Q(reference__icontains=q)
            | Q(entity__full_name__icontains=q)
            | Q(deal__title__icontains=q)
        )
    if selected_status in {choice[0] for choice in CollectionRecord.STATUS_CHOICES}:
        collections_qs = collections_qs.filter(status=selected_status)

    status_tones = {
        CollectionRecord.STATUS_PENDING: {"accent": "#f59e0b", "alt": "#fbbf24", "soft": "rgba(245, 158, 11, 0.12)"},
        CollectionRecord.STATUS_PROMISED: {"accent": "#2563eb", "alt": "#60a5fa", "soft": "rgba(37, 99, 235, 0.12)"},
        CollectionRecord.STATUS_OVERDUE: {"accent": "#dc2626", "alt": "#f97316", "soft": "rgba(220, 38, 38, 0.12)"},
        CollectionRecord.STATUS_DISPUTED: {"accent": "#7c3aed", "alt": "#a78bfa", "soft": "rgba(124, 58, 237, 0.12)"},
        CollectionRecord.STATUS_PAID: {"accent": "#059669", "alt": "#34d399", "soft": "rgba(5, 150, 105, 0.12)"},
    }
    grouped_collections = []
    visible_statuses = [selected_status] if selected_status in status_tones else [choice[0] for choice in CollectionRecord.STATUS_CHOICES]
    raw_collections = list(collections_qs.order_by("sort_order", "due_on", "-updated_at", "id"))
    collections_by_status = {status_key: [] for status_key in visible_statuses}
    for record in raw_collections:
        if record.status in collections_by_status:
            collections_by_status[record.status].append(record)
    for status_key in visible_statuses:
        raw_status_records = collections_by_status.get(status_key, [])
        status_currency = raw_status_records[0].currency if raw_status_records else "USD"
        grouped_collections.append(
            {
                "status": status_key,
                "label": dict(CollectionRecord.STATUS_CHOICES).get(status_key, status_key),
                "collections": [_build_collection_board_card(record, now=today) for record in raw_status_records],
                "count": len(raw_status_records),
                "total_balance_label": _format_currency_amount(
                    status_currency,
                    sum(record.balance for record in raw_status_records),
                ),
                "tone": status_tones[status_key],
            }
        )

    return render(
        request,
        "binncrm/collections.html",
        {
            "labels": labels,
            "grouped_collections": grouped_collections,
            "collection_statuses": CollectionRecord.STATUS_CHOICES,
            "selected_status": selected_status,
            "q": q,
            "can_create_collection": _can(request, PERMISSION_COLLECTIONS_EDIT),
            "can_edit_collection": _can(request, PERMISSION_COLLECTIONS_EDIT),
            "can_move_collections": _can(request, PERMISSION_COLLECTIONS_EDIT),
        },
    )


@login_required
@tenant_permission_required(PERMISSION_COLLECTIONS_EDIT, capability="collections")
def collection_create(request):
    initial = {"is_active": True, "status": CollectionRecord.STATUS_PENDING}
    entity_id = (request.GET.get("entity") or "").strip()
    deal_id = (request.GET.get("deal") or "").strip()
    if entity_id.isdigit():
        initial["entity"] = entity_id
    if deal_id.isdigit():
        initial["deal"] = deal_id
    if request.method == "POST":
        form = CollectionRecordForm(request.POST, tenant=request.tenant)
        if form.is_valid():
            collection = form.save(commit=False)
            collection.created_by = request.user
            collection.updated_by = request.user
            if collection.status != CollectionRecord.STATUS_PAID:
                collection.last_contacted_at = timezone.now()
            _append_collection_to_status_end(collection)
            collection.save()
            log_collection_created(
                collection=collection,
                actor=request.user,
                kind_label=request.tenant.get_label("collection_singular", "Cobranza"),
            )
            messages.success(request, "Cobranza registrada correctamente.")
            return redirect("binncrm:collections")
    else:
        form = CollectionRecordForm(initial=initial, tenant=request.tenant)

    return _render_collection_form(
        request,
        form,
        page_title=f"Nueva {request.tenant.get_label('collection_singular', 'Cobranza')}",
        submit_label="Guardar cobranza",
    )


@login_required
@tenant_permission_required(PERMISSION_COLLECTIONS_EDIT, capability="collections")
def collection_edit(request, pk):
    collection = get_object_or_404(CollectionRecord, pk=pk)
    original_status = collection.status
    if request.method == "POST":
        form = CollectionRecordForm(request.POST, instance=collection, tenant=request.tenant)
        if form.is_valid():
            changed_fields = list(form.changed_data)
            collection = form.save(commit=False)
            collection.updated_by = request.user
            collection.last_contacted_at = timezone.now()
            status_changed = collection.status != original_status
            with transaction.atomic():
                if status_changed:
                    _append_collection_to_status_end(collection)
                collection.save()
                if status_changed:
                    _resequence_collection_status(collection.status)
                    _resequence_collection_status(original_status)
            if changed_fields:
                log_collection_updated(
                    collection=collection,
                    actor=request.user,
                    kind_label=request.tenant.get_label("collection_singular", "Cobranza"),
                    changed_fields=changed_fields,
                    previous_status=original_status,
                )
            messages.success(request, "Cobranza actualizada correctamente.")
            return redirect("binncrm:collections")
    else:
        form = CollectionRecordForm(instance=collection, tenant=request.tenant)

    return _render_collection_form(
        request,
        form,
        collection=collection,
        page_title=f"Editar {request.tenant.get_label('collection_singular', 'Cobranza')}",
        submit_label="Guardar cambios",
    )


@login_required
@tenant_permission_required(PERMISSION_COLLECTIONS_EDIT, capability="collections")
@require_POST
def collection_move(request, pk):
    collection = get_object_or_404(CollectionRecord, pk=pk)
    status = (request.POST.get("status") or "").strip()
    try:
        position = max(int(request.POST.get("position", 0)), 0)
    except (TypeError, ValueError):
        position = 0
    valid_statuses = {choice[0] for choice in CollectionRecord.STATUS_CHOICES}
    if status not in valid_statuses:
        return JsonResponse({"ok": False, "message": "Estado invalido."}, status=400)

    previous_status = collection.status
    with transaction.atomic():
        collection.status = status
        collection.updated_by = request.user
        collection.last_contacted_at = timezone.now()
        collection.save(update_fields=["status", "updated_by", "last_contacted_at", "updated_at"])
        inserted_index = _resequence_collection_status(status, moving_collection=collection, position=position)
        if previous_status != status:
            _resequence_collection_status(previous_status)
            log_collection_updated(
                collection=collection,
                actor=request.user,
                kind_label=request.tenant.get_label("collection_singular", "Cobranza"),
                changed_fields=["status"],
                previous_status=previous_status,
            )

    return JsonResponse(
        {
            "ok": True,
            "status": status,
            "position": inserted_index if inserted_index is not None else position,
        }
    )


@login_required
@tenant_permission_required(PERMISSION_REPORTS_VIEW, capability="reports")
def reports(request):
    tenant = request.tenant
    labels = tenant.tenant_config.labels
    profile = _tenant_profile(tenant)
    feature_flags = tenant.tenant_config.feature_flags or {}
    now = timezone.now()
    today = timezone.localdate()
    custom_blueprints = tenant.document_blueprints
    blueprint_map = get_document_blueprint_map(profile, custom_blueprints=custom_blueprints)

    can_view_entities = feature_flags.get("entities") and _can(request, PERMISSION_ENTITIES_VIEW)
    can_view_deals = feature_flags.get("deals") and _can(request, PERMISSION_DEALS_VIEW)
    can_view_activities = feature_flags.get("activities") and _can(request, PERMISSION_ACTIVITIES_VIEW)
    can_view_documents = feature_flags.get("documents") and _can(request, PERMISSION_DOCUMENTS_VIEW)
    can_view_proposals = feature_flags.get("proposals") and _can(request, PERMISSION_PROPOSALS_VIEW)
    can_view_collections = feature_flags.get("collections") and _can(request, PERMISSION_COLLECTIONS_VIEW)

    entity_qs = Entity.objects.filter(is_active=True) if can_view_entities else Entity.objects.none()
    deal_qs = (
        Deal.objects.select_related("entity", "pipeline").filter(is_active=True, status=Deal.STATUS_OPEN)
        if can_view_deals
        else Deal.objects.none()
    )
    activity_qs = (
        Activity.objects.select_related("entity", "deal", "assigned_to")
        if can_view_activities
        else Activity.objects.none()
    )
    document_qs = (
        Document.objects.select_related("entity", "deal").filter(is_active=True)
        if can_view_documents
        else Document.objects.none()
    )
    proposal_qs = (
        Proposal.objects.select_related("entity", "deal").filter(is_active=True)
        if can_view_proposals
        else Proposal.objects.none()
    )
    collection_qs = (
        CollectionRecord.objects.select_related("entity", "deal").filter(is_active=True)
        if can_view_collections
        else CollectionRecord.objects.none()
    )

    stale_deals_qs = deal_qs.filter(updated_at__lt=now - timedelta(days=14))
    overdue_tasks_qs = activity_qs.filter(activity_type=Activity.TYPE_TASK, completed_at__isnull=True, due_at__lt=now)
    expiring_proposals_qs = proposal_qs.filter(
        status__in=[Proposal.STATUS_DRAFT, Proposal.STATUS_SENT],
        valid_until__isnull=False,
        valid_until__lte=today + timedelta(days=7),
    )
    overdue_collections_qs = collection_qs.exclude(status=CollectionRecord.STATUS_PAID).filter(due_on__lt=today)
    expiring_documents_qs = document_qs.filter(expires_on__isnull=False, expires_on__lte=today + timedelta(days=30))
    renewals_due_qs = deal_qs.filter(expected_close_on__isnull=False, expected_close_on__lte=today + timedelta(days=30))
    open_claims_qs = activity_qs.filter(activity_type=Activity.TYPE_CLAIM, completed_at__isnull=True)

    stale_deals = list(stale_deals_qs.order_by("updated_at")[:6])
    overdue_tasks = list(overdue_tasks_qs.order_by("due_at")[:6])
    expiring_proposals = list(expiring_proposals_qs.order_by("valid_until")[:6])
    overdue_collections = list(overdue_collections_qs.order_by("due_on")[:6])
    expiring_documents = list(expiring_documents_qs.order_by("expires_on")[:6])
    renewals_due = list(renewals_due_qs.order_by("expected_close_on")[:6])
    open_claims = list(open_claims_qs.order_by("due_at", "-created_at")[:6])

    stale_deals_count = stale_deals_qs.count()
    overdue_tasks_count = overdue_tasks_qs.count()
    expiring_proposals_count = expiring_proposals_qs.count()
    overdue_collections_count = overdue_collections_qs.count()
    expiring_documents_count = expiring_documents_qs.count()
    renewals_due_count = renewals_due_qs.count()
    open_claims_count = open_claims_qs.count()

    cold_threshold_days = 45 if profile == "retail_moda" else 30 if profile == "condominio" else 21
    cold_entities_qs = (
        entity_qs.annotate(last_activity_at=Max("activities__created_at"))
        .filter(
            Q(last_activity_at__isnull=True, updated_at__lt=now - timedelta(days=cold_threshold_days))
            | Q(last_activity_at__lt=now - timedelta(days=cold_threshold_days))
        )
        .order_by("last_activity_at", "updated_at")
        if can_view_entities
        else Entity.objects.none()
    )
    cold_entities = list(cold_entities_qs[:6])
    cold_entities_count = cold_entities_qs.count() if can_view_entities else 0

    missing_checklist_entities = []
    missing_checklist_count = 0
    if profile == "broker" and can_view_entities and can_view_documents:
        all_entities = list(entity_qs.order_by("full_name"))
        all_documents = list(document_qs)
        document_map: dict[int, list[Document]] = {}
        for document in all_documents:
            if document.entity_id:
                document_map.setdefault(document.entity_id, []).append(document)
        for entity in all_entities:
            checklist = _build_broker_document_checklist(entity, document_map.get(entity.id, []), blueprint_map=blueprint_map)
            missing_labels = [item["label"] for item in checklist if not item["is_present"]]
            if missing_labels:
                missing_checklist_count += 1
                if len(missing_checklist_entities) < 6:
                    missing_checklist_entities.append(
                        _build_report_item(
                            title=entity.full_name,
                            meta=entity.phone or entity.legal_id or "Sin contacto directo",
                            caption=", ".join(missing_labels[:3]),
                            status="Checklist incompleto",
                            tone="bg-red-50 text-red-700",
                        )
                    )

    report_cards = []
    if profile == "broker":
        report_cards = [
            {
                "label": "Renovaciones proximas",
                "value": renewals_due_count,
                "caption": "Deals abiertos con fecha estimada de cierre en los proximos 30 dias.",
                "tone": "bg-red-50 text-red-700" if renewals_due_count else "bg-green-50 text-green-700",
                "href": reverse("binncrm:index"),
            },
            {
                "label": "Siniestros abiertos",
                "value": open_claims_count,
                "caption": "Casos de siniestro registrados sin cierre o resolucion.",
                "tone": "bg-amber-50 text-amber-700" if open_claims_count else "bg-green-50 text-green-700",
                "href": reverse("binncrm:activities"),
            },
            {
                "label": "Checklist incompleto",
                "value": missing_checklist_count,
                "caption": "Asegurados que todavia tienen huecos documentales criticos.",
                "tone": "bg-red-50 text-red-700" if missing_checklist_count else "bg-green-50 text-green-700",
                "href": reverse("binncrm:documents"),
            },
            {
                "label": "Docs por vencer",
                "value": expiring_documents_count,
                "caption": "Documentos con vencimiento dentro de los proximos 30 dias.",
                "tone": "bg-amber-50 text-amber-700" if expiring_documents_count else "bg-green-50 text-green-700",
                "href": reverse("binncrm:documents"),
            },
        ]
    elif profile == "condominio":
        report_cards = [
            {
                "label": "Cartera vencida",
                "value": overdue_collections_count,
                "caption": "Cobros con fecha vencida que siguen sin marcarse como pagados.",
                "tone": "bg-red-50 text-red-700" if overdue_collections_count else "bg-green-50 text-green-700",
                "href": reverse("binncrm:collections"),
            },
            {
                "label": "Residentes sin toque",
                "value": cold_entities_count,
                "caption": "Fichas sin actividad reciente que conviene revisar hoy.",
                "tone": "bg-amber-50 text-amber-700" if cold_entities_count else "bg-green-50 text-green-700",
                "href": reverse("binncrm:entities"),
            },
            {
                "label": "Tareas vencidas",
                "value": overdue_tasks_count,
                "caption": "Seguimientos de cartera o comunicacion que ya se atrasaron.",
                "tone": "bg-red-50 text-red-700" if overdue_tasks_count else "bg-green-50 text-green-700",
                "href": reverse("binncrm:activities"),
            },
            {
                "label": "Recaudaciones activas",
                "value": deal_qs.count() if can_view_deals else 0,
                "caption": "Cobros o gestiones abiertas dentro del flujo de recaudacion.",
                "tone": "bg-blue-50 text-blue-700",
                "href": reverse("binncrm:index"),
            },
        ]
    elif profile == "servicios":
        report_cards = [
            {
                "label": "Deals quietos",
                "value": stale_deals_count,
                "caption": "Oportunidades sin movimiento real en los ultimos 14 dias.",
                "tone": "bg-amber-50 text-amber-700" if stale_deals_count else "bg-green-50 text-green-700",
                "href": reverse("binncrm:index"),
            },
            {
                "label": "Propuestas por vencer",
                "value": expiring_proposals_count,
                "caption": "Propuestas vigentes que merecen empuje comercial inmediato.",
                "tone": "bg-red-50 text-red-700" if expiring_proposals_count else "bg-green-50 text-green-700",
                "href": reverse("binncrm:proposals"),
            },
            {
                "label": "Cobros vencidos",
                "value": overdue_collections_count,
                "caption": "Saldos pendientes que ya pasaron su fecha de vencimiento.",
                "tone": "bg-red-50 text-red-700" if overdue_collections_count else "bg-green-50 text-green-700",
                "href": reverse("binncrm:collections"),
            },
            {
                "label": "Clientes sin siguiente paso",
                "value": cold_entities_count,
                "caption": "Cuentas que llevan dias sin actividad ni seguimiento reciente.",
                "tone": "bg-amber-50 text-amber-700" if cold_entities_count else "bg-green-50 text-green-700",
                "href": reverse("binncrm:entities"),
            },
        ]
    elif profile == "retail_moda":
        report_cards = [
            {
                "label": "Clientes inactivos",
                "value": cold_entities_count,
                "caption": "Clientes sin contacto reciente o con recompra que se esta enfriando.",
                "tone": "bg-amber-50 text-amber-700" if cold_entities_count else "bg-green-50 text-green-700",
                "href": reverse("binncrm:entities"),
            },
            {
                "label": "Pedidos abiertos",
                "value": deal_qs.count() if can_view_deals else 0,
                "caption": "Pedidos especiales o apartados que siguen en seguimiento.",
                "tone": "bg-blue-50 text-blue-700",
                "href": reverse("binncrm:index"),
            },
            {
                "label": "Tareas vencidas",
                "value": overdue_tasks_count,
                "caption": "Promesas de recompra o mensajes pendientes de enviar.",
                "tone": "bg-red-50 text-red-700" if overdue_tasks_count else "bg-green-50 text-green-700",
                "href": reverse("binncrm:activities"),
            },
            {
                "label": "Deals quietos",
                "value": stale_deals_count,
                "caption": "Pedidos o seguimientos que llevan tiempo sin movimiento.",
                "tone": "bg-amber-50 text-amber-700" if stale_deals_count else "bg-green-50 text-green-700",
                "href": reverse("binncrm:index"),
            },
        ]
    else:
        report_cards = [
            {
                "label": "Deals quietos",
                "value": stale_deals_count,
                "caption": "Negocios abiertos sin movimiento claro en las ultimas dos semanas.",
                "tone": "bg-amber-50 text-amber-700" if stale_deals_count else "bg-green-50 text-green-700",
                "href": reverse("binncrm:index"),
            },
            {
                "label": "Tareas vencidas",
                "value": overdue_tasks_count,
                "caption": "Seguimientos que ya deberian haberse ejecutado.",
                "tone": "bg-red-50 text-red-700" if overdue_tasks_count else "bg-green-50 text-green-700",
                "href": reverse("binncrm:activities"),
            },
            {
                "label": "Propuestas por vencer",
                "value": expiring_proposals_count,
                "caption": "Cotizaciones que necesitan seguimiento antes de caducar.",
                "tone": "bg-red-50 text-red-700" if expiring_proposals_count else "bg-green-50 text-green-700",
                "href": reverse("binncrm:proposals"),
            },
            {
                "label": "Documentos por revisar",
                "value": expiring_documents_count,
                "caption": "Soportes con vigencia corta o necesidad de revision.",
                "tone": "bg-amber-50 text-amber-700" if expiring_documents_count else "bg-green-50 text-green-700",
                "href": reverse("binncrm:documents"),
            },
        ]

    at_risk_items = []
    for deal in stale_deals:
        at_risk_items.append(
            {
                **_build_report_item(
                    title=deal.title,
                    meta=" | ".join(part for part in [deal.entity.full_name, deal.pipeline.name, deal.stage] if part),
                    caption=f"Sin movimiento desde {timezone.localtime(deal.updated_at).strftime('%d/%m/%Y %H:%M')}",
                    status="Deal quieto",
                    tone="bg-amber-50 text-amber-700",
                ),
                "sort_at": deal.updated_at,
            }
        )
    for activity in overdue_tasks:
        at_risk_items.append(
            {
                **_build_report_item(
                    title=activity.title,
                    meta=" | ".join(
                        part for part in [
                            getattr(activity.entity, "full_name", ""),
                            getattr(activity.assigned_to, "username", "") or "Sin responsable",
                        ] if part
                    ),
                    caption=f"Vencio {timezone.localtime(activity.due_at).strftime('%d/%m/%Y %H:%M')}" if activity.due_at else "Tarea sin fecha visible.",
                    status="Tarea vencida",
                    tone="bg-red-50 text-red-700",
                ),
                "sort_at": activity.due_at or activity.created_at,
            }
        )
    at_risk_items = [
        {key: value for key, value in item.items() if key != "sort_at"}
        for item in sorted(at_risk_items, key=lambda item: item["sort_at"])[:6]
    ]

    upcoming_items = []
    for proposal in expiring_proposals:
        upcoming_items.append(
            {
                **_build_report_item(
                    title=proposal.title,
                    meta=getattr(proposal.entity, "full_name", ""),
                    caption=f"Vigencia hasta {proposal.valid_until.strftime('%d/%m/%Y')} | {proposal.currency} {proposal.amount}",
                    status="Propuesta",
                    tone="bg-blue-50 text-blue-700",
                ),
                "sort_at": proposal.valid_until,
            }
        )
    for collection in overdue_collections:
        upcoming_items.append(
            {
                **_build_report_item(
                    title=collection.title,
                    meta=getattr(collection.entity, "full_name", ""),
                    caption=f"Saldo {collection.currency} {collection.balance} | Vencio {collection.due_on.strftime('%d/%m/%Y')}" if collection.due_on else f"Saldo {collection.currency} {collection.balance}",
                    status="Cobro vencido",
                    tone="bg-red-50 text-red-700",
                ),
                "sort_at": collection.due_on or today,
            }
        )
    for document in expiring_documents:
        expiry_label = _document_expiry_status(document, today=today)["label"]
        upcoming_items.append(
            {
                **_build_report_item(
                    title=document.title,
                    meta=get_document_type_label(profile, document.document_type, custom_blueprints=custom_blueprints),
                    caption=expiry_label,
                    status="Documento",
                    tone="bg-amber-50 text-amber-700",
                ),
                "sort_at": document.expires_on or today,
            }
        )
    upcoming_items = [
        {key: value for key, value in item.items() if key != "sort_at"}
        for item in sorted(upcoming_items, key=lambda item: item["sort_at"])[:6]
    ]

    vertical_items = []
    vertical_title = "Salud del vertical"
    vertical_subtitle = "Las alertas mas alineadas con este tipo de negocio."
    vertical_empty = "No se detectaron alertas especificas para este vertical."
    vertical_href = ""

    if profile == "broker":
        vertical_title = "Radar broker"
        vertical_subtitle = "Lo que un broker pequeno suele necesitar mirar antes de perder renovaciones o cobrar tarde."
        vertical_href = reverse("binncrm:documents") if can_view_documents else reverse("binncrm:index")
        for deal in renewals_due:
            vertical_items.append(
                {
                    **_build_report_item(
                        title=deal.title,
                        meta=getattr(deal.entity, "full_name", ""),
                        caption=f"Cierre esperado {deal.expected_close_on.strftime('%d/%m/%Y')}" if deal.expected_close_on else "Sin fecha estimada",
                        status="Renovacion",
                        tone="bg-red-50 text-red-700",
                    ),
                    "sort_at": deal.expected_close_on or today,
                }
            )
        for activity in open_claims:
            vertical_items.append(
                {
                    **_build_report_item(
                        title=activity.title,
                        meta=getattr(activity.entity, "full_name", ""),
                        caption=activity.description[:120] or "Siniestro abierto sin cierre registrado.",
                        status="Siniestro",
                        tone="bg-amber-50 text-amber-700",
                    ),
                    "sort_at": activity.due_at or activity.created_at,
                }
            )
        for item in missing_checklist_entities:
            vertical_items.append({**item, "sort_at": today})
    else:
        if profile == "condominio":
            vertical_title = "Residentes sin seguimiento reciente"
            vertical_subtitle = "Fichas que llevan varios dias sin contacto, gestion o actualizacion visible."
            vertical_empty = "No hay residentes frios detectados."
        elif profile == "servicios":
            vertical_title = "Clientes sin siguiente paso"
            vertical_subtitle = "Cuentas o prospectos que conviene reactivar con una llamada, propuesta o reunion."
            vertical_empty = "No hay clientes enfriandose en este momento."
        elif profile == "retail_moda":
            vertical_title = "Clienteling por reactivar"
            vertical_subtitle = "Clientes con potencial de recompra que quedaron sin toque reciente."
            vertical_empty = "No hay clientes inactivos por reactivar en este momento."
        elif profile == "marketing":
            vertical_title = "Leads sin seguimiento reciente"
            vertical_subtitle = "Contactos comerciales que conviene mover antes de que se enfrien."
            vertical_empty = "No hay leads frios detectados ahora."
        vertical_href = reverse("binncrm:entities") if can_view_entities else ""
        for entity in cold_entities:
            last_touch = getattr(entity, "last_activity_at", None)
            last_touch_label = timezone.localtime(last_touch).strftime("%d/%m/%Y %H:%M") if last_touch else "Sin actividad registrada"
            ultima_compra = _parse_extra_date(entity.data_extra.get("ultima_compra")) if profile == "retail_moda" else None
            caption = f"Ultimo seguimiento: {last_touch_label}"
            if ultima_compra:
                caption = f"{caption} | Ultima compra: {ultima_compra.strftime('%d/%m/%Y')}"
            vertical_items.append(
                {
                    **_build_report_item(
                        title=entity.full_name,
                        meta=entity.phone or entity.email or entity.legal_id or "Sin dato de contacto",
                        caption=caption,
                        status="Inactivo" if profile == "retail_moda" else "Sin seguimiento",
                        tone="bg-amber-50 text-amber-700",
                    ),
                    "sort_at": last_touch or entity.updated_at,
                }
            )

    vertical_items = [
        {key: value for key, value in item.items() if key != "sort_at"}
        for item in sorted(vertical_items, key=lambda item: item["sort_at"])[:6]
    ]

    report_sections = [
        {
            "title": "Seguimiento en riesgo",
            "subtitle": "Deals quietos y tareas vencidas que pueden costarte ingresos o contexto comercial.",
            "href": reverse("binncrm:activities") if can_view_activities else reverse("binncrm:index") if can_view_deals else "",
            "cta": "Abrir modulo",
            "empty_message": "No hay seguimiento en riesgo por ahora.",
            "items": at_risk_items,
        },
        {
            "title": "Vencimientos y compromisos",
            "subtitle": "Propuestas, cobranzas y documentos que merecen accion antes de que se escapen.",
            "href": reverse("binncrm:documents") if can_view_documents else reverse("binncrm:collections") if can_view_collections else reverse("binncrm:proposals") if can_view_proposals else "",
            "cta": "Abrir modulo",
            "empty_message": "No hay vencimientos criticos en este momento.",
            "items": upcoming_items,
        },
        {
            "title": vertical_title,
            "subtitle": vertical_subtitle,
            "href": vertical_href,
            "cta": "Abrir modulo" if vertical_href else "",
            "empty_message": vertical_empty,
            "items": vertical_items,
        },
    ]

    return render(
        request,
        "binncrm/reports.html",
        {
            "labels": labels,
            "workspace_pack": build_workspace_pack(
                profile=profile,
                labels=labels,
                feature_flags=feature_flags,
            ),
            "report_copy": _build_reports_copy(profile, labels),
            "generated_at": timezone.localtime(now),
            "report_cards": report_cards,
            "report_sections": report_sections,
        },
    )


@login_required
@tenant_permission_required(PERMISSION_OBJECTS_VIEW)
def custom_object_catalog(request):
    object_schemas = get_custom_object_schemas(tenant=request.tenant)
    catalog = [
        {
            "object_schema": object_schema,
            "record_count": getattr(object_schema, "active_record_count", 0),
            "field_count": getattr(object_schema, "active_field_count", 0),
            "view_count": getattr(object_schema, "active_view_count", 0),
        }
        for object_schema in object_schemas
    ]
    return render(
        request,
        "binncrm/custom_object_catalog.html",
        {
            "custom_object_catalog": catalog,
            "can_edit_objects": _can(request, PERMISSION_OBJECTS_EDIT),
        },
    )


@login_required
@tenant_permission_required(PERMISSION_OBJECTS_VIEW)
def custom_object_records(request, object_key):
    object_schema = get_object_or_404(
        ObjectSchema.objects.prefetch_related("fields", "views"),
        key=object_key,
        source=ObjectSchema.SOURCE_CUSTOM,
        is_active=True,
    )
    field_definitions = get_object_record_field_definitions(object_schema=object_schema)
    q = (request.GET.get("q") or "").strip()
    records_qs = ObjectRecord.objects.filter(object_schema=object_schema).order_by("-updated_at", "-id")
    if q:
        records_qs = records_qs.filter(_build_object_record_search_query(q, field_definitions))
    record_previews = [build_object_record_preview(object_schema=object_schema, record=record) for record in records_qs[:80]]
    return render(
        request,
        "binncrm/custom_object_records.html",
        {
            "object_schema": object_schema,
            "field_definitions": field_definitions,
            "record_previews": record_previews,
            "object_views": object_schema.views.filter(is_active=True).order_by("position", "label", "id"),
            "q": q,
            "can_edit_objects": _can(request, PERMISSION_OBJECTS_EDIT),
        },
    )


@login_required
@tenant_permission_required(PERMISSION_OBJECTS_VIEW)
def custom_object_record_detail(request, object_key, pk):
    object_schema = get_object_or_404(
        ObjectSchema.objects.prefetch_related("fields", "views"),
        key=object_key,
        source=ObjectSchema.SOURCE_CUSTOM,
        is_active=True,
    )
    record = get_object_or_404(ObjectRecord, pk=pk, object_schema=object_schema)
    field_definitions = get_object_record_field_definitions(object_schema=object_schema)
    field_values = [
        {
            "label": field_definition["label"],
            "value": _serialize_object_value(record.data.get(field_definition["key"]), field_definition),
        }
        for field_definition in field_definitions
    ]
    return render(
        request,
        "binncrm/custom_object_record_detail.html",
        {
            "object_schema": object_schema,
            "record": record,
            "record_preview": build_object_record_preview(object_schema=object_schema, record=record),
            "field_values": field_values,
            "can_edit_objects": _can(request, PERMISSION_OBJECTS_EDIT),
        },
    )


@login_required
@tenant_permission_required(PERMISSION_OBJECTS_EDIT)
def custom_object_record_create(request, object_key):
    object_schema = get_object_or_404(
        ObjectSchema.objects.prefetch_related("fields", "views"),
        key=object_key,
        source=ObjectSchema.SOURCE_CUSTOM,
        is_active=True,
    )
    if request.method == "POST":
        form = ObjectRecordForm(request.POST, object_schema=object_schema)
        if form.is_valid():
            record = form.save(commit=False)
            record.created_by = request.user
            record.updated_by = request.user
            record.save()
            log_object_record_created(record=record, actor=request.user)
            messages.success(request, "Registro custom creado correctamente.")
            return redirect("binncrm:custom_object_record_detail", object_key=object_schema.key, pk=record.pk)
    else:
        form = ObjectRecordForm(object_schema=object_schema)
    return render(
        request,
        "binncrm/custom_object_record_form.html",
        {
            "object_schema": object_schema,
            "form": form,
            "record": None,
            "page_title": f"Nuevo registro en {object_schema.label}",
        },
    )


@login_required
@tenant_permission_required(PERMISSION_OBJECTS_EDIT)
def custom_object_record_edit(request, object_key, pk):
    object_schema = get_object_or_404(
        ObjectSchema.objects.prefetch_related("fields", "views"),
        key=object_key,
        source=ObjectSchema.SOURCE_CUSTOM,
        is_active=True,
    )
    record = get_object_or_404(ObjectRecord, pk=pk, object_schema=object_schema)
    if request.method == "POST":
        form = ObjectRecordForm(request.POST, instance=record, object_schema=object_schema)
        if form.is_valid():
            changed_fields = list(form.changed_data)
            record = form.save(commit=False)
            record.updated_by = request.user
            record.save()
            if changed_fields:
                log_object_record_updated(record=record, actor=request.user, changed_fields=changed_fields)
            messages.success(request, "Registro custom actualizado correctamente.")
            return redirect("binncrm:custom_object_record_detail", object_key=object_schema.key, pk=record.pk)
    else:
        form = ObjectRecordForm(instance=record, object_schema=object_schema)
    return render(
        request,
        "binncrm/custom_object_record_form.html",
        {
            "object_schema": object_schema,
            "form": form,
            "record": record,
            "page_title": f"Editar registro en {object_schema.label}",
        },
    )


@login_required
@tenant_permission_required(PERMISSION_DEALS_MOVE, capability="deals")
@require_POST
def deal_move(request, pk):
    deal = get_object_or_404(Deal, pk=pk)
    stage = (request.POST.get("stage") or "").strip()
    try:
        position = max(int(request.POST.get("position", 0)), 0)
    except (TypeError, ValueError):
        position = 0
    if stage not in deal.pipeline.stage_choices:
        return JsonResponse({"ok": False, "message": "Etapa invalida."}, status=400)
    previous_stage = deal.stage
    previous_pipeline_name = getattr(deal.pipeline, "name", "")

    with transaction.atomic():
        deal.stage = stage
        deal.updated_by = request.user
        deal.save(update_fields=["stage", "updated_by", "updated_at"])
        inserted_index = _resequence_stage(deal.pipeline, stage, moving_deal=deal, position=position)
        if previous_stage != stage:
            _resequence_stage(deal.pipeline, previous_stage)
            log_deal_stage_changed(
                deal=deal,
                actor=request.user,
                kind_label=request.tenant.get_label("deal_singular", "Deal"),
                previous_stage=previous_stage,
                previous_pipeline_name=previous_pipeline_name,
            )

    return JsonResponse(
        {
            "ok": True,
            "stage": stage,
            "position": inserted_index if inserted_index is not None else position,
        }
    )


@login_required
@tenant_permission_required(PERMISSION_ACTIVITIES_VIEW, capability="activities")
def activities(request):
    labels = request.tenant.tenant_config.labels
    q = (request.GET.get("q") or "").strip()
    activities_qs = Activity.objects.select_related("entity", "deal", "assigned_to")
    if q:
        activities_qs = activities_qs.filter(
            Q(title__icontains=q)
            | Q(description__icontains=q)
            | Q(entity__full_name__icontains=q)
        )

    pending_tasks = list(
        activities_qs.filter(activity_type=Activity.TYPE_TASK, completed_at__isnull=True).order_by("due_at", "-created_at")[:12]
    )
    completed_tasks = list(
        activities_qs.filter(activity_type=Activity.TYPE_TASK, completed_at__isnull=False).order_by("-completed_at")[:6]
    )

    return render(
        request,
        "binncrm/activities.html",
        {
            "labels": labels,
            "activities": activities_qs.order_by("-created_at")[:100],
            "pending_task_cards": [_build_task_card(activity) for activity in pending_tasks],
            "completed_task_cards": [_build_task_card(activity) for activity in completed_tasks],
            "task_summary": {
                "pending": len(pending_tasks),
                "overdue": sum(1 for activity in pending_tasks if _task_status(activity)["is_overdue"]),
                "completed": len(completed_tasks),
            },
            "q": q,
            "can_create_activity": _can(request, PERMISSION_ACTIVITIES_EDIT),
            "can_complete_tasks": _can(request, PERMISSION_ACTIVITIES_COMPLETE),
        },
    )


@login_required
@tenant_permission_required(PERMISSION_ACTIVITIES_EDIT, capability="activities")
def activity_create(request):
    initial = {}
    entity_id = (request.GET.get("entity") or "").strip()
    deal_id = (request.GET.get("deal") or "").strip()
    activity_type = (request.GET.get("activity_type") or "").strip()
    if entity_id.isdigit():
        initial["entity"] = entity_id
    if deal_id.isdigit():
        initial["deal"] = deal_id
    if activity_type in {choice[0] for choice in Activity.TYPE_CHOICES}:
        initial["activity_type"] = activity_type
    if request.method == "POST":
        form = ActivityForm(request.POST, tenant=request.tenant, current_user=request.user)
        if form.is_valid():
            activity = form.save(commit=False)
            activity.created_by = request.user
            activity.updated_by = request.user
            if activity.activity_type == Activity.TYPE_TASK and activity.assigned_to_id is None:
                activity.assigned_to = request.user
            activity.save()
            log_activity_created(activity=activity, actor=request.user)
            messages.success(request, "Actividad creada correctamente.")
            return redirect("binncrm:activities")
    else:
        form = ActivityForm(initial=initial, tenant=request.tenant, current_user=request.user)

    return render(
        request,
        "binncrm/activity_form.html",
        {
            "labels": request.tenant.tenant_config.labels,
            "form": form,
            "is_task_mode": (initial.get("activity_type") == Activity.TYPE_TASK),
        },
    )


@login_required
@tenant_permission_required(PERMISSION_ACTIVITIES_COMPLETE, capability="activities")
@require_POST
def activity_toggle_complete(request, pk):
    activity = get_object_or_404(Activity, pk=pk, activity_type=Activity.TYPE_TASK)
    activity.completed_at = None if activity.completed_at else timezone.now()
    activity.updated_by = request.user
    activity.save(update_fields=["completed_at", "updated_by", "updated_at"])
    log_activity_completion_changed(activity=activity, actor=request.user)
    if request.GET.get("next") == "entity" and activity.entity_id:
        return redirect("binncrm:entity_detail", pk=activity.entity_id)
    return redirect("binncrm:activities")


@login_required
@tenant_permission_required(PERMISSION_DOCUMENTS_VIEW, capability="documents")
def documents(request):
    labels = request.tenant.tenant_config.labels
    profile = _tenant_profile(request.tenant)
    custom_blueprints = request.tenant.document_blueprints
    document_blueprints = get_document_blueprints(profile, custom_blueprints=custom_blueprints)
    blueprint_map = get_document_blueprint_map(profile, custom_blueprints=custom_blueprints)
    q = (request.GET.get("q") or "").strip()
    selected_document_type = (request.GET.get("document_type") or "").strip()
    documents_qs = Document.objects.select_related("entity", "deal").filter(is_active=True)
    if q:
        documents_qs = documents_qs.filter(
            Q(title__icontains=q)
            | Q(document_type__icontains=q)
            | Q(storage_key__icontains=q)
        )
    filter_source = documents_qs
    if selected_document_type:
        documents_qs = documents_qs.filter(document_type=selected_document_type)
    document_cards = [
        _build_document_card(
            document,
            profile=profile,
            blueprint_map=blueprint_map,
            custom_blueprints=custom_blueprints,
        )
        for document in documents_qs.order_by("-created_at")[:100]
    ]

    return render(
        request,
        "binncrm/documents.html",
        {
            "labels": labels,
            "document_cards": document_cards,
            "document_blueprints": document_blueprints,
            "document_filters": _build_document_filters(
                filter_source,
                document_blueprints=document_blueprints,
                selected_type=selected_document_type,
            ),
            "selected_document_type": selected_document_type,
            "q": q,
            "can_create_document": _can(request, PERMISSION_DOCUMENTS_EDIT),
            "can_edit_document": _can(request, PERMISSION_DOCUMENTS_EDIT),
        },
    )


@login_required
@tenant_permission_required(PERMISSION_DOCUMENTS_EDIT, capability="documents")
def document_create(request):
    initial = {"is_active": True}
    entity_id = (request.GET.get("entity") or "").strip()
    deal_id = (request.GET.get("deal") or "").strip()
    if entity_id.isdigit():
        initial["entity"] = entity_id
    if deal_id.isdigit():
        initial["deal"] = deal_id
    if request.method == "POST":
        form = DocumentForm(request.POST, tenant=request.tenant)
        if form.is_valid():
            document = form.save(commit=False)
            document.created_by = request.user
            document.updated_by = request.user
            document.save()
            log_document_created(
                document=document,
                profile=_tenant_profile(request.tenant),
                custom_blueprints=request.tenant.document_blueprints,
                actor=request.user,
                kind_label=request.tenant.get_label("document_singular", "Documento"),
            )
            messages.success(request, "Documento registrado correctamente.")
            return redirect("binncrm:documents")
    else:
        form = DocumentForm(initial=initial, tenant=request.tenant)

    return _render_document_form(
        request,
        form,
        page_title=f"Nuevo {request.tenant.get_label('document_singular', 'Documento')}",
        submit_label="Guardar documento",
    )


@login_required
@tenant_permission_required(PERMISSION_DOCUMENTS_EDIT, capability="documents")
def document_edit(request, pk):
    document = get_object_or_404(Document, pk=pk)
    if request.method == "POST":
        form = DocumentForm(request.POST, instance=document, tenant=request.tenant)
        if form.is_valid():
            changed_fields = list(form.changed_data)
            document = form.save(commit=False)
            document.updated_by = request.user
            document.save()
            if changed_fields:
                log_document_updated(
                    document=document,
                    profile=_tenant_profile(request.tenant),
                    custom_blueprints=request.tenant.document_blueprints,
                    actor=request.user,
                    kind_label=request.tenant.get_label("document_singular", "Documento"),
                    changed_fields=changed_fields,
                )
            messages.success(request, "Documento actualizado correctamente.")
            return redirect("binncrm:documents")
    else:
        form = DocumentForm(instance=document, tenant=request.tenant)

    return _render_document_form(
        request,
        form,
        document=document,
        page_title=f"Editar {request.tenant.get_label('document_singular', 'Documento')}",
        submit_label="Guardar cambios",
    )
