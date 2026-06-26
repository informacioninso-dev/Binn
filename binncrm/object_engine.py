from __future__ import annotations

from typing import Any

from django.db.models import Count, Q
from django_tenants.utils import schema_context

from .models import ObjectField, ObjectRecord, ObjectSchema, ObjectView

FIELD_TYPE_SELECT = "select"

BROKER_LIFECYCLE_FIELD = {
    "key": "lifecycle_stage",
    "label": "Etapa broker",
    "type": FIELD_TYPE_SELECT,
    "default": "lead",
    "choices": [
        {"value": "lead", "label": "Lead"},
        {"value": "asegurado", "label": "Asegurado"},
        {"value": "renovacion", "label": "Renovacion"},
    ],
}

SERVICES_LIFECYCLE_FIELD = {
    "key": "service_stage",
    "label": "Etapa servicios",
    "type": FIELD_TYPE_SELECT,
    "default": "prospecto",
    "choices": [
        {"value": "prospecto", "label": "Prospecto"},
        {"value": "cliente_activo", "label": "Cliente activo"},
        {"value": "renovacion_upsell", "label": "Renovacion / upsell"},
    ],
}

SERVICES_RENEWAL_FIELD = {
    "key": "renewal_on",
    "label": "Fecha de renovacion",
    "type": ObjectField.TYPE_DATE,
}

SERVICES_DELIVERY_OWNER_FIELD = {
    "key": "delivery_owner",
    "label": "Responsable delivery",
    "type": ObjectField.TYPE_TEXT,
}

DEFAULT_OBJECT_SCHEMAS = (
    {
        "key": "entity",
        "label": "Contactos",
        "description": "Base flexible de clientes, cuentas o residentes segun el tenant.",
        "default_views": [
            {
                "key": "all_entities",
                "label": "Todos los registros",
                "description": "La base completa ordenada alfabeticamente.",
                "view_type": ObjectView.VIEW_TABLE,
                "config": {"ordering": "full_name"},
            },
            {
                "key": "recently_updated",
                "label": "Actualizados esta semana",
                "description": "Fichas con movimiento reciente para operar mas rapido.",
                "view_type": ObjectView.VIEW_TABLE,
                "config": {"filters": {"updated_within_days": 7}, "ordering": "-updated_at,full_name"},
            },
            {
                "key": "missing_contact",
                "label": "Sin contacto claro",
                "description": "Registros sin telefono ni correo para limpiar la base.",
                "view_type": ObjectView.VIEW_TABLE,
                "config": {"filters": {"missing_contact": True}, "ordering": "full_name"},
            },
        ],
    },
    {
        "key": "deal",
        "label": "Oportunidades",
        "description": "Embudo comercial y operaciones con etapas visibles.",
        "default_views": [
            {
                "key": "pipeline_board",
                "label": "Pipeline principal",
                "description": "Tablero base con todo el embudo abierto.",
                "view_type": ObjectView.VIEW_KANBAN,
                "config": {"ordering": "sort_order,-updated_at"},
            },
            {
                "key": "closing_soon",
                "label": "Por cerrar",
                "description": "Deals abiertos con fecha de cierre proxima.",
                "view_type": ObjectView.VIEW_KANBAN,
                "config": {"filters": {"expected_close_within_days": 14}, "ordering": "sort_order,-updated_at"},
            },
            {
                "key": "stale_deals",
                "label": "Sin movimiento",
                "description": "Deals que se estan enfriando y piden accion.",
                "view_type": ObjectView.VIEW_KANBAN,
                "config": {"filters": {"stale_days": 14}, "ordering": "sort_order,-updated_at"},
            },
        ],
    },
    {
        "key": "activity",
        "label": "Actividades",
        "description": "Timeline, tareas y seguimientos operativos.",
        "default_views": [
            {
                "key": "activity_feed",
                "label": "Feed operativo",
                "description": "Actividad cronologica del equipo.",
                "view_type": ObjectView.VIEW_LIST,
                "config": {"ordering": "-created_at"},
            }
        ],
    },
    {
        "key": "document",
        "label": "Documentos",
        "description": "Repositorio documental y checklist operativo.",
        "default_views": [
            {
                "key": "all_documents",
                "label": "Documentos activos",
                "description": "Vista base del repositorio documental.",
                "view_type": ObjectView.VIEW_TABLE,
                "config": {"ordering": "-created_at"},
            }
        ],
    },
    {
        "key": "proposal",
        "label": "Propuestas",
        "description": "Cotizaciones y propuestas con vigencia controlada.",
        "default_views": [
            {
                "key": "proposal_table",
                "label": "Propuestas abiertas",
                "description": "Seguimiento base de propuestas vivas.",
                "view_type": ObjectView.VIEW_TABLE,
                "config": {"ordering": "-updated_at"},
            }
        ],
    },
    {
        "key": "collection",
        "label": "Cobranzas",
        "description": "Seguimiento de compromisos de pago y saldos abiertos.",
        "default_views": [
            {
                "key": "collection_table",
                "label": "Cobranzas abiertas",
                "description": "Vista operativa de saldos pendientes.",
                "view_type": ObjectView.VIEW_TABLE,
                "config": {"ordering": "due_on,-updated_at"},
            }
        ],
    },
)

