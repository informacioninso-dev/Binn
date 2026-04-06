from django.contrib import admin

from .models import CashTransaction, CoverageAgreement, Invoice


@admin.register(CoverageAgreement)
class CoverageAgreementAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "payer_type", "default_credit_days", "is_active")
    list_filter = ("payer_type", "is_active")
    search_fields = ("code", "name", "contact_name", "email")


@admin.register(Invoice)
class InvoiceAdmin(admin.ModelAdmin):
    list_display = ("invoice_number", "patient", "coverage_agreement", "status", "total_amount", "paid_amount")
    list_filter = ("status", "coverage_agreement")
    search_fields = ("invoice_number", "patient__mrn", "patient__first_name", "patient__last_name")


@admin.register(CashTransaction)
class CashTransactionAdmin(admin.ModelAdmin):
    list_display = (
        "posted_at",
        "transaction_type",
        "payment_method",
        "amount",
        "patient",
        "invoice",
        "concept",
    )
    list_filter = ("transaction_type", "payment_method")
    search_fields = (
        "concept",
        "reference",
        "invoice__invoice_number",
        "patient__first_name",
        "patient__last_name",
        "patient__mrn",
    )
