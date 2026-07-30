import json
import re

from django import forms
from django.core.exceptions import ValidationError
from django.utils import timezone
from django.utils.text import slugify

from access.runtime import get_tenant_user_queryset

from .document_blueprints import (
    build_document_metadata_template,
    build_document_type_choices,
    get_document_blueprint_map,
)
from .models import Activity, CollectionRecord, Deal, Document, Entity, ObjectRecord, Pipeline, Proposal, SavedWorkspaceFilter
from .operational_context import (
    build_activity_operational_context,
    build_collection_operational_context,
    build_proposal_operational_context,
)
from .object_engine import (
    get_entity_field_definitions,
    get_object_record_field_definitions,
    resolve_object_record_title,
)


INPUT = {"class": "binn-input w-full rounded-lg border px-3 py-2"}
TEXTAREA = {"class": "binn-input w-full rounded-lg border px-3 py-2", "rows": 4}
PIPELINE_KEY_RE = re.compile(r"^[a-z0-9]+(?:[-_][a-z0-9]+)*$")


def _build_dynamic_field(field_definition: dict):
    field_type = field_definition.get("type", "text")
    label = field_definition.get("label", field_definition.get("key", "Campo"))
    required = bool(field_definition.get("required", False))
    choices = [(choice["value"], choice["label"]) for choice in field_definition.get("choices", [])]

    if field_type == "textarea":
        return forms.CharField(label=label, required=required, widget=forms.Textarea(attrs=TEXTAREA))
    if field_type == "number":
        return forms.DecimalField(label=label, required=required, widget=forms.NumberInput(attrs=INPUT))
    if field_type == "email":
        return forms.EmailField(label=label, required=required, widget=forms.EmailInput(attrs=INPUT))
    if field_type == "date":
        return forms.DateField(label=label, required=required, widget=forms.DateInput(attrs={**INPUT, "type": "date"}))
    if field_type == "boolean":
        return forms.BooleanField(label=label, required=False)
    if field_type == "select":
        return forms.ChoiceField(
            label=label,
            required=required,
            choices=[("", "Selecciona")] + choices,
            widget=forms.Select(attrs=INPUT),
        )
    return forms.CharField(label=label, required=required, widget=forms.TextInput(attrs=INPUT))


def _parse_pipeline_stage_lines(raw_value: str) -> list[str]:
    parts = []
    for line in (raw_value or "").replace(",", "\n").splitlines():
        value = line.strip()
        if value:
            parts.append(value)

    cleaned = []
    seen = set()
    for part in parts:
        lowered = part.casefold()
        if lowered in seen:
            raise ValidationError(f"La etapa '{part}' esta repetida.")
        cleaned.append(part)
        seen.add(lowered)

    if not cleaned:
        raise ValidationError("Debes definir al menos una etapa para el pipeline.")
    return cleaned


class PipelineTemplateEditorForm(forms.Form):
    pipeline_key = forms.CharField(required=False, widget=forms.HiddenInput())
    label = forms.CharField(
        label="Nombre del pipeline",
        max_length=120,
        widget=forms.TextInput(attrs={**INPUT, "placeholder": "Ventas B2B, Renovaciones, Recaudacion"}),
    )
    stages_text = forms.CharField(
        label="Etapas",
        help_text="Una etapa por linea. El orden aqui define las columnas del tablero.",
        widget=forms.Textarea(
            attrs={
                **TEXTAREA,
                "rows": 8,
                "placeholder": "Nuevo\nDiscovery\nPropuesta\nNegociacion\nGanado",
            }
        ),
    )
    make_default = forms.BooleanField(
        label="Usar como pipeline principal",
        required=False,
        widget=forms.CheckboxInput(attrs={"class": "h-4 w-4 rounded border-gray-300"}),
    )

    def __init__(self, *args, existing_keys=None, current_key=None, **kwargs):
        self.existing_keys = {str(key).strip().lower() for key in (existing_keys or []) if key}
        self.current_key = (current_key or "").strip().lower()
        super().__init__(*args, **kwargs)

    def clean_pipeline_key(self):
        value = (self.cleaned_data.get("pipeline_key") or "").strip().lower()
        if value and not PIPELINE_KEY_RE.match(value):
            raise ValidationError("El identificador interno del pipeline es invalido.")
        return value

    def clean_label(self):
        value = (self.cleaned_data.get("label") or "").strip()
        if not value:
            raise ValidationError("Debes indicar un nombre visible para el pipeline.")
        return value

    def clean_stages_text(self):
        return _parse_pipeline_stage_lines(self.cleaned_data.get("stages_text"))

    def clean(self):
        cleaned = super().clean()
        key = (cleaned.get("pipeline_key") or "").strip().lower()
        label = (cleaned.get("label") or "").strip()
        if not key:
            key = slugify(label).replace("-", "_")
        if not key:
            raise ValidationError("No pude generar una clave interna valida para el pipeline.")
        if not PIPELINE_KEY_RE.match(key):
            raise ValidationError("La clave interna generada para el pipeline es invalida.")
        if key != self.current_key and key in self.existing_keys:
            self.add_error("label", "Ya existe otro pipeline con ese nombre o clave interna.")
        cleaned["pipeline_key"] = key
        cleaned["stages"] = cleaned.get("stages_text", [])
        return cleaned


