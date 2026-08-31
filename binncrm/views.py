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
    ensure_request_tenant_permission,
    request_has_tenant_permission,
    tenant_role_required,
    tenant_permission_required,
)
from access.runtime import get_request_membership
from tenants.workspace_packs import build_workspace_pack
from tenants.models import Client
from tenants.services import sync_tenant_pipelines

from .audit import record_crm_audit_event
from .importers import import_entities_from_csv
from .document_blueprints import (
    build_document_metadata_summary,
    get_document_blueprint_map,
    get_document_blueprints,
    get_document_type_label,
)
from .forms import (
    ActivityForm,
    AssessmentQuestionForm,
    AssessmentResponseForm,
    AssessmentSectionForm,
    AssessmentSubmissionCreateForm,
    AssessmentTemplateForm,
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
from .models import (
    Activity, AssessmentSection, AssessmentSubmission, AssessmentTemplate, CollectionRecord, Deal, Document,
    Entity, ObjectRecord, ObjectSchema, Pipeline, Proposal, SavedWorkspaceFilter,
)
from .assessments import build_template_snapshot, ensure_default_template, save_submission_answers, submission_answer_map
from .operational_context import (
    build_activity_operational_context,
    build_collection_operational_context,
    build_proposal_operational_context,
)
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
    record_timeline_event,
)
from .task_presets import (
    build_task_preset_cards,
    build_task_preset_due_at,
    build_task_preset_form_href,
    build_task_preset_form_initial,
    get_task_preset,
    resolve_task_preset_assignee,
)
from .view_engine import apply_deal_saved_view, apply_entity_saved_view, get_saved_views, resolve_saved_view


def _is_htmx(request) -> bool:
    return request.headers.get("HX-Request") == "true"


def _can(request, permission_code: str) -> bool:
    return request_has_tenant_permission(request, permission_code)


def _require_crm_permission(request, permission_code: str, *, capability: str | None = None):
    ensure_request_tenant_permission(request, permission_code, capability=capability)


def _audit_crm_action(
    request,
    *,
    action: str,
    object_type: str,
    title: str,
    message: str = "",
    metadata: dict | None = None,
    code: str = "",
):
    return record_crm_audit_event(
        tenant=request.tenant,
        actor=request.user,
        action=action,
        object_type=object_type,
        title=title,
        message=message,
        metadata=metadata,
        code=code,
    )


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
    audit_action: str = "updated",
) -> list[str]:
    with schema_context(get_public_schema_name()):
        tenant = Client.objects.select_related("config").get(schema_name=request.tenant.schema_name)
        config = tenant.tenant_config
        config.pipeline_templates = templates
        config.save(update_fields=["pipeline_templates", "updated_at"])
        notices = sync_tenant_pipelines(tenant)
        record_crm_audit_event(
            tenant=tenant,
            actor=request.user,
            action=audit_action,
            object_type="pipeline_config",
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


def _normalize_activity_kind(raw_value: str) -> str:
    value = str(raw_value or "").strip()
    valid_values = {choice[0] for choice in Activity.TYPE_CHOICES}
    return value if value in valid_values else ""


def _normalize_activity_status(raw_value: str) -> str:
    value = str(raw_value or "").strip().lower()
    return value if value in {"open", "overdue", "completed"} else ""


def _apply_activity_operational_filters(queryset, *, selected_kind: str = "", selected_status: str = "", now=None):
    now = now or timezone.now()
    if selected_kind:
        queryset = queryset.filter(activity_type=selected_kind)
    if selected_status == "open":
        queryset = queryset.filter(completed_at__isnull=True)
    elif selected_status == "overdue":
        queryset = queryset.filter(completed_at__isnull=True, due_at__lt=now)
    elif selected_status == "completed":
        queryset = queryset.filter(completed_at__isnull=False)
    return queryset


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
    if field_type == "select":
        choice_label = _resolve_choice_label(value, field_definition.get("choices"))
        return choice_label or str(value)
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


def _resolve_choice_label(value, raw_choices) -> str:
    current_value = str(value or "").strip()
    if not current_value:
        return ""
    for choice in list(raw_choices or []):
        if isinstance(choice, dict):
            choice_value = str(choice.get("value", "")).strip()
            choice_label = str(choice.get("label", choice_value)).strip()
        else:
            choice_value = str(choice).strip()
            choice_label = choice_value
        if choice_value == current_value:
            return choice_label or choice_value
    return ""


def _broker_lifecycle_field_definition(field_definitions: list[dict]) -> dict:
    return next((field for field in field_definitions if field.get("key") == "lifecycle_stage"), {})


def _broker_lifecycle_state(entity: Entity, *, field_definitions: list[dict] | None = None) -> dict:
    field_definitions = field_definitions or []
    lifecycle_field = _broker_lifecycle_field_definition(field_definitions)
    raw_value = str((entity.data_extra or {}).get("lifecycle_stage", "") or "").strip().lower()
    valid_values = {"lead", "asegurado", "renovacion"}
    if raw_value not in valid_values:
        open_deal_count = getattr(entity, "open_deal_count", None)
        deal_count = getattr(entity, "deal_count", None)
        if open_deal_count is None and deal_count is None:
            deal_count = 1 if hasattr(entity, "deals") and entity.deals.exists() else 0
        if (open_deal_count or 0) > 0 or (deal_count or 0) > 0:
            raw_value = "renovacion"
        elif (entity.data_extra or {}).get("poliza"):
            raw_value = "asegurado"
        else:
            raw_value = "lead"

    label_map = {
        "lead": "Lead",
        "asegurado": "Asegurado",
        "renovacion": "Renovacion",
    }
    choice_label = _resolve_choice_label(raw_value, lifecycle_field.get("choices")) if lifecycle_field else ""
    tone_map = {
        "lead": "bg-slate-100 text-slate-700",
        "asegurado": "bg-blue-50 text-blue-700",
        "renovacion": "bg-amber-50 text-amber-700",
    }
    return {
        "key": raw_value,
        "label": choice_label or label_map[raw_value],
        "tone": tone_map[raw_value],
    }


def _services_lifecycle_field_definition(field_definitions: list[dict]) -> dict:
    return next((field for field in field_definitions if field.get("key") == "service_stage"), {})


def _normalize_reference_token(value) -> str:
    return " ".join(str(value or "").strip().lower().split())


def _service_reference_tokens(entity: Entity) -> set[str]:
    data_extra = entity.data_extra or {}
    tokens = {
        _normalize_reference_token(data_extra.get("empresa")),
        _normalize_reference_token(entity.full_name),
        _normalize_reference_token(data_extra.get("legal_name")),
    }
    return {token for token in tokens if token}


def _services_lifecycle_state(entity: Entity, *, field_definitions: list[dict] | None = None, today=None) -> dict:
    field_definitions = field_definitions or []
    today = today or timezone.localdate()
    lifecycle_field = _services_lifecycle_field_definition(field_definitions)
    raw_value = str((entity.data_extra or {}).get("service_stage", "") or "").strip().lower()
    valid_values = {"prospecto", "cliente_activo", "renovacion_upsell"}
    renewal_on = _parse_extra_date((entity.data_extra or {}).get("renewal_on"))
    if raw_value not in valid_values:
        won_deal_count = getattr(entity, "won_deal_count", None)
        open_deal_count = getattr(entity, "open_deal_count", None)
        deal_count = getattr(entity, "deal_count", None)
        if (renewal_on and renewal_on <= today + timedelta(days=60)) or ((open_deal_count or 0) > 0 and (won_deal_count or 0) > 0):
            raw_value = "renovacion_upsell"
        elif (won_deal_count or 0) > 0:
            raw_value = "cliente_activo"
        elif (deal_count or 0) > 0 or (open_deal_count or 0) > 0:
            raw_value = "prospecto"
        else:
            raw_value = "prospecto"

    label_map = {
        "prospecto": "Prospecto",
        "cliente_activo": "Cliente activo",
        "renovacion_upsell": "Renovacion / upsell",
    }
    choice_label = _resolve_choice_label(raw_value, lifecycle_field.get("choices")) if lifecycle_field else ""
    tone_map = {
        "prospecto": "bg-slate-100 text-slate-700",
        "cliente_activo": "bg-emerald-50 text-emerald-700",
        "renovacion_upsell": "bg-amber-50 text-amber-700",
    }
    return {
        "key": raw_value,
        "label": choice_label or label_map[raw_value],
        "tone": tone_map[raw_value],
    }


def _condo_status_field_definition(field_definitions: list[dict]) -> dict:
    return next((field for field in field_definitions if field.get("key") == "resident_status"), {})


def _condo_resident_status(entity: Entity, *, field_definitions: list[dict] | None = None) -> dict:
    field_definitions = field_definitions or []
    status_field = _condo_status_field_definition(field_definitions)
    raw_value = str((entity.data_extra or {}).get("resident_status", "") or "").strip().lower()
    valid_values = {"al_dia", "seguimiento", "promesa_pago", "cartera_vencida"}
    if raw_value not in valid_values:
        overdue_count = int(getattr(entity, "overdue_collection_count", 0) or 0)
        promised_count = int(getattr(entity, "promised_collection_count", 0) or 0)
        open_collection_count = int(getattr(entity, "open_collection_count", 0) or 0)
        if overdue_count > 0:
            raw_value = "cartera_vencida"
        elif promised_count > 0:
            raw_value = "promesa_pago"
        elif open_collection_count > 0:
            raw_value = "seguimiento"
        else:
            raw_value = "al_dia"

    label_map = {
        "al_dia": "Al dia",
        "seguimiento": "En seguimiento",
        "promesa_pago": "Promesa de pago",
        "cartera_vencida": "Cartera vencida",
    }
    tone_map = {
        "al_dia": "bg-green-50 text-green-700",
        "seguimiento": "bg-blue-50 text-blue-700",
        "promesa_pago": "bg-amber-50 text-amber-700",
        "cartera_vencida": "bg-red-50 text-red-700",
    }
    choice_label = _resolve_choice_label(raw_value, status_field.get("choices")) if status_field else ""
    return {
        "key": raw_value,
        "label": choice_label or label_map[raw_value],
        "tone": tone_map[raw_value],
    }


def _condo_reference_tokens(entity: Entity) -> set[str]:
    data_extra = entity.data_extra or {}
    tokens = {
        _normalize_reference_token(entity.full_name),
        _normalize_reference_token(data_extra.get("departamento")),
    }
    return {token for token in tokens if token}


def _matching_condo_records(entity: Entity, records: list[ObjectRecord], *keys: str) -> list[ObjectRecord]:
    entity_tokens = _condo_reference_tokens(entity)
    if not entity_tokens:
        return []
    matches = []
    for record in records:
        record_tokens = {
            _normalize_reference_token((record.data or {}).get(key))
            for key in keys
        }
        record_tokens = {token for token in record_tokens if token}
        if entity_tokens & record_tokens:
            matches.append(record)
    return matches



def _broker_reference_tokens(entity: Entity, *, documents=None) -> set[str]:
    data_extra = entity.data_extra or {}
    tokens = {
        _normalize_reference_token(entity.full_name),
        _normalize_reference_token(entity.legal_id),
        _normalize_reference_token(data_extra.get("placa")),
        _normalize_reference_token(data_extra.get("poliza")),
        _normalize_reference_token(data_extra.get("aseguradora")),
    }
    for document in documents or []:
        metadata = getattr(document, "metadata", None) or {}
        tokens.update(
            {
                _normalize_reference_token(metadata.get("numero_poliza")),
                _normalize_reference_token(metadata.get("placa")),
                _normalize_reference_token(metadata.get("aseguradora")),
            }
        )
    return {token for token in tokens if token}


def _matching_broker_policy_records(entity: Entity, policy_records: list[ObjectRecord], *, documents=None) -> list[ObjectRecord]:
    broker_tokens = _broker_reference_tokens(entity, documents=documents)
    if not broker_tokens:
        return []

    matches = []
    for record in policy_records:
        data = record.data or {}
        record_tokens = {
            _normalize_reference_token(record.title),
            _normalize_reference_token(data.get("numero_poliza")),
            _normalize_reference_token(data.get("producto")),
            _normalize_reference_token(data.get("placa")),
            _normalize_reference_token(data.get("aseguradora")),
            _normalize_reference_token(data.get("cliente")),
            _normalize_reference_token(data.get("asegurado")),
            _normalize_reference_token(data.get("identificacion")),
        }
        record_tokens = {token for token in record_tokens if token}
        if broker_tokens & record_tokens:
            matches.append(record)
    return matches


def _parse_optional_numeric_amount(raw_value) -> float | None:
    if raw_value in (None, ""):
        return None
    if isinstance(raw_value, (int, float)):
        return float(raw_value)

    cleaned = "".join(char for char in str(raw_value).strip() if char.isdigit() or char in {".", ",", "-"})
    if not cleaned:
        return None

    if "," in cleaned and "." in cleaned:
        if cleaned.rfind(",") > cleaned.rfind("."):
            cleaned = cleaned.replace(".", "").replace(",", ".")
        else:
            cleaned = cleaned.replace(",", "")
    elif cleaned.count(",") == 1 and "." not in cleaned:
        cleaned = cleaned.replace(",", ".")
    elif cleaned.count(".") > 1 and "," not in cleaned:
        cleaned = cleaned.replace(".", "")
    elif cleaned.count(",") > 1 and "." not in cleaned:
        cleaned = cleaned.replace(",", "")

    try:
        return float(cleaned)
    except ValueError:
        return None


def _broker_policy_status(policy_record: ObjectRecord, *, today=None) -> dict:
    today = today or timezone.localdate()
    expires_on = _parse_extra_date((policy_record.data or {}).get("vigencia_hasta"))
    if not expires_on:
        return {
            "label": "Sin vigencia",
            "tone": "bg-slate-100 text-slate-700",
            "expires_on": None,
            "days_to_expiry": None,
            "is_expired": False,
            "is_expiring_soon": False,
        }

    days_to_expiry = (expires_on - today).days
    if expires_on < today:
        return {
            "label": f"Vencida {expires_on.strftime('%d/%m/%Y')}",
            "tone": "bg-red-50 text-red-700",
            "expires_on": expires_on,
            "days_to_expiry": days_to_expiry,
            "is_expired": True,
            "is_expiring_soon": False,
        }
    if expires_on <= today + timedelta(days=30):
        return {
            "label": f"Vence {expires_on.strftime('%d/%m/%Y')}",
            "tone": "bg-amber-50 text-amber-700",
            "expires_on": expires_on,
            "days_to_expiry": days_to_expiry,
            "is_expired": False,
            "is_expiring_soon": True,
        }
    return {
        "label": f"Vigente hasta {expires_on.strftime('%d/%m/%Y')}",
        "tone": "bg-green-50 text-green-700",
        "expires_on": expires_on,
        "days_to_expiry": days_to_expiry,
        "is_expired": False,
        "is_expiring_soon": False,
    }


def _collect_broker_due_policy_records(policy_records: list[ObjectRecord], *, today=None, window_days: int = 45) -> list[ObjectRecord]:
    today = today or timezone.localdate()
    matches = []
    for record in policy_records:
        status = _broker_policy_status(record, today=today)
        expires_on = status["expires_on"]
        if not expires_on:
            continue
        if expires_on > today + timedelta(days=window_days):
            continue
        matches.append((expires_on, str(record.title or "").lower(), getattr(record, "pk", 0) or 0, record))

    matches.sort(key=lambda item: (item[0], item[1], item[2]))
    return [item[3] for item in matches]


def _build_broker_policy_report_item(policy_record: ObjectRecord, *, today=None, href: str = "", cta: str = "") -> dict:
    data = policy_record.data or {}
    policy_status = _broker_policy_status(policy_record, today=today)
    prima = _parse_optional_numeric_amount(data.get("prima"))
    currency = str(data.get("moneda") or "USD").strip() or "USD"
    caption_parts = [policy_status["label"]]
    if prima is not None:
        caption_parts.append(_format_currency_amount(currency, prima))

    item = _build_report_item(
        title=data.get("numero_poliza") or policy_record.title or "Poliza",
        meta=" | ".join(part for part in [data.get("producto", ""), data.get("aseguradora", "")] if part),
        caption=" | ".join(part for part in caption_parts if part),
        status="Poliza",
        tone=policy_status["tone"],
        href=href,
        cta=cta,
    )
    item["expires_on"] = policy_status["expires_on"]
    item["days_to_expiry"] = policy_status["days_to_expiry"]
    item["is_expired"] = policy_status["is_expired"]
    item["is_expiring_soon"] = policy_status["is_expiring_soon"]
    return item


def _build_broker_entity_summary(
    entity: Entity,
    *,
    policy_records: list[ObjectRecord],
    documents: list[Document],
    activities: list[Activity],
    collections: list[CollectionRecord],
    blueprint_map: dict,
    today=None,
) -> list[dict]:
    today = today or timezone.localdate()
    checklist = _build_broker_document_checklist(entity, documents, blueprint_map=blueprint_map)
    complete_checklist = sum(1 for item in checklist if item["is_present"])
    missing_checklist = len(checklist) - complete_checklist
    open_claims = [
        activity
        for activity in activities
        if getattr(activity, "activity_type", "") == Activity.TYPE_CLAIM and getattr(activity, "completed_at", None) is None
    ]
    overdue_collections = [
        collection
        for collection in collections
        if getattr(collection, "status", "") != CollectionRecord.STATUS_PAID and _collection_status(collection, now=today)["is_overdue"]
    ]
    dated_policy_statuses = []
    for record in policy_records:
        policy_status = _broker_policy_status(record, today=today)
        if policy_status["expires_on"]:
            dated_policy_statuses.append(policy_status)
    dated_policy_statuses.sort(key=lambda item: item["expires_on"])
    next_policy_status = dated_policy_statuses[0] if dated_policy_statuses else None

    prima_values = [
        amount
        for amount in (_parse_optional_numeric_amount((record.data or {}).get("prima")) for record in policy_records)
        if amount is not None
    ]
    prima_currency = next(
        (
            str((record.data or {}).get("moneda", "")).strip()
            for record in policy_records
            if str((record.data or {}).get("moneda", "")).strip()
        ),
        "USD",
    )
    collection_currency = next((getattr(collection, "currency", "") for collection in collections if getattr(collection, "currency", "")), prima_currency)
    overdue_balance = sum(float(getattr(collection, "balance", 0) or 0) for collection in overdue_collections)

    return [
        {
            "label": "Polizas visibles",
            "value": str(len(policy_records)),
            "tone": "bg-blue-50 text-blue-700" if policy_records else "bg-slate-100 text-slate-700",
        },
        {
            "label": "Proxima vigencia",
            "value": next_policy_status["label"] if next_policy_status else "Sin vigencia",
            "tone": next_policy_status["tone"] if next_policy_status else "bg-slate-100 text-slate-700",
        },
        {
            "label": "Prima visible",
            "value": _format_currency_amount(prima_currency, sum(prima_values)) if prima_values else "USD 0",
            "tone": "bg-blue-50 text-blue-700" if prima_values else "bg-slate-100 text-slate-700",
        },
        {
            "label": "Siniestros abiertos",
            "value": str(len(open_claims)),
            "tone": "bg-red-50 text-red-700" if open_claims else "bg-green-50 text-green-700",
        },
        {
            "label": "Cobranza vencida",
            "value": _format_currency_amount(collection_currency or "USD", overdue_balance) if overdue_balance else "Sin vencidos",
            "tone": "bg-red-50 text-red-700" if overdue_collections else "bg-green-50 text-green-700",
        },
        {
            "label": "Checklist",
            "value": f"{complete_checklist}/{len(checklist)} completos" if checklist else "Sin checklist",
            "tone": "bg-green-50 text-green-700" if checklist and not missing_checklist else ("bg-amber-50 text-amber-700" if checklist else "bg-slate-100 text-slate-700"),
        },
    ]
def _is_condo_incident_closed(raw_status) -> bool:
    return _normalize_reference_token(raw_status) in {"resuelta", "cerrada", "cerrado", "closed", "done"}


def _retail_segment_field_definition(field_definitions: list[dict]) -> dict:
    return next((field for field in field_definitions if field.get("key") == "client_segment"), {})


def _retail_reference_tokens(entity: Entity) -> set[str]:
    data_extra = entity.data_extra or {}
    tokens = {
        _normalize_reference_token(entity.full_name),
        _normalize_reference_token(data_extra.get("instagram")),
    }
    return {token for token in tokens if token}


def _matching_retail_wishlists(entity: Entity, wishlist_records: list[ObjectRecord]) -> list[ObjectRecord]:
    tokens = _retail_reference_tokens(entity)
    if not tokens:
        return []
    matches = []
    for record in wishlist_records:
        cliente_token = _normalize_reference_token((record.data or {}).get("cliente"))
        if cliente_token and cliente_token in tokens:
            matches.append(record)
    return matches


def _retail_clienteling_state(entity: Entity, *, field_definitions: list[dict] | None = None, today=None) -> dict:
    field_definitions = field_definitions or []
    today = today or timezone.localdate()
    segment_field = _retail_segment_field_definition(field_definitions)
    raw_value = str((entity.data_extra or {}).get("client_segment", "") or "").strip().lower()
    valid_values = {"vip", "frecuente", "ocasional", "inactiva"}
    ultima_compra = _parse_extra_date((entity.data_extra or {}).get("ultima_compra"))
    if raw_value not in valid_values:
        if ultima_compra:
            days_since_purchase = (today - ultima_compra).days
            if days_since_purchase >= 90:
                raw_value = "inactiva"
            elif days_since_purchase <= 35:
                raw_value = "frecuente"
            else:
                raw_value = "ocasional"
        else:
            raw_value = "ocasional"

    label_map = {
        "vip": "VIP",
        "frecuente": "Frecuente",
        "ocasional": "Ocasional",
        "inactiva": "Inactiva",
    }
    tone_map = {
        "vip": "bg-fuchsia-50 text-fuchsia-700",
        "frecuente": "bg-emerald-50 text-emerald-700",
        "ocasional": "bg-blue-50 text-blue-700",
        "inactiva": "bg-amber-50 text-amber-700",
    }
    choice_label = _resolve_choice_label(raw_value, segment_field.get("choices")) if segment_field else ""
    return {
        "key": raw_value,
        "label": choice_label or label_map[raw_value],
        "tone": tone_map[raw_value],
    }


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


def _is_deliverable_completed(raw_status) -> bool:
    status = _normalize_reference_token(raw_status)
    return status in {"entregado", "cerrado", "completado", "completa", "done"}


def _matching_service_deliverables(entity: Entity, deliverable_records: list[ObjectRecord]) -> list[ObjectRecord]:
    tokens = _service_reference_tokens(entity)
    if not tokens:
        return []
    matches = []
    for record in deliverable_records:
        cliente_token = _normalize_reference_token((record.data or {}).get("cliente"))
        if cliente_token and cliente_token in tokens:
            matches.append(record)
    return matches


def _matching_service_projects(entity: Entity, project_records: list[ObjectRecord]) -> list[ObjectRecord]:
    tokens = _service_reference_tokens(entity)
    if not tokens:
        return []
    matches = []
    for record in project_records:
        cliente_token = _normalize_reference_token((record.data or {}).get("cliente"))
        if cliente_token and cliente_token in tokens:
            matches.append(record)
    return matches


def _matching_project_deliverables(project_record: ObjectRecord, deliverable_records: list[ObjectRecord]) -> list[ObjectRecord]:
    project_data = project_record.data or {}
    tokens = {
        _normalize_reference_token(project_record.title),
        _normalize_reference_token(project_data.get("nombre")),
    }
    tokens = {token for token in tokens if token}
    if not tokens:
        return []
    matches = []
    for record in deliverable_records:
        project_token = _normalize_reference_token((record.data or {}).get("proyecto"))
        if project_token and project_token in tokens:
            matches.append(record)
    return matches


def _deliverable_needs_attention(record: ObjectRecord, *, today=None) -> bool:
    today = today or timezone.localdate()
    data = record.data or {}
    status = _normalize_reference_token(data.get("estado"))
    if _is_deliverable_completed(status):
        return False
    delivery_on = _parse_extra_date(data.get("fecha_entrega"))
    review_on = _parse_extra_date(data.get("fecha_revision"))
    if status in {"bloqueado", "por_validar"}:
        return True
    if delivery_on and delivery_on <= today + timedelta(days=7):
        return True
    if review_on and review_on <= today + timedelta(days=7):
        return True
    return False


def _build_service_deliverable_report_item(record: ObjectRecord, *, today=None) -> dict:
    today = today or timezone.localdate()
    data = record.data or {}
    status_token = _normalize_reference_token(data.get("estado"))
    delivery_on = _parse_extra_date(data.get("fecha_entrega"))
    review_on = _parse_extra_date(data.get("fecha_revision"))
    status_label = {
        "bloqueado": "Bloqueado",
        "por_validar": "Por validar",
        "por_iniciar": "Por iniciar",
        "en_curso": "En curso",
        "entregado": "Entregado",
    }.get(status_token, str(data.get("estado") or "Entregable").strip().title() or "Entregable")
    attention_rank = 4
    tone = "bg-blue-50 text-blue-700"
    if status_token == "bloqueado":
        status_label = "Bloqueado"
        attention_rank = 0
        tone = "bg-red-50 text-red-700"
    elif delivery_on and delivery_on < today:
        status_label = "Atrasado"
        attention_rank = 1
        tone = "bg-red-50 text-red-700"
    elif status_token == "por_validar":
        status_label = "Por validar"
        attention_rank = 2
        tone = "bg-amber-50 text-amber-700"
    elif review_on and review_on <= today + timedelta(days=7):
        status_label = "Revision"
        attention_rank = 3
        tone = "bg-amber-50 text-amber-700"
    elif delivery_on and delivery_on <= today + timedelta(days=7):
        status_label = "Por vencer"
        attention_rank = 3
        tone = "bg-amber-50 text-amber-700"

    meta = " | ".join(
        part for part in [
            data.get("cliente", ""),
            data.get("proyecto", ""),
        ]
        if part
    )
    caption_parts = []
    if data.get("estado"):
        caption_parts.append(str(data.get("estado")).replace("_", " ").title())
    if delivery_on:
        caption_parts.append(f"Entrega {delivery_on.strftime('%d/%m/%Y')}")
    if review_on:
        caption_parts.append(f"Revision {review_on.strftime('%d/%m/%Y')}")
    href = ""
    object_key = getattr(getattr(record, "object_schema", None), "key", "")
    if object_key and getattr(record, "pk", None):
        href = reverse("binncrm:custom_object_record_detail", kwargs={"object_key": object_key, "pk": record.pk})
    item = _build_report_item(
        title=data.get("nombre") or record.title or "Entregable",
        meta=meta,
        caption=" | ".join(caption_parts),
        status=status_label,
        tone=tone,
        href=href,
        cta="Abrir entregable",
    )
    item["attention_rank"] = attention_rank
    item["sort_on"] = delivery_on or review_on or date.max
    return item


def _build_service_project_report_item(project_record: ObjectRecord, deliverable_records: list[ObjectRecord], *, today=None) -> dict:
    today = today or timezone.localdate()
    data = project_record.data or {}
    project_name = data.get("nombre") or project_record.title or "Proyecto"
    related_deliverables = _matching_project_deliverables(project_record, deliverable_records)
    open_deliverables = [
        record for record in related_deliverables
        if not _is_deliverable_completed((record.data or {}).get("estado"))
    ]
    blocked_deliverables = [
        record for record in open_deliverables
        if _normalize_reference_token((record.data or {}).get("estado")) == "bloqueado"
    ]
    pending_review_deliverables = [
        record for record in open_deliverables
        if _normalize_reference_token((record.data or {}).get("estado")) == "por_validar"
    ]
    due_soon_deliverables = [
        record for record in open_deliverables
        if (_parse_extra_date((record.data or {}).get("fecha_entrega")) or date.max) <= today + timedelta(days=7)
    ]
    next_delivery = min(
        (
            _parse_extra_date((record.data or {}).get("fecha_entrega"))
            for record in open_deliverables
            if _parse_extra_date((record.data or {}).get("fecha_entrega"))
        ),
        default=None,
    )
    next_review = min(
        (
            _parse_extra_date((record.data or {}).get("fecha_revision"))
            for record in open_deliverables
            if _parse_extra_date((record.data or {}).get("fecha_revision"))
        ),
        default=None,
    )
    target_on = _parse_extra_date(data.get("fecha_cierre_objetivo"))
    status_token = _normalize_reference_token(data.get("estado"))
    status_label = {
        "kickoff": "Kickoff",
        "en_ejecucion": "En ejecucion",
        "en_revision": "En revision",
        "cerrado": "Cerrado",
    }.get(status_token, str(data.get("estado") or "En ejecucion").replace("_", " ").title() or "En ejecucion")
    attention_rank = 5
    tone = "bg-blue-50 text-blue-700"
    if blocked_deliverables:
        status_label = "Bloqueado"
        attention_rank = 0
        tone = "bg-red-50 text-red-700"
    elif pending_review_deliverables or status_token == "en_revision":
        status_label = "En revision"
        attention_rank = 1
        tone = "bg-amber-50 text-amber-700"
    elif due_soon_deliverables or (target_on and target_on <= today + timedelta(days=7)):
        status_label = "Por cerrar"
        attention_rank = 2
        tone = "bg-amber-50 text-amber-700"
    elif status_token == "kickoff":
        status_label = "Kickoff"
        attention_rank = 3
        tone = "bg-blue-50 text-blue-700"
    elif status_token == "cerrado":
        status_label = "Cerrado"
        attention_rank = 6
        tone = "bg-green-50 text-green-700"
    elif open_deliverables:
        status_label = "En ejecucion"
        attention_rank = 4
        tone = "bg-blue-50 text-blue-700"

    meta = " | ".join(
        part for part in [
            data.get("cliente", ""),
            data.get("linea_servicio", ""),
            data.get("responsable", ""),
        ]
        if part
    )
    caption_parts = []
    if open_deliverables:
        caption_parts.append(f"{len(open_deliverables)} entregable(s) activos")
    else:
        caption_parts.append("Sin entregables activos")
    if blocked_deliverables:
        caption_parts.append(f"{len(blocked_deliverables)} bloqueado(s)")
    elif pending_review_deliverables:
        caption_parts.append(f"{len(pending_review_deliverables)} por validar")
    if next_delivery:
        caption_parts.append(f"Entrega {next_delivery.strftime('%d/%m/%Y')}")
    elif next_review:
        caption_parts.append(f"Revision {next_review.strftime('%d/%m/%Y')}")
    elif target_on:
        caption_parts.append(f"Cierre {target_on.strftime('%d/%m/%Y')}")

    href = ""
    object_key = getattr(getattr(project_record, "object_schema", None), "key", "")
    if object_key and getattr(project_record, "pk", None):
        href = reverse("binncrm:custom_object_record_detail", kwargs={"object_key": object_key, "pk": project_record.pk})
    item = _build_report_item(
        title=project_name,
        meta=meta,
        caption=" | ".join(caption_parts),
        status=status_label,
        tone=tone,
        href=href,
        cta="Abrir proyecto",
    )
    item["attention_rank"] = attention_rank
    item["sort_on"] = next_delivery or next_review or target_on or date.max
    item["project_name"] = project_name
    item["project_client"] = data.get("cliente", "")
    return item


def _build_services_handoff(entity: Entity, *, activities: list[Activity], documents: list[Document], deliverables: list[ObjectRecord], today=None) -> dict:
    today = today or timezone.localdate()
    kickoff_activity = any(
        activity.activity_type == Activity.TYPE_MEETING and "kickoff" in _normalize_reference_token(activity.title)
        for activity in activities
    )
    contract_present = any(document.document_type == "contrato_servicio" for document in documents)
    kickoff_doc_present = any(document.document_type == "kickoff" for document in documents)
    deliverable_present = bool(deliverables)
    renewal_on = _parse_extra_date((entity.data_extra or {}).get("renewal_on"))
    items = [
        {
            "label": "Contrato",
            "is_ready": contract_present,
            "status": "Listo" if contract_present else "Falta contrato",
            "tone": "bg-green-50 text-green-700" if contract_present else "bg-red-50 text-red-700",
        },
        {
            "label": "Kickoff",
            "is_ready": kickoff_activity or kickoff_doc_present,
            "status": "Listo" if kickoff_activity or kickoff_doc_present else "Falta arranque",
            "tone": "bg-green-50 text-green-700" if kickoff_activity or kickoff_doc_present else "bg-amber-50 text-amber-700",
        },
        {
            "label": "Entregable inicial",
            "is_ready": deliverable_present,
            "status": "Listo" if deliverable_present else "Falta backlog",
            "tone": "bg-green-50 text-green-700" if deliverable_present else "bg-amber-50 text-amber-700",
        },
        {
            "label": "Renovacion",
            "is_ready": renewal_on is not None,
            "status": renewal_on.strftime("%d/%m/%Y") if renewal_on else "Sin fecha",
            "tone": "bg-green-50 text-green-700" if renewal_on and renewal_on >= today else "bg-amber-50 text-amber-700",
        },
    ]
    missing_count = sum(1 for item in items if not item["is_ready"])
    return {
        "items": items,
        "missing_count": missing_count,
        "status_label": "Handoff listo" if missing_count == 0 else f"Handoff pendiente ({missing_count})",
        "status_tone": "bg-green-50 text-green-700" if missing_count == 0 else "bg-amber-50 text-amber-700",
    }



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
                "caption": entity.notes[:120] if entity.notes else "Ficha lista para operar.",
                "href": reverse("binncrm:entity_detail", kwargs={"pk": entity.pk}),
                "link_label": "Operar ficha",
            }
            for entity in Entity.objects.filter(is_active=True)
            .filter(_build_entity_search_query(query, entity_fields))
            .order_by("full_name")[:6]
        ]
        sections.append(
            _build_search_section(
                key="entities",
                title=labels.get("entity_plural", "Contactos"),
                empty_message="No aparecieron fichas con ese termino.",
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
                    "link_label": "Mover deal",
                }
            )
        sections.append(
            _build_search_section(
                key="deals",
                title=labels.get("deal_plural", "Deals"),
                empty_message="No aparecieron deals con ese termino.",
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
                    "link_label": "Operar ficha",
                }
            )
        sections.append(
            _build_search_section(
                key="activities",
                title=labels.get("activity_plural", "Actividades"),
                empty_message="No aparecieron actividades con ese termino.",
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
                    "link_label": "Seguir propuesta",
                }
            )
        sections.append(
            _build_search_section(
                key="proposals",
                title=labels.get("proposal_plural", "Propuestas"),
                empty_message="No aparecieron propuestas con ese termino.",
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
                    "link_label": "Operar cobranza",
                }
            )
        sections.append(
            _build_search_section(
                key="collections",
                title=labels.get("collection_plural", "Cobranzas"),
                empty_message="No aparecieron cobranzas con ese termino.",
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
                    "caption": document.storage_key or document.external_url or "Documento listo para operar.",
                    "href": reverse("binncrm:document_edit", kwargs={"pk": document.pk}),
                    "link_label": "Operar documento",
                }
            )
        sections.append(
            _build_search_section(
                key="documents",
                title=labels.get("document_plural", "Documentos"),
                empty_message="No aparecieron documentos con ese termino.",
                items=document_items,
                href=f"{reverse('binncrm:documents')}?{urlencode({'q': query})}",
            )
        )

    return sections


