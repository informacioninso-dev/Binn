from datetime import date
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase

from binncrm.forms import ActivityForm, CollectionRecordForm, ProposalForm
from binncrm.models import Activity, CollectionRecord, Deal, Entity
from binncrm.operational_context import (
    build_activity_operational_context,
    build_collection_operational_context,
    build_proposal_operational_context,
)


class OperationalContextBuilderTests(SimpleTestCase):
    def test_build_proposal_operational_context_uses_quote_settings(self):
        tenant = SimpleNamespace(
            quote_settings={
                "default_currency": "cop",
                "validity_days": 21,
                "number_prefix": "cot",
                "approval_required_over": 5000,
            }
        )

        context = build_proposal_operational_context(tenant, today=date(2026, 7, 30))

        self.assertEqual(context["default_currency"], "COP")
        self.assertEqual(context["validity_days"], 21)
        self.assertEqual(context["default_valid_until"], date(2026, 8, 20))
        self.assertEqual(context["proposal_number_placeholder"], "COT-20260730")
        self.assertEqual(context["approval_required_over"], 5000)

    def test_build_collection_operational_context_orders_states_and_follow_up_days(self):
        tenant = SimpleNamespace(
            collection_settings={
                "default_currency": "mxn",
                "risk_window_days": 9,
                "follow_up_days": [2, "5", 11],
                "states": ["promised", "pending", "overdue", "paid"],
            }
        )

        context = build_collection_operational_context(tenant)

        self.assertEqual(context["default_currency"], "MXN")
        self.assertEqual(context["risk_window_days"], 9)
        self.assertEqual(context["follow_up_days"], [2, 5, 11])
        self.assertEqual(context["states"], ["promised", "pending", "overdue", "paid"])
        self.assertEqual(
            context["state_labels"],
            ["Promesa de pago", "Pendiente", "Vencida", "Pagada"],
        )
        self.assertEqual(context["default_status"], "promised")

    def test_build_activity_operational_context_maps_primary_channel_to_default_type(self):
        tenant = SimpleNamespace(
            communication_settings={
                "primary_channel": "email",
                "channels": ["email", "whatsapp", "phone"],
                "broadcast_enabled": True,
                "consent_required": False,
            }
        )

        context = build_activity_operational_context(tenant)

        self.assertEqual(context["primary_channel_label"], "Email")
        self.assertEqual(context["default_activity_type"], Activity.TYPE_EMAIL)
        self.assertEqual(context["default_activity_title"], "Correo de seguimiento")
        self.assertEqual(context["channels_label"], "Email, WhatsApp, Llamada")
        self.assertTrue(context["broadcast_enabled"])
        self.assertFalse(context["consent_required"])


class OperationalFormDefaultsTests(SimpleTestCase):
    @patch(
        "binncrm.forms.build_proposal_operational_context",
        return_value={
            "default_currency": "COP",
            "validity_days": 21,
            "default_valid_until": date(2026, 8, 20),
            "number_prefix": "COT",
            "proposal_number_placeholder": "COT-20260730",
            "approval_required_over": 5000,
        },
    )
    @patch("binncrm.forms.Deal.objects.filter", return_value=Deal.objects.none())
    @patch("binncrm.forms.Entity.objects.filter", return_value=Entity.objects.none())
    def test_proposal_form_applies_quote_defaults(
        self,
        entity_filter_mock,
        deal_filter_mock,
        proposal_ops_mock,
    ):
        form = ProposalForm(tenant=SimpleNamespace())

        self.assertEqual(form.initial["currency"], "COP")
        self.assertEqual(form.initial["valid_until"], date(2026, 8, 20))
        self.assertEqual(form.fields["currency"].widget.attrs["placeholder"], "COP")
        self.assertEqual(form.fields["proposal_number"].widget.attrs["placeholder"], "COT-20260730")

    @patch(
        "binncrm.forms.build_collection_operational_context",
        return_value={
            "default_currency": "MXN",
            "risk_window_days": 9,
            "follow_up_days": [2, 5, 11],
            "follow_up_label": "2, 5, 11",
            "states": ["promised", "pending", "overdue", "paid"],
            "state_labels": ["Promesa de pago", "Pendiente", "Vencida", "Pagada"],
            "default_status": "promised",
        },
    )
    @patch("binncrm.forms.Deal.objects.filter", return_value=Deal.objects.none())
    @patch("binncrm.forms.Entity.objects.filter", return_value=Entity.objects.none())
    def test_collection_form_uses_collection_defaults_and_state_order(
        self,
        entity_filter_mock,
        deal_filter_mock,
        collection_ops_mock,
    ):
        form = CollectionRecordForm(tenant=SimpleNamespace())

        self.assertEqual(form.initial["currency"], "MXN")
        self.assertEqual(form.initial["status"], "promised")
        self.assertEqual(form.fields["currency"].widget.attrs["placeholder"], "MXN")
        self.assertEqual(
            [choice[0] for choice in form.fields["status"].choices[:4]],
            ["promised", "pending", "overdue", "paid"],
        )

    @patch(
        "binncrm.forms.build_activity_operational_context",
        return_value={
            "primary_channel": "email",
            "primary_channel_label": "Email",
            "channels": ["email", "whatsapp"],
            "channels_label": "Email, WhatsApp",
            "default_activity_type": Activity.TYPE_EMAIL,
            "default_activity_title": "Correo de seguimiento",
            "broadcast_enabled": False,
            "consent_required": True,
        },
    )
    @patch("binncrm.forms.get_tenant_user_queryset", return_value=get_user_model().objects.none())
    @patch("binncrm.forms.Deal.objects.filter", return_value=Deal.objects.none())
    @patch("binncrm.forms.Entity.objects.filter", return_value=Entity.objects.none())
    def test_activity_form_defaults_type_and_title_from_operational_context(
        self,
        entity_filter_mock,
        deal_filter_mock,
        user_queryset_mock,
        activity_ops_mock,
    ):
        form = ActivityForm(
            tenant=SimpleNamespace(),
            current_user=SimpleNamespace(is_authenticated=False),
        )

        self.assertEqual(form.initial["activity_type"], Activity.TYPE_EMAIL)
        self.assertEqual(form.initial["title"], "Correo de seguimiento")