SUPPORTED_FIELD_TYPES = {
    ObjectField.TYPE_TEXT,
    ObjectField.TYPE_TEXTAREA,
    ObjectField.TYPE_NUMBER,
    ObjectField.TYPE_EMAIL,
    ObjectField.TYPE_DATE,
    ObjectField.TYPE_BOOLEAN,
    FIELD_TYPE_SELECT,
}

SYSTEM_OBJECT_KEYS = {definition["key"] for definition in DEFAULT_OBJECT_SCHEMAS}


def get_entity_field_definitions(*, tenant=None) -> list[dict]:
    return get_object_field_definitions(object_key="entity", tenant=tenant)


def get_object_field_definitions(*, object_key: str, tenant=None) -> list[dict]:
    fallback = _fallback_field_definitions(object_key=object_key, tenant=tenant)
    if tenant is None or not getattr(tenant, "schema_name", ""):
        return fallback

    try:
        object_schema = (
            ObjectSchema.objects.prefetch_related("fields")
            .filter(key=object_key, is_active=True)
            .first()
        )
    except Exception:
        return fallback

    if object_schema is None:
        return fallback

    stored_definitions = [
        _normalize_field_definition(
            {
                "key": field.key,
                "label": field.label,
                "type": field.field_type,
                "required": field.required,
                **(field.config or {}),
            },
            position=index,
        )
        for index, field in enumerate(
            object_schema.fields.filter(is_active=True).order_by("position", "label", "id"),
            start=1,
        )
    ]

    if object_key != "entity" or not fallback:
        return stored_definitions

    stored_keys = {field_definition["key"] for field_definition in stored_definitions}
    merged_definitions = list(stored_definitions)
    next_position = len(merged_definitions) + 1
    for field_definition in fallback:
        if field_definition["key"] in stored_keys:
            continue
        merged_definitions.append(_normalize_field_definition(field_definition, position=next_position))
        next_position += 1
    return merged_definitions


def get_object_schema_catalog(*, tenant=None) -> list[dict]:
    if tenant is None or not getattr(tenant, "schema_name", ""):
        return [dict(item) for item in DEFAULT_OBJECT_SCHEMAS]

    try:
        object_schemas = (
            ObjectSchema.objects.prefetch_related("fields", "views")
            .filter(is_active=True)
            .order_by("label", "id")
        )
    except Exception:
        return [dict(item) for item in DEFAULT_OBJECT_SCHEMAS]

    catalog = []
    for object_schema in object_schemas:
        catalog.append(
            {
                "key": object_schema.key,
                "label": object_schema.label,
                "description": object_schema.description,
                "source": object_schema.source,
                "field_count": object_schema.fields.filter(is_active=True).count(),
                "view_count": object_schema.views.filter(is_active=True).count(),
                "record_count": object_schema.records.filter(is_active=True).count() if hasattr(object_schema, "records") else 0,
            }
        )
    return catalog


