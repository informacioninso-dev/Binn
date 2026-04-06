from decimal import Decimal

from django import forms

from .models import CashTransaction, CoverageAgreement, Invoice


_INPUT = {"class": "w-full rounded-lg border px-3 py-2"}


class CoverageAgreementForm(forms.ModelForm):
    class Meta:
        model = CoverageAgreement
        fields = [
            "code",
            "name",
            "payer_type",
            "contact_name",
            "phone",
            "email",
            "default_discount_percent",
            "default_credit_days",
            "notes",
            "is_active",
        ]
        widgets = {
            "code": forms.TextInput(attrs=_INPUT),
            "name": forms.TextInput(attrs=_INPUT),
            "payer_type": forms.Select(attrs=_INPUT),
            "contact_name": forms.TextInput(attrs=_INPUT),
            "phone": forms.TextInput(attrs=_INPUT),
            "email": forms.EmailInput(attrs=_INPUT),
            "default_discount_percent": forms.NumberInput(attrs={**_INPUT, "step": "0.01"}),
            "default_credit_days": forms.NumberInput(attrs=_INPUT),
            "notes": forms.Textarea(attrs={**_INPUT, "rows": 3}),
            "is_active": forms.CheckboxInput(attrs={"class": "h-4 w-4 rounded border-gray-300"}),
        }


class InvoiceForm(forms.ModelForm):
    class Meta:
        model = Invoice
        fields = [
            "invoice_number",
            "patient",
            "location",
            "appointment",
            "coverage_agreement",
            "issued_at",
            "due_date",
            "status",
            "subtotal",
            "discount_amount",
            "notes",
        ]
        widgets = {
            "invoice_number": forms.TextInput(attrs=_INPUT),
            "patient": forms.Select(attrs=_INPUT),
            "location": forms.Select(attrs=_INPUT),
            "appointment": forms.Select(attrs=_INPUT),
            "coverage_agreement": forms.Select(attrs=_INPUT),
            "issued_at": forms.DateTimeInput(
                attrs={**_INPUT, "type": "datetime-local"},
                format="%Y-%m-%dT%H:%M",
            ),
            "due_date": forms.DateInput(attrs={**_INPUT, "type": "date"}),
            "status": forms.Select(attrs=_INPUT),
            "subtotal": forms.NumberInput(attrs={**_INPUT, "step": "0.01"}),
            "discount_amount": forms.NumberInput(attrs={**_INPUT, "step": "0.01"}),
            "notes": forms.Textarea(attrs={**_INPUT, "rows": 3}),
        }

    def __init__(self, *args, tenant=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["issued_at"].input_formats = ["%Y-%m-%dT%H:%M"]
        self.fields["patient"].queryset = self.fields["patient"].queryset.order_by("last_name", "first_name")
        self.fields["location"].queryset = self.fields["location"].queryset.filter(is_active=True).order_by("name")
        self.fields["appointment"].queryset = self.fields["appointment"].queryset.select_related("patient").order_by(
            "-scheduled_at"
        )
        self.fields["coverage_agreement"].queryset = self.fields["coverage_agreement"].queryset.filter(
            is_active=True
        ).order_by("name")
        self.fields["appointment"].required = False
        self.fields["location"].required = False
        self.fields["coverage_agreement"].required = False

    def clean(self):
        cleaned = super().clean()
        subtotal = cleaned.get("subtotal") or Decimal("0.00")
        discount_amount = cleaned.get("discount_amount") or Decimal("0.00")
        appointment = cleaned.get("appointment")
        location = cleaned.get("location")
        if subtotal < Decimal("0.00"):
            self.add_error("subtotal", "El subtotal no puede ser negativo.")
        if discount_amount < Decimal("0.00"):
            self.add_error("discount_amount", "El descuento no puede ser negativo.")
        if discount_amount > subtotal:
            self.add_error("discount_amount", "El descuento no puede ser mayor al subtotal.")
        if appointment is not None and location is None and appointment.location_id:
            cleaned["location"] = appointment.location
            self.cleaned_data["location"] = appointment.location
        return cleaned


class CashTransactionForm(forms.ModelForm):
    class Meta:
        model = CashTransaction
        fields = [
            "posted_at",
            "transaction_type",
            "payment_method",
            "patient",
            "appointment",
            "invoice",
            "amount",
            "concept",
            "reference",
            "notes",
        ]
        widgets = {
            "posted_at": forms.DateTimeInput(
                attrs={**_INPUT, "type": "datetime-local"},
                format="%Y-%m-%dT%H:%M",
            ),
            "transaction_type": forms.Select(attrs=_INPUT),
            "payment_method": forms.Select(attrs=_INPUT),
            "patient": forms.Select(attrs=_INPUT),
            "appointment": forms.Select(attrs=_INPUT),
            "invoice": forms.Select(attrs=_INPUT),
            "amount": forms.NumberInput(attrs={**_INPUT, "step": "0.01"}),
            "concept": forms.TextInput(attrs=_INPUT),
            "reference": forms.TextInput(attrs=_INPUT),
            "notes": forms.Textarea(attrs={**_INPUT, "rows": 3}),
        }

    def __init__(self, *args, tenant=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["posted_at"].input_formats = ["%Y-%m-%dT%H:%M"]
        self.fields["patient"].queryset = self.fields["patient"].queryset.order_by("last_name", "first_name")
        self.fields["appointment"].queryset = self.fields["appointment"].queryset.select_related("patient").order_by(
            "-scheduled_at"
        )
        self.fields["invoice"].queryset = self.fields["invoice"].queryset.select_related("patient").order_by(
            "-issued_at", "-id"
        )
        self.fields["patient"].required = False
        self.fields["appointment"].required = False
        self.fields["invoice"].required = False

    def clean_amount(self):
        amount = self.cleaned_data["amount"]
        if amount <= 0:
            raise forms.ValidationError("El monto debe ser mayor a cero.")
        return amount

    def clean(self):
        cleaned = super().clean()
        invoice = cleaned.get("invoice")
        patient = cleaned.get("patient")
        appointment = cleaned.get("appointment")

        if invoice is not None:
            if patient is None:
                cleaned["patient"] = invoice.patient
                self.cleaned_data["patient"] = invoice.patient
            elif invoice.patient_id != patient.id:
                self.add_error("patient", "La factura seleccionada pertenece a otro paciente.")

            if appointment is None and invoice.appointment_id:
                cleaned["appointment"] = invoice.appointment
                self.cleaned_data["appointment"] = invoice.appointment

        return cleaned
