from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from .forms import CommissionGenerationForm, IntegrationConnectionForm, LocationForm
from .services import execute_automation_rule


class LocationFormTests(SimpleTestCase):
    def test_code_is_normalized(self):
        form = LocationForm(
            data={
                "code": " matriz quito ",
                "name": "Matriz Quito",
                "address": "",
                "phone": "",
                "is_active": True,
            }
        )

        with patch.object(LocationForm, "validate_unique", return_value=None):
            self.assertTrue(form.is_valid())
        self.assertEqual(form.cleaned_data["code"], "MATRIZ-QUITO")


class CommissionGenerationFormTests(SimpleTestCase):
    def test_period_end_cannot_be_before_start(self):
        form = CommissionGenerationForm(
            data={
                "period_start": "2026-04-10",
                "period_end": "2026-04-05",
            }
        )

        self.assertFalse(form.is_valid())
        self.assertIn("period_end", form.errors)


class IntegrationConnectionFormTests(SimpleTestCase):
    def test_secret_hint_is_trimmed(self):
        form = IntegrationConnectionForm(
            data={
                "name": "WhatsApp Cloud",
                "provider": "WHATSAPP",
                "status": "TESTING",
                "endpoint": "https://example.test",
                "secret_hint": "  key-last4  ",
                "notes": "",
                "is_active": True,
            }
        )

        with patch.object(IntegrationConnectionForm, "validate_unique", return_value=None):
            self.assertTrue(form.is_valid())
        self.assertEqual(form.cleaned_data["secret_hint"], "key-last4")


class AutomationExecutionTests(SimpleTestCase):
    @patch("operations.services.AutomationRun.objects.create")
    @patch("operations.services.Appointment.objects.filter")
    def test_follow_up_rule_creates_run(self, appointment_filter, run_create):
        appointment_filter.return_value.count.return_value = 4
        run = SimpleNamespace(
            pk=12,
            executed_at=MagicMock(),
            status="SUCCESS",
            summary="4 atenciones elegibles para seguimiento.",
        )
        run_create.return_value = run
        rule = SimpleNamespace(
            trigger="FOLLOW_UP",
            channel="INTERNAL",
            last_run_at=None,
            save=MagicMock(),
        )

        created_run = execute_automation_rule(rule)

        self.assertIs(created_run, run)
        run_create.assert_called_once()
        rule.save.assert_called_once_with(update_fields=["last_run_at"])