def get_object_views(*, object_key: str, tenant=None) -> list[dict]:
    fallback = _fallback_object_views(object_key=object_key)
    if tenant is None or not getattr(tenant, "schema_name", ""):
        return fallback

    try:
        object_schema = (
            ObjectSchema.objects.prefetch_related("views")
            .filter(key=object_key, is_active=True)
            .first()
        )
    except Exception:
        return fallback

    if object_schema is None:
        return fallback

    stored_views = [
        {
            "key": view.key,
            "label": view.label,
            "description": view.description,
            "view_type": view.view_type,
            "position": view.position,
            "is_default": view.is_default,
            "config": dict(view.config or {}),
        }
        for view in object_schema.views.filter(is_active=True).order_by("position", "label", "id")
    ]
    if not stored_views:
        return fallback

    stored_by_key = {view["key"]: dict(view) for view in stored_views}
    merged_views = list(stored_views)
    for fallback_view in fallback:
        if fallback_view["key"] not in stored_by_key:
            merged_views.append(dict(fallback_view))
    return sorted(merged_views, key=lambda item: (item.get("position", 0), item.get("label", ""), item.get("key", "")))


def sync_tenant_object_schemas(tenant) -> list[str]:
    notices: list[str] = []
    active_schema_keys: list[str] = []

    with schema_context(tenant.schema_name):
        for position, definition in enumerate(DEFAULT_OBJECT_SCHEMAS, start=1):
            active_schema_keys.append(definition["key"])
            object_schema, created = ObjectSchema.objects.update_or_create(
                key=definition["key"],
                defaults={
                    "label": definition["label"],
                    "description": definition["description"],
                    "source": ObjectSchema.SOURCE_SYSTEM,
                    "settings": {},
                    "is_active": True,
                    "updated_by": None,
                },
            )
            if created:
                notices.append(f"Objeto base '{object_schema.label}' inicializado.")
            _sync_default_views(
                object_schema=object_schema,
                definitions=definition.get("default_views") or [definition["default_view"]],
            )
            if definition["key"] == "entity":
                _sync_dynamic_entity_fields(object_schema=object_schema, entity_fields=getattr(tenant, "entity_fields", []))

        for position, definition in enumerate(getattr(tenant, "custom_objects", []) or [], start=1):
            object_schema, created = ObjectSchema.objects.update_or_create(
                key=definition["key"],
                defaults={
                    "label": definition["label"],
                    "description": definition.get("description", ""),
                    "source": ObjectSchema.SOURCE_CUSTOM,
                    "settings": dict(definition.get("settings", {})),
                    "is_active": True,
                    "updated_by": None,
                },
            )
            active_schema_keys.append(definition["key"])
            if created:
                notices.append(f"Objeto custom '{object_schema.label}' inicializado.")
            _sync_custom_object_schema(object_schema=object_schema, definition=definition)

        stale_schemas = ObjectSchema.objects.filter(is_active=True, source=ObjectSchema.SOURCE_CUSTOM)
        if active_schema_keys:
            stale_schemas = stale_schemas.exclude(key__in=active_schema_keys)
        stale_schemas.update(is_active=False)

    return notices


def get_custom_object_schemas(*, tenant=None) -> list[ObjectSchema]:
    if tenant is None or not getattr(tenant, "schema_name", ""):
        return []
    try:
        return list(
            ObjectSchema.objects.prefetch_related("fields", "views")
            .annotate(
                active_record_count=Count("records", filter=Q(records__is_active=True), distinct=True),
                active_field_count=Count("fields", filter=Q(fields__is_active=True), distinct=True),
                active_view_count=Count("views", filter=Q(views__is_active=True), distinct=True),
            )
            .filter(source=ObjectSchema.SOURCE_CUSTOM, is_active=True)
            .order_by("label", "id")
        )
    except Exception:
        return []


def get_object_schema_definition(*, object_key: str):
    return (
        ObjectSchema.objects.prefetch_related("fields", "views")
        .filter(key=object_key, is_active=True)
        .first()
    )


def get_object_record_field_definitions(*, object_schema: ObjectSchema) -> list[dict]:
    return [
        _normalize_field_definition(
            {
                "key": field.key,
                "label": field.label,
                "type": field.field_type,
                "required": field.required,
                **(field.config or {}),
            },
            position=index,
        )
        for index, field in enumerate(
            object_schema.fields.filter(is_active=True).order_by("position", "label", "id"),
            start=1,
        )
    ]


