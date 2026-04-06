from django import forms

from tenants.models import TenantMembership
from tenants.utils import get_tenant_user_queryset

from .models import Appointment


_INPUT = {"class": "w-full rounded-lg border px-3 py-2"}


class AppointmentForm(forms.ModelForm):
    class Meta:
        model = Appointment
        fields = [
            "patient",
            "location",
            "provider",
            "scheduled_at",
            "duration_minutes",
            "appointment_type",
            "channel",
            "status",
            "reason",
            "notes",
            "front_desk_notes",
        ]
        widgets = {
            "patient": forms.Select(attrs=_INPUT),
            "location": forms.Select(attrs=_INPUT),
            "provider": forms.Select(attrs=_INPUT),
            "scheduled_at": forms.DateTimeInput(
                attrs={**_INPUT, "type": "datetime-local"},
                format="%Y-%m-%dT%H:%M",
            ),
            "duration_minutes": forms.NumberInput(attrs=_INPUT),
            "appointment_type": forms.Select(attrs=_INPUT),
            "channel": forms.Select(attrs=_INPUT),
            "status": forms.Select(attrs=_INPUT),
            "reason": forms.TextInput(attrs=_INPUT),
            "notes": forms.Textarea(attrs={**_INPUT, "rows": 3}),
            "front_desk_notes": forms.Textarea(attrs={**_INPUT, "rows": 2}),
        }

    def __init__(self, *args, tenant=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["scheduled_at"].input_formats = ["%Y-%m-%dT%H:%M"]
        if tenant is not None:
            self.fields["patient"].queryset = self.fields["patient"].queryset.order_by("last_name", "first_name")
            self.fields["location"].queryset = self.fields["location"].queryset.filter(is_active=True).order_by("name")
            self.fields["provider"].queryset = get_tenant_user_queryset(
                tenant,
                roles=[TenantMembership.ROLE_DOCTOR],
            )
        self.fields["location"].required = False
        self.fields["provider"].required = False
