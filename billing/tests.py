from unittest.mock import patch

from django.test import SimpleTestCase

from .forms import CashTransactionForm, InvoiceForm


class CashTransactionFormTests(SimpleTestCase):
    def test_amount_must_be_greater_than_zero(self):
        form = CashTransactionForm(
            data={
                "posted_at": "2026-04-05T10:30",
                "transaction_type": "PAYMENT",
                "payment_method": "CASH",
                "amount": "0.00",
                "concept": "Consulta general",
            }
        )

        self.assertFalse(form.is_valid())
        self.assertIn("amount", form.errors)


class InvoiceFormTests(SimpleTestCase):
    def test_discount_cannot_exceed_subtotal(self):
        form = InvoiceForm(
            data={
                "invoice_number": "FAC-001",
                "issued_at": "2026-04-06T09:30",
                "status": "ISSUED",
                "subtotal": "50.00",
                "discount_amount": "60.00",
            }
        )

        with patch.object(InvoiceForm, "validate_unique", return_value=None):
            self.assertFalse(form.is_valid())
        self.assertIn("discount_amount", form.errors)