def _build_report_item(
    *,
    title: str,
    meta: str = "",
    caption: str = "",
    status: str = "",
    tone: str = "bg-gray-100 text-gray-700",
    href: str = "",
    cta: str = "",
) -> dict:
    return {
        "title": title,
        "meta": meta,
        "caption": caption,
        "status": status,
        "tone": tone,
        "href": href,
        "cta": cta,
    }


def _build_broker_lifecycle_summary(*, entities: list[Entity], field_definitions: list[dict]) -> list[dict]:
    counters = {"lead": 0, "asegurado": 0, "renovacion": 0}
    for entity in entities:
        state = _broker_lifecycle_state(entity, field_definitions=field_definitions)
        counters[state["key"]] += 1
    return [
        {
            "label": "Leads",
            "value": counters["lead"],
            "caption": "Contactos por convertir a asegurados formales.",
            "tone": "bg-slate-100 text-slate-700",
        },
        {
            "label": "Asegurados",
            "value": counters["asegurado"],
            "caption": "Clientes ya vigentes pero sin renovacion activa encima.",
            "tone": "bg-blue-50 text-blue-700",
        },
        {
            "label": "En renovacion",
            "value": counters["renovacion"],
            "caption": "Fichas que ya tienen renovaciones abiertas o en curso.",
            "tone": "bg-amber-50 text-amber-700",
        },
    ]


def _build_services_lifecycle_summary(*, entities: list[Entity], field_definitions: list[dict], today=None) -> list[dict]:
    counters = {"prospecto": 0, "cliente_activo": 0, "renovacion_upsell": 0}
    for entity in entities:
        state = _services_lifecycle_state(entity, field_definitions=field_definitions, today=today)
        counters[state["key"]] += 1
    return [
        {
            "label": "Prospectos B2B",
            "value": counters["prospecto"],
            "caption": "Cuentas todavia en tramo comercial o discovery.",
            "tone": "bg-slate-100 text-slate-700",
        },
        {
            "label": "Clientes activos",
            "value": counters["cliente_activo"],
            "caption": "Cuentas ya ganadas con servicio en curso.",
            "tone": "bg-emerald-50 text-emerald-700",
        },
        {
            "label": "Renovacion / upsell",
            "value": counters["renovacion_upsell"],
            "caption": "Clientes que ya piden renovacion, expansion o siguiente alcance.",
            "tone": "bg-amber-50 text-amber-700",
        },
    ]


def _service_line_field_definition(field_definitions: list[dict]) -> dict:
    return next((field for field in field_definitions if field.get("key") == "service_line"), {})


def _service_account_health_field_definition(field_definitions: list[dict]) -> dict:
    return next((field for field in field_definitions if field.get("key") == "account_health"), {})


def _coerce_local_date(value):
    if isinstance(value, datetime):
        return timezone.localdate(value)
    if isinstance(value, date):
        return value
    return None


def _parse_numeric_amount(value) -> float:
    raw_value = str(value or "").strip()
    if not raw_value:
        return 0.0
    normalized = raw_value.replace(",", ".")
    try:
        return float(normalized)
    except ValueError:
        return 0.0


def _service_line_label(entity: Entity, *, field_definitions: list[dict] | None = None) -> str:
    field_definitions = field_definitions or []
    line_field = _service_line_field_definition(field_definitions)
    raw_value = str((entity.data_extra or {}).get("service_line", "") or "").strip()
    return _resolve_choice_label(raw_value, line_field.get("choices")) or raw_value or "Sin linea"


def _service_account_health_state(entity: Entity, *, field_definitions: list[dict] | None = None, today=None) -> dict:
    field_definitions = field_definitions or []
    today = today or timezone.localdate()
    health_field = _service_account_health_field_definition(field_definitions)
    raw_value = _normalize_reference_token((entity.data_extra or {}).get("account_health"))
    valid_values = {"estable", "seguimiento", "riesgo", "expansion"}
    if raw_value not in valid_values:
        lifecycle = _services_lifecycle_state(entity, field_definitions=field_definitions, today=today)
        if lifecycle["key"] == "renovacion_upsell":
            raw_value = "expansion"
        elif lifecycle["key"] == "cliente_activo":
            raw_value = "estable"
        else:
            raw_value = "seguimiento"
    label_map = {
        "estable": "Estable",
        "seguimiento": "Seguimiento",
        "riesgo": "En riesgo",
        "expansion": "Expansion",
    }
    tone_map = {
        "estable": "bg-green-50 text-green-700",
        "seguimiento": "bg-blue-50 text-blue-700",
        "riesgo": "bg-red-50 text-red-700",
        "expansion": "bg-amber-50 text-amber-700",
    }
    choice_label = _resolve_choice_label(raw_value, health_field.get("choices")) if health_field else ""
    return {
        "key": raw_value,
        "label": choice_label or label_map[raw_value],
        "tone": tone_map[raw_value],
    }


def _service_activation_snapshot(entity: Entity, *, won_deals: list, activities: list, documents: list) -> dict:
    won_dates = [
        _coerce_local_date(getattr(deal, "updated_at", None))
        for deal in list(won_deals or [])
    ]
    won_dates = [value for value in won_dates if value]
    kickoff_dates = []
    for activity in list(activities or []):
        if getattr(activity, "activity_type", "") != Activity.TYPE_MEETING:
            continue
        if "kickoff" not in _normalize_reference_token(getattr(activity, "title", "")):
            continue
        kickoff_dates.append(_coerce_local_date(getattr(activity, "due_at", None)) or _coerce_local_date(getattr(activity, "created_at", None)))
    for document in list(documents or []):
        if getattr(document, "document_type", "") != "kickoff":
            continue
        kickoff_dates.append(_coerce_local_date(getattr(document, "created_at", None)))
    kickoff_dates = [value for value in kickoff_dates if value]
    started_on = _parse_extra_date((entity.data_extra or {}).get("started_on"))
    first_won_on = min(won_dates) if won_dates else None
    kickoff_on = min(kickoff_dates) if kickoff_dates else None
    activation_on = kickoff_on or started_on
    lag_days = None
    if first_won_on and activation_on and activation_on >= first_won_on:
        lag_days = (activation_on - first_won_on).days
    return {
        "first_won_on": first_won_on,
        "kickoff_on": kickoff_on,
        "started_on": started_on,
        "activation_on": activation_on,
        "lag_days": lag_days,
        "pending_kickoff": bool(first_won_on and not kickoff_on),
    }


