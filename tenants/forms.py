import json
import re

from django import forms
from django.conf import settings
from django.contrib.auth.forms import AuthenticationForm
from django.core.exceptions import ValidationError

from access.models import TenantMembership
from access.runtime import count_case_insensitive_usernames

from .defaults import (
    DASHBOARD_WIDGET_LABELS,
    MODULE_ORDER_LABELS,
    PROFILE_CHOICES,
    ROLE_PERMISSION_LABELS,
    VALID_ROLE_KEYS,
    get_profile_defaults,
    resolve_dashboard_widgets,
    resolve_module_order,
    resolve_role_policies,
)
from .models import Client
from .services import sync_tenant_object_schemas, sync_tenant_pipelines


_SCHEMA_RE = re.compile(r"^[a-z][a-z0-9_]{2,62}$")
_SUBDOMAIN_RE = re.compile(r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$")
_CONFIG_KEY_RE = re.compile(r"^[a-z][a-z0-9_]{1,49}$")
_PIPELINE_KEY_RE = re.compile(r"^[a-z0-9]+(?:[-_][a-z0-9]+)*$")
_FIELD_TYPES = {"text", "textarea", "number", "email", "date", "boolean"}
_OBJECT_VIEW_TYPES = {"table", "list"}
_RESERVED_OBJECT_KEYS = {"entity", "deal", "activity", "document", "proposal", "collection"}

_INPUT = {"class": "binn-input w-full rounded-lg border px-3 py-2"}
_JSON_TEXTAREA = {
    "class": "binn-input w-full rounded-lg border px-3 py-2 font-mono text-xs",
    "rows": 10,
    "spellcheck": "false",
}


def _case_insensitive_username_count(username: str) -> int:
    return count_case_insensitive_usernames(username)


def _pretty_json(value) -> str:
    return json.dumps(value, indent=2, ensure_ascii=True)


def _parse_json(raw_value: str, *, label: str):
    raw_value = (raw_value or "").strip()
    if not raw_value:
        return None
    try:
        return json.loads(raw_value)
    except json.JSONDecodeError as exc:
        raise ValidationError(f"{label}: JSON invalido ({exc.msg}).") from exc


def _clean_feature_flags(value):
    parsed = _parse_json(value, label="Feature flags")
    if parsed is None:
        return {}
    if not isinstance(parsed, dict):
        raise ValidationError("Feature flags debe ser un objeto JSON.")

    cleaned = {}
    for key, item in parsed.items():
        normalized_key = str(key).strip()
        if not _CONFIG_KEY_RE.match(normalized_key):
            raise ValidationError(
                "Cada feature flag debe usar claves tipo snake_case, por ejemplo 'documents' o 'fiscal_lookup'."
            )
        if not isinstance(item, bool):
            raise ValidationError(f"El feature flag '{normalized_key}' debe ser booleano.")
        cleaned[normalized_key] = item
    return cleaned


def _clean_labels(value):
    parsed = _parse_json(value, label="Labels")
    if parsed is None:
        return {}
    if not isinstance(parsed, dict):
        raise ValidationError("Labels debe ser un objeto JSON.")

    cleaned = {}
    for key, item in parsed.items():
        normalized_key = str(key).strip()
        if not normalized_key:
            raise ValidationError("Cada label debe tener una clave no vacia.")
        if not isinstance(item, str):
            raise ValidationError(f"El label '{normalized_key}' debe ser texto.")
        cleaned[normalized_key] = item.strip()
    return cleaned


def _clean_entity_fields(value):
    parsed = _parse_json(value, label="Entity fields")
    if parsed is None:
        return []
    if not isinstance(parsed, list):
        raise ValidationError("Entity fields debe ser una lista JSON.")

    cleaned = []
    seen_keys = set()
    for index, item in enumerate(parsed, start=1):
        if not isinstance(item, dict):
            raise ValidationError(f"El campo #{index} debe ser un objeto JSON.")

        key = str(item.get("key", "")).strip().lower()
        label = str(item.get("label", "")).strip()
        field_type = str(item.get("type", "text")).strip().lower()
        required = item.get("required", False)

        if not _CONFIG_KEY_RE.match(key):
            raise ValidationError(
                f"El campo #{index} necesita una clave valida en snake_case, por ejemplo 'placa' o 'departamento'."
            )
        if key in seen_keys:
            raise ValidationError(f"La clave '{key}' esta repetida en entity_fields.")
        if not label:
            raise ValidationError(f"El campo '{key}' necesita un label visible.")
        if field_type not in _FIELD_TYPES:
            raise ValidationError(
                f"El campo '{key}' usa un tipo invalido. Usa uno de: {', '.join(sorted(_FIELD_TYPES))}."
            )
        if not isinstance(required, bool):
            raise ValidationError(f"El atributo 'required' del campo '{key}' debe ser booleano.")

        cleaned_item = dict(item)
        cleaned_item["key"] = key
        cleaned_item["label"] = label
        cleaned_item["type"] = field_type
        cleaned_item["required"] = required
        cleaned.append(cleaned_item)
        seen_keys.add(key)

    return cleaned


def _clean_custom_objects(value):
    parsed = _parse_json(value, label="Custom objects")
    if parsed is None:
        return []
    if not isinstance(parsed, list):
        raise ValidationError("Custom objects debe ser una lista JSON.")

    cleaned = []
    seen_keys = set()
    for index, item in enumerate(parsed, start=1):
        if not isinstance(item, dict):
            raise ValidationError(f"El objeto custom #{index} debe ser un objeto JSON.")

        key = str(item.get("key", "")).strip().lower()
        label = str(item.get("label", "")).strip()
        description = str(item.get("description", "")).strip()
        settings = item.get("settings", {}) or {}
        fields = item.get("fields", []) or []
        views = item.get("views", []) or []

        if not _PIPELINE_KEY_RE.match(key):
            raise ValidationError(
                f"El objeto custom #{index} necesita una clave valida tipo slug, por ejemplo 'poliza_detalle' o 'unidad'."
            )
        if key in _RESERVED_OBJECT_KEYS:
            raise ValidationError(f"La clave '{key}' esta reservada por un objeto del sistema.")
        if key in seen_keys:
            raise ValidationError(f"La clave '{key}' esta repetida en custom_objects.")
        if not label:
            raise ValidationError(f"El objeto custom '{key}' necesita un label visible.")
        if not isinstance(settings, dict):
            raise ValidationError(f"El objeto custom '{key}' debe usar un objeto JSON en settings.")
        if not isinstance(fields, list) or not fields:
            raise ValidationError(f"El objeto custom '{key}' necesita una lista de fields con al menos un campo.")
        if views and not isinstance(views, list):
            raise ValidationError(f"El objeto custom '{key}' debe usar una lista en views.")

        cleaned_fields = []
        field_keys = set()
        for field_index, field in enumerate(fields, start=1):
            if not isinstance(field, dict):
                raise ValidationError(f"El campo #{field_index} del objeto '{key}' debe ser un objeto JSON.")
            field_key = str(field.get("key", "")).strip().lower()
            field_label = str(field.get("label", "")).strip()
            field_type = str(field.get("type", "text")).strip().lower()
            required = field.get("required", False)
            if not _CONFIG_KEY_RE.match(field_key):
                raise ValidationError(
                    f"El campo '{field_key or field_index}' del objeto '{key}' necesita una clave valida en snake_case."
                )
            if field_key in field_keys:
                raise ValidationError(f"El campo '{field_key}' esta repetido en el objeto '{key}'.")
            if not field_label:
                raise ValidationError(f"El campo '{field_key}' del objeto '{key}' necesita un label visible.")
            if field_type not in _FIELD_TYPES:
                raise ValidationError(f"El campo '{field_key}' del objeto '{key}' usa un tipo invalido.")
            if not isinstance(required, bool):
                raise ValidationError(f"El atributo 'required' del campo '{field_key}' debe ser booleano.")
            cleaned_field = dict(field)
            cleaned_field["key"] = field_key
            cleaned_field["label"] = field_label
            cleaned_field["type"] = field_type
            cleaned_field["required"] = required
            cleaned_fields.append(cleaned_field)
            field_keys.add(field_key)

        primary_field = str(settings.get("primary_field", "")).strip().lower()
        subtitle_field = str(settings.get("subtitle_field", "")).strip().lower()
        if primary_field and primary_field not in field_keys:
            raise ValidationError(f"El primary_field '{primary_field}' del objeto '{key}' no existe en fields.")
        if subtitle_field and subtitle_field not in field_keys:
            raise ValidationError(f"El subtitle_field '{subtitle_field}' del objeto '{key}' no existe en fields.")

        cleaned_views = []
        seen_view_keys = set()
        for view_index, view in enumerate(views, start=1):
            if not isinstance(view, dict):
                raise ValidationError(f"La vista #{view_index} del objeto '{key}' debe ser un objeto JSON.")
            view_key = str(view.get("key", "")).strip().lower()
            view_label = str(view.get("label", "")).strip()
            view_type = str(view.get("view_type", "table")).strip().lower()
            if not _PIPELINE_KEY_RE.match(view_key):
                raise ValidationError(f"La vista #{view_index} del objeto '{key}' necesita una clave valida.")
            if view_key in seen_view_keys:
                raise ValidationError(f"La vista '{view_key}' esta repetida en el objeto '{key}'.")
            if not view_label:
                raise ValidationError(f"La vista '{view_key}' del objeto '{key}' necesita un label visible.")
            if view_type not in _OBJECT_VIEW_TYPES:
                raise ValidationError(
                    f"La vista '{view_key}' del objeto '{key}' usa un tipo invalido. Usa uno de: {', '.join(sorted(_OBJECT_VIEW_TYPES))}."
                )
            cleaned_views.append(
                {
                    "key": view_key,
                    "label": view_label,
                    "description": str(view.get("description", "")).strip(),
                    "view_type": view_type,
                    "config": view.get("config", {}) if isinstance(view.get("config", {}), dict) else {},
                }
            )
            seen_view_keys.add(view_key)

        cleaned_item = {
            "key": key,
            "label": label,
            "description": description,
            "settings": {
                **({"primary_field": primary_field} if primary_field else {}),
                **({"subtitle_field": subtitle_field} if subtitle_field else {}),
            },
            "fields": cleaned_fields,
        }
        if cleaned_views:
            cleaned_item["views"] = cleaned_views
        cleaned.append(cleaned_item)
        seen_keys.add(key)

    return cleaned


def _clean_module_order(value):
    parsed = _parse_json(value, label="Module order")
    if parsed is None:
        return []
    if not isinstance(parsed, list):
        raise ValidationError("Module order debe ser una lista JSON.")

    cleaned = []
    seen_keys = set()
    for index, item in enumerate(parsed, start=1):
        key = str(item).strip().lower()
        if key not in MODULE_ORDER_LABELS:
            raise ValidationError(
                f"El modulo #{index} no es valido. Usa uno de: {', '.join(sorted(MODULE_ORDER_LABELS))}."
            )
        if key in seen_keys:
            raise ValidationError(f"El modulo '{key}' esta repetido en module_order.")
        cleaned.append(key)
        seen_keys.add(key)
    return resolve_module_order(cleaned)


def _clean_dashboard_widgets(value):
    parsed = _parse_json(value, label="Dashboard widgets")
    if parsed is None:
        return []
    if not isinstance(parsed, list):
        raise ValidationError("Dashboard widgets debe ser una lista JSON.")

    cleaned = []
    seen_keys = set()
    for index, item in enumerate(parsed, start=1):
        key = str(item).strip().lower()
        if key not in DASHBOARD_WIDGET_LABELS:
            raise ValidationError(
                f"El widget #{index} no es valido. Usa uno de: {', '.join(sorted(DASHBOARD_WIDGET_LABELS))}."
            )
        if key in seen_keys:
            raise ValidationError(f"El widget '{key}' esta repetido en dashboard_widgets.")
        cleaned.append(key)
        seen_keys.add(key)
    return resolve_dashboard_widgets(cleaned)


def _clean_role_policies(value):
    parsed = _parse_json(value, label="Role policies")
    if parsed is None:
        return {}
    if not isinstance(parsed, dict):
        raise ValidationError("Role policies debe ser un objeto JSON.")

    cleaned = {}
    for role_key, permissions in parsed.items():
        normalized_role = str(role_key).strip().lower()
        if normalized_role not in VALID_ROLE_KEYS:
            raise ValidationError(
                f"El rol '{normalized_role}' no es valido. Usa uno de: {', '.join(VALID_ROLE_KEYS)}."
            )
        if not isinstance(permissions, list):
            raise ValidationError(f"El rol '{normalized_role}' debe usar una lista de permisos.")

        cleaned_permissions = []
        seen_codes = set()
        for permission_code in permissions:
            normalized_code = str(permission_code).strip().lower()
            if normalized_code == "*":
                cleaned_permissions = ["*"]
                seen_codes = {"*"}
                break
            if normalized_code not in ROLE_PERMISSION_LABELS:
                raise ValidationError(
                    f"El permiso '{normalized_code}' no es valido para el rol '{normalized_role}'."
                )
            if normalized_code in seen_codes:
                raise ValidationError(
                    f"El permiso '{normalized_code}' esta repetido dentro del rol '{normalized_role}'."
                )
            cleaned_permissions.append(normalized_code)
            seen_codes.add(normalized_code)

        cleaned[normalized_role] = cleaned_permissions
    return resolve_role_policies(cleaned)


def _clean_pipeline_templates(value):
    parsed = _parse_json(value, label="Pipeline templates")
    if parsed is None:
        return []
    if not isinstance(parsed, list):
        raise ValidationError("Pipeline templates debe ser una lista JSON.")

    cleaned = []
    seen_keys = set()
    for index, item in enumerate(parsed, start=1):
        if not isinstance(item, dict):
            raise ValidationError(f"El pipeline #{index} debe ser un objeto JSON.")

        key = str(item.get("key", "")).strip().lower()
        label = str(item.get("label", "")).strip()
        stages = item.get("stages", [])

        if not _PIPELINE_KEY_RE.match(key):
            raise ValidationError(
                f"El pipeline #{index} necesita una clave valida tipo slug, por ejemplo 'renovaciones'."
            )
        if key in seen_keys:
            raise ValidationError(f"La clave de pipeline '{key}' esta repetida.")
        if not label:
            raise ValidationError(f"El pipeline '{key}' necesita un label visible.")
        if not isinstance(stages, list) or not stages:
            raise ValidationError(f"El pipeline '{key}' necesita una lista de etapas.")

        cleaned_stages = []
        seen_stages = set()
        for stage in stages:
            if not isinstance(stage, str) or not stage.strip():
                raise ValidationError(f"Todas las etapas del pipeline '{key}' deben ser texto.")
            normalized_stage = stage.strip()
            if normalized_stage in seen_stages:
                raise ValidationError(f"La etapa '{normalized_stage}' esta repetida en el pipeline '{key}'.")
            cleaned_stages.append(normalized_stage)
            seen_stages.add(normalized_stage)

        cleaned_item = dict(item)
        cleaned_item["key"] = key
        cleaned_item["label"] = label
        cleaned_item["stages"] = cleaned_stages
        cleaned.append(cleaned_item)
        seen_keys.add(key)

    return cleaned


def _clean_document_blueprints(value):
    parsed = _parse_json(value, label="Document blueprints")
    if parsed is None:
        return []
    if not isinstance(parsed, list):
        raise ValidationError("Document blueprints debe ser una lista JSON.")

    cleaned = []
    seen_keys = set()
    for index, item in enumerate(parsed, start=1):
        if not isinstance(item, dict):
            raise ValidationError(f"El blueprint #{index} debe ser un objeto JSON.")

        key = str(item.get("key", "")).strip().lower()
        label = str(item.get("label", "")).strip()
        category = str(item.get("category", "")).strip()
        description = str(item.get("description", "")).strip()
        storage_hint = str(item.get("storage_hint", "")).strip()
        metadata_fields = item.get("metadata_fields", [])

        if not _PIPELINE_KEY_RE.match(key):
            raise ValidationError(
                f"El blueprint #{index} necesita una clave valida tipo slug, por ejemplo 'poliza' o 'estado_cuenta'."
            )
        if key in seen_keys:
            raise ValidationError(f"La clave de blueprint '{key}' esta repetida.")
        if not label:
            raise ValidationError(f"El blueprint '{key}' necesita un label visible.")
        if metadata_fields and not isinstance(metadata_fields, list):
            raise ValidationError(f"El blueprint '{key}' debe usar una lista en metadata_fields.")

        cleaned_metadata_fields = []
        metadata_keys = set()
        for field_index, field in enumerate(metadata_fields, start=1):
            if not isinstance(field, dict):
                raise ValidationError(f"El campo #{field_index} del blueprint '{key}' debe ser un objeto JSON.")

            metadata_key = str(field.get("key", "")).strip().lower()
            metadata_label = str(field.get("label", "")).strip()
            field_type = str(field.get("type", "text")).strip().lower()

            if not _CONFIG_KEY_RE.match(metadata_key):
                raise ValidationError(
                    f"El campo '{metadata_key or field_index}' del blueprint '{key}' necesita una clave valida en snake_case."
                )
            if metadata_key in metadata_keys:
                raise ValidationError(f"El campo '{metadata_key}' esta repetido en el blueprint '{key}'.")
            if not metadata_label:
                raise ValidationError(f"El campo '{metadata_key}' del blueprint '{key}' necesita un label visible.")
            if field_type not in _FIELD_TYPES:
                raise ValidationError(
                    f"El campo '{metadata_key}' del blueprint '{key}' usa un tipo invalido."
                )

            cleaned_field = dict(field)
            cleaned_field["key"] = metadata_key
            cleaned_field["label"] = metadata_label
            cleaned_field["type"] = field_type
            cleaned_metadata_fields.append(cleaned_field)
            metadata_keys.add(metadata_key)

        cleaned_item = dict(item)
        cleaned_item["key"] = key
        cleaned_item["label"] = label
        cleaned_item["category"] = category
        cleaned_item["description"] = description
        cleaned_item["storage_hint"] = storage_hint
        cleaned_item["metadata_fields"] = cleaned_metadata_fields
        cleaned.append(cleaned_item)
        seen_keys.add(key)

    return cleaned


class TenantCreateForm(forms.Form):
    name = forms.CharField(label="Nombre", max_length=120, widget=forms.TextInput(attrs=_INPUT))
    schema_name = forms.CharField(label="Schema", max_length=63, widget=forms.TextInput(attrs=_INPUT))
    subdomain = forms.CharField(
        label="Subdominio",
        max_length=63,
        widget=forms.TextInput(attrs={**_INPUT, "placeholder": "acme"}),
        help_text=f"Se convertira en subdominio.{settings.TENANT_BASE_DOMAIN}",
    )
    plan = forms.ChoiceField(label="Plan", choices=Client.PLAN_CHOICES, widget=forms.Select(attrs=_INPUT))
    profile = forms.ChoiceField(
        label="Perfil",
        choices=PROFILE_CHOICES,
        widget=forms.Select(attrs=_INPUT),
        help_text="Preconfigura etiquetas, campos flexibles y pipeline inicial.",
    )

    admin_username = forms.CharField(
        label="Usuario admin",
        max_length=150,
        required=False,
        widget=forms.TextInput(attrs=_INPUT),
    )
    admin_email = forms.EmailField(
        label="Email admin",
        required=False,
        widget=forms.EmailInput(attrs=_INPUT),
    )
    admin_password = forms.CharField(
        label="Password admin",
        required=False,
        widget=forms.PasswordInput(attrs=_INPUT),
    )

    def clean_schema_name(self):
        value = (self.cleaned_data.get("schema_name") or "").strip().lower()
        value = re.sub(r"[\s-]+", "_", value)
        value = re.sub(r"[^a-z0-9_]", "", value)
        if value == "public":
            raise ValidationError("El schema 'public' esta reservado.")
        if not _SCHEMA_RE.match(value):
            raise ValidationError("Schema invalido. Usa letras, numeros y guion bajo; min 3 caracteres.")
        return value

    def clean_subdomain(self):
        value = (self.cleaned_data.get("subdomain") or "").strip().lower()
        value = value.replace("https://", "").replace("http://", "").strip("/")

        base_domain = settings.TENANT_BASE_DOMAIN
        if value.endswith(f".{base_domain}"):
            value = value[: -(len(base_domain) + 1)]

        value = re.sub(r"[\s_]+", "-", value)
        value = re.sub(r"[^a-z0-9-]", "-", value)
        value = re.sub(r"-{2,}", "-", value).strip("-")

        if not _SUBDOMAIN_RE.match(value):
            raise ValidationError("Subdominio invalido. Solo letras, numeros y guiones.")

        return f"{value}.{base_domain}"

    def clean(self):
        cleaned = super().clean()
        username = (cleaned.get("admin_username") or "").strip()
        password = (cleaned.get("admin_password") or "").strip()
        email = (cleaned.get("admin_email") or "").strip()

        any_admin = any([username, password, email])
        if any_admin and not username:
            self.add_error("admin_username", "Requerido si vas a crear o usar admin.")
        if username:
            user_matches = _case_insensitive_username_count(username)
            if user_matches > 1:
                self.add_error(
                    "admin_username",
                    "Hay varios usuarios globales con ese nombre. Corrige ese conflicto antes de reutilizarlo.",
                )
            elif user_matches == 0 and not password:
                self.add_error("admin_password", "Requerido para crear un admin nuevo.")
        return cleaned


class TenantEditForm(forms.ModelForm):
    profile = forms.ChoiceField(label="Perfil", choices=PROFILE_CHOICES, widget=forms.Select(attrs=_INPUT))
    reset_to_profile_defaults = forms.BooleanField(
        label="Reaplicar defaults del perfil",
        required=False,
        help_text="Sobrescribe labels, feature flags, campos flexibles y pipelines con los defaults del perfil elegido.",
        widget=forms.CheckboxInput(attrs={"class": "h-4 w-4 rounded border-gray-300"}),
    )
    feature_flags_json = forms.CharField(
        label="Feature flags JSON",
        required=False,
        help_text='Objeto JSON. Ejemplo: {"entities": true, "documents": false}',
        widget=forms.Textarea(attrs=_JSON_TEXTAREA),
    )
    labels_json = forms.CharField(
        label="Labels JSON",
        required=False,
        help_text='Objeto JSON para renombrar la interfaz. Ejemplo: {"entity_plural": "Residentes"}',
        widget=forms.Textarea(attrs=_JSON_TEXTAREA),
    )
    entity_fields_json = forms.CharField(
        label="Entity fields JSON",
        required=False,
        help_text='Lista JSON de campos flexibles. Ejemplo: [{"key": "placa", "label": "Placa", "type": "text"}]',
        widget=forms.Textarea(attrs=_JSON_TEXTAREA),
    )
    custom_objects_json = forms.CharField(
        label="Custom objects JSON",
        required=False,
        help_text='Lista JSON para definir objetos custom del tenant. Ejemplo: [{"key": "poliza", "label": "Polizas", "fields": [{"key": "numero", "label": "Numero", "type": "text"}]}]',
        widget=forms.Textarea(attrs={**_JSON_TEXTAREA, "rows": 14}),
    )
    module_order_json = forms.CharField(
        label="Module order JSON",
        required=False,
        help_text='Lista JSON con el orden de modulos visibles. Ejemplo: ["entities", "deals", "documents", "activities"]',
        widget=forms.Textarea(attrs={**_JSON_TEXTAREA, "rows": 6}),
    )
    dashboard_widgets_json = forms.CharField(
        label="Dashboard widgets JSON",
        required=False,
        help_text='Lista JSON para mostrar u ocultar bloques del panel. Ejemplo: ["highlights", "summary_cards", "pipeline_panel"]',
        widget=forms.Textarea(attrs={**_JSON_TEXTAREA, "rows": 6}),
    )
    role_policies_json = forms.CharField(
        label="Role policies JSON",
        required=False,
        help_text='Objeto JSON para permisos por rol. Ejemplo: {"viewer": ["dashboard.view", "entities.view"]}',
        widget=forms.Textarea(attrs={**_JSON_TEXTAREA, "rows": 12}),
    )
    document_blueprints_json = forms.CharField(
        label="Document blueprints JSON",
        required=False,
        help_text='Lista JSON para extender o sobreescribir tipos documentales del tenant.',
        widget=forms.Textarea(attrs={**_JSON_TEXTAREA, "rows": 10}),
    )
    pipeline_templates_json = forms.CharField(
        label="Pipelines y etapas (JSON)",
        required=False,
        help_text=(
            'Aqui defines las columnas del tablero de oportunidades. '
            'Ejemplo: [{"key": "ventas", "label": "Ventas", "stages": ["Nuevo", "Contactado", "Propuesta", "Ganado"]}]'
        ),
        widget=forms.Textarea(
            attrs={
                **_JSON_TEXTAREA,
                "rows": 12,
                "placeholder": (
                    '[\n'
                    '  {\n'
                    '    "key": "ventas",\n'
                    '    "label": "Ventas",\n'
                    '    "stages": ["Nuevo", "Contactado", "Propuesta", "Ganado"]\n'
                    "  }\n"
                    "]"
                ),
            }
        ),
    )

    class Meta:
        model = Client
        fields = ("name", "plan", "max_users", "storage_quota_mb", "is_active", "allow_consolidation")
        widgets = {
            "name": forms.TextInput(attrs=_INPUT),
            "plan": forms.Select(attrs=_INPUT),
            "max_users": forms.NumberInput(attrs=_INPUT),
            "storage_quota_mb": forms.NumberInput(attrs=_INPUT),
            "is_active": forms.CheckboxInput(attrs={"class": "h-4 w-4 rounded border-gray-300"}),
            "allow_consolidation": forms.CheckboxInput(attrs={"class": "h-4 w-4 rounded border-gray-300"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.sync_notices = []
        self.fields["allow_consolidation"].label = "Permitir consolidacion corporativa"
        self.fields["allow_consolidation"].help_text = (
            "Si se apaga, este tenant puede seguir dentro de un holding, "
            "pero no compartira datos con ninguna otra empresa."
        )
        self.fields["max_users"].label = "Limite de usuarios"
        self.fields["max_users"].help_text = "Tope administrativo de accesos locales activos para esta empresa."
        self.fields["storage_quota_mb"].label = "Storage quota (MB)"
        self.fields["storage_quota_mb"].help_text = "Tope administrativo de almacenamiento operativo visible para esta empresa."
        if self.instance.pk:
            config = self.instance.tenant_config
            self.fields["profile"].initial = config.profile
            self.fields["feature_flags_json"].initial = _pretty_json(config.feature_flags)
            self.fields["labels_json"].initial = _pretty_json(config.labels)
            self.fields["entity_fields_json"].initial = _pretty_json(config.entity_fields)
            self.fields["custom_objects_json"].initial = _pretty_json(config.custom_objects)
            self.fields["module_order_json"].initial = _pretty_json(resolve_module_order(config.module_order))
            self.fields["dashboard_widgets_json"].initial = _pretty_json(resolve_dashboard_widgets(config.dashboard_widgets))
            self.fields["role_policies_json"].initial = _pretty_json(resolve_role_policies(config.role_policies))
            self.fields["document_blueprints_json"].initial = _pretty_json(config.document_blueprints)
            self.fields["pipeline_templates_json"].initial = _pretty_json(config.pipeline_templates)

    def clean_feature_flags_json(self):
        return _clean_feature_flags(self.cleaned_data.get("feature_flags_json"))

    def clean_labels_json(self):
        return _clean_labels(self.cleaned_data.get("labels_json"))

    def clean_entity_fields_json(self):
        return _clean_entity_fields(self.cleaned_data.get("entity_fields_json"))

    def clean_custom_objects_json(self):
        return _clean_custom_objects(self.cleaned_data.get("custom_objects_json"))

    def clean_module_order_json(self):
        return _clean_module_order(self.cleaned_data.get("module_order_json"))

    def clean_dashboard_widgets_json(self):
        return _clean_dashboard_widgets(self.cleaned_data.get("dashboard_widgets_json"))

    def clean_role_policies_json(self):
        return _clean_role_policies(self.cleaned_data.get("role_policies_json"))

    def clean_document_blueprints_json(self):
        return _clean_document_blueprints(self.cleaned_data.get("document_blueprints_json"))

    def clean_pipeline_templates_json(self):
        return _clean_pipeline_templates(self.cleaned_data.get("pipeline_templates_json"))

    def clean(self):
        cleaned = super().clean()
        profile = cleaned.get("profile")
        if cleaned.get("reset_to_profile_defaults") and profile:
            defaults = get_profile_defaults(profile)
            cleaned["feature_flags_json"] = defaults["feature_flags"]
            cleaned["labels_json"] = defaults["labels"]
            cleaned["entity_fields_json"] = defaults["entity_fields"]
            cleaned["custom_objects_json"] = defaults["custom_objects"]
            cleaned["module_order_json"] = defaults["module_order"]
            cleaned["dashboard_widgets_json"] = defaults["dashboard_widgets"]
            cleaned["role_policies_json"] = defaults["role_policies"]
            cleaned["document_blueprints_json"] = defaults["document_blueprints"]
            cleaned["pipeline_templates_json"] = defaults["pipeline_templates"]
        return cleaned

    def save(self, commit=True):
        tenant = super().save(commit=commit)
        if not commit:
            return tenant

        config = tenant.tenant_config
        config.profile = self.cleaned_data["profile"]
        config.feature_flags = self.cleaned_data["feature_flags_json"]
        config.labels = self.cleaned_data["labels_json"]
        config.entity_fields = self.cleaned_data["entity_fields_json"]
        config.custom_objects = self.cleaned_data["custom_objects_json"]
        config.module_order = self.cleaned_data["module_order_json"]
        config.dashboard_widgets = self.cleaned_data["dashboard_widgets_json"]
        config.role_policies = self.cleaned_data["role_policies_json"]
        config.document_blueprints = self.cleaned_data["document_blueprints_json"]
        config.pipeline_templates = self.cleaned_data["pipeline_templates_json"]
        config.save()
        self.sync_notices = sync_tenant_pipelines(tenant)
        self.sync_notices.extend(sync_tenant_object_schemas(tenant))
        return tenant


class TenantListFilterForm(forms.Form):
    STATUS_ALL = ""
    STATUS_ACTIVE = "active"
    STATUS_INACTIVE = "inactive"
    STATUS_CHOICES = [
        (STATUS_ALL, "Todos los estados"),
        (STATUS_ACTIVE, "Solo activos"),
        (STATUS_INACTIVE, "Solo inactivos"),
    ]

    q = forms.CharField(
        required=False,
        label="Buscar",
        widget=forms.TextInput(attrs={**_INPUT, "placeholder": "Tenant, schema o dominio"}),
    )
    plan = forms.ChoiceField(
        required=False,
        label="Plan",
        choices=[("", "Todos los planes"), *Client.PLAN_CHOICES],
        widget=forms.Select(attrs=_INPUT),
    )
    status = forms.ChoiceField(
        required=False,
        label="Estado",
        choices=STATUS_CHOICES,
        widget=forms.Select(attrs=_INPUT),
    )


class AddMemberForm(forms.Form):
    username = forms.CharField(
        label="Usuario",
        max_length=150,
        widget=forms.TextInput(attrs={**_INPUT, "placeholder": "username"}),
    )
    role = forms.ChoiceField(
        label="Rol local",
        choices=TenantMembership.ROLE_CHOICES,
        initial=TenantMembership.ROLE_OPERATOR,
        widget=forms.Select(attrs=_INPUT),
    )

    def clean(self):
        cleaned = super().clean()
        username = (cleaned.get("username") or "").strip()
        if not username:
            self.add_error("username", "Ingresa un usuario existente.")
            return cleaned

        user_matches = _case_insensitive_username_count(username)
        if user_matches == 0:
            self.add_error("username", "El usuario no existe. Crealo desde la administracion global.")
        elif user_matches > 1:
            self.add_error(
                "username",
                "Hay varios usuarios globales con ese nombre. Corrige ese conflicto antes de asignarlo.",
            )

        return cleaned


class TenantAuthenticationForm(AuthenticationForm):
    username = forms.CharField(
        label="Usuario o correo",
        max_length=254,
        widget=forms.TextInput(
            attrs={
                "autofocus": True,
                "class": "binn-input binn-auth-input w-full rounded-lg border px-3 py-2",
                "placeholder": "tuusuario o correo@empresa.com",
                "autocomplete": "username",
                "spellcheck": "false",
            }
        ),
    )
    password = forms.CharField(
        label="Contraseña",
        strip=False,
        widget=forms.PasswordInput(
            attrs={
                "class": "binn-input binn-auth-input w-full rounded-lg border px-3 py-2",
                "placeholder": "Tu contraseña",
                "autocomplete": "current-password",
            }
        ),
    )
