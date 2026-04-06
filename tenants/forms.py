import re

from django import forms
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import AuthenticationForm
from django.core.exceptions import ValidationError

from .models import Client, TenantMembership


_SCHEMA_RE = re.compile(r"^[a-z][a-z0-9_]{2,62}$")
_SUBDOMAIN_RE = re.compile(r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$")

_INPUT = {"class": "w-full rounded-lg border px-3 py-2"}


def _case_insensitive_username_count(username: str) -> int:
    user_model = get_user_model()
    return user_model._default_manager.filter(username__iexact=username).count()


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
    class Meta:
        model = Client
        fields = ("name", "plan", "is_active")
        widgets = {
            "name": forms.TextInput(attrs=_INPUT),
            "plan": forms.Select(attrs=_INPUT),
            "is_active": forms.CheckboxInput(attrs={"class": "h-4 w-4 rounded border-gray-300"}),
        }


class TenantListFilterForm(forms.Form):
    STATUS_ALL = ""
    STATUS_ACTIVE = "active"
    STATUS_INACTIVE = "inactive"
    STATUS_CHOICES = [
        (STATUS_ALL, "Todos los estados"),
        (STATUS_ACTIVE, "Solo activas"),
        (STATUS_INACTIVE, "Solo inactivas"),
    ]

    ALERT_ALL = ""
    ALERT_OK = "ok"
    ALERT_NEEDS_ATTENTION = "attention"
    ALERT_CHOICES = [
        (ALERT_ALL, "Todas"),
        (ALERT_OK, "Sin alertas"),
        (ALERT_NEEDS_ATTENTION, "Con alertas"),
    ]

    q = forms.CharField(
        required=False,
        label="Buscar",
        widget=forms.TextInput(attrs={**_INPUT, "placeholder": "Clinica, schema o dominio"}),
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
    alert_state = forms.ChoiceField(
        required=False,
        label="Alertas",
        choices=ALERT_CHOICES,
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
        initial=TenantMembership.ROLE_ASSISTANT,
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
                "class": "w-full rounded-lg border px-3 py-2 focus:outline-none focus:ring-2 focus:ring-blue-500",
            }
        ),
    )
    password = forms.CharField(
        label="Contrasena",
        strip=False,
        widget=forms.PasswordInput(
            attrs={
                "class": "w-full rounded-lg border px-3 py-2 pr-10 focus:outline-none focus:ring-2 focus:ring-blue-500",
            }
        ),
    )