def _build_services_analytics_bundle(
    *,
    entities: list[Entity],
    field_definitions: list[dict],
    project_records: list[ObjectRecord],
    deliverable_records: list[ObjectRecord],
    won_deals_by_entity: dict[int, list],
    activities_by_entity: dict[int, list],
    documents_by_entity: dict[int, list],
    today=None,
) -> dict:
    today = today or timezone.localdate()
    line_buckets: dict[str, dict] = {}
    health_focus_items = []
    activation_items = []
    retainer_active_total = 0.0
    renewal_retainer_total = 0.0
    risk_accounts = 0
    activation_lags = []

    for entity in entities:
        entity_pk = getattr(entity, "pk", None)
        lifecycle = _services_lifecycle_state(entity, field_definitions=field_definitions, today=today)
        health = _service_account_health_state(entity, field_definitions=field_definitions, today=today)
        service_line = _service_line_label(entity, field_definitions=field_definitions)
        retainer_value = _parse_numeric_amount((entity.data_extra or {}).get("retainer_mensual"))
        is_active_account = lifecycle["key"] != "prospecto"
        if is_active_account:
            retainer_active_total += retainer_value
        if lifecycle["key"] == "renovacion_upsell":
            renewal_retainer_total += retainer_value
        if health["key"] == "riesgo":
            risk_accounts += 1

        bucket = line_buckets.setdefault(
            service_line,
            {"label": service_line, "total": 0, "active": 0, "risk": 0, "renewal": 0, "retainer": 0.0},
        )
        bucket["total"] += 1
        bucket["active"] += 1 if is_active_account else 0
        bucket["risk"] += 1 if health["key"] == "riesgo" else 0
        bucket["renewal"] += 1 if lifecycle["key"] == "renovacion_upsell" else 0
        bucket["retainer"] += retainer_value

        if health["key"] in {"riesgo", "expansion"} or lifecycle["key"] == "renovacion_upsell":
            renewal_on = _parse_extra_date((entity.data_extra or {}).get("renewal_on"))
            caption_parts = []
            if (entity.data_extra or {}).get("servicio_principal"):
                caption_parts.append((entity.data_extra or {}).get("servicio_principal"))
            if renewal_on:
                caption_parts.append(f"Renovacion {renewal_on.strftime('%d/%m/%Y')}")
            if retainer_value:
                caption_parts.append(_format_currency_amount("USD", retainer_value))
            health_focus_items.append(
                _build_report_item(
                    title=(entity.data_extra or {}).get("empresa") or entity.full_name,
                    meta=" | ".join(part for part in [service_line, (entity.data_extra or {}).get("delivery_owner", "")] if part),
                    caption=" | ".join(caption_parts) or "Cuenta con lectura prioritaria para direccion.",
                    status=health["label"],
                    tone=health["tone"],
                    href=reverse("binncrm:entity_detail", kwargs={"pk": entity_pk}) if entity_pk else "",
                    cta="Abrir cuenta",
                )
            )

        snapshot = _service_activation_snapshot(
            entity,
            won_deals=won_deals_by_entity.get(entity_pk, []),
            activities=activities_by_entity.get(entity_pk, []),
            documents=documents_by_entity.get(entity_pk, []),
        )
        if snapshot["lag_days"] is not None:
            activation_lags.append(snapshot["lag_days"])
        if snapshot["first_won_on"]:
            if snapshot["pending_kickoff"]:
                status_label = "Pendiente kickoff"
                tone = "bg-red-50 text-red-700"
            elif snapshot["lag_days"] is None:
                status_label = "Sin medicion"
                tone = "bg-slate-100 text-slate-700"
            elif snapshot["lag_days"] > 14:
                status_label = f"{snapshot['lag_days']} dias"
                tone = "bg-red-50 text-red-700"
            elif snapshot["lag_days"] > 7:
                status_label = f"{snapshot['lag_days']} dias"
                tone = "bg-amber-50 text-amber-700"
            else:
                status_label = f"{snapshot['lag_days']} dias"
                tone = "bg-green-50 text-green-700"
            activation_items.append(
                _build_report_item(
                    title=(entity.data_extra or {}).get("empresa") or entity.full_name,
                    meta=" | ".join(part for part in [service_line, (entity.data_extra or {}).get("delivery_owner", "")] if part),
                    caption=" | ".join(
                        part for part in [
                            f"Ganado {snapshot['first_won_on'].strftime('%d/%m/%Y')}" if snapshot["first_won_on"] else "",
                            f"Kickoff {snapshot['kickoff_on'].strftime('%d/%m/%Y')}" if snapshot["kickoff_on"] else "Sin kickoff",
                            f"Inicio {snapshot['started_on'].strftime('%d/%m/%Y')}" if snapshot["started_on"] else "",
                        ]
                        if part
                    ),
                    status=status_label,
                    tone=tone,
                    href=reverse("binncrm:entity_detail", kwargs={"pk": entity_pk}) if entity_pk else "",
                    cta="Abrir cuenta",
                )
            )

    avg_activation_days = round(sum(activation_lags) / len(activation_lags), 1) if activation_lags else None
    active_project_records = [
        record for record in project_records
        if _normalize_reference_token((record.data or {}).get("estado")) != "cerrado"
    ]
    owner_buckets: dict[str, dict] = {}
    for project_record in active_project_records:
        data = project_record.data or {}
        owner = data.get("responsable") or "Sin responsable"
        bucket = owner_buckets.setdefault(owner, {"owner": owner, "total": 0, "blocked": 0, "review": 0, "due_soon": 0, "lines": set()})
        bucket["total"] += 1
        line_value = str(data.get("linea_servicio") or "").strip()
        if line_value:
            bucket["lines"].add(line_value)
        status_token = _normalize_reference_token(data.get("estado"))
        if status_token == "en_revision":
            bucket["review"] += 1
        if _build_service_project_report_item(project_record, deliverable_records, today=today)["status"] == "Bloqueado":
            bucket["blocked"] += 1
        target_on = _parse_extra_date(data.get("fecha_cierre_objetivo"))
        if target_on and target_on <= today + timedelta(days=7):
            bucket["due_soon"] += 1

    analytics_cards = [
        {"label": "Retainer activo", "value": _format_currency_amount("USD", retainer_active_total), "caption": "Ingreso mensual visible en cuentas activas o en renovacion.", "tone": "bg-blue-50 text-blue-700" if retainer_active_total else "bg-slate-100 text-slate-700"},
        {"label": "Renovacion mensual", "value": _format_currency_amount("USD", renewal_retainer_total), "caption": "MRR expuesto en cuentas que ya piden renovacion o siguiente alcance.", "tone": "bg-amber-50 text-amber-700" if renewal_retainer_total else "bg-green-50 text-green-700"},
        {"label": "Cuentas en riesgo", "value": risk_accounts, "caption": "Clientes que ya muestran senal clara de friccion o deterioro.", "tone": "bg-red-50 text-red-700" if risk_accounts else "bg-green-50 text-green-700"},
        {"label": "Activacion promedio", "value": f"{avg_activation_days} dias" if avg_activation_days is not None else "s/d", "caption": "Tiempo medio desde negocio ganado hasta kickoff o arranque visible.", "tone": "bg-emerald-50 text-emerald-700" if avg_activation_days is not None and avg_activation_days <= 7 else "bg-amber-50 text-amber-700" if avg_activation_days is not None else "bg-slate-100 text-slate-700"},
    ]

    service_line_items = []
    for bucket in sorted(line_buckets.values(), key=lambda item: (-item["active"], -item["retainer"], item["label"])):
        if bucket["risk"] > 0:
            status_label = "En riesgo"
            tone = "bg-red-50 text-red-700"
        elif bucket["renewal"] > 0:
            status_label = "Renovacion"
            tone = "bg-amber-50 text-amber-700"
        elif bucket["active"] > 0:
            status_label = "Activa"
            tone = "bg-green-50 text-green-700"
        else:
            status_label = "Prospecto"
            tone = "bg-slate-100 text-slate-700"
        service_line_items.append(
            _build_report_item(
                title=bucket["label"],
                meta=f"{bucket['total']} cuenta(s)",
                caption=" | ".join(part for part in [f"{bucket['active']} activa(s)", f"{bucket['risk']} en riesgo" if bucket["risk"] else "", f"{bucket['renewal']} en renovacion" if bucket["renewal"] else "", _format_currency_amount("USD", bucket["retainer"]) if bucket["retainer"] else ""] if part),
                status=status_label,
                tone=tone,
                href=reverse("binncrm:entities"),
                cta="Abrir cartera",
            )
        )

    owner_items = []
    for bucket in sorted(owner_buckets.values(), key=lambda item: (-item["blocked"], -item["review"], -item["total"], item["owner"])):
        if bucket["blocked"] > 0:
            status_label = "Bloqueos"
            tone = "bg-red-50 text-red-700"
        elif bucket["review"] > 0:
            status_label = "Revision"
            tone = "bg-amber-50 text-amber-700"
        elif bucket["due_soon"] > 0:
            status_label = "Por cerrar"
            tone = "bg-amber-50 text-amber-700"
        else:
            status_label = "Operando"
            tone = "bg-blue-50 text-blue-700"
        owner_items.append(
            _build_report_item(
                title=bucket["owner"],
                meta=" | ".join(sorted(bucket["lines"])) or "Sin linea definida",
                caption=" | ".join(part for part in [f"{bucket['total']} proyecto(s)", f"{bucket['blocked']} bloqueado(s)" if bucket["blocked"] else "", f"{bucket['review']} en revision" if bucket["review"] else "", f"{bucket['due_soon']} por cerrar" if bucket["due_soon"] else ""] if part),
                status=status_label,
                tone=tone,
                href=reverse("binncrm:custom_object_records", kwargs={"object_key": "proyecto"}),
                cta="Abrir proyectos",
            )
        )

    analytics_sections = [
        {"title": "Cartera por linea de servicio", "subtitle": "Distribucion de cuentas, retainer visible y presion operativa por tipo de servicio.", "href": reverse("binncrm:entities"), "cta": "Cobrar cartera", "empty_message": "No hay cuentas de servicio registradas todavia.", "items": service_line_items},
        {"title": "Cuentas en riesgo y expansion", "subtitle": "Fichas que merecen lectura de direccion por deterioro o por oportunidad clara de crecimiento.", "href": reverse("binncrm:entities"), "cta": "Operar cuentas", "empty_message": "No hay cuentas marcadas en riesgo o expansion ahora mismo.", "items": sorted(health_focus_items, key=lambda item: (0 if item["status"] == "En riesgo" else 1, item["title"]))[:6]},
        {"title": "Capacidad por responsable", "subtitle": "Carga operativa, bloqueos y cierres proximos por cada owner de delivery.", "href": reverse("binncrm:custom_object_records", kwargs={"object_key": "proyecto"}), "cta": "Operar proyectos", "empty_message": "No hay proyectos activos para repartir capacidad todavia.", "items": owner_items[:6]},
        {"title": "Activacion comercial -> delivery", "subtitle": "Tiempo real desde negocio ganado hasta kickoff o arranque visible por cuenta.", "href": reverse("binncrm:entities"), "cta": "Operar cuentas", "empty_message": "No hay cuentas activadas suficientes para medir este tramo.", "items": sorted(activation_items, key=lambda item: (0 if item["status"] == "Pendiente kickoff" else 1, item["title"]))[:6]},
    ]
    return {"cards": analytics_cards, "sections": analytics_sections}



def _build_reports_copy(profile: str, labels: dict) -> dict:
    entity_plural = labels.get("entity_plural", "Contactos")
    deal_plural = labels.get("deal_plural", "Oportunidades")
    profiles = {
        "broker": {
            "kicker": "Radar broker",
            "title": "Renovaciones y documentos",
            "subtitle": "Vencimientos, siniestros y faltantes.",
            "highlights": ["Renovaciones proximas", "Siniestros abiertos", "Checklist documental"],
        },
        "condominio": {
            "kicker": "Radar de cobro",
            "title": "Cartera y residentes",
            "subtitle": "Mora, promesas y seguimiento.",
            "highlights": ["Cartera vencida", "Residentes sin contacto", "Gestiones atrasadas"],
        },
        "servicios": {
            "kicker": "Radar B2B",
            "title": "Propuestas y cobros",
            "subtitle": "Deals quietos, cierres y cuentas en riesgo.",
            "highlights": ["Deals quietos", "Propuestas por vencer", "Cobros por empujar"],
        },
        "retail_moda": {
            "kicker": "Radar de recompra",
            "title": "Recompra y clientas",
            "subtitle": "Inactivas, pedidos y seguimiento.",
            "highlights": ["Clientes inactivos", "Pedidos especiales", "Seguimientos de recompra"],
        },
        "marketing": {
            "kicker": "Radar de captacion",
            "title": "Leads y pipeline",
            "subtitle": "Embudo, tareas y propuestas.",
            "highlights": ["Embudo enfriandose", "Propuestas vigentes", "Seguimiento atrasado"],
        },
    }
    shared = {
        "kicker": "Radar Binn",
        "title": "Radar operativo",
        "subtitle": "Seguimiento, vencimientos y dinero pendiente.",
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
    return f"{value[: limit - 1].rstrip()}..."


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
            "proposal_ops": build_proposal_operational_context(request.tenant),
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
            "collection_ops": build_collection_operational_context(request.tenant),
        },
    )


