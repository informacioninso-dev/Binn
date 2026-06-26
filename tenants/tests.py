import json
from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.contrib.auth.models import AnonymousUser
from django.contrib.auth import get_user_model
from django.test import RequestFactory, SimpleTestCase, TestCase

from access.permissions import PERMISSION_DEALS_MOVE, membership_has_tenant_permission
from core.runtime_services import ServiceRuntimeStatus
from tenants.defaults import (
    PROFILE_BROKER,
    PROFILE_CONDOMINIO,
    PROFILE_RETAIL_MODA,
    PROFILE_SERVICIOS,
    build_profile_launchpad,
    get_profile_defaults,
)
from tenants.forms import TenantEditForm
from tenants.models import Client
from tenants.services import TenantProvisionError, assign_tenant_membership, create_tenant
from tenants.views import SystemHealthView, SystemRuntimeHealthView
from tenants.workspace_packs import build_group_pack_mix, build_workspace_pack


class TenantEditFormTests(SimpleTestCase):
    def _base_data(self):
        return {
            "name": "Tenant Demo",
            "plan": Client.PLAN_SHARED,
            "profile": PROFILE_BROKER,
            "max_users": "25",
            "storage_quota_mb": "2048",
            "is_active": "on",
            "feature_flags_json": '{"entities": true, "documents": true, "kanban": true}',
            "labels_json": '{"entity_plural": "Asegurados", "deal_plural": "Renovaciones"}',
            "entity_fields_json": '[{"key": "placa", "label": "Placa", "type": "text", "required": true}]',
            "custom_objects_json": '[{"key": "poliza_detalle", "label": "Polizas", "fields": [{"key": "numero_poliza", "label": "Numero de poliza", "type": "text", "required": true}]}]',
            "module_order_json": '["documents", "entities", "deals", "activities"]',
            "dashboard_widgets_json": '["summary_cards", "quick_actions", "pipeline_panel"]',
            "role_policies_json": '{"viewer": ["dashboard.view", "entities.view"], "operator": ["dashboard.view", "deals.move"]}',
            "document_blueprints_json": (
                '[{"key": "certificado", "label": "Certificado", "category": "Entrega", '
                '"description": "Documento listo para compartir con el cliente.", '
                '"storage_hint": "broker/certificados/{numero_poliza}/{filename}", '
                '"metadata_fields": [{"key": "numero_poliza", "label": "Numero de poliza", "type": "text"}]}]'
            ),
            "pipeline_templates_json": '[{"key": "renovaciones", "label": "Renovaciones", "stages": ["Cotizado", "Emitido"]}]',
        }

    def test_accepts_valid_camaleonic_configuration(self):
        form = TenantEditForm(
            data=self._base_data(),
            instance=Client(name="Tenant Demo", plan=Client.PLAN_SHARED, is_active=True),
        )

        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["feature_flags_json"]["documents"], True)
        self.assertEqual(form.cleaned_data["entity_fields_json"][0]["key"], "placa")
        self.assertEqual(form.cleaned_data["custom_objects_json"][0]["key"], "poliza_detalle")
        self.assertEqual(form.cleaned_data["module_order_json"][0], "documents")
        self.assertEqual(form.cleaned_data["dashboard_widgets_json"][0], "summary_cards")
        self.assertEqual(form.cleaned_data["role_policies_json"]["viewer"], ["dashboard.view", "entities.view"])
        self.assertEqual(form.cleaned_data["document_blueprints_json"][0]["key"], "certificado")
        self.assertEqual(form.cleaned_data["pipeline_templates_json"][0]["stages"], ["Cotizado", "Emitido"])

    def test_rejects_non_boolean_feature_flags(self):
        data = self._base_data()
        data["feature_flags_json"] = '{"entities": "si"}'
        form = TenantEditForm(
            data=data,
            instance=Client(name="Tenant Demo", plan=Client.PLAN_SHARED, is_active=True),
        )

        self.assertFalse(form.is_valid())
        self.assertIn("feature_flags_json", form.errors)

    def test_reset_to_profile_defaults_restores_profile_blueprint(self):
        data = self._base_data()
        data["profile"] = PROFILE_CONDOMINIO
        data["reset_to_profile_defaults"] = "on"
        form = TenantEditForm(
            data=data,
            instance=Client(name="Tenant Demo", plan=Client.PLAN_SHARED, is_active=True),
        )

        self.assertTrue(form.is_valid(), form.errors)
        defaults = get_profile_defaults(PROFILE_CONDOMINIO)
        self.assertEqual(form.cleaned_data["feature_flags_json"], defaults["feature_flags"])
        self.assertEqual(form.cleaned_data["entity_fields_json"], defaults["entity_fields"])
        self.assertEqual(form.cleaned_data["custom_objects_json"], defaults["custom_objects"])
        self.assertEqual(form.cleaned_data["module_order_json"], defaults["module_order"])
        self.assertEqual(form.cleaned_data["dashboard_widgets_json"], defaults["dashboard_widgets"])
        self.assertEqual(form.cleaned_data["role_policies_json"], defaults["role_policies"])

    def test_structured_admin_controls_sync_runtime_configuration(self):
        data = self._base_data()
        data.update(
            {
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
            }
        )
        form = TenantEditForm(
            data=data,
            instance=Client(name="Tenant Demo", plan=Client.PLAN_SHARED, is_active=True),
        )

        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["module_order_json"][:3], ["reports", "documents", "entities"])
        self.assertEqual(form.cleaned_data["dashboard_widgets_json"], ["summary_cards", "quick_actions"])
        self.assertTrue(form.cleaned_data["feature_flags_json"]["reports"])
        self.assertTrue(form.cleaned_data["feature_flags_json"]["documents"])
        self.assertTrue(form.cleaned_data["feature_flags_json"]["entities"])
        self.assertFalse(form.cleaned_data["feature_flags_json"]["deals"])
        self.assertTrue(form.cleaned_data["feature_flags_json"]["fiscal_lookup"])
        self.assertFalse(form.cleaned_data["feature_flags_json"]["kanban"])
        self.assertEqual(form.cleaned_data["labels_json"]["brand_name"], "Binn Broker")
        self.assertEqual(form.cleaned_data["labels_json"]["deal_plural"], "Casos")
        self.assertEqual(form.cleaned_data["role_policies_json"]["manager"], ["dashboard.view", "reports.view"])
        self.assertEqual(form.cleaned_data["role_policies_json"]["operator"], ["dashboard.view", "entities.view", "entities.edit"])
        self.assertEqual(form.cleaned_data["role_policies_json"]["analyst"], ["dashboard.view", "reports.view"])
        self.assertEqual(form.cleaned_data["role_policies_json"]["viewer"], ["dashboard.view"])

    def test_structured_admin_controls_require_at_least_one_visible_module(self):
        data = self._base_data()
        data.update(
            {
                "structured_admin_surface": "structured",
                "enabled_modules": [],
                "extra_features": [],
                "module_order_csv": "",
                "dashboard_widgets_selected": ["summary_cards"],
                "manager_access_mode": "full",
                "manager_permissions": [],
                "operator_permissions": ["dashboard.view"],
                "analyst_permissions": ["dashboard.view"],
                "viewer_permissions": ["dashboard.view"],
            }
        )
        form = TenantEditForm(
            data=data,
            instance=Client(name="Tenant Demo", plan=Client.PLAN_SHARED, is_active=True),
        )

        self.assertFalse(form.is_valid())
        self.assertIn("enabled_modules", form.errors)

    def test_rejects_duplicated_pipeline_keys(self):
        data = self._base_data()
        data["pipeline_templates_json"] = (
            '[{"key": "captacion", "label": "Captacion", "stages": ["Nuevo"]}, '
            '{"key": "captacion", "label": "Duplicado", "stages": ["Otro"]}]'
        )
        form = TenantEditForm(
            data=data,
            instance=Client(name="Tenant Demo", plan=Client.PLAN_SHARED, is_active=True),
        )

        self.assertFalse(form.is_valid())
        self.assertIn("pipeline_templates_json", form.errors)

    def test_rejects_invalid_dashboard_widget(self):
        data = self._base_data()
        data["dashboard_widgets_json"] = '["summary_cards", "unknown_widget"]'
        form = TenantEditForm(
            data=data,
            instance=Client(name="Tenant Demo", plan=Client.PLAN_SHARED, is_active=True),
        )

        self.assertFalse(form.is_valid())
        self.assertIn("dashboard_widgets_json", form.errors)

    def test_rejects_invalid_role_permission(self):
        data = self._base_data()
        data["role_policies_json"] = '{"viewer": ["entities.destroy"]}'
        form = TenantEditForm(
            data=data,
            instance=Client(name="Tenant Demo", plan=Client.PLAN_SHARED, is_active=True),
        )

        self.assertFalse(form.is_valid())
        self.assertIn("role_policies_json", form.errors)


