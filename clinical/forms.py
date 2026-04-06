from django import forms

from tenants.models import TenantMembership
from tenants.utils import get_tenant_user_queryset

from .models import (
    ClinicalDiagnosis,
    ClinicalDocument,
    ClinicalEncounter,
    ClinicalOrder,
    Prescription,
)


_INPUT = {"class": "w-full rounded-lg border px-3 py-2"}


class ClinicalEncounterForm(forms.ModelForm):
    class Meta:
        model = ClinicalEncounter
        fields = [
            "patient",
            "appointment",
            "provider",
            "encounter_date",
            "encounter_type",
            "status",
            "chief_complaint",
            "vitals_summary",
            "subjective",
            "objective",
            "assessment",
            "plan",
        ]
        widgets = {
            "patient": forms.Select(attrs=_INPUT),
            "appointment": forms.Select(attrs=_INPUT),
            "provider": forms.Select(attrs=_INPUT),
            "encounter_date": forms.DateTimeInput(
                attrs={**_INPUT, "type": "datetime-local"},
                format="%Y-%m-%dT%H:%M",
            ),
            "encounter_type": forms.Select(attrs=_INPUT),
            "status": forms.Select(attrs=_INPUT),
            "chief_complaint": forms.TextInput(attrs=_INPUT),
            "vitals_summary": forms.TextInput(attrs=_INPUT),
            "subjective": forms.Textarea(attrs={**_INPUT, "rows": 4}),
            "objective": forms.Textarea(attrs={**_INPUT, "rows": 4}),
            "assessment": forms.Textarea(attrs={**_INPUT, "rows": 4}),
            "plan": forms.Textarea(attrs={**_INPUT, "rows": 4}),
        }

    def __init__(self, *args, tenant=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["encounter_date"].input_formats = ["%Y-%m-%dT%H:%M"]
        self.fields["patient"].queryset = self.fields["patient"].queryset.order_by("last_name", "first_name")
        self.fields["appointment"].queryset = self.fields["appointment"].queryset.select_related("patient").order_by(
            "-scheduled_at"
        )
        self.fields["provider"].required = False
        if tenant is not None:
            self.fields["provider"].queryset = get_tenant_user_queryset(
                tenant,
                roles=[TenantMembership.ROLE_DOCTOR],
            )


class ClinicalDiagnosisForm(forms.ModelForm):
    class Meta:
        model = ClinicalDiagnosis
        fields = ["diagnosis_type", "code", "description", "notes"]
        widgets = {
            "diagnosis_type": forms.Select(attrs=_INPUT),
            "code": forms.TextInput(attrs=_INPUT),
            "description": forms.TextInput(attrs=_INPUT),
            "notes": forms.Textarea(attrs={**_INPUT, "rows": 3}),
        }


class ClinicalOrderForm(forms.ModelForm):
    class Meta:
        model = ClinicalOrder
        fields = ["order_type", "status", "description", "instructions", "scheduled_for", "result_summary"]
        widgets = {
            "order_type": forms.Select(attrs=_INPUT),
            "status": forms.Select(attrs=_INPUT),
            "description": forms.TextInput(attrs=_INPUT),
            "instructions": forms.Textarea(attrs={**_INPUT, "rows": 3}),
            "scheduled_for": forms.DateTimeInput(
                attrs={**_INPUT, "type": "datetime-local"},
                format="%Y-%m-%dT%H:%M",
            ),
            "result_summary": forms.Textarea(attrs={**_INPUT, "rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["scheduled_for"].input_formats = ["%Y-%m-%dT%H:%M"]
        self.fields["scheduled_for"].required = False


class PrescriptionForm(forms.ModelForm):
    class Meta:
        model = Prescription
        fields = [
            "medication_name",
            "presentation",
            "route",
            "dosage",
            "frequency",
            "duration_days",
            "instructions",
            "status",
        ]
        widgets = {
            "medication_name": forms.TextInput(attrs=_INPUT),
            "presentation": forms.TextInput(attrs=_INPUT),
            "route": forms.TextInput(attrs=_INPUT),
            "dosage": forms.TextInput(attrs=_INPUT),
            "frequency": forms.TextInput(attrs=_INPUT),
            "duration_days": forms.NumberInput(attrs=_INPUT),
            "instructions": forms.Textarea(attrs={**_INPUT, "rows": 3}),
            "status": forms.Select(attrs=_INPUT),
        }


class ClinicalDocumentForm(forms.ModelForm):
    class Meta:
        model = ClinicalDocument
        fields = ["patient", "title", "document_type", "notes", "file"]
        widgets = {
            "patient": forms.Select(attrs=_INPUT),
            "title": forms.TextInput(attrs=_INPUT),
            "document_type": forms.Select(attrs=_INPUT),
            "notes": forms.Textarea(attrs={**_INPUT, "rows": 3}),
            "file": forms.ClearableFileInput(attrs=_INPUT),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["patient"].queryset = self.fields["patient"].queryset.order_by("last_name", "first_name")
