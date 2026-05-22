from __future__ import annotations

from django import forms
from django.contrib.auth import get_user_model
from django.utils.text import slugify

from tenants.models import Client

from .models import BillingAccount, CorporateGroup, GroupMembership, GroupTenantAccess, GroupTenantLink, OperationalAccessGrant


INPUT = {"class": "binn-input w-full rounded-lg border px-3 py-2"}
TEXTAREA = {"class": "binn-input w-full rounded-lg border px-3 py-2", "rows": 4}


class CorporateGroupForm(forms.ModelForm):
    slug = forms.SlugField(
        required=False,
        help_text="Opcional. Si se deja vacio, se genera automaticamente desde el nombre.",
        widget=forms.TextInput(attrs=INPUT),
    )

    class Meta:
        model = CorporateGroup
        fields = ("name", "slug", "status", "operating_model", "consolidation_mode", "owner", "notes")
        widgets = {
            "name": forms.TextInput(attrs=INPUT),
            "status": forms.Select(attrs=INPUT),
            "operating_model": forms.Select(attrs=INPUT),
            "consolidation_mode": forms.Select(attrs=INPUT),
            "owner": forms.Select(attrs=INPUT),
            "notes": forms.Textarea(attrs=TEXTAREA),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        user_model = get_user_model()
        self.fields["owner"].queryset = user_model._default_manager.filter(is_active=True).order_by("username")
        self.fields["notes"].help_text = "Notas operativas y decisiones de gobierno para este holding."

    def clean_slug(self):
        slug = (self.cleaned_data.get("slug") or "").strip().lower()
        if slug:
            return slug
        name = (self.cleaned_data.get("name") or "").strip()
        return slugify(name)[:180]


class BillingAccountForm(forms.ModelForm):
    class Meta:
        model = BillingAccount
        fields = (
            "billing_name",
            "billing_email",
            "tax_id",
            "status",
            "external_reference",
            "seat_limit",
            "manager_limit",
            "storage_limit_mb",
            "monthly_amount",
            "currency",
            "renews_on",
            "enforce_limits",
            "notes",
        )
        widgets = {
            "billing_name": forms.TextInput(attrs=INPUT),
            "billing_email": forms.EmailInput(attrs=INPUT),
            "tax_id": forms.TextInput(attrs=INPUT),
            "status": forms.Select(attrs=INPUT),
            "external_reference": forms.TextInput(attrs=INPUT),
            "seat_limit": forms.NumberInput(attrs=INPUT),
            "manager_limit": forms.NumberInput(attrs=INPUT),
            "storage_limit_mb": forms.NumberInput(attrs=INPUT),
            "monthly_amount": forms.NumberInput(attrs={**INPUT, "step": "0.01", "min": "0"}),
            "currency": forms.TextInput(attrs=INPUT),
            "renews_on": forms.DateInput(attrs={**INPUT, "type": "date"}),
            "enforce_limits": forms.CheckboxInput(attrs={"class": "h-4 w-4 rounded border-gray-300"}),
            "notes": forms.Textarea(attrs=TEXTAREA),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["seat_limit"].help_text = "Cantidad total de miembros activos del holding cubierta por licencias."
        self.fields["manager_limit"].help_text = "Cuantos responsables pueden quedar asignados a islas/empresas del grupo."
        self.fields["storage_limit_mb"].help_text = "Pool total de almacenamiento operativo del holding."
        self.fields["monthly_amount"].help_text = "Referencia comercial del fee mensual del holding."
        self.fields["enforce_limits"].help_text = "Si se apaga, los limites quedan como referencia y no como semaforo contractual."


class GroupMembershipAssignForm(forms.Form):
    username = forms.CharField(
        label="Usuario global",
        max_length=150,
        widget=forms.TextInput(attrs={**INPUT, "placeholder": "usuario o correo principal"}),
    )
    role = forms.ChoiceField(label="Rol de grupo", choices=GroupMembership.ROLE_CHOICES, widget=forms.Select(attrs=INPUT))
    is_active = forms.BooleanField(
        label="Membresia activa",
        required=False,
        initial=True,
        widget=forms.CheckboxInput(attrs={"class": "h-4 w-4 rounded border-gray-300"}),
    )

    def __init__(self, *args, group=None, **kwargs):
        self.group = group
        self.user = None
        super().__init__(*args, **kwargs)

    def clean_username(self):
        raw_value = (self.cleaned_data.get("username") or "").strip()
        if not raw_value:
            raise forms.ValidationError("Ingresa un usuario global.")

        user_model = get_user_model()
        users = user_model._default_manager.filter(username__iexact=raw_value).order_by("id")
        if not users.exists():
            users = user_model._default_manager.filter(email__iexact=raw_value).order_by("id")
        count = users.count()
        if count == 0:
            raise forms.ValidationError("El usuario global no existe.")
        if count > 1:
            raise forms.ValidationError("Hay varios usuarios globales que coinciden con ese identificador.")
        self.user = users.first()
        return raw_value


class GroupTenantLinkForm(forms.ModelForm):
    class Meta:
        model = GroupTenantLink
        fields = ("tenant", "consolidation_mode", "is_primary", "is_active")
        widgets = {
            "tenant": forms.Select(attrs=INPUT),
            "consolidation_mode": forms.Select(attrs=INPUT),
            "is_primary": forms.CheckboxInput(attrs={"class": "h-4 w-4 rounded border-gray-300"}),
            "is_active": forms.CheckboxInput(attrs={"class": "h-4 w-4 rounded border-gray-300"}),
        }

    def __init__(self, *args, group=None, **kwargs):
        self.group = group
        super().__init__(*args, **kwargs)
        self.fields["tenant"].queryset = Client.objects.filter(is_active=True).order_by("name")
        self.fields["tenant"].help_text = "Si eliges una empresa ya vinculada, se actualiza su politica actual."


class GroupTenantAccessAssignForm(forms.Form):
    username = forms.CharField(
        label="Usuario del grupo",
        max_length=150,
        widget=forms.TextInput(attrs={**INPUT, "placeholder": "usuario o correo del miembro"}),
    )
    tenant = forms.ChoiceField(label="Empresa del grupo", choices=(), widget=forms.Select(attrs=INPUT))
    role = forms.ChoiceField(label="Rol en la empresa", choices=GroupTenantAccess.ROLE_CHOICES, widget=forms.Select(attrs=INPUT))
    is_active = forms.BooleanField(
        label="Acceso activo",
        required=False,
        initial=True,
        widget=forms.CheckboxInput(attrs={"class": "h-4 w-4 rounded border-gray-300"}),
    )

    def __init__(self, *args, group=None, **kwargs):
        self.group = group
        self.user = None
        self.group_membership = None
        self.link_by_tenant_id = {}
        super().__init__(*args, **kwargs)
        choices = []
        if group is not None:
            links = (
                group.tenant_links.select_related("tenant")
                .filter(is_active=True, tenant__is_active=True)
                .order_by("tenant__name")
            )
            for link in links:
                self.link_by_tenant_id[str(link.tenant_id)] = link
                choices.append((str(link.tenant_id), f"{link.tenant.name} ({link.get_consolidation_mode_display()})"))
        self.fields["tenant"].choices = choices
        self.fields["tenant"].help_text = "Solo las empresas con detalle total podran abrirse en drill-down."

    def clean_username(self):
        raw_value = (self.cleaned_data.get("username") or "").strip()
        if not raw_value:
            raise forms.ValidationError("Ingresa un usuario del grupo.")
        user_model = get_user_model()
        users = user_model._default_manager.filter(username__iexact=raw_value).order_by("id")
        if not users.exists():
            users = user_model._default_manager.filter(email__iexact=raw_value).order_by("id")
        if users.count() == 0:
            raise forms.ValidationError("El usuario global no existe.")
        if users.count() > 1:
            raise forms.ValidationError("Hay varios usuarios globales que coinciden con ese identificador.")
        self.user = users.first()
        if self.group is not None:
            self.group_membership = (
                GroupMembership.objects.select_related("group", "user")
                .filter(group=self.group, user=self.user, is_active=True)
                .first()
            )
            if self.group_membership is None:
                raise forms.ValidationError("Ese usuario no tiene una membresia activa en este holding.")
        return raw_value

    def clean_tenant(self):
        tenant_id = str(self.cleaned_data.get("tenant") or "")
        link = self.link_by_tenant_id.get(tenant_id)
        if link is None:
            raise forms.ValidationError("Selecciona una empresa valida del holding.")
        self.link = link
        return tenant_id


class OperationalAccessRequestForm(forms.Form):
    tenant = forms.ChoiceField(label="Empresa objetivo", choices=(), widget=forms.Select(attrs=INPUT))
    justification = forms.CharField(
        label="Justificacion",
        required=False,
        widget=forms.Textarea(
            attrs={
                **TEXTAREA,
                "rows": 5,
                "placeholder": "Explica por que el holding necesita ver detalle operativo de esta empresa.",
            }
        ),
    )
    expires_at = forms.DateTimeField(
        label="Expira en",
        required=False,
        widget=forms.DateTimeInput(attrs={**INPUT, "type": "datetime-local"}, format="%Y-%m-%dT%H:%M"),
        input_formats=["%Y-%m-%dT%H:%M"],
        help_text="Opcional. Si se define, el acceso se revoca solo al vencer.",
    )

    def __init__(self, *args, group=None, **kwargs):
        self.group = group
        self.link_by_tenant_id = {}
        super().__init__(*args, **kwargs)
        choices = []
        if group is not None:
            links = (
                group.tenant_links.select_related("tenant")
                .filter(is_active=True, tenant__is_active=True)
                .order_by("tenant__name")
            )
            for link in links:
                self.link_by_tenant_id[str(link.tenant_id)] = link
                choices.append((str(link.tenant_id), f"{link.tenant.name} ({link.get_consolidation_mode_display()})"))
        self.fields["tenant"].choices = choices

    def clean_tenant(self):
        tenant_id = str(self.cleaned_data.get("tenant") or "")
        link = self.link_by_tenant_id.get(tenant_id)
        if link is None:
            raise forms.ValidationError("Selecciona una empresa valida del holding.")
        if link.effective_mode != CorporateGroup.MODE_FULL:
            raise forms.ValidationError("Solo puedes solicitar acceso operativo a empresas con modo detalle total.")
        self.link = link
        return tenant_id


class OperationalAccessGrantDecisionForm(forms.Form):
    status = forms.ChoiceField(
        label="Decision",
        choices=[
            (OperationalAccessGrant.STATUS_APPROVED, "Aprobar"),
            (OperationalAccessGrant.STATUS_REJECTED, "Rechazar"),
            (OperationalAccessGrant.STATUS_REVOKED, "Revocar"),
        ],
        widget=forms.Select(attrs=INPUT),
    )
    decision_note = forms.CharField(
        label="Nota de decision",
        required=False,
        widget=forms.Textarea(attrs={**TEXTAREA, "rows": 3}),
    )
    expires_at = forms.DateTimeField(
        label="Expira en",
        required=False,
        widget=forms.DateTimeInput(attrs={**INPUT, "type": "datetime-local"}, format="%Y-%m-%dT%H:%M"),
        input_formats=["%Y-%m-%dT%H:%M"],
    )
