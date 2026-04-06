from django import forms

from tenants.models import TenantMembership
from tenants.utils import get_tenant_user_queryset

from .models import Lead


_INPUT = {"class": "w-full rounded-lg border px-3 py-2"}


class LeadForm(forms.ModelForm):
    class Meta:
        model = Lead
        fields = [
            "full_name",
            "phone",
            "email",
            "source",
            "stage",
            "interested_service",
            "assigned_to",
            "next_contact_at",
            "notes",
            "is_active",
        ]
        widgets = {
            "full_name": forms.TextInput(attrs=_INPUT),
            "phone": forms.TextInput(attrs=_INPUT),
            "email": forms.EmailInput(attrs=_INPUT),
            "source": forms.Select(attrs=_INPUT),
            "stage": forms.Select(attrs=_INPUT),
            "interested_service": forms.TextInput(attrs=_INPUT),
            "assigned_to": forms.Select(attrs=_INPUT),
            "next_contact_at": forms.DateTimeInput(
                attrs={**_INPUT, "type": "datetime-local"},
                format="%Y-%m-%dT%H:%M",
            ),
            "notes": forms.Textarea(attrs={**_INPUT, "rows": 4}),
            "is_active": forms.CheckboxInput(attrs={"class": "h-4 w-4 rounded border-gray-300"}),
        }

    def __init__(self, *args, tenant=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["next_contact_at"].input_formats = ["%Y-%m-%dT%H:%M"]
        if tenant is not None:
            self.fields["assigned_to"].queryset = get_tenant_user_queryset(
                tenant,
                roles=[
                    TenantMembership.ROLE_RECEPTION,
                    TenantMembership.ROLE_ASSISTANT,
                    TenantMembership.ROLE_DOCTOR,
                ],
            )
        self.fields["assigned_to"].required = False