def _render_document_form(request, form, *, page_title: str, submit_label: str, document=None):
    profile = _tenant_profile(request.tenant)
    today = timezone.localdate()
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
                    audit_action="updated" if is_edit else "created",
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
                    audit_action="removed",
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
                    audit_action="set_default",
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
                    audit_action="reordered",
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
    profile = _tenant_profile(request.tenant)
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
    if profile == "broker":
        queryset = queryset.annotate(
            deal_count=Count("deals", filter=Q(deals__is_active=True), distinct=True),
            open_deal_count=Count(
                "deals",
                filter=Q(deals__is_active=True, deals__status=Deal.STATUS_OPEN),
                distinct=True,
            ),
        )
    elif profile == "servicios":
        queryset = queryset.annotate(
            deal_count=Count("deals", filter=Q(deals__is_active=True), distinct=True),
            open_deal_count=Count(
                "deals",
                filter=Q(deals__is_active=True, deals__status=Deal.STATUS_OPEN),
                distinct=True,
            ),
            won_deal_count=Count(
                "deals",
                filter=Q(deals__is_active=True, deals__status=Deal.STATUS_WON),
                distinct=True,
            ),
        )
    elif profile == "condominio":
        today = timezone.localdate()
        queryset = queryset.annotate(
            open_collection_count=Count(
                "collections",
                filter=Q(collections__is_active=True) & ~Q(collections__status=CollectionRecord.STATUS_PAID),
                distinct=True,
            ),
            promised_collection_count=Count(
                "collections",
                filter=Q(collections__is_active=True, collections__status=CollectionRecord.STATUS_PROMISED),
                distinct=True,
            ),
            overdue_collection_count=Count(
                "collections",
                filter=Q(collections__is_active=True)
                & ~Q(collections__status=CollectionRecord.STATUS_PAID)
                & Q(collections__due_on__lt=today),
                distinct=True,
            ),
        )
    elif profile == "retail_moda":
        queryset = queryset.annotate(
            deal_count=Count("deals", filter=Q(deals__is_active=True), distinct=True),
            open_deal_count=Count(
                "deals",
                filter=Q(deals__is_active=True, deals__status=Deal.STATUS_OPEN),
                distinct=True,
            ),
        )
    queryset = apply_entity_saved_view(queryset, view=current_view)
    if q:
        queryset = queryset.filter(_build_entity_search_query(q, entity_fields))

    entity_list = list(queryset[:100])
    column_definitions = entity_fields[:2]
    entity_rows = [
        {
            "instance": entity,
            "extra_values": _build_extra_values(entity, column_definitions),
            "broker_lifecycle": _broker_lifecycle_state(entity, field_definitions=entity_fields) if profile == "broker" else None,
            "service_lifecycle": _services_lifecycle_state(entity, field_definitions=entity_fields) if profile == "servicios" else None,
            "condo_status": _condo_resident_status(entity, field_definitions=entity_fields) if profile == "condominio" else None,
            "retail_segment": _retail_clienteling_state(entity, field_definitions=entity_fields) if profile == "retail_moda" else None,
        }
        for entity in entity_list
    ]

    context = {
        "labels": labels,
        "profile": profile,
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
    _require_crm_permission(request, PERMISSION_ENTITIES_EDIT, capability="entities")
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
                _audit_crm_action(
                    request,
                    action="imported",
                    object_type="entity",
                    title=f"Importacion de {request.tenant.get_label('entity_plural', 'contactos').lower()} completada",
                    message=(
                        f"Se procesaron {import_summary['processed']} filas: "
                        f"{import_summary['created']} creadas, "
                        f"{import_summary['updated']} actualizadas y "
                        f"{import_summary['skipped']} omitidas."
                    ),
                    metadata={
                        "processed": import_summary["processed"],
                        "created": import_summary["created"],
                        "updated": import_summary["updated"],
                        "skipped": import_summary["skipped"],
                        "error_count": import_summary["error_count"],
                        "update_existing": form.cleaned_data["update_existing"],
                    },
                )
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
    _require_crm_permission(request, PERMISSION_ENTITIES_EDIT, capability="entities")
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
            _audit_crm_action(
                request,
                action="created",
                object_type="entity",
                title=f"{request.tenant.get_label('entity_singular', 'Contacto')} creado",
                message=f"Se creo '{entity.full_name}'.",
                metadata={
                    "entity_id": entity.pk,
                    "entity_name": entity.full_name,
                },
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
    profile = _tenant_profile(request.tenant)
    entity_queryset = Entity.objects.all()
    if profile == "broker":
        entity_queryset = entity_queryset.annotate(
            deal_count=Count("deals", filter=Q(deals__is_active=True), distinct=True),
            open_deal_count=Count(
                "deals",
                filter=Q(deals__is_active=True, deals__status=Deal.STATUS_OPEN),
                distinct=True,
            ),
        )
    elif profile == "servicios":
        entity_queryset = entity_queryset.annotate(
            deal_count=Count("deals", filter=Q(deals__is_active=True), distinct=True),
            open_deal_count=Count(
                "deals",
                filter=Q(deals__is_active=True, deals__status=Deal.STATUS_OPEN),
                distinct=True,
            ),
            won_deal_count=Count(
                "deals",
                filter=Q(deals__is_active=True, deals__status=Deal.STATUS_WON),
                distinct=True,
            ),
        )
    elif profile == "condominio":
        today = timezone.localdate()
        entity_queryset = entity_queryset.annotate(
            open_collection_count=Count(
                "collections",
                filter=Q(collections__is_active=True) & ~Q(collections__status=CollectionRecord.STATUS_PAID),
                distinct=True,
            ),
            promised_collection_count=Count(
                "collections",
                filter=Q(collections__is_active=True, collections__status=CollectionRecord.STATUS_PROMISED),
                distinct=True,
            ),
            overdue_collection_count=Count(
                "collections",
                filter=Q(collections__is_active=True)
                & ~Q(collections__status=CollectionRecord.STATUS_PAID)
                & Q(collections__due_on__lt=today),
                distinct=True,
            ),
        )
    elif profile == "retail_moda":
        entity_queryset = entity_queryset.annotate(
            deal_count=Count("deals", filter=Q(deals__is_active=True), distinct=True),
            open_deal_count=Count(
                "deals",
                filter=Q(deals__is_active=True, deals__status=Deal.STATUS_OPEN),
                distinct=True,
            ),
        )
    entity = get_object_or_404(entity_queryset, pk=pk)
    entity_field_definitions = get_entity_field_definitions(tenant=request.tenant)
    extra_values = _build_extra_values(entity, entity_field_definitions)
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
    all_activities = (
        list(entity.activities.select_related("deal", "assigned_to").order_by("-created_at"))
        if can_view_activities
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
    recent_meetings = [activity for activity in all_activities if activity.activity_type == Activity.TYPE_MEETING][:5]
    recent_proposals = (
        list(entity.proposals.select_related("deal").order_by("-updated_at")[:5])
        if can_view_proposals
        else []
    )
    all_collections = (
        list(entity.collections.select_related("deal").order_by("due_on", "-updated_at"))
        if can_view_collections
        else []
    )
    recent_collections = all_collections[:5]
    project_records = []
    project_schema = None
    deliverable_records = []
    deliverable_schema = None
    condo_unit_records = []
    condo_incident_records = []
    condo_communication_records = []
    condo_unit_schema = None
    condo_incident_schema = None
    condo_communication_schema = None
    retail_wishlist_records = []
    retail_wishlist_schema = None
    broker_policy_records = []
    broker_policy_schema = None
    if profile == "broker" and _can(request, PERMISSION_OBJECTS_VIEW):
        broker_policy_schema = get_object_schema_definition(object_key="poliza_detalle")
        if broker_policy_schema is not None and broker_policy_schema.source == ObjectSchema.SOURCE_CUSTOM:
            broker_policy_records = _matching_broker_policy_records(
                entity,
                list(ObjectRecord.objects.filter(object_schema=broker_policy_schema, is_active=True).order_by("-updated_at", "-id")),
                documents=all_documents,
            )
    elif profile == "servicios" and _can(request, PERMISSION_OBJECTS_VIEW):
        project_schema = get_object_schema_definition(object_key="proyecto")
        if project_schema is not None and project_schema.source == ObjectSchema.SOURCE_CUSTOM:
            project_records = _matching_service_projects(
                entity,
                list(ObjectRecord.objects.filter(object_schema=project_schema, is_active=True).order_by("-updated_at", "-id")),
            )
        deliverable_schema = get_object_schema_definition(object_key="entregable")
        if deliverable_schema is not None and deliverable_schema.source == ObjectSchema.SOURCE_CUSTOM:
            deliverable_records = _matching_service_deliverables(
                entity,
                list(ObjectRecord.objects.filter(object_schema=deliverable_schema, is_active=True).order_by("-updated_at", "-id")),
            )
    elif profile == "condominio" and _can(request, PERMISSION_OBJECTS_VIEW):
        condo_unit_schema = get_object_schema_definition(object_key="unidad")
        if condo_unit_schema is not None and condo_unit_schema.source == ObjectSchema.SOURCE_CUSTOM:
            condo_unit_records = _matching_condo_records(
                entity,
                list(ObjectRecord.objects.filter(object_schema=condo_unit_schema, is_active=True).order_by("-updated_at", "-id")),
                "codigo_unidad",
                "residente_actual",
                "propietario",
            )
        condo_incident_schema = get_object_schema_definition(object_key="incidencia")
        if condo_incident_schema is not None and condo_incident_schema.source == ObjectSchema.SOURCE_CUSTOM:
            condo_incident_records = _matching_condo_records(
                entity,
                list(ObjectRecord.objects.filter(object_schema=condo_incident_schema, is_active=True).order_by("-updated_at", "-id")),
                "codigo_unidad",
                "residente",
            )
        condo_communication_schema = get_object_schema_definition(object_key="comunicado")
        if condo_communication_schema is not None and condo_communication_schema.source == ObjectSchema.SOURCE_CUSTOM:
            condo_communication_records = _matching_condo_records(
                entity,
                list(ObjectRecord.objects.filter(object_schema=condo_communication_schema, is_active=True).order_by("-updated_at", "-id")),
                "codigo_unidad",
                "dirigido_a",
            )
    elif profile == "retail_moda" and _can(request, PERMISSION_OBJECTS_VIEW):
        retail_wishlist_schema = get_object_schema_definition(object_key="wishlist")
        if retail_wishlist_schema is not None and retail_wishlist_schema.source == ObjectSchema.SOURCE_CUSTOM:
            retail_wishlist_records = _matching_retail_wishlists(
                entity,
                list(ObjectRecord.objects.filter(object_schema=retail_wishlist_schema, is_active=True).order_by("-updated_at", "-id")),
            )
    services_project_items = []
    if profile == "servicios":
        for record in project_records[:3]:
            item = _build_service_project_report_item(record, deliverable_records, today=today)
            project_name = item.get("project_name") or (record.data or {}).get("nombre") or record.title or ""
            project_client = item.get("project_client") or (entity.data_extra or {}).get("empresa") or entity.full_name
            item["deliverable_href"] = (
                f"{reverse('binncrm:custom_object_record_create', kwargs={'object_key': deliverable_schema.key})}?{urlencode({'cliente': project_client, 'proyecto': project_name})}"
                if deliverable_schema is not None and _can(request, PERMISSION_OBJECTS_EDIT)
                else ""
            )
            services_project_items.append(item)
    if profile == "condominio":
        setattr(
            entity,
            "open_collection_count",
            sum(1 for collection in all_collections if collection.status != CollectionRecord.STATUS_PAID),
        )
        setattr(
            entity,
            "promised_collection_count",
            sum(1 for collection in all_collections if collection.status == CollectionRecord.STATUS_PROMISED),
        )
        setattr(
            entity,
            "overdue_collection_count",
            sum(1 for collection in all_collections if _collection_status(collection)["is_overdue"]),
        )
    condo_status = _condo_resident_status(entity, field_definitions=entity_field_definitions) if profile == "condominio" else None
    condo_currency = next((collection.currency for collection in all_collections if getattr(collection, "currency", "")), "USD")
    condo_open_balance = sum((collection.balance or 0 for collection in all_collections if collection.status != CollectionRecord.STATUS_PAID), 0)
    condo_overdue_balance = sum((collection.balance or 0 for collection in all_collections if _collection_status(collection)["is_overdue"]), 0)
    condo_latest_statement = next((document for document in all_documents if document.document_type == "estado_cuenta"), None)
    condo_latest_payment_proof = next((document for document in all_documents if document.document_type == "comprobante_pago"), None)
    condo_summary_items = []
    retail_segment = _retail_clienteling_state(entity, field_definitions=entity_field_definitions) if profile == "retail_moda" else None
    retail_last_purchase = _parse_extra_date((entity.data_extra or {}).get("ultima_compra")) if profile == "retail_moda" else None
    retail_open_wishlists = [record for record in retail_wishlist_records if (record.data or {}).get("vigente")]
    retail_summary_items = []
    broker_summary_items = []
    broker_policy_items = []
    if profile == "broker":
        broker_summary_items = _build_broker_entity_summary(
            entity,
            policy_records=broker_policy_records,
            documents=all_documents,
            activities=all_activities,
            collections=all_collections,
            blueprint_map=blueprint_map,
            today=today,
        )
        broker_policy_display_records = _collect_broker_due_policy_records(
            broker_policy_records,
            today=today,
            window_days=365,
        )
        for record in broker_policy_records:
            if record not in broker_policy_display_records:
                broker_policy_display_records.append(record)
        for record in broker_policy_display_records[:4]:
            href = (
                reverse("binncrm:custom_object_record_detail", kwargs={"object_key": broker_policy_schema.key, "pk": record.pk})
                if broker_policy_schema is not None and getattr(record, "pk", None)
                else ""
            )
            broker_policy_items.append(
                _build_broker_policy_report_item(
                    record,
                    today=today,
                    href=href,
                    cta="Abrir poliza",
                )
            )
    if profile == "condominio":
        condo_summary_items = [
            {
                "label": "Unidad",
                "value": (entity.data_extra or {}).get("departamento")
                or ((condo_unit_records[0].data or {}).get("codigo_unidad") if condo_unit_records else "")
                or "Sin unidad",
                "tone": "bg-slate-100 text-slate-700",
            },
            {
                "label": "Cartera abierta",
                "value": _format_currency_amount(condo_currency, condo_open_balance),
                "tone": "bg-blue-50 text-blue-700" if condo_open_balance else "bg-green-50 text-green-700",
            },
            {
                "label": "Cartera vencida",
                "value": _format_currency_amount(condo_currency, condo_overdue_balance),
                "tone": "bg-red-50 text-red-700" if condo_overdue_balance else "bg-green-50 text-green-700",
            },
            {
                "label": "Incidencias",
                "value": str(sum(1 for record in condo_incident_records if not _is_condo_incident_closed((record.data or {}).get("estado")))),
                "tone": "bg-amber-50 text-amber-700" if condo_incident_records else "bg-slate-100 text-slate-700",
            },
            {
                "label": "Estado de cuenta",
                "value": condo_latest_statement.title if condo_latest_statement else "No cargado",
                "tone": "bg-blue-50 text-blue-700" if condo_latest_statement else "bg-slate-100 text-slate-700",
            },
            {
                "label": "Ultimo comprobante",
                "value": condo_latest_payment_proof.title if condo_latest_payment_proof else "Sin comprobante",
                "tone": "bg-green-50 text-green-700" if condo_latest_payment_proof else "bg-slate-100 text-slate-700",
            },
        ]
    elif profile == "retail_moda":
        retail_summary_items = [
            {
                "label": "Segmento",
                "value": retail_segment["label"] if retail_segment else "Sin segmento",
                "tone": retail_segment["tone"] if retail_segment else "bg-slate-100 text-slate-700",
            },
            {
                "label": "Ultima compra",
                "value": retail_last_purchase.strftime("%d/%m/%Y") if retail_last_purchase else "Sin compra",
                "tone": "bg-emerald-50 text-emerald-700" if retail_last_purchase else "bg-slate-100 text-slate-700",
            },
            {
                "label": "Canal preferido",
                "value": _format_extra_value((entity.data_extra or {}).get("canal_preferido"), {"type": "select", "choices": [
                    {"value": "whatsapp", "label": "WhatsApp"},
                    {"value": "instagram", "label": "Instagram"},
                    {"value": "tienda", "label": "Tienda"},
                    {"value": "email", "label": "Email"},
                ]}) or "Sin canal",
                "tone": "bg-blue-50 text-blue-700",
            },
            {
                "label": "Pedidos abiertos",
                "value": str(getattr(entity, "open_deal_count", 0) or 0),
                "tone": "bg-amber-50 text-amber-700" if (getattr(entity, "open_deal_count", 0) or 0) else "bg-slate-100 text-slate-700",
            },
            {
                "label": "Wishlists activas",
                "value": str(len(retail_open_wishlists)),
                "tone": "bg-fuchsia-50 text-fuchsia-700" if retail_open_wishlists else "bg-slate-100 text-slate-700",
            },
        ]
    context = {
        "labels": request.tenant.tenant_config.labels,
        "entity": entity,
        "recent_deals": entity.deals.select_related("pipeline").order_by("-updated_at")[:5] if can_view_deals else [],
        "recent_proposal_cards": [_build_proposal_card(proposal) for proposal in recent_proposals],
        "recent_collection_cards": [_build_collection_card(collection) for collection in recent_collections],
        "recent_activities": (
            all_activities[:6]
            if can_view_activities
            else []
        ),
        "recent_meetings": recent_meetings,
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
        "broker_lifecycle": _broker_lifecycle_state(entity, field_definitions=entity_field_definitions) if profile == "broker" else None,
        "broker_summary_items": broker_summary_items,
        "broker_policy_items": broker_policy_items,
        "service_lifecycle": _services_lifecycle_state(entity, field_definitions=entity_field_definitions) if profile == "servicios" else None,
        "condo_status": condo_status,
        "retail_segment": retail_segment,
        "retail_summary_items": retail_summary_items,
        "retail_wishlist_records": retail_wishlist_records[:4],
        "condo_summary_items": condo_summary_items,
        "condo_recent_incidents": condo_incident_records[:3],
        "condo_recent_communications": condo_communication_records[:3],
        "open_task_cards": [_build_task_card(activity) for activity in open_tasks],
        "task_preset_cards": build_task_preset_cards(
            request.tenant,
            entity_id=entity.pk,
            next_url=reverse("binncrm:entity_detail", kwargs={"pk": entity.pk}),
            limit=4,
        ),
        "broker_document_checklist": (
            _build_broker_document_checklist(entity, all_documents, blueprint_map=blueprint_map)
            if profile == "broker"
            else []
        ),
        "services_handoff": (
            _build_services_handoff(
                entity,
                activities=all_activities,
                documents=all_documents,
                deliverables=deliverable_records,
            )
            if profile == "servicios"
            else {}
        ),
        "services_project_items": services_project_items,
        "services_project_records": project_records[:3],
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
        "can_create_assessment": _can(request, PERMISSION_ENTITIES_EDIT) and request.tenant.has_capability("assessments"),
        "can_complete_tasks": _can(request, PERMISSION_ACTIVITIES_COMPLETE),
        "can_view_objects": _can(request, PERMISSION_OBJECTS_VIEW),
        "can_edit_objects": _can(request, PERMISSION_OBJECTS_EDIT),
        "has_broker_policy_object": broker_policy_schema is not None,
        "has_project_object": project_schema is not None,
        "has_deliverable_object": deliverable_schema is not None,
        "has_condo_unit_object": condo_unit_schema is not None,
        "has_condo_incident_object": condo_incident_schema is not None,
        "has_condo_communication_object": condo_communication_schema is not None,
        "has_retail_wishlist_object": retail_wishlist_schema is not None,
    }
    return render(request, "binncrm/entity_detail.html", context)


@login_required
@tenant_permission_required(PERMISSION_ENTITIES_EDIT, capability="entities")
def entity_edit(request, pk):
    _require_crm_permission(request, PERMISSION_ENTITIES_EDIT, capability="entities")
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
                _audit_crm_action(
                    request,
                    action="updated",
                    object_type="entity",
                    title=f"{request.tenant.get_label('entity_singular', 'Contacto')} actualizado",
                    message=f"Se actualizo '{entity.full_name}'.",
                    metadata={
                        "entity_id": entity.pk,
                        "entity_name": entity.full_name,
                        "changed_fields": changed_fields,
                    },
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
    _require_crm_permission(request, PERMISSION_DEALS_EDIT, capability="deals")
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
            _audit_crm_action(
                request,
                action="created",
                object_type="deal",
                title=f"{request.tenant.get_label('deal_singular', 'Deal')} creado",
                message=f"Se creo '{deal.title}' en {deal.pipeline.name}/{deal.stage}.",
                metadata={
                    "deal_id": deal.pk,
                    "deal_title": deal.title,
                    "entity_id": deal.entity_id,
                    "pipeline_id": deal.pipeline_id,
                    "pipeline_name": deal.pipeline.name,
                    "stage": deal.stage,
                    "status": deal.status,
                    "amount": deal.amount,
                    "currency": deal.currency,
                },
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
    _require_crm_permission(request, PERMISSION_DEALS_EDIT, capability="deals")
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
                _audit_crm_action(
                    request,
                    action="moved",
                    object_type="deal",
                    title=f"{request.tenant.get_label('deal_singular', 'Deal')} movido",
                    message=(
                        f"Se movio '{deal.title}' de {original_pipeline_name or deal.pipeline.name}/{original_stage or '-'} "
                        f"a {deal.pipeline.name}/{deal.stage}."
                    ),
                    metadata={
                        "deal_id": deal.pk,
                        "deal_title": deal.title,
                        "entity_id": deal.entity_id,
                        "pipeline_id": deal.pipeline_id,
                        "pipeline_name": deal.pipeline.name,
                        "previous_pipeline_name": original_pipeline_name,
                        "previous_stage": original_stage,
                        "current_stage": deal.stage,
                        "status": deal.status,
                        "changed_fields": changed_fields,
                    },
                )
            elif changed_fields:
                log_deal_updated(
                    deal=deal,
                    actor=request.user,
                    kind_label=request.tenant.get_label("deal_singular", "Deal"),
                    changed_fields=changed_fields,
                )
                _audit_crm_action(
                    request,
                    action="updated",
                    object_type="deal",
                    title=f"{request.tenant.get_label('deal_singular', 'Deal')} actualizado",
                    message=f"Se actualizo '{deal.title}'.",
                    metadata={
                        "deal_id": deal.pk,
                        "deal_title": deal.title,
                        "entity_id": deal.entity_id,
                        "pipeline_id": deal.pipeline_id,
                        "pipeline_name": deal.pipeline.name,
                        "stage": deal.stage,
                        "status": deal.status,
                        "changed_fields": changed_fields,
                    },
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
    proposal_ops = build_proposal_operational_context(request.tenant)
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
            "proposal_ops": proposal_ops,
            "can_create_proposal": _can(request, PERMISSION_PROPOSALS_EDIT),
            "can_edit_proposal": _can(request, PERMISSION_PROPOSALS_EDIT),
        },
    )


@login_required
@tenant_permission_required(PERMISSION_PROPOSALS_EDIT, capability="proposals")
def proposal_create(request):
    _require_crm_permission(request, PERMISSION_PROPOSALS_EDIT, capability="proposals")
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
            _audit_crm_action(
                request,
                action="created",
                object_type="proposal",
                title=f"{request.tenant.get_label('proposal_singular', 'Propuesta')} creada",
                message=f"Se creo '{proposal.title}'.",
                metadata={
                    "proposal_id": proposal.pk,
                    "proposal_title": proposal.title,
                    "entity_id": proposal.entity_id,
                    "deal_id": proposal.deal_id,
                    "status": proposal.status,
                    "amount": proposal.amount,
                    "currency": proposal.currency,
                },
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
    _require_crm_permission(request, PERMISSION_PROPOSALS_EDIT, capability="proposals")
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
                _audit_crm_action(
                    request,
                    action="moved" if original_status and original_status != proposal.status else "updated",
                    object_type="proposal",
                    title=(
                        f"{request.tenant.get_label('proposal_singular', 'Propuesta')} movida"
                        if original_status and original_status != proposal.status
                        else f"{request.tenant.get_label('proposal_singular', 'Propuesta')} actualizada"
                    ),
                    message=(
                        f"Se movio '{proposal.title}' de {original_status} a {proposal.status}."
                        if original_status and original_status != proposal.status
                        else f"Se actualizo '{proposal.title}'."
                    ),
                    metadata={
                        "proposal_id": proposal.pk,
                        "proposal_title": proposal.title,
                        "entity_id": proposal.entity_id,
                        "deal_id": proposal.deal_id,
                        "status": proposal.status,
                        "previous_status": original_status,
                        "changed_fields": changed_fields,
                    },
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
    collection_ops = build_collection_operational_context(request.tenant)
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
    collection_statuses = [
        (status, dict(CollectionRecord.STATUS_CHOICES).get(status, status.title()))
        for status in collection_ops["states"]
    ]
    collection_statuses.extend(
        [
            (status, label)
            for status, label in CollectionRecord.STATUS_CHOICES
            if status not in collection_ops["states"]
        ]
    )
    grouped_collections = []
    visible_statuses = [selected_status] if selected_status in status_tones else [status for status, _ in collection_statuses]
    raw_collections = list(collections_qs.order_by("sort_order", "due_on", "-updated_at", "id"))
    collections_by_status = {status_key: [] for status_key in visible_statuses}
    for record in raw_collections:
        if record.status in collections_by_status:
            collections_by_status[record.status].append(record)
    for status_key in visible_statuses:
        raw_status_records = collections_by_status.get(status_key, [])
        status_currency = raw_status_records[0].currency if raw_status_records else collection_ops["default_currency"]
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
            "collection_statuses": collection_statuses,
            "collection_ops": collection_ops,
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
    _require_crm_permission(request, PERMISSION_COLLECTIONS_EDIT, capability="collections")
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
            _audit_crm_action(
                request,
                action="created",
                object_type="collection",
                title=f"{request.tenant.get_label('collection_singular', 'Cobranza')} creada",
                message=f"Se registro '{collection.title}' con estado {collection.status}.",
                metadata={
                    "collection_id": collection.pk,
                    "collection_title": collection.title,
                    "entity_id": collection.entity_id,
                    "deal_id": collection.deal_id,
                    "status": collection.status,
                    "balance": collection.balance,
                    "currency": collection.currency,
                    "due_on": collection.due_on,
                },
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
    _require_crm_permission(request, PERMISSION_COLLECTIONS_EDIT, capability="collections")
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
                _audit_crm_action(
                    request,
                    action="moved" if status_changed else "updated",
                    object_type="collection",
                    title=(
                        f"{request.tenant.get_label('collection_singular', 'Cobranza')} movida"
                        if status_changed
                        else f"{request.tenant.get_label('collection_singular', 'Cobranza')} actualizada"
                    ),
                    message=(
                        f"Se movio '{collection.title}' de {original_status} a {collection.status}."
                        if status_changed
                        else f"Se actualizo '{collection.title}'."
                    ),
                    metadata={
                        "collection_id": collection.pk,
                        "collection_title": collection.title,
                        "entity_id": collection.entity_id,
                        "deal_id": collection.deal_id,
                        "status": collection.status,
                        "previous_status": original_status,
                        "balance": collection.balance,
                        "currency": collection.currency,
                        "changed_fields": changed_fields,
                    },
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
    _require_crm_permission(request, PERMISSION_COLLECTIONS_EDIT, capability="collections")
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

    _audit_crm_action(
        request,
        action="moved" if previous_status != status else "reordered",
        object_type="collection",
        title=(
            f"{request.tenant.get_label('collection_singular', 'Cobranza')} movida"
            if previous_status != status
            else f"{request.tenant.get_label('collection_singular', 'Cobranza')} reordenada"
        ),
        message=(
            f"Se movio '{collection.title}' de {previous_status} a {status}."
            if previous_status != status
            else f"Se reordeno '{collection.title}' dentro de {status}."
        ),
        metadata={
            "collection_id": collection.pk,
            "collection_title": collection.title,
            "entity_id": collection.entity_id,
            "deal_id": collection.deal_id,
            "previous_status": previous_status,
            "current_status": status,
            "position": inserted_index if inserted_index is not None else position,
        },
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
def condominio_hub(request):
    tenant = request.tenant
    if _tenant_profile(tenant) != "condominio":
        return redirect("binncrm:reports")

    labels = tenant.tenant_config.labels
    feature_flags = tenant.tenant_config.feature_flags or {}
    workspace_pack = build_workspace_pack(
        profile=_tenant_profile(tenant),
        labels=labels,
        feature_flags=feature_flags,
    )
    now = timezone.now()
    today = timezone.localdate()
    entity_field_definitions = get_entity_field_definitions(tenant=tenant)
    custom_blueprints = tenant.document_blueprints
    blueprint_map = get_document_blueprint_map("condominio", custom_blueprints=custom_blueprints)

    can_view_entities = feature_flags.get("entities") and _can(request, PERMISSION_ENTITIES_VIEW)
    can_view_deals = feature_flags.get("deals") and _can(request, PERMISSION_DEALS_VIEW)
    can_view_activities = feature_flags.get("activities") and _can(request, PERMISSION_ACTIVITIES_VIEW)
    can_view_documents = feature_flags.get("documents") and _can(request, PERMISSION_DOCUMENTS_VIEW)
    can_view_collections = feature_flags.get("collections") and _can(request, PERMISSION_COLLECTIONS_VIEW)
    can_view_objects = _can(request, PERMISSION_OBJECTS_VIEW)
    can_edit_objects = _can(request, PERMISSION_OBJECTS_EDIT)

    entity_qs = Entity.objects.none()
    if can_view_entities:
        entity_qs = Entity.objects.filter(is_active=True).annotate(
            open_collection_count=Count(
                "collections",
                filter=Q(collections__is_active=True) & ~Q(collections__status=CollectionRecord.STATUS_PAID),
                distinct=True,
            ),
            promised_collection_count=Count(
                "collections",
                filter=Q(collections__is_active=True, collections__status=CollectionRecord.STATUS_PROMISED),
                distinct=True,
            ),
            overdue_collection_count=Count(
                "collections",
                filter=Q(collections__is_active=True)
                & ~Q(collections__status=CollectionRecord.STATUS_PAID)
                & Q(collections__due_on__lt=today),
                distinct=True,
            ),
        )
    collection_qs = (
        CollectionRecord.objects.select_related("entity", "deal").filter(is_active=True)
        if can_view_collections
        else CollectionRecord.objects.none()
    )
    activity_qs = (
        Activity.objects.select_related("entity", "deal", "assigned_to").all()
        if can_view_activities
        else Activity.objects.none()
    )
    document_qs = (
        Document.objects.select_related("entity", "deal").filter(is_active=True)
        if can_view_documents
        else Document.objects.none()
    )

    entities = list(entity_qs.order_by("full_name")) if can_view_entities else []
    resident_states = [_condo_resident_status(entity, field_definitions=entity_field_definitions) for entity in entities]
    overdue_collections_qs = collection_qs.exclude(status=CollectionRecord.STATUS_PAID).filter(due_on__lt=today)
    promised_collections_qs = collection_qs.filter(status=CollectionRecord.STATUS_PROMISED)
    pending_tasks_qs = activity_qs.filter(activity_type=Activity.TYPE_TASK, completed_at__isnull=True)
    recent_documents = list(document_qs.order_by("-created_at")[:6]) if can_view_documents else []
    document_cards = [
        _build_document_card(
            document,
            profile="condominio",
            blueprint_map=blueprint_map,
            custom_blueprints=custom_blueprints,
        )
        for document in recent_documents
    ]

    unit_schema = None
    incident_schema = None
    communication_schema = None
    unit_records = []
    incident_records = []
    communication_records = []
    if can_view_objects:
        unit_schema = get_object_schema_definition(object_key="unidad")
        if unit_schema is not None and unit_schema.source == ObjectSchema.SOURCE_CUSTOM:
            unit_records = list(ObjectRecord.objects.filter(object_schema=unit_schema, is_active=True).order_by("-updated_at", "-id"))
        incident_schema = get_object_schema_definition(object_key="incidencia")
        if incident_schema is not None and incident_schema.source == ObjectSchema.SOURCE_CUSTOM:
            incident_records = list(ObjectRecord.objects.filter(object_schema=incident_schema, is_active=True).order_by("-updated_at", "-id"))
        communication_schema = get_object_schema_definition(object_key="comunicado")
        if communication_schema is not None and communication_schema.source == ObjectSchema.SOURCE_CUSTOM:
            communication_records = list(
                ObjectRecord.objects.filter(object_schema=communication_schema, is_active=True).order_by("-updated_at", "-id")
            )

    open_incidents = [
        record for record in incident_records
        if not _is_condo_incident_closed((record.data or {}).get("estado"))
    ]
    residents_overdue_count = sum(1 for state in resident_states if state["key"] == "cartera_vencida")
    residents_followup_count = sum(1 for state in resident_states if state["key"] in {"promesa_pago", "seguimiento"})

    summary_cards = [
        {
            "label": "Residentes con mora",
            "value": residents_overdue_count,
            "caption": "Fichas con cartera vencida o gestion atrasada.",
            "tone": "bg-red-50 text-red-700" if residents_overdue_count else "bg-green-50 text-green-700",
            "href": reverse("binncrm:entities") if can_view_entities else "",
        },
        {
            "label": "Seguimientos de cobro",
            "value": residents_followup_count,
            "caption": "Residentes con promesa de pago o seguimiento abierto.",
            "tone": "bg-amber-50 text-amber-700" if residents_followup_count else "bg-green-50 text-green-700",
            "href": reverse("binncrm:collections") if can_view_collections else reverse("binncrm:entities") if can_view_entities else "",
        },
        {
            "label": "Unidades visibles",
            "value": len(unit_records),
            "caption": "Padron operativo de unidades sin salir del CRM.",
            "tone": "bg-blue-50 text-blue-700" if unit_records else "bg-slate-100 text-slate-700",
            "href": reverse("binncrm:custom_object_records", kwargs={"object_key": unit_schema.key}) if unit_schema is not None and can_view_objects else "",
        },
        {
            "label": "Incidencias abiertas",
            "value": len(open_incidents),
            "caption": "Casos operativos que siguen en gestion o sin resolver.",
            "tone": "bg-red-50 text-red-700" if open_incidents else "bg-green-50 text-green-700",
            "href": reverse("binncrm:custom_object_records", kwargs={"object_key": incident_schema.key}) if incident_schema is not None and can_view_objects else "",
        },
    ]

    quick_actions = []
    if _can(request, PERMISSION_ENTITIES_EDIT):
        quick_actions.append({"label": "Nuevo residente", "href": reverse("binncrm:entity_create")})
    if _can(request, PERMISSION_COLLECTIONS_EDIT):
        quick_actions.append({"label": "Nueva cobranza", "href": reverse("binncrm:collection_create")})
    if _can(request, PERMISSION_ACTIVITIES_EDIT):
        quick_actions.append(
            {
                "label": "Nueva tarea",
                "href": f"{reverse('binncrm:activity_create')}?{urlencode({'activity_type': Activity.TYPE_TASK})}",
            }
        )
    if can_edit_objects and communication_schema is not None:
        quick_actions.append(
            {
                "label": "Nuevo comunicado",
                "href": reverse("binncrm:custom_object_record_create", kwargs={"object_key": communication_schema.key}),
            }
        )
    if can_edit_objects and incident_schema is not None:
        quick_actions.append(
            {
                "label": "Nueva incidencia",
                "href": reverse("binncrm:custom_object_record_create", kwargs={"object_key": incident_schema.key}),
            }
        )
    if _can(request, PERMISSION_DOCUMENTS_EDIT):
        quick_actions.append(
            {
                "label": "Subir estado de cuenta",
                "href": f"{reverse('binncrm:document_create')}?{urlencode({'document_type': 'estado_cuenta'})}",
            }
        )

    condo_sections = [
        {
            "title": "Cartera vencida",
            "subtitle": "Lo que ya vencio y merece llamada, acuerdo o escalamiento hoy.",
            "href": reverse("binncrm:collections") if can_view_collections else "",
            "cta": "Cobrar cartera",
            "empty_message": "No hay cartera vencida en este momento.",
            "items": [
                _build_report_item(
                    title=collection.title,
                    meta=" | ".join(
                        part for part in [
                            getattr(collection.entity, "full_name", ""),
                            (getattr(collection.entity, "data_extra", {}) or {}).get("departamento", ""),
                        ] if part
                    ),
                    caption=" | ".join(
                        part for part in [
                            _format_currency_amount(collection.currency, collection.balance),
                            f"Vencio {collection.due_on.strftime('%d/%m/%Y')}" if collection.due_on else "",
                        ] if part
                    ),
                    status=_collection_status(collection, now=today)["label"],
                    tone=_collection_status(collection, now=today)["tone"],
                )
                for collection in overdue_collections_qs.order_by("due_on", "sort_order")[:6]
            ],
        },
        {
            "title": "Promesas y seguimiento de cobro",
            "subtitle": "Compromisos de pago y tareas abiertas para que la cobranza no se enfrie.",
            "href": reverse("binncrm:collections") if can_view_collections else reverse("binncrm:activities") if can_view_activities else "",
            "cta": "Seguir seguimiento",
            "empty_message": "No hay promesas de pago ni tareas operativas pendientes.",
            "items": [
                *[
                    _build_report_item(
                        title=collection.title,
                        meta=getattr(collection.entity, "full_name", ""),
                        caption=" | ".join(
                            part for part in [
                                _format_currency_amount(collection.currency, collection.balance),
                                f"Prometido {collection.promised_for.strftime('%d/%m/%Y')}" if collection.promised_for else "",
                            ] if part
                        ),
                        status=dict(CollectionRecord.STATUS_CHOICES).get(collection.status, collection.status),
                        tone="bg-amber-50 text-amber-700",
                    )
                    for collection in promised_collections_qs.order_by("promised_for", "due_on")[:3]
                ],
                *[
                    _build_report_item(
                        title=activity.title,
                        meta=getattr(activity.entity, "full_name", ""),
                        caption=_task_status(activity, now=now)["label"],
                        status="Tarea",
                        tone=_task_status(activity, now=now)["tone"],
                    )
                    for activity in pending_tasks_qs.order_by("due_at", "-created_at")[:3]
                ],
            ],
        },
        {
            "title": "Incidencias simples",
            "subtitle": "Casos operativos para mantenimiento, convivencia, seguridad o cartera.",
            "href": reverse("binncrm:custom_object_records", kwargs={"object_key": incident_schema.key}) if incident_schema is not None and can_view_objects else "",
            "cta": "Resolver incidencias",
            "empty_message": "No hay incidencias abiertas ahora mismo.",
            "items": [
                _build_report_item(
                    title=record.title,
                    meta=" | ".join(
                        part for part in [
                            (record.data or {}).get("codigo_unidad", ""),
                            (record.data or {}).get("residente", ""),
                        ] if part
                    ),
                    caption=" | ".join(
                        part for part in [
                            _resolve_choice_label((record.data or {}).get("tipo"), [
                                {"value": "mantenimiento", "label": "Mantenimiento"},
                                {"value": "convivencia", "label": "Convivencia"},
                                {"value": "seguridad", "label": "Seguridad"},
                                {"value": "cartera", "label": "Cartera"},
                                {"value": "otro", "label": "Otro"},
                            ]),
                            (record.data or {}).get("comentario", "")[:120],
                        ] if part
                    ),
                    status=_resolve_choice_label((record.data or {}).get("estado"), [
                        {"value": "abierta", "label": "Abierta"},
                        {"value": "en_gestion", "label": "En gestion"},
                        {"value": "resuelta", "label": "Resuelta"},
                    ]) or "Incidencia",
                    tone="bg-red-50 text-red-700" if not _is_condo_incident_closed((record.data or {}).get("estado")) else "bg-green-50 text-green-700",
                )
                for record in open_incidents[:6]
            ],
        },
        {
            "title": "Comunicados",
            "subtitle": "Mensajes ya enviados o listos para residentes, bloques o unidades.",
            "href": reverse("binncrm:custom_object_records", kwargs={"object_key": communication_schema.key}) if communication_schema is not None and can_view_objects else "",
            "cta": "Operar comunicados",
            "empty_message": "Todavia no hay comunicados registrados.",
            "items": [
                _build_report_item(
                    title=record.title,
                    meta=" | ".join(
                        part for part in [
                            (record.data or {}).get("dirigido_a", ""),
                            (record.data or {}).get("codigo_unidad", ""),
                        ] if part
                    ),
                    caption=" | ".join(
                        part for part in [
                            _resolve_choice_label((record.data or {}).get("canal"), [
                                {"value": "whatsapp", "label": "WhatsApp"},
                                {"value": "email", "label": "Email"},
                                {"value": "cartelera", "label": "Cartelera"},
                            ]),
                            _parse_extra_date((record.data or {}).get("fecha_envio")).strftime("%d/%m/%Y") if _parse_extra_date((record.data or {}).get("fecha_envio")) else "",
                        ] if part
                    ),
                    status=_resolve_choice_label((record.data or {}).get("estado"), [
                        {"value": "borrador", "label": "Borrador"},
                        {"value": "enviado", "label": "Enviado"},
                        {"value": "confirmado", "label": "Confirmado"},
                    ]) or "Comunicado",
                    tone="bg-blue-50 text-blue-700",
                )
                for record in communication_records[:6]
            ],
        },
        {
            "title": "Residentes y unidades",
            "subtitle": "Padron operativo para revisar bloque, propietario y ocupacion desde una sola vista.",
            "href": reverse("binncrm:entities") if can_view_entities else reverse("binncrm:custom_object_records", kwargs={"object_key": unit_schema.key}) if unit_schema is not None and can_view_objects else "",
            "cta": "Operar padron",
            "empty_message": "No hay residentes ni unidades cargadas todavia.",
            "items": [
                *[
                    _build_report_item(
                        title=entity.full_name,
                        meta=" | ".join(
                            part for part in [
                                (entity.data_extra or {}).get("departamento", ""),
                                (entity.data_extra or {}).get("torre", ""),
                            ] if part
                        ),
                        caption=_condo_resident_status(entity, field_definitions=entity_field_definitions)["label"],
                        status="Residente",
                        tone=_condo_resident_status(entity, field_definitions=entity_field_definitions)["tone"],
                    )
                    for entity in entities[:3]
                ],
                *[
                    _build_report_item(
                        title=(record.data or {}).get("codigo_unidad", record.title),
                        meta=" | ".join(
                            part for part in [
                                (record.data or {}).get("torre", ""),
                                (record.data or {}).get("propietario", ""),
                            ] if part
                        ),
                        caption=" | ".join(
                            part for part in [
                                (record.data or {}).get("residente_actual", ""),
                                _resolve_choice_label((record.data or {}).get("estado_ocupacion"), [
                                    {"value": "ocupada", "label": "Ocupada"},
                                    {"value": "vacia", "label": "Vacia"},
                                    {"value": "arriendo", "label": "Arriendo"},
                                ]),
                            ] if part
                        ),
                        status="Unidad",
                        tone="bg-slate-100 text-slate-700",
                    )
                    for record in unit_records[:3]
                ],
            ],
        },
        {
            "title": "Documentos clave y adjuntos",
            "subtitle": "Contratos, estados de cuenta y comprobantes visibles dentro del tenant.",
            "href": reverse("binncrm:documents") if can_view_documents else "",
            "cta": "Operar documentos",
            "empty_message": "No hay documentos clave cargados todavia.",
            "items": [
                _build_report_item(
                    title=item["document"].title,
                    meta=" | ".join(
                        part for part in [
                            item["type_label"],
                            getattr(item["document"].entity, "full_name", ""),
                        ] if part
                    ),
                    caption=" | ".join(
                        part for part in [
                            item["expiry_status"]["label"],
                            item["metadata_items"][0]["value"] if item["metadata_items"] else "",
                        ] if part
                    ),
                    status=item["verification_label"],
                    tone=item["verification_tone"],
                )
                for item in document_cards
            ],
        },
    ]

    context = {
        "labels": labels,
        "workspace_pack": workspace_pack,
        "summary_cards": summary_cards,
        "condo_sections": condo_sections,
        "quick_actions": quick_actions,
        "generated_at": timezone.localtime(now),
    }
    return render(request, "binncrm/condominio_hub.html", context)


@login_required
@tenant_permission_required(PERMISSION_REPORTS_VIEW, capability="reports")
def broker_hub(request):
    tenant = request.tenant
    if _tenant_profile(tenant) != "broker":
        return redirect("binncrm:reports")

    labels = tenant.tenant_config.labels
    feature_flags = tenant.tenant_config.feature_flags or {}
    workspace_pack = build_workspace_pack(
        profile=_tenant_profile(tenant),
        labels=labels,
        feature_flags=feature_flags,
    )
    now = timezone.now()
    today = timezone.localdate()
    entity_field_definitions = get_entity_field_definitions(tenant=tenant)
    custom_blueprints = tenant.document_blueprints
    blueprint_map = get_document_blueprint_map("broker", custom_blueprints=custom_blueprints)

    can_view_entities = feature_flags.get("entities") and _can(request, PERMISSION_ENTITIES_VIEW)
    can_view_deals = feature_flags.get("deals") and _can(request, PERMISSION_DEALS_VIEW)
    can_view_activities = feature_flags.get("activities") and _can(request, PERMISSION_ACTIVITIES_VIEW)
    can_view_documents = feature_flags.get("documents") and _can(request, PERMISSION_DOCUMENTS_VIEW)
    can_view_proposals = feature_flags.get("proposals") and _can(request, PERMISSION_PROPOSALS_VIEW)
    can_view_collections = feature_flags.get("collections") and _can(request, PERMISSION_COLLECTIONS_VIEW)
    can_view_objects = _can(request, PERMISSION_OBJECTS_VIEW)
    can_edit_objects = _can(request, PERMISSION_OBJECTS_EDIT)

    entity_qs = Entity.objects.none()
    if can_view_entities:
        entity_qs = Entity.objects.filter(is_active=True).annotate(
            deal_count=Count("deals", filter=Q(deals__is_active=True), distinct=True),
            open_deal_count=Count(
                "deals",
                filter=Q(deals__is_active=True, deals__status=Deal.STATUS_OPEN),
                distinct=True,
            ),
        )
    deal_qs = (
        Deal.objects.select_related("entity", "pipeline").filter(is_active=True, status=Deal.STATUS_OPEN)
        if can_view_deals
        else Deal.objects.none()
    )
    activity_qs = (
        Activity.objects.select_related("entity", "deal", "assigned_to").all()
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

    entities = list(entity_qs.order_by("full_name")) if can_view_entities else []
    all_documents = list(document_qs.order_by("expires_on", "title")) if can_view_documents else []
    documents_by_entity: dict[int, list[Document]] = {}
    for document in all_documents:
        if document.entity_id:
            documents_by_entity.setdefault(document.entity_id, []).append(document)

    broker_policy_schema = None
    policy_records = []
    if can_view_objects:
        broker_policy_schema = get_object_schema_definition(object_key="poliza_detalle")
        if broker_policy_schema is not None and broker_policy_schema.source == ObjectSchema.SOURCE_CUSTOM:
            policy_records = list(ObjectRecord.objects.filter(object_schema=broker_policy_schema, is_active=True).order_by("-updated_at", "-id"))
    expiring_policy_records = _collect_broker_due_policy_records(policy_records, today=today, window_days=45)

    renewals_due_qs = deal_qs.filter(expected_close_on__isnull=False, expected_close_on__lte=today + timedelta(days=30))
    open_claims_qs = activity_qs.filter(activity_type=Activity.TYPE_CLAIM, completed_at__isnull=True)
    overdue_collections_qs = collection_qs.exclude(status=CollectionRecord.STATUS_PAID).filter(due_on__lt=today)
    expiring_documents_qs = document_qs.filter(expires_on__isnull=False, expires_on__lte=today + timedelta(days=30))
    proposals_due_qs = proposal_qs.filter(
        status__in=[Proposal.STATUS_DRAFT, Proposal.STATUS_SENT],
        valid_until__isnull=False,
        valid_until__lte=today + timedelta(days=7),
    )

    renewals_due_count = renewals_due_qs.count() if can_view_deals else 0
    expiring_policy_count = len(expiring_policy_records)
    open_claims_count = open_claims_qs.count() if can_view_activities else 0
    overdue_collections_count = overdue_collections_qs.count() if can_view_collections else 0
    expiring_documents_count = expiring_documents_qs.count() if can_view_documents else 0

    renewals_due = list(renewals_due_qs.order_by("expected_close_on", "sort_order", "-updated_at")[:6])
    open_claims = list(open_claims_qs.order_by("due_at", "-created_at")[:6])
    overdue_collections = list(overdue_collections_qs.order_by("due_on", "sort_order", "-updated_at")[:6])
    expiring_documents = list(expiring_documents_qs.order_by("expires_on", "title")[:6])
    proposals_due = list(proposals_due_qs.order_by("valid_until", "-updated_at")[:6])

    checklist_gaps = []
    for entity in entities:
        checklist = _build_broker_document_checklist(
            entity,
            documents_by_entity.get(entity.id, []),
            blueprint_map=blueprint_map,
        )
        missing_labels = [item["label"] for item in checklist if not item["is_present"]]
        if not missing_labels:
            continue
        checklist_gaps.append(
            _build_report_item(
                title=entity.full_name,
                meta=entity.phone or entity.legal_id or "Sin contacto directo",
                caption=", ".join(missing_labels[:3]),
                status="Checklist incompleto",
                tone="bg-red-50 text-red-700",
            )
        )

    summary_cards = []
    if can_view_entities:
        summary_cards.extend(
            {
                **card,
                "href": reverse("binncrm:entities"),
            }
            for card in _build_broker_lifecycle_summary(
                entities=entities,
                field_definitions=entity_field_definitions,
            )
        )
    summary_cards.extend(
        [
            {
                "label": "Renovaciones proximas",
                "value": renewals_due_count,
                "caption": "Deals abiertos con cierre estimado en los proximos 30 dias.",
                "tone": "bg-amber-50 text-amber-700" if renewals_due_count else "bg-green-50 text-green-700",
                "href": reverse("binncrm:index") if can_view_deals else "",
            },
            {
                "label": "Polizas por vencer",
                "value": expiring_policy_count,
                "caption": "Registros de poliza con vigencia ya encima.",
                "tone": "bg-amber-50 text-amber-700" if expiring_policy_count else "bg-green-50 text-green-700",
                "href": reverse("binncrm:custom_object_records", kwargs={"object_key": broker_policy_schema.key}) if broker_policy_schema is not None else "",
                "cta": "Ver polizas",
            },
            {
                "label": "Siniestros abiertos",
                "value": open_claims_count,
                "caption": "Casos que siguen sin resolucion ni cierre.",
                "tone": "bg-red-50 text-red-700" if open_claims_count else "bg-green-50 text-green-700",
                "href": f"{reverse('binncrm:activities')}?{urlencode({'kind': Activity.TYPE_CLAIM, 'status': 'open'})}" if can_view_activities else "",
            },
            {
                "label": "Cobranza en riesgo",
                "value": overdue_collections_count,
                "caption": "Cobros vencidos que todavia no estan pagados.",
                "tone": "bg-red-50 text-red-700" if overdue_collections_count else "bg-green-50 text-green-700",
                "href": reverse("binncrm:collections") if can_view_collections else "",
            },
            {
                "label": "Docs por vencer",
                "value": expiring_documents_count,
                "caption": "Documentos que caducan dentro de 30 dias.",
                "tone": "bg-amber-50 text-amber-700" if expiring_documents_count else "bg-green-50 text-green-700",
                "href": reverse("binncrm:documents") if can_view_documents else "",
            },
        ]
    )

    quick_actions = []
    if _can(request, PERMISSION_ENTITIES_EDIT):
        quick_actions.append(
            {"label": f"Nuevo {tenant.get_label('entity_singular', 'Asegurado')}", "href": reverse("binncrm:entity_create")}
        )
    if _can(request, PERMISSION_DEALS_EDIT):
        quick_actions.append(
            {"label": f"Nueva {tenant.get_label('deal_singular', 'Renovacion')}", "href": reverse("binncrm:deal_create")}
        )
    if can_edit_objects and broker_policy_schema is not None:
        quick_actions.append(
            {"label": "Nueva poliza", "href": reverse("binncrm:custom_object_record_create", kwargs={"object_key": broker_policy_schema.key})}
        )
    if _can(request, PERMISSION_ACTIVITIES_EDIT):
        quick_actions.extend(
            [
                {
                    "label": "Nuevo siniestro",
                    "href": f"{reverse('binncrm:activity_create')}?{urlencode({'activity_type': Activity.TYPE_CLAIM})}",
                },
                {
                    "label": "Nueva tarea",
                    "href": f"{reverse('binncrm:activity_create')}?{urlencode({'activity_type': Activity.TYPE_TASK})}",
                },
            ]
        )
    if _can(request, PERMISSION_DOCUMENTS_EDIT):
        quick_actions.append({"label": "Adjuntar documento", "href": reverse("binncrm:document_create")})
    if _can(request, PERMISSION_COLLECTIONS_EDIT):
        quick_actions.append({"label": "Cargar cobranza", "href": reverse("binncrm:collection_create")})

    broker_sections = [
        {
            "title": "Renovaciones por vencer",
            "subtitle": "Prioriza negocios que ya piden contacto o cierre.",
            "href": reverse("binncrm:index") if can_view_deals else "",
            "cta": "Mover pipeline",
            "empty_message": "No hay renovaciones abiertas por vencer en los proximos 30 dias.",
            "items": [
                _build_report_item(
                    title=deal.title,
                    meta=" | ".join(
                        part
                        for part in [
                            getattr(deal.entity, "full_name", ""),
                            getattr(deal.pipeline, "name", ""),
                            deal.stage,
                        ]
                        if part
                    ),
                    caption=" | ".join(
                        part
                        for part in [
                            f"Cierra {deal.expected_close_on.strftime('%d/%m/%Y')}" if deal.expected_close_on else "",
                            _format_currency_amount(deal.currency, deal.amount),
                        ]
                        if part
                    ),
                    status="Renovacion",
                    tone="bg-amber-50 text-amber-700",
                )
                for deal in renewals_due
            ],
        },
        {
            "title": "Polizas por vencer",
            "subtitle": "Vigencias ya encima para anticipar renovacion, cobro o ajuste.",
            "href": reverse("binncrm:custom_object_records", kwargs={"object_key": broker_policy_schema.key}) if broker_policy_schema is not None else "",
            "cta": "Operar polizas",
            "empty_message": "No hay polizas con vigencia cercana en los proximos 45 dias.",
            "items": [
                _build_broker_policy_report_item(record, today=today)
                for record in expiring_policy_records[:6]
            ],
        },
        {
            "title": "Siniestros abiertos",
            "subtitle": "Casos que requieren seguimiento operativo o respuesta al cliente.",
            "href": f"{reverse('binncrm:activities')}?{urlencode({'kind': Activity.TYPE_CLAIM, 'status': 'open'})}" if can_view_activities else "",
            "cta": "Resolver siniestros",
            "empty_message": "No hay siniestros abiertos ahora mismo.",
            "items": [
                _build_report_item(
                    title=activity.title,
                    meta=" | ".join(
                        part
                        for part in [
                            getattr(activity.entity, "full_name", ""),
                            getattr(activity.assigned_to, "username", "") or "Sin responsable",
                        ]
                        if part
                    ),
                    caption=activity.description[:140] or _task_status(activity, now=now)["label"],
                    status="Siniestro",
                    tone="bg-red-50 text-red-700",
                )
                for activity in open_claims
            ],
        },
        {
            "title": "Checklist documental",
            "subtitle": "Asegurados con huecos antes de emitir, renovar o cobrar.",
            "href": reverse("binncrm:documents") if can_view_documents else "",
            "cta": "Operar documentos",
            "empty_message": "No hay fichas con checklist broker incompleto.",
            "items": checklist_gaps[:6],
        },
        {
            "title": "Cobranza ligera",
            "subtitle": "Prima o saldo que ya vencio y merece insistencia.",
            "href": reverse("binncrm:collections") if can_view_collections else "",
            "cta": "Cobrar cartera",
            "empty_message": "No hay cobranzas vencidas en este momento.",
            "items": [
                _build_report_item(
                    title=record.title,
                    meta=getattr(record.entity, "full_name", ""),
                    caption=" | ".join(
                        part
                        for part in [
                            _format_currency_amount(record.currency, record.balance),
                            f"Vencio {record.due_on.strftime('%d/%m/%Y')}" if record.due_on else "",
                        ]
                        if part
                    ),
                    status=dict(CollectionRecord.STATUS_CHOICES).get(record.status, record.status),
                    tone=_collection_status(record, now=today)["tone"],
                )
                for record in overdue_collections
            ],
        },
        {
            "title": "Documentos por vencer",
            "subtitle": "Soportes que pronto dejan de estar vigentes.",
            "href": reverse("binncrm:documents") if can_view_documents else "",
            "cta": "Operar documentos",
            "empty_message": "No hay documentos por vencer en los proximos 30 dias.",
            "items": [
                _build_report_item(
                    title=document.title,
                    meta=" | ".join(
                        part
                        for part in [
                            get_document_type_label("broker", document.document_type, custom_blueprints=custom_blueprints),
                            getattr(document.entity, "full_name", ""),
                        ]
                        if part
                    ),
                    caption=_document_expiry_status(document, today=today)["label"],
                    status="Documento",
                    tone=_document_expiry_status(document, today=today)["tone"],
                )
                for document in expiring_documents
            ],
        },
        {
            "title": "Cotizaciones por empujar",
            "subtitle": "Propuestas que caducan pronto y conviene mover hoy.",
            "href": reverse("binncrm:proposals") if can_view_proposals else "",
            "cta": "Seguir propuestas",
            "empty_message": "No hay cotizaciones por vencer esta semana.",
            "items": [
                _build_report_item(
                    title=proposal.title,
                    meta=getattr(proposal.entity, "full_name", ""),
                    caption=" | ".join(
                        part
                        for part in [
                            _format_currency_amount(proposal.currency, proposal.amount),
                            f"Vigencia {proposal.valid_until.strftime('%d/%m/%Y')}" if proposal.valid_until else "",
                        ]
                        if part
                    ),
                    status=_proposal_status(proposal, now=today)["label"],
                    tone=_proposal_status(proposal, now=today)["tone"],
                )
                for proposal in proposals_due
            ],
        },
    ]

    context = {
        "labels": labels,
        "workspace_pack": workspace_pack,
        "summary_cards": summary_cards,
        "broker_sections": broker_sections,
        "quick_actions": quick_actions,
        "generated_at": timezone.localtime(now),
    }
    return render(request, "binncrm/broker_hub.html", context)
@login_required
@tenant_permission_required(PERMISSION_REPORTS_VIEW, capability="reports")
def services_hub(request):
    tenant = request.tenant
    if _tenant_profile(tenant) != "servicios":
        return redirect("binncrm:reports")

    labels = tenant.tenant_config.labels
    feature_flags = tenant.tenant_config.feature_flags or {}
    workspace_pack = build_workspace_pack(
        profile=_tenant_profile(tenant),
        labels=labels,
        feature_flags=feature_flags,
    )
    now = timezone.now()
    today = timezone.localdate()
    entity_field_definitions = get_entity_field_definitions(tenant=tenant)

    can_view_entities = feature_flags.get("entities") and _can(request, PERMISSION_ENTITIES_VIEW)
    can_view_deals = feature_flags.get("deals") and _can(request, PERMISSION_DEALS_VIEW)
    can_view_activities = feature_flags.get("activities") and _can(request, PERMISSION_ACTIVITIES_VIEW)
    can_view_documents = feature_flags.get("documents") and _can(request, PERMISSION_DOCUMENTS_VIEW)
    can_view_proposals = feature_flags.get("proposals") and _can(request, PERMISSION_PROPOSALS_VIEW)
    can_view_collections = feature_flags.get("collections") and _can(request, PERMISSION_COLLECTIONS_VIEW)
    can_view_objects = _can(request, PERMISSION_OBJECTS_VIEW)
    can_edit_objects = _can(request, PERMISSION_OBJECTS_EDIT)

    entity_qs = Entity.objects.none()
    if can_view_entities:
        entity_qs = Entity.objects.filter(is_active=True).annotate(
            deal_count=Count("deals", filter=Q(deals__is_active=True), distinct=True),
            open_deal_count=Count(
                "deals",
                filter=Q(deals__is_active=True, deals__status=Deal.STATUS_OPEN),
                distinct=True,
            ),
            won_deal_count=Count(
                "deals",
                filter=Q(deals__is_active=True, deals__status=Deal.STATUS_WON),
                distinct=True,
            ),
        )
    deal_qs = (
        Deal.objects.select_related("entity", "pipeline").filter(is_active=True)
        if can_view_deals
        else Deal.objects.none()
    )
    activity_qs = (
        Activity.objects.select_related("entity", "deal", "assigned_to").all()
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

    entities = list(entity_qs.order_by("full_name")) if can_view_entities else []
    meetings_qs = activity_qs.filter(activity_type=Activity.TYPE_MEETING, completed_at__isnull=True)
    renewals_due_entities = []
    for entity in entities:
        renewal_on = _parse_extra_date((entity.data_extra or {}).get("renewal_on"))
        state = _services_lifecycle_state(entity, field_definitions=entity_field_definitions, today=today)
        if renewal_on and renewal_on <= today + timedelta(days=60):
            renewals_due_entities.append((entity, renewal_on, state))
        elif state["key"] == "renovacion_upsell":
            renewals_due_entities.append((entity, renewal_on, state))
    renewals_due_entities = sorted(
        renewals_due_entities,
        key=lambda item: item[1] or (today + timedelta(days=365)),
    )

    proposals_due_qs = proposal_qs.filter(
        status__in=[Proposal.STATUS_DRAFT, Proposal.STATUS_SENT],
        valid_until__isnull=False,
        valid_until__lte=today + timedelta(days=10),
    )
    overdue_meetings_qs = meetings_qs.filter(due_at__lt=now)
    upcoming_meetings_qs = meetings_qs.filter(due_at__gte=now)
    stale_deals_qs = deal_qs.filter(status=Deal.STATUS_OPEN, updated_at__lt=now - timedelta(days=14))
    overdue_collections_qs = collection_qs.exclude(status=CollectionRecord.STATUS_PAID).filter(due_on__lt=today)
    won_deals_qs = deal_qs.filter(status=Deal.STATUS_WON)

    all_documents = list(document_qs.order_by("-created_at")) if can_view_documents else []
    documents_by_entity: dict[int, list[Document]] = {}
    for document in all_documents:
        if document.entity_id:
            documents_by_entity.setdefault(document.entity_id, []).append(document)
    all_activities = list(activity_qs.order_by("-created_at")) if can_view_activities else []
    activities_by_entity: dict[int, list[Activity]] = {}
    for activity in all_activities:
        if activity.entity_id:
            activities_by_entity.setdefault(activity.entity_id, []).append(activity)
    won_deals = list(won_deals_qs.order_by("updated_at")) if can_view_deals else []
    won_deals_by_entity: dict[int, list[Deal]] = {}
    for deal in won_deals:
        if deal.entity_id:
            won_deals_by_entity.setdefault(deal.entity_id, []).append(deal)

    project_schema = None
    project_records = []
    deliverable_schema = None
    deliverable_records = []
    if can_view_objects:
        project_schema = get_object_schema_definition(object_key="proyecto")
        if project_schema is not None and project_schema.source == ObjectSchema.SOURCE_CUSTOM:
            project_records = list(
                ObjectRecord.objects.filter(object_schema=project_schema, is_active=True).order_by("-updated_at", "-id")
            )
        deliverable_schema = get_object_schema_definition(object_key="entregable")
        if deliverable_schema is not None and deliverable_schema.source == ObjectSchema.SOURCE_CUSTOM:
            deliverable_records = list(
                ObjectRecord.objects.filter(object_schema=deliverable_schema, is_active=True).order_by("-updated_at", "-id")
            )
    active_project_records = [
        record for record in project_records
        if _normalize_reference_token((record.data or {}).get("estado")) != "cerrado"
    ]
    project_workload_items = [
        _build_service_project_report_item(record, deliverable_records, today=today)
        for record in active_project_records
    ]
    project_workload_items = sorted(
        project_workload_items,
        key=lambda item: (item.get("attention_rank", 99), item.get("sort_on") or date.max, item.get("title", "")),
    )
    deliverable_attention_items = [
        _build_service_deliverable_report_item(record, today=today)
        for record in deliverable_records
        if _deliverable_needs_attention(record, today=today)
    ]
    deliverable_attention_items = sorted(
        deliverable_attention_items,
        key=lambda item: (item.get("attention_rank", 99), item.get("sort_on") or date.max, item.get("title", "")),
    )
    analytics_bundle = _build_services_analytics_bundle(
        entities=entities,
        field_definitions=entity_field_definitions,
        project_records=project_records,
        deliverable_records=deliverable_records,
        won_deals_by_entity=won_deals_by_entity,
        activities_by_entity=activities_by_entity,
        documents_by_entity=documents_by_entity,
        today=today,
    )

    handoff_pending = []
    for entity in entities:
        if getattr(entity, "won_deal_count", 0) <= 0:
            continue
        matched_deliverables = _matching_service_deliverables(entity, deliverable_records)
        handoff = _build_services_handoff(
            entity,
            activities=list(entity.activities.all()) if can_view_activities else [],
            documents=documents_by_entity.get(entity.id, []),
            deliverables=matched_deliverables,
            today=today,
        )
        if handoff["missing_count"] > 0:
            handoff_pending.append((entity, handoff))

    summary_cards = []
    if can_view_entities:
        summary_cards.extend(
            {
                **card,
                "href": reverse("binncrm:entities"),
            }
            for card in _build_services_lifecycle_summary(
                entities=entities,
                field_definitions=entity_field_definitions,
                today=today,
            )
        )
    summary_cards.extend(
        [
            {
                "label": "Propuestas por cerrar",
                "value": proposals_due_qs.count() if can_view_proposals else 0,
                "caption": "Cotizaciones que caducan pronto o ya piden respuesta.",
                "tone": "bg-red-50 text-red-700" if can_view_proposals and proposals_due_qs.exists() else "bg-green-50 text-green-700",
                "href": reverse("binncrm:proposals") if can_view_proposals else "",
            },
            {
                "label": "Meetings pendientes",
                "value": meetings_qs.count() if can_view_activities else 0,
                "caption": "Reuniones de discovery, kickoff o seguimiento aun abiertas.",
                "tone": "bg-amber-50 text-amber-700" if can_view_activities and meetings_qs.exists() else "bg-green-50 text-green-700",
                "href": f"{reverse('binncrm:activities')}?{urlencode({'kind': Activity.TYPE_MEETING, 'status': 'open'})}" if can_view_activities else "",
            },
            {
                "label": "Proyectos activos",
                "value": len(active_project_records),
                "caption": "Cuentas en ejecucion o revision que ya requieren lectura operativa.",
                "tone": "bg-blue-50 text-blue-700" if active_project_records else "bg-slate-100 text-slate-700",
                "href": reverse("binncrm:custom_object_records", kwargs={"object_key": project_schema.key}) if project_schema is not None and can_view_objects else "",
            },
            {
                "label": "Backlog delivery",
                "value": len(deliverable_attention_items),
                "caption": "Entregables bloqueados, por validar o por vencer que ya piden mover equipo.",
                "tone": "bg-amber-50 text-amber-700" if deliverable_attention_items else "bg-green-50 text-green-700",
                "href": reverse("binncrm:custom_object_records", kwargs={"object_key": deliverable_schema.key}) if deliverable_schema is not None and can_view_objects else "",
            },
            {
                "label": "Handoffs pendientes",
                "value": len(handoff_pending),
                "caption": "Cuentas ganadas que aun no cierran bien el traspaso a delivery.",
                "tone": "bg-red-50 text-red-700" if handoff_pending else "bg-green-50 text-green-700",
                "href": reverse("binncrm:entities") if can_view_entities else "",
            },
            {
                "label": "Renovacion / upsell",
                "value": len(renewals_due_entities),
                "caption": "Cuentas activas que ya piden expansion o renovacion cercana.",
                "tone": "bg-amber-50 text-amber-700" if renewals_due_entities else "bg-green-50 text-green-700",
                "href": reverse("binncrm:entities") if can_view_entities else "",
            },
        ]
    )

    quick_actions = []
    if _can(request, PERMISSION_ENTITIES_EDIT):
        quick_actions.append({"label": "Nuevo cliente", "href": reverse("binncrm:entity_create")})
    if _can(request, PERMISSION_DEALS_EDIT):
        quick_actions.append({"label": "Nueva oportunidad", "href": reverse("binncrm:deal_create")})
    if _can(request, PERMISSION_PROPOSALS_EDIT):
        quick_actions.append({"label": "Nueva propuesta", "href": reverse("binncrm:proposal_create")})
    if _can(request, PERMISSION_ACTIVITIES_EDIT):
        quick_actions.append(
            {
                "label": "Nueva reunion",
                "href": f"{reverse('binncrm:activity_create')}?{urlencode({'activity_type': Activity.TYPE_MEETING})}",
            }
        )
    if can_edit_objects and project_schema is not None:
        quick_actions.append(
            {
                "label": "Nuevo proyecto",
                "href": reverse("binncrm:custom_object_record_create", kwargs={"object_key": project_schema.key}),
            }
        )
    if can_edit_objects and deliverable_schema is not None:
        quick_actions.append(
            {
                "label": "Nuevo entregable",
                "href": reverse("binncrm:custom_object_record_create", kwargs={"object_key": deliverable_schema.key}),
            }
        )

    services_sections = [
        {
            "title": "Oportunidades B2B en riesgo",
            "subtitle": "Deals abiertos que se estan enfriando o merecen empuje comercial.",
            "href": reverse("binncrm:index") if can_view_deals else "",
            "cta": "Mover pipeline",
            "empty_message": "No hay oportunidades enfriandose en este momento.",
            "items": [
                _build_report_item(
                    title=deal.title,
                    meta=" | ".join(part for part in [getattr(deal.entity, "full_name", ""), getattr(deal.pipeline, "name", ""), deal.stage] if part),
                    caption=f"Sin movimiento desde {timezone.localtime(deal.updated_at).strftime('%d/%m/%Y %H:%M')}",
                    status="Oportunidad",
                    tone="bg-amber-50 text-amber-700",
                )
                for deal in stale_deals_qs.order_by("updated_at")[:6]
            ],
        },
        {
            "title": "Propuestas por mover",
            "subtitle": "Cotizaciones vivas que conviene cerrar, corregir o empujar esta semana.",
            "href": reverse("binncrm:proposals") if can_view_proposals else "",
            "cta": "Seguir propuestas",
            "empty_message": "No hay propuestas con urgencia inmediata.",
            "items": [
                _build_report_item(
                    title=proposal.title,
                    meta=getattr(proposal.entity, "full_name", ""),
                    caption=" | ".join(
                        part for part in [
                            _format_currency_amount(proposal.currency, proposal.amount),
                            f"Vence {proposal.valid_until.strftime('%d/%m/%Y')}" if proposal.valid_until else "",
                        ] if part
                    ),
                    status=_proposal_status(proposal, now=today)["label"],
                    tone=_proposal_status(proposal, now=today)["tone"],
                )
                for proposal in proposals_due_qs.order_by("valid_until", "-updated_at")[:6]
            ],
        },
        {
            "title": "Reuniones de seguimiento",
            "subtitle": "Discovery, kickoff y sesiones pendientes para que el proceso no se enfrie.",
            "href": f"{reverse('binncrm:activities')}?{urlencode({'kind': Activity.TYPE_MEETING, 'status': 'open'})}" if can_view_activities else "",
            "cta": "Seguir reuniones",
            "empty_message": "No hay reuniones abiertas ni pendientes.",
            "items": [
                _build_report_item(
                    title=activity.title,
                    meta=" | ".join(part for part in [getattr(activity.entity, "full_name", ""), getattr(activity.assigned_to, "username", "") or "Sin responsable"] if part),
                    caption=_task_status(activity, now=now)["label"] if activity.due_at else "Reunion sin fecha visible.",
                    status="Reunion",
                    tone="bg-red-50 text-red-700" if activity in list(overdue_meetings_qs[:6]) else "bg-blue-50 text-blue-700",
                )
                for activity in list(overdue_meetings_qs.order_by("due_at")[:3]) + list(upcoming_meetings_qs.order_by("due_at")[:3])
            ],
        },
        {
            "title": "Proyectos en ejecucion",
            "subtitle": "Lectura rapida del backlog real por proyecto: entregables, revision y cierre objetivo.",
            "href": reverse("binncrm:custom_object_records", kwargs={"object_key": project_schema.key}) if project_schema is not None and can_view_objects else "",
            "cta": "Operar proyectos",
            "empty_message": "No hay proyectos activos cargados todavia.",
            "items": project_workload_items[:6],
        },
        {
            "title": "Handoff comercial -> servicio",
            "subtitle": "Cuentas ganadas que todavia no dejan listo contrato, kickoff o backlog.",
            "href": reverse("binncrm:entities") if can_view_entities else "",
            "cta": "Operar clientes",
            "empty_message": "No hay handoffs pendientes; el paso a delivery esta limpio.",
            "items": [
                _build_report_item(
                    title=entity.full_name,
                    meta=(entity.data_extra or {}).get("empresa", "") or entity.phone or entity.email,
                    caption=", ".join(item["label"] for item in handoff["items"] if not item["is_ready"]),
                    status=handoff["status_label"],
                    tone=handoff["status_tone"],
                )
                for entity, handoff in handoff_pending[:6]
            ],
        },
        {
            "title": "Renovaciones y upsell",
            "subtitle": "Cuentas activas con fecha de renovacion encima o senal clara de expansion.",
            "href": reverse("binncrm:entities") if can_view_entities else "",
            "cta": "Operar clientes",
            "empty_message": "No hay cuentas en renovacion o upsell cercano.",
            "items": [
                _build_report_item(
                    title=entity.full_name,
                    meta=(entity.data_extra or {}).get("empresa", "") or (entity.data_extra or {}).get("servicio_principal", ""),
                    caption=f"Renovacion {renewal_on.strftime('%d/%m/%Y')}" if renewal_on else "Cliente activo sin fecha cargada.",
                    status=state["label"],
                    tone=state["tone"],
                )
                for entity, renewal_on, state in renewals_due_entities[:6]
            ],
        },
        {
            "title": "Backlog delivery y cobro",
            "subtitle": "Entregables bloqueados, por validar o por vencer, junto con cartera vencida que puede tensionar la cuenta.",
            "href": reverse("binncrm:custom_object_records", kwargs={"object_key": deliverable_schema.key}) if deliverable_schema is not None and can_view_objects else reverse("binncrm:collections") if can_view_collections else "",
            "cta": "Operar backlog",
            "empty_message": "No hay backlog de delivery ni cobranzas vencidas ahora.",
            "items": [
                *deliverable_attention_items[:4],
                *[
                    _build_report_item(
                        title=collection.title,
                        meta=getattr(collection.entity, "full_name", ""),
                        caption=" | ".join(
                            part for part in [
                                _format_currency_amount(collection.currency, collection.balance),
                                f"Vencio {collection.due_on.strftime('%d/%m/%Y')}" if collection.due_on else "",
                            ] if part
                        ),
                        status=dict(CollectionRecord.STATUS_CHOICES).get(collection.status, collection.status),
                        tone=_collection_status(collection, now=today)["tone"],
                    )
                    for collection in overdue_collections_qs.order_by("due_on", "sort_order")[:3]
                ],
            ],
        },
    ]

    context = {
        "labels": labels,
        "workspace_pack": workspace_pack,
        "summary_cards": summary_cards,
        "analytics_cards": analytics_bundle["cards"],
        "analytics_sections": analytics_bundle["sections"],
        "services_sections": services_sections,
        "quick_actions": quick_actions,
        "generated_at": timezone.localtime(now),
    }
    return render(request, "binncrm/services_hub.html", context)


@login_required
@tenant_permission_required(PERMISSION_REPORTS_VIEW, capability="reports")
def retail_hub(request):
    tenant = request.tenant
    if _tenant_profile(tenant) != "retail_moda":
        return redirect("binncrm:reports")

    labels = tenant.tenant_config.labels
    feature_flags = tenant.tenant_config.feature_flags or {}
    workspace_pack = build_workspace_pack(
        profile=_tenant_profile(tenant),
        labels=labels,
        feature_flags=feature_flags,
    )
    now = timezone.now()
    today = timezone.localdate()
    entity_field_definitions = get_entity_field_definitions(tenant=tenant)

    can_view_entities = feature_flags.get("entities") and _can(request, PERMISSION_ENTITIES_VIEW)
    can_view_deals = feature_flags.get("deals") and _can(request, PERMISSION_DEALS_VIEW)
    can_view_activities = feature_flags.get("activities") and _can(request, PERMISSION_ACTIVITIES_VIEW)
    can_view_objects = _can(request, PERMISSION_OBJECTS_VIEW)
    can_edit_objects = _can(request, PERMISSION_OBJECTS_EDIT)

    entity_qs = Entity.objects.none()
    if can_view_entities:
        entity_qs = Entity.objects.filter(is_active=True).annotate(
            deal_count=Count("deals", filter=Q(deals__is_active=True), distinct=True),
            open_deal_count=Count(
                "deals",
                filter=Q(deals__is_active=True, deals__status=Deal.STATUS_OPEN),
                distinct=True,
            ),
        )
    deal_qs = (
        Deal.objects.select_related("entity", "pipeline").filter(is_active=True)
        if can_view_deals
        else Deal.objects.none()
    )
    activity_qs = (
        Activity.objects.select_related("entity", "deal", "assigned_to").all()
        if can_view_activities
        else Activity.objects.none()
    )

    entities = list(entity_qs.order_by("full_name")) if can_view_entities else []
    entity_states = []
    segment_counts = {"vip": 0, "frecuente": 0, "ocasional": 0, "inactiva": 0}
    for entity in entities:
        state = _retail_clienteling_state(entity, field_definitions=entity_field_definitions, today=today)
        last_purchase = _parse_extra_date((entity.data_extra or {}).get("ultima_compra"))
        entity_states.append((entity, state, last_purchase))
        segment_counts[state["key"]] = segment_counts.get(state["key"], 0) + 1

    vip_and_frequent = [item for item in entity_states if item[1]["key"] in {"vip", "frecuente"}]
    inactive_clients = [item for item in entity_states if item[1]["key"] == "inactiva"]
    open_deals = list(deal_qs.filter(status=Deal.STATUS_OPEN).order_by("expected_close_on", "-updated_at")[:6]) if can_view_deals else []
    whatsapp_followups = list(activity_qs.filter(activity_type=Activity.TYPE_WHATSAPP).order_by("-updated_at")[:4]) if can_view_activities else []
    overdue_tasks = list(
        activity_qs.filter(activity_type=Activity.TYPE_TASK, completed_at__isnull=True, due_at__lt=now).order_by("due_at")[:4]
    ) if can_view_activities else []

    wishlist_schema = None
    wishlist_records = []
    if can_view_objects:
        wishlist_schema = get_object_schema_definition(object_key="wishlist")
        if wishlist_schema is not None and wishlist_schema.source == ObjectSchema.SOURCE_CUSTOM:
            wishlist_records = list(
                ObjectRecord.objects.filter(object_schema=wishlist_schema, is_active=True).order_by("-updated_at", "-id")
            )
    active_wishlists = [record for record in wishlist_records if (record.data or {}).get("vigente")]

    summary_cards = [
        {
            "label": "VIP y frecuentes",
            "value": len(vip_and_frequent),
            "caption": "Clientas con mejor senal de recompra o relacion activa.",
            "tone": "bg-fuchsia-50 text-fuchsia-700" if vip_and_frequent else "bg-slate-100 text-slate-700",
            "href": reverse("binncrm:entities") if can_view_entities else "",
        },
        {
            "label": "Recompra en curso",
            "value": len(open_deals),
            "caption": "Pedidos especiales o apartados que siguen abiertos.",
            "tone": "bg-blue-50 text-blue-700" if open_deals else "bg-slate-100 text-slate-700",
            "href": reverse("binncrm:index") if can_view_deals else "",
        },
        {
            "label": "Wishlists activas",
            "value": len(active_wishlists),
            "caption": "Piezas reservadas o intereses que merecen seguimiento.",
            "tone": "bg-emerald-50 text-emerald-700" if active_wishlists else "bg-slate-100 text-slate-700",
            "href": reverse("binncrm:custom_object_records", kwargs={"object_key": wishlist_schema.key}) if wishlist_schema is not None and can_view_objects else "",
        },
        {
            "label": "Clientas inactivas",
            "value": len(inactive_clients),
            "caption": "Base que ya pide mensaje, drop o accion de reactivacion.",
            "tone": "bg-amber-50 text-amber-700" if inactive_clients else "bg-green-50 text-green-700",
            "href": reverse("binncrm:entities") if can_view_entities else "",
        },
    ]

    quick_actions = []
    if _can(request, PERMISSION_ENTITIES_EDIT):
        quick_actions.append({"label": "Nueva clienta", "href": reverse("binncrm:entity_create")})
    if _can(request, PERMISSION_DEALS_EDIT):
        quick_actions.append({"label": "Nuevo pedido especial", "href": reverse("binncrm:deal_create")})
    if _can(request, PERMISSION_ACTIVITIES_EDIT):
        quick_actions.append(
            {
                "label": "Follow-up WhatsApp",
                "href": f"{reverse('binncrm:activity_create')}?{urlencode({'activity_type': Activity.TYPE_WHATSAPP, 'title': 'Follow-up WhatsApp'})}",
            }
        )
    if can_edit_objects and wishlist_schema is not None:
        quick_actions.append(
            {
                "label": "Nueva wishlist",
                "href": reverse("binncrm:custom_object_record_create", kwargs={"object_key": wishlist_schema.key}),
            }
        )

    retail_sections = [
        {
            "title": "Clientes VIP y frecuentes",
            "subtitle": "Base que ya compra, responde o vale proteger con clienteling fino.",
            "href": reverse("binncrm:entities") if can_view_entities else "",
            "cta": "Operar clientes",
            "empty_message": "No hay clientes VIP o frecuentes detectados ahora.",
            "items": [
                _build_report_item(
                    title=entity.full_name,
                    meta=" | ".join(
                        part for part in [
                            (entity.data_extra or {}).get("talla", ""),
                            (entity.data_extra or {}).get("estilo", ""),
                            (entity.data_extra or {}).get("canal_preferido", ""),
                        ] if part
                    ),
                    caption=" | ".join(
                        part for part in [
                            f"Ultima compra {last_purchase.strftime('%d/%m/%Y')}" if last_purchase else "Sin compra registrada",
                            (entity.data_extra or {}).get("instagram", ""),
                        ] if part
                    ),
                    status=state["label"],
                    tone=state["tone"],
                )
                for entity, state, last_purchase in vip_and_frequent[:6]
            ],
        },
        {
            "title": "Recompra y pedidos especiales",
            "subtitle": "Apartados, pedidos y oportunidades de recompra que siguen abiertas.",
            "href": reverse("binncrm:index") if can_view_deals else "",
            "cta": "Mover pipeline",
            "empty_message": "No hay recompra ni pedidos especiales abiertos.",
            "items": [
                _build_report_item(
                    title=deal.title,
                    meta=" | ".join(part for part in [getattr(deal.entity, "full_name", ""), getattr(deal.pipeline, "name", ""), deal.stage] if part),
                    caption=" | ".join(
                        part for part in [
                            _format_currency_amount(deal.currency, deal.amount),
                            f"Cierre {deal.expected_close_on.strftime('%d/%m/%Y')}" if deal.expected_close_on else "",
                        ] if part
                    ),
                    status="Pedido abierto",
                    tone="bg-blue-50 text-blue-700",
                )
                for deal in open_deals
            ],
        },
        {
            "title": "WhatsApp follow-up",
            "subtitle": "Mensajes ya enviados y tareas vencidas para que el clienteling no se enfrie.",
            "href": f"{reverse('binncrm:activities')}?{urlencode({'kind': Activity.TYPE_WHATSAPP})}" if can_view_activities else "",
            "cta": "Seguir seguimiento",
            "empty_message": "No hay follow-ups por WhatsApp ni tareas vencidas ahora.",
            "items": [
                *[
                    _build_report_item(
                        title=activity.title,
                        meta=" | ".join(part for part in [getattr(activity.entity, "full_name", ""), getattr(activity.assigned_to, "username", "") or "Sin responsable"] if part),
                        caption=activity.description[:120] or "Seguimiento por WhatsApp registrado.",
                        status="WhatsApp",
                        tone="bg-emerald-50 text-emerald-700",
                    )
                    for activity in whatsapp_followups
                ],
                *[
                    _build_report_item(
                        title=activity.title,
                        meta=getattr(activity.entity, "full_name", ""),
                        caption=_task_status(activity, now=now)["label"],
                        status="Tarea vencida",
                        tone=_task_status(activity, now=now)["tone"],
                    )
                    for activity in overdue_tasks
                ],
            ],
        },
        {
            "title": "Listas por segmento",
            "subtitle": "Lectura rapida de VIP, frecuentes, ocasionales e inactivas para planear acciones.",
            "href": reverse("binncrm:entities") if can_view_entities else "",
            "cta": "Operar base",
            "empty_message": "No hay segmentos calculados todavia.",
            "items": [
                _build_report_item(
                    title=label,
                    meta=f"{count} clienta(s)",
                    caption=caption,
                    status="Segmento",
                    tone=tone,
                )
                for label, count, caption, tone in [
                    ("VIP", segment_counts["vip"], "Base premium para drops, preventas y trato prioritario.", "bg-fuchsia-50 text-fuchsia-700"),
                    ("Frecuentes", segment_counts["frecuente"], "Clientas con compra reciente o ritmo sano de contacto.", "bg-emerald-50 text-emerald-700"),
                    ("Ocasionales", segment_counts["ocasional"], "Base tibia que necesita propuestas mas finas.", "bg-blue-50 text-blue-700"),
                    ("Inactivas", segment_counts["inactiva"], "Reactivacion por WhatsApp, nueva coleccion o incentivo.", "bg-amber-50 text-amber-700"),
                ]
            ],
        },
        {
            "title": "Wishlists y apartados",
            "subtitle": "Piezas deseadas, reservas y contexto para vender mejor sin inventario completo.",
            "href": reverse("binncrm:custom_object_records", kwargs={"object_key": wishlist_schema.key}) if wishlist_schema is not None and can_view_objects else "",
            "cta": "Operar wishlists",
            "empty_message": "No hay wishlists activas ni apartados registrados.",
            "items": [
                _build_report_item(
                    title=(record.data or {}).get("pieza", record.title),
                    meta=" | ".join(
                        part for part in [
                            (record.data or {}).get("cliente", ""),
                            (record.data or {}).get("categoria", ""),
                        ] if part
                    ),
                    caption=" | ".join(
                        part for part in [
                            (record.data or {}).get("talla", ""),
                            _resolve_choice_label((record.data or {}).get("prioridad"), [
                                {"value": "alta", "label": "Alta"},
                                {"value": "media", "label": "Media"},
                                {"value": "baja", "label": "Baja"},
                            ]),
                            _parse_extra_date((record.data or {}).get("fecha_followup")).strftime("%d/%m/%Y") if _parse_extra_date((record.data or {}).get("fecha_followup")) else "",
                        ] if part
                    ),
                    status="Wishlist" if (record.data or {}).get("vigente") else "Historico",
                    tone="bg-fuchsia-50 text-fuchsia-700" if (record.data or {}).get("vigente") else "bg-slate-100 text-slate-700",
                )
                for record in (active_wishlists[:4] or wishlist_records[:4])
            ],
        },
        {
            "title": "Clientes por reactivar",
            "subtitle": "Fichas que se enfriaron y merecen drop, mensaje o llamada esta semana.",
            "href": reverse("binncrm:entities") if can_view_entities else "",
            "cta": "Operar base",
            "empty_message": "No hay clientas inactivas para reactivar en este momento.",
            "items": [
                _build_report_item(
                    title=entity.full_name,
                    meta=" | ".join(part for part in [(entity.data_extra or {}).get("instagram", ""), (entity.data_extra or {}).get("estilo", "")] if part),
                    caption=f"Ultima compra {last_purchase.strftime('%d/%m/%Y')}" if last_purchase else "Sin compra registrada",
                    status="Inactiva",
                    tone="bg-amber-50 text-amber-700",
                )
                for entity, state, last_purchase in inactive_clients[:6]
            ],
        },
    ]

    context = {
        "labels": labels,
        "workspace_pack": workspace_pack,
        "summary_cards": summary_cards,
        "retail_sections": retail_sections,
        "quick_actions": quick_actions,
        "generated_at": timezone.localtime(now),
    }
    return render(request, "binncrm/retail_hub.html", context)


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
            "cta": "Operar modulo",
            "empty_message": "No hay seguimiento en riesgo por ahora.",
            "items": at_risk_items,
        },
        {
            "title": "Vencimientos y compromisos",
            "subtitle": "Propuestas, cobranzas y documentos que merecen accion antes de que se escapen.",
            "href": reverse("binncrm:documents") if can_view_documents else reverse("binncrm:collections") if can_view_collections else reverse("binncrm:proposals") if can_view_proposals else "",
            "cta": "Operar modulo",
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
    _require_crm_permission(request, PERMISSION_OBJECTS_EDIT)
    object_schema = get_object_or_404(
        ObjectSchema.objects.prefetch_related("fields", "views"),
        key=object_key,
        source=ObjectSchema.SOURCE_CUSTOM,
        is_active=True,
    )
    field_definitions = get_object_record_field_definitions(object_schema=object_schema)
    initial = {}
    for field_definition in field_definitions:
        raw_value = (request.GET.get(field_definition["key"]) or "").strip()
        if raw_value:
            initial[f"data__{field_definition['key']}"] = raw_value
    if request.method == "POST":
        form = ObjectRecordForm(request.POST, object_schema=object_schema)
        if form.is_valid():
            record = form.save(commit=False)
            record.created_by = request.user
            record.updated_by = request.user
            record.save()
            log_object_record_created(record=record, actor=request.user)
            _audit_crm_action(
                request,
                action="created",
                object_type="object_record",
                title=f"{object_schema.label} creado",
                message=f"Se creo '{record.title or object_schema.label}'.",
                metadata={
                    "record_id": record.pk,
                    "object_key": object_schema.key,
                    "object_label": object_schema.label,
                },
            )
            messages.success(request, "Registro custom creado correctamente.")
            return redirect("binncrm:custom_object_record_detail", object_key=object_schema.key, pk=record.pk)
    else:
        form = ObjectRecordForm(object_schema=object_schema, initial=initial)
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
    _require_crm_permission(request, PERMISSION_OBJECTS_EDIT)
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
                _audit_crm_action(
                    request,
                    action="updated",
                    object_type="object_record",
                    title=f"{object_schema.label} actualizado",
                    message=f"Se actualizo '{record.title or object_schema.label}'.",
                    metadata={
                        "record_id": record.pk,
                        "object_key": object_schema.key,
                        "object_label": object_schema.label,
                        "changed_fields": changed_fields,
                    },
                )
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
    _require_crm_permission(request, PERMISSION_DEALS_MOVE, capability="deals")
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

    _audit_crm_action(
        request,
        action="moved" if previous_stage != stage else "reordered",
        object_type="deal",
        title=(
            f"{request.tenant.get_label('deal_singular', 'Deal')} movido"
            if previous_stage != stage
            else f"{request.tenant.get_label('deal_singular', 'Deal')} reordenado"
        ),
        message=(
            f"Se movio '{deal.title}' de {previous_stage} a {stage}."
            if previous_stage != stage
            else f"Se reordeno '{deal.title}' dentro de {stage}."
        ),
        metadata={
            "deal_id": deal.pk,
            "deal_title": deal.title,
            "entity_id": deal.entity_id,
            "pipeline_id": deal.pipeline_id,
            "pipeline_name": getattr(deal.pipeline, "name", ""),
            "previous_pipeline_name": previous_pipeline_name,
            "previous_stage": previous_stage,
            "current_stage": stage,
            "position": inserted_index if inserted_index is not None else position,
        },
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
    selected_kind = _normalize_activity_kind(request.GET.get("kind"))
    selected_status = _normalize_activity_status(request.GET.get("status"))
    now = timezone.now()

    base_qs = Activity.objects.select_related("entity", "deal", "assigned_to")
    if q:
        base_qs = base_qs.filter(
            Q(title__icontains=q)
            | Q(description__icontains=q)
            | Q(entity__full_name__icontains=q)
        )

    activities_qs = _apply_activity_operational_filters(
        base_qs,
        selected_kind=selected_kind,
        selected_status=selected_status,
        now=now,
    )
    show_task_lanes = selected_kind in {"", Activity.TYPE_TASK}
    task_qs = base_qs.filter(activity_type=Activity.TYPE_TASK)
    if selected_status == "completed":
        pending_tasks = []
        completed_tasks = list(task_qs.filter(completed_at__isnull=False).order_by("-completed_at")[:6]) if show_task_lanes else []
    elif selected_status == "overdue":
        pending_tasks = list(task_qs.filter(completed_at__isnull=True, due_at__lt=now).order_by("due_at", "-created_at")[:12]) if show_task_lanes else []
        completed_tasks = []
    elif selected_status == "open":
        pending_tasks = list(task_qs.filter(completed_at__isnull=True).order_by("due_at", "-created_at")[:12]) if show_task_lanes else []
        completed_tasks = []
    else:
        pending_tasks = list(task_qs.filter(completed_at__isnull=True).order_by("due_at", "-created_at")[:12]) if show_task_lanes else []
        completed_tasks = list(task_qs.filter(completed_at__isnull=False).order_by("-completed_at")[:6]) if show_task_lanes else []

    selected_kind_label = dict(Activity.TYPE_CHOICES).get(selected_kind, labels.get("activity_plural", "Actividades"))
    timeline_title = "Timeline reciente" if not selected_kind else f"{selected_kind_label} recientes"
    timeline_note = "Ordenado por actividad mas nueva para decidir el siguiente toque."
    if selected_kind == Activity.TYPE_CLAIM:
        timeline_note = "Usa este carril para no dejar siniestros abiertos sin responsable ni fecha."

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
            "selected_kind": selected_kind,
            "selected_status": selected_status,
            "activity_kind_choices": [("", "Todas")] + list(Activity.TYPE_CHOICES),
            "activity_status_choices": [
                ("", "Todo"),
                ("open", "Abiertas"),
                ("overdue", "Vencidas"),
                ("completed", "Completadas"),
            ],
            "show_task_lanes": show_task_lanes,
            "timeline_title": timeline_title,
            "timeline_note": timeline_note,
            "task_preset_cards": build_task_preset_cards(request.tenant, limit=4),
            "can_create_activity": _can(request, PERMISSION_ACTIVITIES_EDIT),
            "can_complete_tasks": _can(request, PERMISSION_ACTIVITIES_COMPLETE),
        },
    )


@login_required
@tenant_permission_required(PERMISSION_ACTIVITIES_EDIT, capability="activities")
def activity_create(request):
    _require_crm_permission(request, PERMISSION_ACTIVITIES_EDIT, capability="activities")
    initial = {}
    entity_id = (request.GET.get("entity") or "").strip()
    deal_id = (request.GET.get("deal") or "").strip()
    activity_type = (request.GET.get("activity_type") or "").strip()
    title = (request.GET.get("title") or "").strip()
    preset_key = (request.GET.get("preset") or "").strip().lower()
    entity_id_value = int(entity_id) if entity_id.isdigit() else None
    deal_id_value = int(deal_id) if deal_id.isdigit() else None
    selected_task_preset = get_task_preset(request.tenant, preset_key)
    if selected_task_preset is not None:
        initial.update(
            build_task_preset_form_initial(
                request.tenant,
                preset_key,
                entity_id=entity_id_value,
                deal_id=deal_id_value,
                current_user=request.user,
            )
        )
    if entity_id.isdigit():
        initial["entity"] = entity_id
    if deal_id.isdigit():
        initial["deal"] = deal_id
    if activity_type in {choice[0] for choice in Activity.TYPE_CHOICES}:
        initial["activity_type"] = activity_type
    if title:
        initial["title"] = title
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
            _audit_crm_action(
                request,
                action="created",
                object_type="activity",
                title=f"{activity.get_activity_type_display()} creada",
                message=f"Se creo '{activity.title}'.",
                metadata={
                    "activity_id": activity.pk,
                    "activity_type": activity.activity_type,
                    "entity_id": activity.entity_id,
                    "deal_id": activity.deal_id,
                    "assigned_to_id": activity.assigned_to_id,
                    "due_at": activity.due_at,
                    "preset_key": preset_key,
                },
            )
            messages.success(request, "Actividad creada correctamente.")
            return redirect("binncrm:activities")
    else:
        form = ActivityForm(initial=initial, tenant=request.tenant, current_user=request.user)

    activity_ops = build_activity_operational_context(request.tenant)
    selected_activity_type = (
        str(form.data.get("activity_type") or "").strip()
        if request.method == "POST"
        else str(form.initial.get("activity_type") or "").strip()
    )
    task_preset_cards = build_task_preset_cards(
        request.tenant,
        entity_id=entity_id_value or initial.get("entity"),
        deal_id=deal_id_value or initial.get("deal"),
        selected_key=preset_key,
        limit=6,
    )
    selected_task_preset_card = next((item for item in task_preset_cards if item["is_selected"]), None)

    return render(
        request,
        "binncrm/activity_form.html",
        {
            "labels": request.tenant.tenant_config.labels,
            "form": form,
            "activity_ops": activity_ops,
            "task_preset_cards": task_preset_cards,
            "selected_task_preset": selected_task_preset,
            "selected_task_preset_card": selected_task_preset_card,
            "is_task_mode": (selected_activity_type == Activity.TYPE_TASK),
            "is_meeting_mode": (selected_activity_type == Activity.TYPE_MEETING),
        },
    )


@login_required
@tenant_permission_required(PERMISSION_ACTIVITIES_EDIT, capability="activities")
@require_POST
def activity_preset_create(request):
    _require_crm_permission(request, PERMISSION_ACTIVITIES_EDIT, capability="activities")
    preset_key = (request.POST.get("preset") or "").strip().lower()
    raw_entity_id = (request.POST.get("entity") or "").strip()
    raw_deal_id = (request.POST.get("deal") or "").strip()
    entity_id_value = int(raw_entity_id) if raw_entity_id.isdigit() else None
    deal_id_value = int(raw_deal_id) if raw_deal_id.isdigit() else None
    fallback_url = build_task_preset_form_href(
        preset_key=preset_key,
        entity_id=entity_id_value,
        deal_id=deal_id_value,
    )
    task_preset = get_task_preset(request.tenant, preset_key)
    if task_preset is None:
        messages.error(request, "Ese preset de tarea ya no esta disponible para esta empresa.")
        return redirect("binncrm:activities")

    entity = Entity.objects.filter(pk=entity_id_value, is_active=True).first() if entity_id_value else None
    deal = Deal.objects.filter(pk=deal_id_value, is_active=True).first() if deal_id_value else None
    if deal is not None and entity is None:
        entity = getattr(deal, "entity", None)
    if deal is not None and entity is not None and getattr(deal, "entity_id", None) != getattr(entity, "pk", None):
        messages.error(request, "El deal seleccionado no pertenece a la ficha elegida.")
        return redirect(fallback_url)
    if entity is None:
        messages.error(
            request,
            "Para usar un preset rapido primero entra desde una ficha o selecciona la entidad en el formulario.",
        )
        return redirect(fallback_url)

    assignee = resolve_task_preset_assignee(
        request.tenant,
        task_preset=task_preset,
        current_user=request.user,
    )
    due_at = build_task_preset_due_at(task_preset)
    activity = Activity.objects.create(
        entity=entity,
        deal=deal,
        activity_type=Activity.TYPE_TASK,
        title=task_preset["label"],
        description=task_preset.get("description", "") or f"Preset operativo: {task_preset['label']}.",
        assigned_to=assignee,
        due_at=due_at,
        created_by=request.user,
        updated_by=request.user,
    )
    log_activity_created(activity=activity, actor=request.user)
    _audit_crm_action(
        request,
        action="created",
        object_type="task",
        title="Tarea creada desde preset",
        message=f"Se creo '{activity.title}' para {entity.full_name}.",
        metadata={
            "activity_id": activity.pk,
            "activity_type": activity.activity_type,
            "entity_id": activity.entity_id,
            "deal_id": activity.deal_id,
            "assigned_to_id": activity.assigned_to_id,
            "due_at": activity.due_at,
            "preset_key": task_preset["key"],
            "preset_priority": task_preset["priority"],
            "preset_owner_role": task_preset["owner_role"],
        },
    )
    messages.success(request, f"Tarea '{activity.title}' creada para {entity.full_name}.")
    next_url = str(request.POST.get("next") or "").strip()
    if next_url.startswith("/"):
        return redirect(next_url)
    return redirect("binncrm:entity_detail", pk=entity.pk)


@login_required
@tenant_permission_required(PERMISSION_ACTIVITIES_COMPLETE, capability="activities")
@require_POST
def activity_toggle_complete(request, pk):
    _require_crm_permission(request, PERMISSION_ACTIVITIES_COMPLETE, capability="activities")
    activity = get_object_or_404(Activity, pk=pk, activity_type=Activity.TYPE_TASK)
    activity.completed_at = None if activity.completed_at else timezone.now()
    activity.updated_by = request.user
    activity.save(update_fields=["completed_at", "updated_by", "updated_at"])
    log_activity_completion_changed(activity=activity, actor=request.user)
    _audit_crm_action(
        request,
        action="completed" if activity.completed_at else "reopened",
        object_type="task",
        title="Tarea completada" if activity.completed_at else "Tarea reabierta",
        message=(
            f"Se completo '{activity.title}'."
            if activity.completed_at
            else f"Se reabrio '{activity.title}'."
        ),
        metadata={
            "activity_id": activity.pk,
            "activity_type": activity.activity_type,
            "entity_id": activity.entity_id,
            "deal_id": activity.deal_id,
            "completed_at": activity.completed_at,
        },
    )
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
    _require_crm_permission(request, PERMISSION_DOCUMENTS_EDIT, capability="documents")
    initial = {"is_active": True}
    entity_id = (request.GET.get("entity") or "").strip()
    deal_id = (request.GET.get("deal") or "").strip()
    document_type = (request.GET.get("document_type") or "").strip()
    if entity_id.isdigit():
        initial["entity"] = entity_id
    if deal_id.isdigit():
        initial["deal"] = deal_id
    if document_type:
        initial["document_type"] = document_type
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
            _audit_crm_action(
                request,
                action="created",
                object_type="document",
                title=f"{request.tenant.get_label('document_singular', 'Documento')} creado",
                message=f"Se registro '{document.title}'.",
                metadata={
                    "document_id": document.pk,
                    "document_title": document.title,
                    "document_type": document.document_type,
                    "entity_id": document.entity_id,
                    "deal_id": document.deal_id,
                    "storage_provider": document.storage_provider,
                    "storage_key": document.storage_key,
                },
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
    _require_crm_permission(request, PERMISSION_DOCUMENTS_EDIT, capability="documents")
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
                _audit_crm_action(
                    request,
                    action="updated",
                    object_type="document",
                    title=f"{request.tenant.get_label('document_singular', 'Documento')} actualizado",
                    message=f"Se actualizo '{document.title}'.",
                    metadata={
                        "document_id": document.pk,
                        "document_title": document.title,
                        "document_type": document.document_type,
                        "entity_id": document.entity_id,
                        "deal_id": document.deal_id,
                        "storage_provider": document.storage_provider,
                        "storage_key": document.storage_key,
                        "changed_fields": changed_fields,
                    },
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


def _assessment_question_groups(form, snapshot):
    groups = []
    for section in snapshot.get("sections", []):
        groups.append({
            "title": section.get("title", "Preguntas"),
            "description": section.get("description", ""),
            "fields": [form[f"answer__{question['key']}"] for question in section.get("questions", [])],
        })
    return groups


@login_required
@tenant_permission_required(PERMISSION_ENTITIES_VIEW, capability="assessments")
def assessments(request):
    ensure_default_template()
    submissions = AssessmentSubmission.objects.select_related("template", "entity", "deal").all()
    status = (request.GET.get("status") or "").strip()
    if status in dict(AssessmentSubmission.STATUS_CHOICES):
        submissions = submissions.filter(status=status)
    return render(request, "binncrm/assessments.html", {
        "submissions": submissions[:80], "status": status, "status_choices": AssessmentSubmission.STATUS_CHOICES,
        "can_manage": _can(request, PERMISSION_ENTITIES_EDIT),
    })


@login_required
@tenant_permission_required(PERMISSION_ENTITIES_EDIT, capability="assessments")
def assessment_submission_create(request):
    ensure_default_template()
    entity = Entity.objects.filter(pk=request.GET.get("entity")).first()
    deal = Deal.objects.select_related("entity").filter(pk=request.GET.get("deal")).first()
    if request.method == "POST":
        form = AssessmentSubmissionCreateForm(request.POST, entity=entity, deal=deal)
        if form.is_valid():
            submission = form.save(commit=False)
            submission.snapshot = build_template_snapshot(submission.template)
            submission.status = AssessmentSubmission.STATUS_SENT if submission.capture_mode == AssessmentSubmission.MODE_CLIENT else AssessmentSubmission.STATUS_DRAFT
            submission.created_by = request.user
            submission.updated_by = request.user
            submission.save()
            record_timeline_event(
                category="entity", event_key="assessment.created", kind_label="Levantamiento", title=submission.template.name,
                meta=submission.get_capture_mode_display(), description="Diagnostico creado para seguimiento.", actor=request.user,
                entity=submission.entity, deal=submission.deal, payload={"assessment_submission_id": submission.pk},
            )
            messages.success(request, "Levantamiento creado. Ya puedes responderlo o compartir el enlace.")
            return redirect("binncrm:assessment_submission_detail", pk=submission.pk)
    else:
        form = AssessmentSubmissionCreateForm(entity=entity, deal=deal)
    return render(request, "binncrm/assessment_submission_form.html", {"form": form, "entity": entity, "deal": deal})


@login_required
@tenant_permission_required(PERMISSION_ENTITIES_VIEW, capability="assessments")
def assessment_submission_detail(request, pk):
    submission = get_object_or_404(AssessmentSubmission.objects.select_related("template", "entity", "deal").prefetch_related("answers"), pk=pk)
    return render(request, "binncrm/assessment_submission_detail.html", {
        "submission": submission,
        "public_url": request.build_absolute_uri(reverse("binncrm:assessment_public_response", kwargs={"token": submission.public_token})),
        "answers": submission.answers.all(), "can_manage": _can(request, PERMISSION_ENTITIES_EDIT),
    })


@login_required
@tenant_permission_required(PERMISSION_ENTITIES_EDIT, capability="assessments")
def assessment_submission_respond(request, pk):
    submission = get_object_or_404(AssessmentSubmission.objects.prefetch_related("answers"), pk=pk)
    if submission.is_expired:
        messages.error(request, "Este levantamiento ya vencio.")
        return redirect("binncrm:assessment_submission_detail", pk=submission.pk)
    initial_answers = submission_answer_map(submission)
    form = AssessmentResponseForm(request.POST or None, snapshot=submission.snapshot, initial_answers=initial_answers)
    if request.method == "POST" and form.is_valid():
        save_submission_answers(submission, form.cleaned_data, submitted_by_name=request.user.get_full_name() or request.user.username, complete=True)
        record_timeline_event(
            category="entity", event_key="assessment.completed", kind_label="Levantamiento", title=submission.template.name,
            meta="Completado por equipo", description="Diagnostico registrado.", actor=request.user,
            entity=submission.entity, deal=submission.deal, payload={"assessment_submission_id": submission.pk},
        )
        messages.success(request, "Levantamiento completado y registrado en la ficha.")
        return redirect("binncrm:assessment_submission_detail", pk=submission.pk)
    return render(request, "binncrm/assessment_response_form.html", {
        "form": form, "submission": submission, "question_groups": _assessment_question_groups(form, submission.snapshot), "is_public": False,
    })


@login_required
@tenant_role_required(*CRM_ADMIN_ALLOWED_ROLES)
@tenant_permission_required(PERMISSION_ENTITIES_EDIT, capability="assessments")
def assessment_templates(request):
    ensure_default_template()
    form = AssessmentTemplateForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        template = form.save(commit=False)
        template.created_by = request.user
        template.updated_by = request.user
        template.save()
        messages.success(request, "Plantilla creada. Agrega secciones y preguntas.")
        return redirect("binncrm:assessment_template_detail", pk=template.pk)
    return render(request, "binncrm/assessment_templates.html", {"templates": AssessmentTemplate.objects.all(), "form": form})


@login_required
@tenant_role_required(*CRM_ADMIN_ALLOWED_ROLES)
@tenant_permission_required(PERMISSION_ENTITIES_EDIT, capability="assessments")
def assessment_template_detail(request, pk):
    template = get_object_or_404(AssessmentTemplate.objects.prefetch_related("sections__questions"), pk=pk)
    action = request.POST.get("action") if request.method == "POST" else ""
    section_form = AssessmentSectionForm(request.POST if action == "section" else None)
    question_form = AssessmentQuestionForm(request.POST if action == "question" else None)
    if action == "section" and section_form.is_valid():
        section = section_form.save(commit=False)
        section.template = template
        section.created_by = request.user
        section.updated_by = request.user
        section.save()
        messages.success(request, "Seccion agregada.")
        return redirect("binncrm:assessment_template_detail", pk=template.pk)
    if action == "question" and question_form.is_valid():
        section = get_object_or_404(template.sections.all(), pk=request.POST.get("section_id"))
        question = question_form.save(commit=False)
        question.section = section
        question.created_by = request.user
        question.updated_by = request.user
        question.save()
        messages.success(request, "Pregunta agregada.")
        return redirect("binncrm:assessment_template_detail", pk=template.pk)
    return render(request, "binncrm/assessment_template_detail.html", {"template": template, "section_form": section_form, "question_form": question_form})


def assessment_public_response(request, token):
    """Public access is restricted to one opaque, frozen and non-expired execution."""
    submission = get_object_or_404(AssessmentSubmission.objects.prefetch_related("answers"), public_token=token)
    if submission.is_expired or submission.status == AssessmentSubmission.STATUS_COMPLETED:
        return render(request, "binncrm/assessment_public_closed.html", {"submission": submission}, status=410)
    initial_answers = submission_answer_map(submission)
    form = AssessmentResponseForm(request.POST or None, snapshot=submission.snapshot, initial_answers=initial_answers)
    if request.method == "POST" and form.is_valid():
        save_submission_answers(submission, form.cleaned_data, submitted_by_name="Cliente", complete=True)
        record_timeline_event(
            category="entity", event_key="assessment.client_completed", kind_label="Levantamiento", title=submission.template.name,
            meta="Respondido por cliente", description="Respuesta recibida desde enlace seguro.",
            entity=submission.entity, deal=submission.deal, payload={"assessment_submission_id": submission.pk},
        )
        return render(request, "binncrm/assessment_public_complete.html", {"submission": submission})
    return render(request, "binncrm/assessment_response_form.html", {
        "form": form, "submission": submission, "question_groups": _assessment_question_groups(form, submission.snapshot), "is_public": True,
    })
