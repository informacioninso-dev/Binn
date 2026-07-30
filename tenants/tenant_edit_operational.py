from __future__ import annotations

from copy import deepcopy

from django import forms
from django.core.exceptions import ValidationError

from .forms import TenantEditForm, _INPUT, _JSON_TEXTAREA, _parse_json, _pretty_json
from .operational_settings import (
    COMMUNICATION_CHANNEL_LABELS,
    HOMEPAGE_DENSITY_LABELS,
    HOMEPAGE_LAYOUT_LABELS,
    get_operational_defaults,
    merge_operational_defaults,
    resolve_collection_settings,
    resolve_communication_settings,
    resolve_homepage_layout,
    resolve_quote_settings,
    resolve_task_presets,
)


class OperationalTenantEditForm(TenantEditForm):
    homepage_layout_mode = forms.ChoiceField(
        label="Enfoque de portada",
        required=False,
        choices=[(key, label) for key, label in HOMEPAGE_LAYOUT_LABELS.items()],
        widget=forms.Select(attrs=_INPUT),
        help_text="Define la prioridad narrativa de la portada del CRM.",
    )
    homepage_layout_density = forms.ChoiceField(
        label="Densidad visual",
        required=False,
        choices=[(key, label) for key, label in HOMEPAGE_DENSITY_LABELS.items()],
        widget=forms.Select(attrs=_INPUT),
        help_text="Ajusta si la portada debe sentirse mas aireada o mas compacta.",
    )
    communication_primary_channel = forms.ChoiceField(
        label="Canal principal",
        required=False,
        choices=[(key, label) for key, label in COMMUNICATION_CHANNEL_LABELS.items()],
        widget=forms.Select(attrs=_INPUT),
        help_text="Canal por defecto para seguimiento visible desde el tenant.",
    )
    communication_broadcast_enabled = forms.BooleanField(
        label="Permitir difusion masiva",
        required=False,
        widget=forms.CheckboxInput(attrs={"class": "h-4 w-4 rounded border-gray-300"}),
        help_text="Marca si este tenant podra usar comunicacion saliente masiva cuando esa capa exista.",
    )
    quote_default_currency = forms.CharField(
        label="Moneda de propuestas",
        required=False,
        widget=forms.TextInput(attrs={**_INPUT, "placeholder": "USD"}),
    )
    quote_validity_days = forms.IntegerField(
        label="Validez de propuestas (dias)",
        required=False,
        min_value=1,
        widget=forms.NumberInput(attrs=_INPUT),
    )
    collection_default_currency = forms.CharField(
        label="Moneda de cobranzas",
        required=False,
        widget=forms.TextInput(attrs={**_INPUT, "placeholder": "USD"}),
    )
    collection_risk_window_days = forms.IntegerField(
        label="Ventana de riesgo (dias)",
        required=False,
        min_value=0,
        widget=forms.NumberInput(attrs=_INPUT),
        help_text="Dias previos al vencimiento en que una cobranza ya debe aparecer en radar.",
    )
    task_presets_json = forms.CharField(
        label="Task presets JSON",
        required=False,
        help_text="Lista JSON para sembrar tareas tipo por tenant. Cada item debe tener key y label.",
        widget=forms.Textarea(attrs={**_JSON_TEXTAREA, "rows": 10}),
    )
    collection_settings_json = forms.CharField(
        label="Collection settings JSON",
        required=False,
        help_text="Objeto JSON para reglas de cobranza, moneda, seguimiento y estados.",
        widget=forms.Textarea(attrs={**_JSON_TEXTAREA, "rows": 8}),
    )
    communication_settings_json = forms.CharField(
        label="Communication settings JSON",
        required=False,
        help_text="Objeto JSON para canal principal, canales habilitados y reglas de consentimiento.",
        widget=forms.Textarea(attrs={**_JSON_TEXTAREA, "rows": 8}),
    )
    quote_settings_json = forms.CharField(
        label="Quote settings JSON",
        required=False,
        help_text="Objeto JSON para moneda, prefijo y validez de propuestas o cotizaciones.",
        widget=forms.Textarea(attrs={**_JSON_TEXTAREA, "rows": 8}),
    )
    homepage_layout_json = forms.CharField(
        label="Homepage layout JSON",
        required=False,
        help_text="Objeto JSON para controlar modo, densidad y metrica hero de la portada.",
        widget=forms.Textarea(attrs={**_JSON_TEXTAREA, "rows": 8}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        profile = self.instance.tenant_config.profile if self.instance.pk else (self.initial.get("profile") or "general")
        defaults = get_operational_defaults(profile)
        if self.instance.pk:
            config = self.instance.tenant_config
            task_presets = resolve_task_presets(config.task_presets)
            collection_settings = resolve_collection_settings(config.collection_settings)
            communication_settings = resolve_communication_settings(config.communication_settings)
            quote_settings = resolve_quote_settings(config.quote_settings)
            homepage_layout = resolve_homepage_layout(config.homepage_layout)
        else:
            task_presets = defaults["task_presets"]
            collection_settings = defaults["collection_settings"]
            communication_settings = defaults["communication_settings"]
            quote_settings = defaults["quote_settings"]
            homepage_layout = defaults["homepage_layout"]

        self.fields["homepage_layout_mode"].initial = homepage_layout["mode"]
        self.fields["homepage_layout_density"].initial = homepage_layout["density"]
        self.fields["communication_primary_channel"].initial = communication_settings["primary_channel"]
        self.fields["communication_broadcast_enabled"].initial = communication_settings["broadcast_enabled"]
        self.fields["quote_default_currency"].initial = quote_settings["default_currency"]
        self.fields["quote_validity_days"].initial = quote_settings["validity_days"]
        self.fields["collection_default_currency"].initial = collection_settings["default_currency"]
        self.fields["collection_risk_window_days"].initial = collection_settings["risk_window_days"]
        self.fields["task_presets_json"].initial = _pretty_json(task_presets)
        self.fields["collection_settings_json"].initial = _pretty_json(collection_settings)
        self.fields["communication_settings_json"].initial = _pretty_json(communication_settings)
        self.fields["quote_settings_json"].initial = _pretty_json(quote_settings)
        self.fields["homepage_layout_json"].initial = _pretty_json(homepage_layout)

    def _current_operational_value(self, key, defaults):
        if self.instance.pk:
            return deepcopy(getattr(self.instance.tenant_config, key))
        return deepcopy(defaults[key])

    def clean_task_presets_json(self):
        parsed = _parse_json(self.cleaned_data.get("task_presets_json"), label="Task presets")
        if parsed is None:
            return []
        if not isinstance(parsed, list):
            raise ValidationError("Task presets debe ser una lista JSON.")
        cleaned = resolve_task_presets(parsed)
        if parsed and not cleaned:
            raise ValidationError("Task presets necesita al menos un item valido con key y label.")
        return cleaned

    def clean_collection_settings_json(self):
        parsed = _parse_json(self.cleaned_data.get("collection_settings_json"), label="Collection settings")
        if parsed is None:
            return {}
        if not isinstance(parsed, dict):
            raise ValidationError("Collection settings debe ser un objeto JSON.")
        return resolve_collection_settings(parsed)

    def clean_communication_settings_json(self):
        parsed = _parse_json(self.cleaned_data.get("communication_settings_json"), label="Communication settings")
        if parsed is None:
            return {}
        if not isinstance(parsed, dict):
            raise ValidationError("Communication settings debe ser un objeto JSON.")
        return resolve_communication_settings(parsed)

    def clean_quote_settings_json(self):
        parsed = _parse_json(self.cleaned_data.get("quote_settings_json"), label="Quote settings")
        if parsed is None:
            return {}
        if not isinstance(parsed, dict):
            raise ValidationError("Quote settings debe ser un objeto JSON.")
        return resolve_quote_settings(parsed)

    def clean_homepage_layout_json(self):
        parsed = _parse_json(self.cleaned_data.get("homepage_layout_json"), label="Homepage layout")
        if parsed is None:
            return {}
        if not isinstance(parsed, dict):
            raise ValidationError("Homepage layout debe ser un objeto JSON.")
        return resolve_homepage_layout(parsed)

    def clean(self):
        cleaned = super().clean()
        profile = cleaned.get("profile")
        if not profile:
            return cleaned

        defaults = get_operational_defaults(profile)
        if cleaned.get("reset_to_profile_defaults"):
            cleaned["task_presets_json"] = defaults["task_presets"]
            cleaned["collection_settings_json"] = defaults["collection_settings"]
            cleaned["communication_settings_json"] = defaults["communication_settings"]
            cleaned["quote_settings_json"] = defaults["quote_settings"]
            cleaned["homepage_layout_json"] = defaults["homepage_layout"]
            return cleaned

        if not self._structured_surface_submitted():
            return cleaned

        operational_controls_changed = any(
            field_name in self.changed_data
            for field_name in (
                "homepage_layout_mode",
                "homepage_layout_density",
                "communication_primary_channel",
                "communication_broadcast_enabled",
                "quote_default_currency",
                "quote_validity_days",
                "collection_default_currency",
                "collection_risk_window_days",
            )
        )
        if not operational_controls_changed and self.instance.pk:
            return cleaned

        collection_settings = cleaned.get("collection_settings_json") or self._current_operational_value("collection_settings", defaults)
        collection_settings = resolve_collection_settings(collection_settings)
        quote_settings = cleaned.get("quote_settings_json") or self._current_operational_value("quote_settings", defaults)
        quote_settings = resolve_quote_settings(quote_settings)
        communication_settings = (
            cleaned.get("communication_settings_json")
            or self._current_operational_value("communication_settings", defaults)
        )
        communication_settings = resolve_communication_settings(communication_settings)
        homepage_layout = cleaned.get("homepage_layout_json") or self._current_operational_value("homepage_layout", defaults)
        homepage_layout = resolve_homepage_layout(homepage_layout)

        collection_currency = str(cleaned.get("collection_default_currency") or "").strip().upper()
        if collection_currency:
            collection_settings["default_currency"] = collection_currency
        if cleaned.get("collection_risk_window_days") is not None:
            collection_settings["risk_window_days"] = cleaned["collection_risk_window_days"]

        quote_currency = str(cleaned.get("quote_default_currency") or "").strip().upper()
        if quote_currency:
            quote_settings["default_currency"] = quote_currency
        if cleaned.get("quote_validity_days") is not None:
            quote_settings["validity_days"] = cleaned["quote_validity_days"]

        primary_channel = str(cleaned.get("communication_primary_channel") or "").strip().lower()
        if primary_channel:
            communication_settings["primary_channel"] = primary_channel
        communication_settings["broadcast_enabled"] = bool(cleaned.get("communication_broadcast_enabled"))
        communication_settings = resolve_communication_settings(communication_settings)

        homepage_mode = str(cleaned.get("homepage_layout_mode") or "").strip().lower()
        homepage_density = str(cleaned.get("homepage_layout_density") or "").strip().lower()
        if homepage_mode:
            homepage_layout["mode"] = homepage_mode
        if homepage_density:
            homepage_layout["density"] = homepage_density

        merged = merge_operational_defaults(
            profile,
            task_presets=cleaned.get("task_presets_json") if "task_presets_json" in cleaned else None,
            collection_settings=collection_settings,
            communication_settings=communication_settings,
            quote_settings=quote_settings,
            homepage_layout=homepage_layout,
        )
        cleaned["task_presets_json"] = merged["task_presets"]
        cleaned["collection_settings_json"] = merged["collection_settings"]
        cleaned["communication_settings_json"] = merged["communication_settings"]
        cleaned["quote_settings_json"] = merged["quote_settings"]
        cleaned["homepage_layout_json"] = merged["homepage_layout"]
        return cleaned

    def save(self, commit=True):
        tenant = super().save(commit=commit)
        if not commit:
            return tenant

        config = tenant.tenant_config
        config.task_presets = self.cleaned_data["task_presets_json"]
        config.collection_settings = self.cleaned_data["collection_settings_json"]
        config.communication_settings = self.cleaned_data["communication_settings_json"]
        config.quote_settings = self.cleaned_data["quote_settings_json"]
        config.homepage_layout = self.cleaned_data["homepage_layout_json"]
        config.save(
            update_fields=[
                "task_presets",
                "collection_settings",
                "communication_settings",
                "quote_settings",
                "homepage_layout",
                "updated_at",
            ]
        )
        return tenant

