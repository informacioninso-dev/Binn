from django import forms
from django.utils import timezone

from .models import (
    AutomationRule,
    CommissionScheme,
    IntegrationConnection,
    Location,
)


_INPUT = {"class": "w-full rounded-lg border px-3 py-2"}


class LocationForm(forms.ModelForm):
    def clean_code(self):
        code = (self.cleaned_data.get("code") or "").strip().upper().replace(" ", "-")
        if not code:
            raise forms.ValidationError("El codigo es obligatorio.")
        return code

    def clean_name(self):
        name = (self.cleaned_data.get("name") or "").strip()
        if not name:
            raise forms.ValidationError("El nombre es obligatorio.")
        return name

    class Meta:
        model = Location
        fields = ["code", "name", "address", "phone", "is_active"]
        widgets = {
            "code": forms.TextInput(attrs=_INPUT),
            "name": forms.TextInput(attrs=_INPUT),
            "address": forms.TextInput(attrs=_INPUT),
            "phone": forms.TextInput(attrs=_INPUT),
            "is_active": forms.CheckboxInput(attrs={"class": "h-4 w-4 rounded border-gray-300"}),
        }


class CommissionSchemeForm(forms.ModelForm):
    class Meta:
        model = CommissionScheme
        fields = ["name", "applies_to_role", "basis", "percentage", "flat_amount", "is_active", "notes"]
        widgets = {
            "name": forms.TextInput(attrs=_INPUT),
            "applies_to_role": forms.TextInput(attrs={**_INPUT, "placeholder": "doctor, assistant, cashier..."}),
            "basis": forms.Select(attrs=_INPUT),
            "percentage": forms.NumberInput(attrs={**_INPUT, "step": "0.01"}),
            "flat_amount": forms.NumberInput(attrs={**_INPUT, "step": "0.01"}),
            "is_active": forms.CheckboxInput(attrs={"class": "h-4 w-4 rounded border-gray-300"}),
            "notes": forms.Textarea(attrs={**_INPUT, "rows": 3}),
        }


class CommissionGenerationForm(forms.Form):
    period_start = forms.DateField(
        label="Periodo desde",
        widget=forms.DateInput(attrs={**_INPUT, "type": "date"}),
    )
    period_end = forms.DateField(
        label="Periodo hasta",
        widget=forms.DateInput(attrs={**_INPUT, "type": "date"}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        today = timezone.localdate()
        self.fields["period_start"].initial = today.replace(day=1)
        self.fields["period_end"].initial = today

    def clean(self):
        cleaned = super().clean()
        start = cleaned.get("period_start")
        end = cleaned.get("period_end")
        if start and end and end < start:
            self.add_error("period_end", "La fecha final no puede ser menor a la inicial.")
        return cleaned


class AutomationRuleForm(forms.ModelForm):
    class Meta:
        model = AutomationRule
        fields = ["name", "trigger", "channel", "target_role", "offset_minutes", "template_text", "is_active"]
        widgets = {
            "name": forms.TextInput(attrs=_INPUT),
            "trigger": forms.Select(attrs=_INPUT),
            "channel": forms.Select(attrs=_INPUT),
            "target_role": forms.TextInput(attrs={**_INPUT, "placeholder": "doctor, reception, cashier..."}),
            "offset_minutes": forms.NumberInput(attrs=_INPUT),
            "template_text": forms.Textarea(attrs={**_INPUT, "rows": 4}),
            "is_active": forms.CheckboxInput(attrs={"class": "h-4 w-4 rounded border-gray-300"}),
        }


class IntegrationConnectionForm(forms.ModelForm):
    def clean_secret_hint(self):
        return (self.cleaned_data.get("secret_hint") or "").strip()

    class Meta:
        model = IntegrationConnection
        fields = ["name", "provider", "status", "endpoint", "secret_hint", "notes", "is_active"]
        widgets = {
            "name": forms.TextInput(attrs=_INPUT),
            "provider": forms.Select(attrs=_INPUT),
            "status": forms.Select(attrs=_INPUT),
            "endpoint": forms.TextInput(attrs=_INPUT),
            "secret_hint": forms.TextInput(attrs={**_INPUT, "placeholder": "ultimos 4 o alias seguro"}),
            "notes": forms.Textarea(attrs={**_INPUT, "rows": 3}),
            "is_active": forms.CheckboxInput(attrs={"class": "h-4 w-4 rounded border-gray-300"}),
        }