class SavedWorkspaceFilterForm(forms.ModelForm):
    q = forms.CharField(required=False, widget=forms.HiddenInput())
    view = forms.CharField(required=False, widget=forms.HiddenInput())
    pipeline = forms.CharField(required=False, widget=forms.HiddenInput())

    class Meta:
        model = SavedWorkspaceFilter
        fields = ["label"]
        widgets = {
            "label": forms.TextInput(
                attrs={
                    **INPUT,
                    "placeholder": "Ej. Deals frios, contacto sin telefono",
                    "maxlength": 80,
                }
            ),
        }

    def __init__(self, *args, object_type: str, **kwargs):
        self.object_type = object_type
        super().__init__(*args, **kwargs)

    def clean_label(self):
        value = (self.cleaned_data.get("label") or "").strip()
        if not value:
            raise ValidationError("Pon un nombre corto para identificar este filtro.")
        return value

    def clean(self):
        cleaned = super().clean()
        params = {
            "q": (cleaned.get("q") or "").strip(),
            "view": (cleaned.get("view") or "").strip(),
        }
        if self.object_type == SavedWorkspaceFilter.OBJECT_DEAL:
            params["pipeline"] = (cleaned.get("pipeline") or "").strip()
        cleaned["normalized_params"] = {key: value for key, value in params.items() if value}
        return cleaned


class EntityForm(forms.ModelForm):
    class Meta:
        model = Entity
        fields = ["full_name", "legal_id", "phone", "email", "notes", "is_active"]
        widgets = {
            "full_name": forms.TextInput(attrs=INPUT),
            "legal_id": forms.TextInput(attrs=INPUT),
            "phone": forms.TextInput(attrs=INPUT),
            "email": forms.EmailInput(attrs=INPUT),
            "notes": forms.Textarea(attrs=TEXTAREA),
            "is_active": forms.CheckboxInput(attrs={"class": "h-4 w-4 rounded border-gray-300"}),
        }

    def __init__(self, *args, tenant=None, **kwargs):
        self.tenant = tenant
        super().__init__(*args, **kwargs)
        self.extra_field_names = []
        data_extra = self.instance.data_extra if self.instance and self.instance.pk else {}

        field_definitions = get_entity_field_definitions(tenant=tenant) if tenant is not None else []
        for field_definition in field_definitions:
            field_name = f"extra__{field_definition['key']}"
            field = _build_dynamic_field(field_definition)
            field.initial = data_extra.get(field_definition["key"], field_definition.get("default"))
            self.fields[field_name] = field
            self.extra_field_names.append(field_name)

    def save(self, commit=True):
        instance = super().save(commit=False)
        extra_data = {}
        for field_name in self.extra_field_names:
            extra_key = field_name.split("__", 1)[1]
            extra_data[extra_key] = self.cleaned_data.get(field_name)
        instance.data_extra = extra_data
        if commit:
            instance.save()
        return instance


