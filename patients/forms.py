from django import forms

from .models import Patient


_INPUT = {"class": "w-full rounded-lg border px-3 py-2"}


class PatientForm(forms.ModelForm):
    class Meta:
        model = Patient
        fields = [
            "mrn",
            "document_type",
            "document_number",
            "first_name",
            "last_name",
            "birth_date",
            "sex",
            "source",
            "phone",
            "email",
            "address",
            "responsible_party_name",
            "responsible_party_phone",
            "emergency_contact_name",
            "emergency_contact_phone",
            "insurance_provider",
            "insurance_plan",
            "notes",
            "marketing_opt_in",
            "is_active",
        ]
        widgets = {
            "mrn": forms.TextInput(attrs=_INPUT),
            "document_type": forms.Select(attrs=_INPUT),
            "document_number": forms.TextInput(attrs=_INPUT),
            "first_name": forms.TextInput(attrs=_INPUT),
            "last_name": forms.TextInput(attrs=_INPUT),
            "birth_date": forms.DateInput(attrs={**_INPUT, "type": "date"}),
            "sex": forms.Select(attrs=_INPUT),
            "source": forms.Select(attrs=_INPUT),
            "phone": forms.TextInput(attrs=_INPUT),
            "email": forms.EmailInput(attrs=_INPUT),
            "address": forms.TextInput(attrs=_INPUT),
            "responsible_party_name": forms.TextInput(attrs=_INPUT),
            "responsible_party_phone": forms.TextInput(attrs=_INPUT),
            "emergency_contact_name": forms.TextInput(attrs=_INPUT),
            "emergency_contact_phone": forms.TextInput(attrs=_INPUT),
            "insurance_provider": forms.TextInput(attrs=_INPUT),
            "insurance_plan": forms.TextInput(attrs=_INPUT),
            "notes": forms.Textarea(attrs={**_INPUT, "rows": 3}),
            "marketing_opt_in": forms.CheckboxInput(attrs={"class": "h-4 w-4 rounded border-gray-300"}),
            "is_active": forms.CheckboxInput(attrs={"class": "h-4 w-4 rounded border-gray-300"}),
        }