class TenantLaunchpadTests(SimpleTestCase):
    def test_broker_launchpad_enables_documents_and_renovaciones_pipeline(self):
        launchpad = build_profile_launchpad(PROFILE_BROKER)

        self.assertTrue(any(item["key"] == "documents" for item in launchpad["enabled_capabilities"]))
        self.assertTrue(any(item["key"] == "proposals" for item in launchpad["enabled_capabilities"]))
        self.assertTrue(any(item["key"] == "collections" for item in launchpad["enabled_capabilities"]))
        self.assertTrue(any(pipeline["key"] == "renovaciones" for pipeline in launchpad["pipelines"]))
        self.assertIn("renovaciones", launchpad["headline"].lower())
        self.assertEqual(launchpad["module_order"][0]["key"], "entities")
        self.assertTrue(any(widget["key"] == "summary_cards" for widget in launchpad["dashboard_widgets"]))
        self.assertTrue(any(policy["role"] == "owner" for policy in launchpad["role_policies"]))

    def test_condominio_launchpad_enables_documents_and_operational_objects(self):
        launchpad = build_profile_launchpad(PROFILE_CONDOMINIO)

        self.assertTrue(any(item["key"] == "documents" for item in launchpad["enabled_capabilities"]))
        self.assertTrue(any(item["key"] == "proposals" for item in launchpad["hidden_capabilities"]))
        self.assertTrue(any(item["key"] == "collections" for item in launchpad["enabled_capabilities"]))
        self.assertEqual(launchpad["labels"]["entity_plural"], "Residentes")
        self.assertEqual(launchpad["pipelines"][0]["label"], "Recaudacion")
        self.assertTrue(any(item["key"] == "incidencia" for item in launchpad["custom_objects"]))
        self.assertTrue(any(item["key"] == "comunicado" for item in launchpad["custom_objects"]))

    def test_services_launchpad_enables_reports_and_b2b_pipeline(self):
        launchpad = build_profile_launchpad(PROFILE_SERVICIOS)

        self.assertTrue(any(item["key"] == "reports" for item in launchpad["enabled_capabilities"]))
        self.assertTrue(any(item["key"] == "objects" for item in launchpad["enabled_capabilities"]))
        self.assertTrue(any(pipeline["key"] == "servicios_b2b" for pipeline in launchpad["pipelines"]))
        self.assertEqual(launchpad["labels"]["entity_plural"], "Clientes")
        self.assertTrue(any(field["key"] == "service_line" for field in launchpad["entity_fields"]))
        self.assertTrue(any(item["key"] == "proyecto" for item in launchpad["custom_objects"]))
        self.assertTrue(any(item["key"] == "entregable" for item in launchpad["custom_objects"]))
        self.assertEqual(launchpad["module_order"][1]["key"], "objects")

    def test_retail_launchpad_exposes_clienteling_fields(self):
        launchpad = build_profile_launchpad(PROFILE_RETAIL_MODA)

        self.assertTrue(any(item["key"] == "reports" for item in launchpad["enabled_capabilities"]))
        self.assertTrue(any(item["key"] == "objects" for item in launchpad["enabled_capabilities"]))
        self.assertTrue(any(field["key"] == "client_segment" for field in launchpad["entity_fields"]))
        self.assertTrue(any(field["key"] == "talla" for field in launchpad["entity_fields"]))
        self.assertTrue(any(item["key"] == "wishlist" for item in launchpad["custom_objects"]))
        self.assertEqual(launchpad["pipelines"][0]["label"], "Clienteling")