def resolve_object_record_title(
    *,
    object_schema: ObjectSchema,
    data: dict[str, Any],
    field_definitions: list[dict] | None = None,
) -> str:
    settings = dict(object_schema.settings or {})
    if field_definitions is None:
        field_definitions = (
            get_object_record_field_definitions(object_schema=object_schema)
            if object_schema.pk
            else []
        )
    primary_key = str(settings.get("primary_field", "")).strip().lower()
    if not primary_key:
        primary_text_field = next(
            (field["key"] for field in field_definitions if field["type"] in {ObjectField.TYPE_TEXT, ObjectField.TYPE_EMAIL}),
            "",
        )
        primary_key = primary_text_field or (field_definitions[0]["key"] if field_definitions else "")
    raw_value = (data or {}).get(primary_key)
    if raw_value not in (None, "", []):
        return str(raw_value).strip()[:180]
    return object_schema.label


def build_object_record_preview(*, object_schema: ObjectSchema, record: ObjectRecord) -> dict[str, Any]:
    field_definitions = get_object_record_field_definitions(object_schema=object_schema)
    settings = dict(object_schema.settings or {})
    subtitle_key = str(settings.get("subtitle_field", "")).strip().lower()
    subtitle = ""
    if subtitle_key:
        subtitle = _format_object_record_value(record.data.get(subtitle_key), next((field for field in field_definitions if field["key"] == subtitle_key), {}))
    primary_values = []
    for field_definition in field_definitions:
        formatted_value = _format_object_record_value(record.data.get(field_definition["key"]), field_definition)
        if not formatted_value:
            continue
        primary_values.append(
            {
                "key": field_definition["key"],
                "label": field_definition["label"],
                "value": formatted_value,
            }
        )
    return {
        "record": record,
        "title": record.title or resolve_object_record_title(object_schema=object_schema, data=record.data or {}),
        "subtitle": subtitle,
        "fields": primary_values,
    }


def _sync_default_views(*, object_schema, definitions: list[dict]) -> None:
    active_keys: list[str] = []
    for position, definition in enumerate(definitions, start=1):
        active_keys.append(definition["key"])
        ObjectView.objects.update_or_create(
            object_schema=object_schema,
            key=definition["key"],
            defaults={
                "label": definition["label"],
                "description": definition.get("description", ""),
                "view_type": definition["view_type"],
                "position": position,
                "config": dict(definition.get("config", {})),
                "is_default": position == 1,
                "is_active": True,
                "updated_by": None,
            },
        )

    stale_views = object_schema.views.filter(is_active=True)
    if active_keys:
        stale_views = stale_views.exclude(key__in=active_keys)
    stale_views.update(is_active=False)


def _sync_custom_object_schema(*, object_schema, definition: dict[str, Any]) -> None:
    object_schema.label = definition["label"]
    object_schema.description = definition.get("description", "")
    object_schema.source = ObjectSchema.SOURCE_CUSTOM
    object_schema.settings = dict(definition.get("settings", {}))
    object_schema.is_active = True
    object_schema.save(update_fields=["label", "description", "source", "settings", "is_active", "updated_at"])

    _sync_object_fields(object_schema=object_schema, field_definitions=definition.get("fields", []), is_system=False)
    _sync_default_views(
        object_schema=object_schema,
        definitions=definition.get("views") or _build_default_custom_object_views(definition),
    )


def _sync_object_fields(*, object_schema, field_definitions: list[dict], is_system: bool) -> None:
    normalized_fields = [
        _normalize_field_definition(field_definition, position=index)
        for index, field_definition in enumerate(field_definitions or [], start=1)
    ]
    configured_keys = [field["key"] for field in normalized_fields]

    for position, field_definition in enumerate(normalized_fields, start=1):
        extra_config = {
            key: value
            for key, value in field_definition.items()
            if key not in {"key", "label", "type", "required", "position"}
        }
        ObjectField.objects.update_or_create(
            object_schema=object_schema,
            key=field_definition["key"],
            defaults={
                "label": field_definition["label"],
                "field_type": field_definition["type"],
                "position": position,
                "required": field_definition["required"],
                "config": extra_config,
                "is_system": is_system,
                "is_active": True,
                "updated_by": None,
            },
        )

    stale_fields = object_schema.fields.filter(is_system=is_system)
    if configured_keys:
        stale_fields = stale_fields.exclude(key__in=configured_keys)
    for stale_field in stale_fields:
        if stale_field.is_active:
            stale_field.is_active = False
            stale_field.save(update_fields=["is_active", "updated_at"])


