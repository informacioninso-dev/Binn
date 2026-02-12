# partners/models.py
from django.db import models
from core.models import AuditModel 
from django import forms
from .models import Partner



class IdentificationType(models.TextChoices):
    RUC = "RUC", "RUC"
    DNI = "DNI", "Cédula"
    PASSPORT = "PASSPORT", "Pasaporte"
    OTHER = "OTHER", "Otro"


class CompanyType(models.TextChoices):
    COMPANY = "COMPANY", "Empresa"
    PERSON = "PERSON", "Persona natural"


class PartnerCategory(models.TextChoices):
    A = "A", "Categoría A"
    B = "B", "Categoría B"
    C = "C", "Categoría C"
    OTHER = "OTHER", "Otra"


class RetentionProfile(models.TextChoices):
    NONE = "NONE", "No emite retención"
    AGENT = "AGENT", "Agente de retención general"
    RENT = "RENT", "Retención en renta"
    VAT = "VAT", "Retención en IVA"
    RENT_VAT = "RENT_VAT", "Retención en renta e IVA"



class PartnerForm(forms.ModelForm):
    """
    Formulario principal para crear / editar socios (clientes/proveedores).
    """

    class Meta:
        model = Partner
        fields = [
            # Identificación básica
            "code",
            # "alt_code",  # Oculto - se puede usar en admin si se necesita
            "identification_type",
            "identification",
            "trade_name",
            "legal_name",
            "company_type",
            "category",

            # Flags de uso
            "is_customer",
            "is_supplier",
            "is_public_entity",

            # Lista de precios
            "price_list",

            # Crédito
            "credit_limit",
            "credit_available",
            "credit_used",
            "credit_terms_days",
            "retention_profile",

            # Ubicación
            "branch_name",
            "address",
            "city",
            "province",
            "country",

            # Contacto
            "contact_name",
            "contact_email",
            "contact_phone",
            "website",

            # Calificación ISO 13485
            "is_qualified_supplier",
            "qualification_level",
            "qualification_date",
            "qualification_notes",

            # Otros
            "notes",
            "is_active",
        ]

        widgets = {
            "code": forms.TextInput(attrs={"class": "w-full rounded-lg border px-3 py-2 text-sm"}),
            "alt_code": forms.TextInput(attrs={"class": "w-full rounded-lg border px-3 py-2 text-sm"}),
            "identification_type": forms.Select(attrs={"class": "w-full rounded-lg border px-3 py-2 text-sm"}),
            "identification": forms.TextInput(attrs={"class": "w-full rounded-lg border px-3 py-2 text-sm"}),
            "trade_name": forms.TextInput(attrs={"class": "w-full rounded-lg border px-3 py-2 text-sm"}),
            "legal_name": forms.TextInput(attrs={"class": "w-full rounded-lg border px-3 py-2 text-sm"}),
            "company_type": forms.Select(attrs={"class": "w-full rounded-lg border px-3 py-2 text-sm"}),
            "category": forms.Select(attrs={"class": "w-full rounded-lg border px-3 py-2 text-sm"}),

            "is_customer": forms.CheckboxInput(attrs={"class": "rounded"}),
            "is_supplier": forms.CheckboxInput(attrs={"class": "rounded"}),
            "is_public_entity": forms.CheckboxInput(attrs={"class": "rounded"}),

            "price_list": forms.Select(attrs={"class": "w-full rounded-lg border px-3 py-2 text-sm"}),

            "credit_limit": forms.NumberInput(attrs={"class": "w-full rounded-lg border px-3 py-2 text-sm", "step": "0.01"}),
            "credit_available": forms.NumberInput(attrs={"class": "w-full rounded-lg border px-3 py-2 text-sm", "step": "0.01"}),
            "credit_used": forms.NumberInput(attrs={"class": "w-full rounded-lg border px-3 py-2 text-sm", "step": "0.01"}),
            "credit_terms_days": forms.NumberInput(attrs={"class": "w-full rounded-lg border px-3 py-2 text-sm"}),

            "retention_profile": forms.Select(attrs={"class": "w-full rounded-lg border px-3 py-2 text-sm"}),

            "branch_name": forms.TextInput(attrs={"class": "w-full rounded-lg border px-3 py-2 text-sm"}),
            "address": forms.TextInput(attrs={"class": "w-full rounded-lg border px-3 py-2 text-sm"}),
            "city": forms.TextInput(attrs={"class": "w-full rounded-lg border px-3 py-2 text-sm"}),
            "province": forms.TextInput(attrs={"class": "w-full rounded-lg border px-3 py-2 text-sm"}),
            "country": forms.TextInput(attrs={"class": "w-full rounded-lg border px-3 py-2 text-sm"}),

            "contact_name": forms.TextInput(attrs={"class": "w-full rounded-lg border px-3 py-2 text-sm"}),
            "contact_email": forms.EmailInput(attrs={"class": "w-full rounded-lg border px-3 py-2 text-sm"}),
            "contact_phone": forms.TextInput(attrs={"class": "w-full rounded-lg border px-3 py-2 text-sm"}),
            "website": forms.URLInput(attrs={"class": "w-full rounded-lg border px-3 py-2 text-sm"}),

            "is_qualified_supplier": forms.CheckboxInput(attrs={"class": "rounded"}),
            "qualification_level": forms.TextInput(attrs={"class": "w-full rounded-lg border px-3 py-2 text-sm"}),
            "qualification_date": forms.DateInput(attrs={"class": "w-full rounded-lg border px-3 py-2 text-sm", "type": "date"}),
            "qualification_notes": forms.Textarea(attrs={"class": "w-full rounded-lg border px-3 py-2 text-sm", "rows": 3}),

            "notes": forms.Textarea(attrs={"class": "w-full rounded-lg border px-3 py-2 text-sm", "rows": 3}),
            "is_active": forms.CheckboxInput(attrs={"class": "rounded"}),
        }