class WorkspacePackTests(SimpleTestCase):
    def test_workspace_pack_exposes_broker_operating_focus(self):
        pack = build_workspace_pack(
            profile=PROFILE_BROKER,
            labels={"entity_plural": "Asegurados", "deal_plural": "Renovaciones"},
            feature_flags={"collab": True, "documents": True},
        )

        self.assertEqual(pack["title"], "Pack Broker de Seguros")
        self.assertTrue(pack["collab_enabled"])
        self.assertIn("Docs bajo control", pack["pillars"])

    def test_group_pack_mix_aggregates_visible_metrics_by_profile(self):
        tenant_config = type("Config", (), {"profile": PROFILE_CONDOMINIO})()
        tenant = type("Tenant", (), {"tenant_config": tenant_config})()

        mix = build_group_pack_mix(
            tenant_rows=[
                {
                    "tenant": tenant,
                    "metrics_visible": True,
                    "entity_count": 12,
                    "open_deals_count": 4,
                    "overdue_activities_count": 2,
                },
                {
                    "tenant": tenant,
                    "metrics_visible": False,
                    "entity_count": 30,
                    "open_deals_count": 9,
                    "overdue_activities_count": 5,
                },
            ]
        )

        self.assertEqual(mix[0]["profile_label"], "Administracion de condominios")
        self.assertEqual(mix[0]["tenant_count"], 2)
        self.assertEqual(mix[0]["visible_tenant_count"], 1)
        self.assertEqual(mix[0]["entity_count"], 12)