def _sync_dynamic_entity_fields(*, object_schema, entity_fields: list[dict]) -> None:
    _sync_object_fields(object_schema=object_schema, field_definitions=entity_fields, is_system=False)


def _build_default_custom_object_views(definition: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "key": f"{definition['key']}_all",
            "label": "Todos los registros",
            "description": "Vista base del objeto custom.",
            "view_type": ObjectView.VIEW_TABLE,
            "config": {"ordering": "-updated_at"},
        },
        {
            "key": f"{definition['key']}_recent",
            "label": "Actualizados recientemente",
            "description": "Registros con movimiento reciente.",
            "view_type": ObjectView.VIEW_LIST,
            "config": {"ordering": "-updated_at"},
        },
    ]


def _fallback_field_definitions(*, object_key: str, tenant=None) -> list[dict]:
    if object_key != "entity":
        return []
    configured_fields = list(getattr(tenant, "entity_fields", []) or [])
    profile = getattr(getattr(tenant, "tenant_config", tenant), "profile", "")
    if profile == "broker" and not any(str(field.get("key", "")).strip().lower() == BROKER_LIFECYCLE_FIELD["key"] for field in configured_fields):
        configured_fields = [BROKER_LIFECYCLE_FIELD, *configured_fields]
    if profile == "servicios":
        existing_keys = {str(field.get("key", "")).strip().lower() for field in configured_fields}
        services_fields = [SERVICES_LIFECYCLE_FIELD, SERVICES_RENEWAL_FIELD, SERVICES_DELIVERY_OWNER_FIELD]
        missing_fields = [field for field in services_fields if field["key"] not in existing_keys]
        if missing_fields:
            configured_fields = [*missing_fields, *configured_fields]
    return [
        _normalize_field_definition(field_definition, position=index)
        for index, field_definition in enumerate(configured_fields, start=1)
    ]


def _fallback_object_views(*, object_key: str) -> list[dict]:
    for definition in DEFAULT_OBJECT_SCHEMAS:
        if definition["key"] != object_key:
            continue
        return [
            {
                "key": view_definition["key"],
                "label": view_definition["label"],
                "description": view_definition.get("description", ""),
                "view_type": view_definition["view_type"],
                "position": position,
                "is_default": position == 1,
                "config": dict(view_definition.get("config", {})),
            }
            for position, view_definition in enumerate(
                definition.get("default_views") or [definition["default_view"]],
                start=1,
            )
        ]
    return []


def _normalize_field_definition(field_definition: dict[str, Any], *, position: int) -> dict:
    field_type = str(field_definition.get("type", ObjectField.TYPE_TEXT)).strip().lower()
    if field_type not in SUPPORTED_FIELD_TYPES:
        field_type = ObjectField.TYPE_TEXT
    normalized = dict(field_definition)
    normalized["key"] = str(field_definition.get("key", "")).strip().lower()
    normalized["label"] = str(field_definition.get("label", normalized["key"])).strip() or normalized["key"]
    normalized["type"] = field_type
    normalized["required"] = bool(field_definition.get("required", False))
    normalized["position"] = position
    normalized["choices"] = _normalize_choice_definitions(field_definition.get("choices"))
    normalized["default"] = field_definition.get("default")
    return normalized


def _format_object_record_value(value, field_definition: dict[str, Any]) -> str:
    if value in (None, "", []):
        return ""
    field_type = field_definition.get("type", ObjectField.TYPE_TEXT)
    if field_type == ObjectField.TYPE_BOOLEAN:
        return "Si" if bool(value) else "No"
    if field_type == FIELD_TYPE_SELECT:
        resolved_label = _resolve_choice_label(value, field_definition.get("choices"))
        return resolved_label or str(value)
    return str(value)


def _normalize_choice_definitions(raw_choices) -> list[dict[str, str]]:
    normalized = []
    for choice in list(raw_choices or []):
        if isinstance(choice, dict):
            value = str(choice.get("value", "")).strip()
            label = str(choice.get("label", value)).strip()
        else:
            value = str(choice).strip()
            label = value
        if not value:
            continue
        normalized.append({"value": value, "label": label or value})
    return normalized


def _resolve_choice_label(value, raw_choices) -> str:
    current_value = str(value or "").strip()
    if not current_value:
        return ""
    for choice in _normalize_choice_definitions(raw_choices):
        if choice["value"] == current_value:
            return choice["label"]
    return ""
