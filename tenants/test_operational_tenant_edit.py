from django.test import SimpleTestCase

from tenants.defaults import PROFILE_BROKER
from tenants.models import Client
from tenants.tenant_edit_operational import OperationalTenantEditForm


class OperationalTenantEditFormTests(SimpleTestCase):
    def _base_data(self):
        return {
            "name": "Tenant Demo",
            "plan": Client.PLAN_SHARED,
            "profile": PROFILE_BROKER,
            "max_users": "25",
            "storage_quota_mb": "2048",
            "is_active": "on",
            "structured_admin_surface": "structured",
            "enabled_modules": ["reports", "documents", "entities"],
            "extra_features": ["fiscal_lookup"],
            "module_order_csv": "reports, documents, entities",
            "dashboard_widgets_selected": ["summary_cards", "quick_actions"],
            "brand_name": "Binn Broker",
            "dashboard_title": "Mesa operativa de renovaciones",
            "entity_singular": "Cuenta",
            "entity_plural": "Cuentas",
            "deal_singular": "Caso",
            "deal_plural": "Casos",
            "manager_access_mode": "custom",
            "manager_permissions": ["dashboard.view", "reports.view"],
            "operator_permissions": ["dashboard.view", "entities.view", "entities.edit"],
            "analyst_permissions": ["dashboard.view", "reports.view"],
            "viewer_permissions": ["dashboard.view"],
            "feature_flags_json": "{}",
            "labels_json": "{}",
            "entity_fields_json": "[]",
            "custom_objects_json": "[]",
            "module_order_json": "[]",
            "dashboard_widgets_json": "[]",
            "role_policies_json": "{}",
            "document_blueprints_json": "[]",
            "pipeline_templates_json": '[{"key": "renovaciones", "label": "Renovaciones", "stages": ["Cotizado", "Emitido"]}]',
            "homepage_layout_mode": "sales",
            "homepage_layout_density": "compact",
            "communication_primary_channel": "email",
            "communication_broadcast_enabled": "on",
            "quote_default_currency": "usd",
            "quote_validity_days": "30",
            "collection_default_currency": "usd",
            "collection_risk_window_days": "9",
            "task_presets_json": '[{"key": "renovar", "label": "Llamar renovacion", "due_in_days": 2, "priority": "high", "owner_role": "operator"}]',
            "collection_settings_json": '{"follow_up_days": [2, 5], "states": ["pending", "paid"]}',
            "communication_settings_json": '{"channels": ["email", "whatsapp"], "consent_required": true}',
            "quote_settings_json": '{"number_prefix": "COT"}',
            "homepage_layout_json": '{"hero_metric": "open_deals", "show_guided_steps": false}',
        }

    def test_structured_operational_controls_sync_json_payloads(self):
        form = OperationalTenantEditForm(
            data=self._base_data(),
            instance=Client(name="Tenant Demo", plan=Client.PLAN_SHARED, is_active=True),
        )

        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["homepage_layout_json"]["mode"], "sales")
        self.assertEqual(form.cleaned_data["homepage_layout_json"]["density"], "compact")
        self.assertEqual(form.cleaned_data["communication_settings_json"]["primary_channel"], "email")
        self.assertTrue(form.cleaned_data["communication_settings_json"]["broadcast_enabled"])
        self.assertEqual(form.cleaned_data["quote_settings_json"]["default_currency"], "USD")
        self.assertEqual(form.cleaned_data["quote_settings_json"]["validity_days"], 30)
        self.assertEqual(form.cleaned_data["collection_settings_json"]["default_currency"], "USD")
        self.assertEqual(form.cleaned_data["collection_settings_json"]["risk_window_days"], 9)
        self.assertEqual(form.cleaned_data["task_presets_json"][0]["key"], "renovar")