class TenantPermissionPolicyTests(SimpleTestCase):
    def test_membership_permission_uses_role_policies(self):
        tenant = Client(name="Demo", schema_name="demo", plan=Client.PLAN_SHARED)
        tenant.tenant_config = type(
            "Config",
            (),
            {"role_policies": {"viewer": ["dashboard.view"], "operator": ["dashboard.view", "deals.move"]}},
        )()
        membership = type("Membership", (), {"role": "operator"})()

        self.assertTrue(membership_has_tenant_permission(membership, tenant, PERMISSION_DEALS_MOVE))


class TenantMembershipCapacityTests(TestCase):
    def setUp(self):
        self.user_model = get_user_model()
        self.owner = self.user_model.objects.create_user(username="tenantowner", password="x")
        self.extra_user = self.user_model.objects.create_user(username="tenantextra", password="x")
        self.tenant = Client(
            name="Capacidad Demo",
            schema_name="capacidaddemo",
            plan=Client.PLAN_SHARED,
            is_active=True,
            max_users=1,
        )
        self.tenant.auto_create_schema = False
        self.tenant.save()

    def test_assign_tenant_membership_blocks_new_user_when_limit_reached(self):
        assign_tenant_membership(tenant=self.tenant, username="tenantowner", role="owner")

        with self.assertRaises(TenantProvisionError) as ctx:
            assign_tenant_membership(tenant=self.tenant, username="tenantextra", role="viewer")

        self.assertIn("limite de 1 usuarios activos", str(ctx.exception))

    def test_assign_tenant_membership_allows_updating_existing_active_user(self):
        result = assign_tenant_membership(tenant=self.tenant, username="tenantowner", role="owner")

        updated = assign_tenant_membership(tenant=self.tenant, username="tenantowner", role="manager")

        self.assertEqual(result.membership.pk, updated.membership.pk)
        self.assertEqual(updated.membership.role, "manager")