class DealForm(forms.ModelForm):
    stage = forms.ChoiceField(choices=(), widget=forms.Select(attrs=INPUT))

    class Meta:
        model = Deal
        fields = ["entity", "pipeline", "title", "amount", "currency", "stage", "expected_close_on", "status", "notes", "is_active"]
        widgets = {
            "entity": forms.Select(attrs=INPUT),
            "pipeline": forms.Select(attrs=INPUT),
            "title": forms.TextInput(attrs=INPUT),
            "amount": forms.NumberInput(attrs=INPUT),
            "currency": forms.TextInput(attrs=INPUT),
            "expected_close_on": forms.DateInput(attrs={**INPUT, "type": "date"}),
            "status": forms.Select(attrs=INPUT),
            "notes": forms.Textarea(attrs=TEXTAREA),
            "is_active": forms.CheckboxInput(attrs={"class": "h-4 w-4 rounded border-gray-300"}),
        }

    def __init__(self, *args, tenant=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["entity"].queryset = Entity.objects.filter(is_active=True).order_by("full_name")
        self.fields["pipeline"].queryset = Pipeline.objects.filter(is_active=True).order_by("position", "name")
        self.pipeline_stage_map = {
            str(pipeline.pk): list(pipeline.stage_choices)
            for pipeline in self.fields["pipeline"].queryset
        }

        selected_pipeline = None
        pipeline_id = self.data.get("pipeline") or getattr(self.instance, "pipeline_id", None)
        if pipeline_id:
            selected_pipeline = self.fields["pipeline"].queryset.filter(pk=pipeline_id).first()
        if selected_pipeline is None:
            selected_pipeline = self.fields["pipeline"].queryset.first()
            if selected_pipeline and not self.instance.pk:
                self.initial["pipeline"] = selected_pipeline.pk

        stages = selected_pipeline.stage_choices if selected_pipeline else []
        self.fields["stage"].choices = [(stage, stage) for stage in stages]
        if stages and not self.initial.get("stage") and not self.instance.pk:
            self.initial["stage"] = stages[0]
        self.fields["stage"].widget.attrs["data-stage-field"] = "true"
        self.fields["pipeline"].widget.attrs["data-pipeline-field"] = "true"

    def clean(self):
        cleaned = super().clean()
        pipeline = cleaned.get("pipeline")
        stage = cleaned.get("stage")
        if pipeline and stage and stage not in pipeline.stage_choices:
            self.add_error("stage", "Selecciona una etapa valida para el pipeline.")
        if pipeline and not stage and pipeline.stage_choices:
            cleaned["stage"] = pipeline.stage_choices[0]
        return cleaned


class ActivityForm(forms.ModelForm):
    class Meta:
        model = Activity
        fields = ["entity", "deal", "activity_type", "title", "description", "assigned_to", "due_at", "completed_at"]
        widgets = {
            "entity": forms.Select(attrs=INPUT),
            "deal": forms.Select(attrs=INPUT),
            "activity_type": forms.Select(attrs=INPUT),
            "title": forms.TextInput(attrs=INPUT),
            "description": forms.Textarea(attrs=TEXTAREA),
            "assigned_to": forms.Select(attrs=INPUT),
            "due_at": forms.DateTimeInput(attrs={**INPUT, "type": "datetime-local"}, format="%Y-%m-%dT%H:%M"),
            "completed_at": forms.DateTimeInput(attrs={**INPUT, "type": "datetime-local"}, format="%Y-%m-%dT%H:%M"),
        }

    def __init__(self, *args, tenant=None, current_user=None, **kwargs):
        self.tenant = tenant
        self.current_user = current_user
        super().__init__(*args, **kwargs)
        self.fields["entity"].queryset = Entity.objects.filter(is_active=True).order_by("full_name")
        self.fields["deal"].queryset = Deal.objects.filter(is_active=True).order_by("title")
        if tenant is not None:
            self.fields["assigned_to"].queryset = get_tenant_user_queryset(tenant)
            activity_ops = build_activity_operational_context(tenant)
            if not self.is_bound and not self.instance.pk and not self.initial.get("activity_type") and activity_ops["default_activity_type"]:
                self.initial["activity_type"] = activity_ops["default_activity_type"]
            if (
                not self.is_bound
                and not self.instance.pk
                and not self.initial.get("title")
                and self.initial.get("activity_type") == activity_ops["default_activity_type"]
                and activity_ops["default_activity_title"]
            ):
                self.initial["title"] = activity_ops["default_activity_title"]
        if current_user is not None and getattr(current_user, "is_authenticated", False) and not self.initial.get("assigned_to"):
            self.initial["assigned_to"] = current_user.pk
        self.fields["deal"].required = False
        self.fields["assigned_to"].required = False
        self.fields["due_at"].input_formats = ["%Y-%m-%dT%H:%M"]
        self.fields["completed_at"].input_formats = ["%Y-%m-%dT%H:%M"]

    def clean(self):
        cleaned = super().clean()
        entity = cleaned.get("entity")
        deal = cleaned.get("deal")
        if deal and not entity:
            cleaned["entity"] = deal.entity
        if entity and deal and deal.entity_id != entity.id:
            self.add_error("deal", "El deal seleccionado no pertenece a la entidad elegida.")
        if cleaned.get("activity_type") == Activity.TYPE_TASK and not cleaned.get("due_at"):
            self.add_error("due_at", "Las tareas deben tener fecha y hora de vencimiento.")
        if cleaned.get("activity_type") == Activity.TYPE_MEETING and not cleaned.get("due_at"):
            self.add_error("due_at", "Las reuniones deben tener fecha y hora agendada.")
        return cleaned


class DocumentForm(forms.ModelForm):
    document_type = forms.ChoiceField(
        label="Tipo de documento",
        choices=(),
        widget=forms.Select(attrs=INPUT),
    )
    metadata_json = forms.CharField(
        label="Metadata JSON",
        required=False,
        widget=forms.Textarea(attrs={**TEXTAREA, "rows": 5}),
        help_text="Opcional. Guarda metadatos extra del archivo en formato JSON o carga una plantilla segun el tipo.",
    )

    class Meta:
        model = Document
        fields = [
            "title",
            "document_type",
            "entity",
            "deal",
            "storage_provider",
            "bucket_name",
            "storage_key",
            "external_url",
            "content_type",
            "file_size",
            "expires_on",
            "is_verified",
            "is_active",
        ]
        widgets = {
            "title": forms.TextInput(attrs=INPUT),
            "document_type": forms.TextInput(attrs=INPUT),
            "entity": forms.Select(attrs=INPUT),
            "deal": forms.Select(attrs=INPUT),
            "storage_provider": forms.Select(attrs=INPUT),
            "bucket_name": forms.TextInput(attrs=INPUT),
            "storage_key": forms.TextInput(attrs=INPUT),
            "external_url": forms.URLInput(attrs=INPUT),
            "content_type": forms.TextInput(attrs=INPUT),
            "file_size": forms.NumberInput(attrs=INPUT),
            "expires_on": forms.DateInput(attrs={**INPUT, "type": "date"}),
            "is_verified": forms.CheckboxInput(attrs={"class": "h-4 w-4 rounded border-gray-300"}),
            "is_active": forms.CheckboxInput(attrs={"class": "h-4 w-4 rounded border-gray-300"}),
        }

    def __init__(self, *args, tenant=None, **kwargs):
        self.tenant = tenant
        super().__init__(*args, **kwargs)
        config = getattr(tenant, "tenant_config", tenant)
        profile = getattr(config, "profile", "general")
        custom_blueprints = getattr(config, "document_blueprints", [])
        self.document_blueprint_map = get_document_blueprint_map(profile, custom_blueprints=custom_blueprints)
        self.metadata_templates = {
            key: build_document_metadata_template(profile, key, custom_blueprints=custom_blueprints)
            for key in self.document_blueprint_map
        }
        self.fields["document_type"].choices = build_document_type_choices(
            profile,
            custom_blueprints=custom_blueprints,
        )
        self.fields["entity"].queryset = Entity.objects.filter(is_active=True).order_by("full_name")
        self.fields["deal"].queryset = Deal.objects.filter(is_active=True).order_by("title")
        self.fields["deal"].required = False
        self.fields["entity"].required = False
        self.fields["bucket_name"].widget.attrs["placeholder"] = "binn-broker-docs"
        self.fields["storage_key"].widget.attrs["placeholder"] = "broker/polizas/12345/archivo.pdf"
        self.fields["external_url"].widget.attrs["placeholder"] = "https://storage.example.com/documento.pdf"
        self.fields["content_type"].widget.attrs["placeholder"] = "application/pdf"
        self.fields["file_size"].widget.attrs["min"] = 0

        if self.fields["document_type"].choices and not self.instance.pk and not self.initial.get("document_type"):
            self.initial["document_type"] = self.fields["document_type"].choices[0][0]
        if self.instance and self.instance.pk and self.instance.metadata:
            self.fields["metadata_json"].initial = json.dumps(self.instance.metadata, indent=2, ensure_ascii=True)

    def clean_metadata_json(self):
        value = (self.cleaned_data.get("metadata_json") or "").strip()
        if not value:
            return {}
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError as exc:
            raise forms.ValidationError(f"JSON invalido: {exc.msg}") from exc
        if not isinstance(parsed, dict):
            raise forms.ValidationError("La metadata debe ser un objeto JSON.")
        return parsed

    def clean(self):
        cleaned = super().clean()
        entity = cleaned.get("entity")
        deal = cleaned.get("deal")
        if deal and not entity:
            cleaned["entity"] = deal.entity
        if entity and deal and deal.entity_id != entity.id:
            self.add_error("deal", "El deal seleccionado no pertenece a la entidad elegida.")
        storage_provider = cleaned.get("storage_provider")
        external_url = (cleaned.get("external_url") or "").strip()
        bucket_name = (cleaned.get("bucket_name") or "").strip()
        storage_key = (cleaned.get("storage_key") or "").strip()
        if storage_provider == Document.STORAGE_EXTERNAL and not external_url:
            self.add_error("external_url", "Ingresa la URL externa del documento.")
        if storage_provider == Document.STORAGE_S3 and not storage_key:
            self.add_error("storage_key", "Ingresa la ruta del archivo en storage.")
        if storage_provider == Document.STORAGE_MANUAL and not (storage_key or external_url or bucket_name):
            self.add_error("storage_key", "Registra al menos una referencia manual para ubicar el documento.")
        return cleaned

    def save(self, commit=True):
        instance = super().save(commit=False)
        instance.metadata = self.cleaned_data["metadata_json"]
        if commit:
            instance.save()
        return instance


class ProposalForm(forms.ModelForm):
    class Meta:
        model = Proposal
        fields = [
            "entity",
            "deal",
            "title",
            "proposal_number",
            "amount",
            "currency",
            "status",
            "valid_until",
            "summary",
            "terms",
            "is_active",
        ]
        widgets = {
            "entity": forms.Select(attrs=INPUT),
            "deal": forms.Select(attrs=INPUT),
            "title": forms.TextInput(attrs=INPUT),
            "proposal_number": forms.TextInput(attrs=INPUT),
            "amount": forms.NumberInput(attrs=INPUT),
            "currency": forms.TextInput(attrs=INPUT),
            "status": forms.Select(attrs=INPUT),
            "valid_until": forms.DateInput(attrs={**INPUT, "type": "date"}),
            "summary": forms.Textarea(attrs=TEXTAREA),
            "terms": forms.Textarea(attrs={**TEXTAREA, "rows": 5}),
            "is_active": forms.CheckboxInput(attrs={"class": "h-4 w-4 rounded border-gray-300"}),
        }

    def __init__(self, *args, tenant=None, **kwargs):
        self.tenant = tenant
        super().__init__(*args, **kwargs)
        self.fields["entity"].queryset = Entity.objects.filter(is_active=True).order_by("full_name")
        self.fields["deal"].queryset = Deal.objects.filter(is_active=True).order_by("title")
        self.fields["entity"].required = False
        self.fields["deal"].required = False
        if tenant is not None:
            proposal_ops = build_proposal_operational_context(tenant)
            if not self.is_bound and not self.instance.pk:
                self.initial.setdefault("currency", proposal_ops["default_currency"])
                self.initial.setdefault("valid_until", proposal_ops["default_valid_until"])
            self.fields["currency"].widget.attrs.setdefault("placeholder", proposal_ops["default_currency"])
            self.fields["proposal_number"].widget.attrs.setdefault("placeholder", proposal_ops["proposal_number_placeholder"])

    def clean(self):
        cleaned = super().clean()
        entity = cleaned.get("entity")
        deal = cleaned.get("deal")
        if deal and not entity:
            cleaned["entity"] = deal.entity
            entity = deal.entity
        if entity is None:
            self.add_error("entity", "Selecciona una entidad o un deal asociado.")
        if entity and deal and deal.entity_id != entity.id:
            self.add_error("deal", "El deal seleccionado no pertenece a la entidad elegida.")
        return cleaned


class CollectionRecordForm(forms.ModelForm):
    class Meta:
        model = CollectionRecord
        fields = [
            "entity",
            "deal",
            "title",
            "reference",
            "amount_due",
            "amount_paid",
            "currency",
            "status",
            "due_on",
            "promised_for",
            "notes",
            "is_active",
        ]
        widgets = {
            "entity": forms.Select(attrs=INPUT),
            "deal": forms.Select(attrs=INPUT),
            "title": forms.TextInput(attrs=INPUT),
            "reference": forms.TextInput(attrs=INPUT),
            "amount_due": forms.NumberInput(attrs=INPUT),
            "amount_paid": forms.NumberInput(attrs=INPUT),
            "currency": forms.TextInput(attrs=INPUT),
            "status": forms.Select(attrs=INPUT),
            "due_on": forms.DateInput(attrs={**INPUT, "type": "date"}),
            "promised_for": forms.DateInput(attrs={**INPUT, "type": "date"}),
            "notes": forms.Textarea(attrs=TEXTAREA),
            "is_active": forms.CheckboxInput(attrs={"class": "h-4 w-4 rounded border-gray-300"}),
        }

    def __init__(self, *args, tenant=None, **kwargs):
        self.tenant = tenant
        super().__init__(*args, **kwargs)
        self.fields["entity"].queryset = Entity.objects.filter(is_active=True).order_by("full_name")
        self.fields["deal"].queryset = Deal.objects.filter(is_active=True).order_by("title")
        self.fields["entity"].required = False
        self.fields["deal"].required = False
        if tenant is not None:
            collection_ops = build_collection_operational_context(tenant)
            choice_map = dict(CollectionRecord.STATUS_CHOICES)
            configured_choices = [(status, choice_map[status]) for status in collection_ops["states"] if status in choice_map]
            remaining_choices = [
                (status, label)
                for status, label in CollectionRecord.STATUS_CHOICES
                if status not in collection_ops["states"]
            ]
            self.fields["status"].choices = configured_choices + remaining_choices
            if not self.is_bound and not self.instance.pk:
                self.initial.setdefault("currency", collection_ops["default_currency"])
                self.initial.setdefault("status", collection_ops["default_status"])
            self.fields["currency"].widget.attrs.setdefault("placeholder", collection_ops["default_currency"])

    def clean(self):
        cleaned = super().clean()
        entity = cleaned.get("entity")
        deal = cleaned.get("deal")
        amount_due = cleaned.get("amount_due") or 0
        amount_paid = cleaned.get("amount_paid") or 0
        status = cleaned.get("status")
        if deal and not entity:
            cleaned["entity"] = deal.entity
            entity = deal.entity
        if entity is None:
            self.add_error("entity", "Selecciona una entidad o un deal asociado.")
        if entity and deal and deal.entity_id != entity.id:
            self.add_error("deal", "El deal seleccionado no pertenece a la entidad elegida.")
        if amount_paid > amount_due:
            self.add_error("amount_paid", "El monto pagado no puede superar el monto pendiente.")
        if status == CollectionRecord.STATUS_PROMISED and not cleaned.get("promised_for"):
            self.add_error("promised_for", "Si existe promesa de pago, registra la fecha prometida.")
        if status == CollectionRecord.STATUS_PAID and amount_paid <= 0:
            self.add_error("amount_paid", "Registra el monto pagado para marcar la cobranza como pagada.")
        return cleaned


class EntityImportForm(forms.Form):
    csv_file = forms.FileField(
        label="Archivo CSV",
        help_text="Sube un CSV exportado desde Excel o Google Sheets con encabezados en la primera fila.",
        widget=forms.ClearableFileInput(attrs={**INPUT, "accept": ".csv,text/csv"}),
    )
    update_existing = forms.BooleanField(
        label="Actualizar fichas existentes",
        required=False,
        initial=True,
        help_text="Si una fila coincide por identificacion, correo o telefono, Binn actualiza esa ficha en vez de duplicarla.",
        widget=forms.CheckboxInput(attrs={"class": "h-4 w-4 rounded border-gray-300"}),
    )


class ObjectRecordForm(forms.ModelForm):
    class Meta:
        model = ObjectRecord
        fields = ["is_active"]
        widgets = {
            "is_active": forms.CheckboxInput(attrs={"class": "h-4 w-4 rounded border-gray-300"}),
        }

    def __init__(self, *args, object_schema, **kwargs):
        self.object_schema = object_schema
        super().__init__(*args, **kwargs)
        self.dynamic_field_names = []
        payload = self.instance.data if self.instance and self.instance.pk else {}
        self.object_field_definitions = get_object_record_field_definitions(object_schema=object_schema)
        for field_definition in self.object_field_definitions:
            field_name = f"data__{field_definition['key']}"
            field = _build_dynamic_field(field_definition)
            field.initial = payload.get(field_definition["key"])
            self.fields[field_name] = field
            self.dynamic_field_names.append(field_name)

    def save(self, commit=True):
        instance = super().save(commit=False)
        instance.object_schema = self.object_schema
        payload = {}
        for field_name in self.dynamic_field_names:
            payload[field_name.split("__", 1)[1]] = self.cleaned_data.get(field_name)
        instance.data = payload
        instance.title = resolve_object_record_title(
            object_schema=self.object_schema,
            data=payload,
            field_definitions=self.object_field_definitions,
        )
        if commit:
            instance.save()
        return instance