class TenantProvisioningServiceTests(SimpleTestCase):
    @patch("tenants.services._validate_tenant_request")
    @patch("tenants.services._get_existing_user", return_value=None)
    @patch("tenants.services.Client")
    @patch("tenants.services.Domain")
    @patch("tenants.services.TenantConfig")
    @patch(
        "tenants.services.build_tenant_launchpad",
        return_value={
            "headline": "CRM listo",
            "enabled_capabilities": [{"key": "entities", "label": "Fichas"}],
            "hidden_capabilities": [],
            "pipelines": [],
        },
    )
    @patch("tenants.services.record_tenant_event")
    @patch("tenants.services.sync_tenant_pipelines", return_value=[])
    @patch("tenants.services.sync_tenant_object_schemas", return_value=[])
    @patch("tenants.services.ensure_tenant_admin_membership", return_value=[])
    @patch("tenants.services.get_public_schema_name", return_value="public")
    @patch("tenants.services.schema_context", side_effect=lambda schema: nullcontext())
    def test_create_tenant_provisions_schema_explicitly(
        self,
        schema_context_mock,
        public_schema_mock,
        ensure_admin_mock,
        sync_objects_mock,
        sync_pipelines_mock,
        record_event_mock,
        launchpad_mock,
        tenant_config_mock,
        domain_mock,
        client_class_mock,
        get_existing_user_mock,
        validate_request_mock,
    ):
        client = MagicMock()
        client.schema_name = "demo"
        client.name = "Demo"
        client.pk = 1
        client_class_mock.return_value = client

        config = MagicMock()
        config.get_profile_display.return_value = "General"
        tenant_config_mock.objects.filter.return_value.first.return_value = None
        tenant_config_mock.return_value = config

        result = create_tenant(
            schema_name="demo",
            name="Demo",
            domain="demo.binnso.com",
            plan=Client.PLAN_SHARED,
            profile="general",
        )

        self.assertIs(result.client, client)
        self.assertFalse(client.auto_create_schema)
        client.save.assert_called_once()
        domain_mock.objects.create.assert_called_once_with(
            domain="demo.binnso.com",
            tenant=client,
            is_primary=True,
        )
        client.create_schema.assert_called_once_with(check_if_exists=True, verbosity=0)
        sync_pipelines_mock.assert_called_once_with(client)
        sync_objects_mock.assert_called_once_with(client)
        ensure_admin_mock.assert_not_called()
        self.assertGreaterEqual(record_event_mock.call_count, 2)

    @patch("tenants.services._safe_drop_client")
    @patch("tenants.services._validate_tenant_request")
    @patch("tenants.services._get_existing_user", return_value=None)
    @patch("tenants.services.Client")
    @patch("tenants.services.Domain")
    @patch("tenants.services.TenantConfig")
    @patch(
        "tenants.services.build_tenant_launchpad",
        return_value={
            "headline": "CRM listo",
            "enabled_capabilities": [{"key": "entities", "label": "Fichas"}],
            "hidden_capabilities": [],
            "pipelines": [],
        },
    )
    @patch("tenants.services.record_tenant_event")
    @patch("tenants.services.get_public_schema_name", return_value="public")
    @patch("tenants.services.schema_context", side_effect=lambda schema: nullcontext())
    def test_create_tenant_rolls_back_when_schema_provision_fails(
        self,
        schema_context_mock,
        public_schema_mock,
        record_event_mock,
        launchpad_mock,
        tenant_config_mock,
        domain_mock,
        client_class_mock,
        get_existing_user_mock,
        validate_request_mock,
        safe_drop_client_mock,
    ):
        client = MagicMock()
        client.schema_name = "demo"
        client.name = "Demo"
        client.pk = 1
        client.create_schema.side_effect = RuntimeError("boom")
        client_class_mock.return_value = client

        config = MagicMock()
        config.get_profile_display.return_value = "General"
        tenant_config_mock.objects.filter.return_value.first.return_value = None
        tenant_config_mock.return_value = config

        with self.assertRaises(TenantProvisionError) as ctx:
            create_tenant(
                schema_name="demo",
                name="Demo",
                domain="demo.binnso.com",
                plan=Client.PLAN_SHARED,
                profile="general",
            )

        self.assertIn("No se pudo provisionar el schema", str(ctx.exception))
        safe_drop_client_mock.assert_called_once_with(client)


class SystemHealthViewTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.user_model = get_user_model()

    def test_public_health_payload_is_minimal(self):
        request = RequestFactory().get("/health/")

        response = SystemHealthView.as_view()(request)
        payload = json.loads(response.content)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload, {"status": "ok"})

    @patch("tenants.views.get_runtime_services_status")
    def test_runtime_health_payload_includes_runtime_services_for_superadmin(self, get_runtime_services_status_mock):
        get_runtime_services_status_mock.return_value = {
            "database": ServiceRuntimeStatus(True, True, True, True, "sql", "Base de datos responde a SELECT 1."),
            "redis": ServiceRuntimeStatus(False, True, False, True, "disabled", "Redis no esta configurado."),
            "cache": ServiceRuntimeStatus(True, True, True, True, "memory", "Cache default responde a set/get."),
            "channels": ServiceRuntimeStatus(False, True, False, True, "disabled", "Realtime deshabilitado por configuracion."),
            "celery": ServiceRuntimeStatus(False, True, False, True, "disabled", "Workers de background deshabilitados por configuracion."),
            "celery_result_backend": ServiceRuntimeStatus(False, True, False, True, "disabled", "Celery result backend deshabilitado junto con los workers."),
        }
        request = self.factory.get("/health/runtime/")
        request.user = self.user_model.objects.create_superuser(username="root", email="root@example.com", password="x")
        request.tenant = SimpleNamespace(schema_name="public")

        response = SystemRuntimeHealthView.as_view()(request)
        payload = json.loads(response.content)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["tenant"], "public")
        self.assertIn("database", payload["services"])
        self.assertIn("celery", payload["services"])

    @patch("tenants.views.get_runtime_services_status")
    def test_runtime_health_returns_503_when_any_service_is_unhealthy(self, get_runtime_services_status_mock):
        get_runtime_services_status_mock.return_value = {
            "database": ServiceRuntimeStatus(True, True, True, True, "sql", "Base de datos responde a SELECT 1."),
            "redis": ServiceRuntimeStatus(True, True, True, False, "configured", "Redis fallo: timeout"),
            "cache": ServiceRuntimeStatus(True, True, True, True, "redis", "Cache default responde a set/get."),
            "channels": ServiceRuntimeStatus(True, True, True, False, "redis", "Realtime usa Redis pero Redis no responde."),
            "celery": ServiceRuntimeStatus(False, True, False, True, "disabled", "Workers de background deshabilitados por configuracion."),
            "celery_result_backend": ServiceRuntimeStatus(False, True, False, True, "disabled", "Celery result backend deshabilitado junto con los workers."),
        }
        request = self.factory.get("/health/runtime/")
        request.user = self.user_model.objects.create_superuser(username="ops", email="ops@example.com", password="x")
        request.tenant = SimpleNamespace(schema_name="public")

        response = SystemRuntimeHealthView.as_view()(request)
        payload = json.loads(response.content)

        self.assertEqual(response.status_code, 503)
        self.assertEqual(payload["status"], "error")
        self.assertFalse(payload["services"]["redis"]["healthy"])

    def test_runtime_health_requires_authentication(self):
        request = self.factory.get("/health/runtime/")
        request.user = AnonymousUser()

        response = SystemRuntimeHealthView.as_view()(request)

        self.assertEqual(response.status_code, 302)
