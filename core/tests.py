from types import SimpleNamespace

from django.test import SimpleTestCase

from core.navigation import build_navigation_model
from tenants.models import TenantMembership


class NavigationModelTests(SimpleTestCase):
    def _request(self, *, is_authenticated=True, is_superuser=False, tenant=None, membership=None, namespace="", url_name="dashboard"):
        return SimpleNamespace(
            user=SimpleNamespace(is_authenticated=is_authenticated, is_superuser=is_superuser),
            tenant=tenant,
            tenant_membership=membership,
            resolver_match=SimpleNamespace(namespace=namespace, url_name=url_name),
        )

    def test_public_superadmin_sees_clinics_link(self):
        request = self._request(
            is_superuser=True,
            tenant=SimpleNamespace(schema_name="public"),
        )

        nav = build_navigation_model(request)

        self.assertEqual([item.label for item in nav.primary_items], ["Mis clinicas", "Clinicas"])

    def test_doctor_gets_agenda_patients_and_atencion(self):
        tenant = SimpleNamespace(
            schema_name="clinica_a",
            has_capability=lambda capability: capability in {"appointments.basic", "patients.basic", "clinical.basic"},
        )
        membership = SimpleNamespace(
            is_admin=False,
            role=TenantMembership.ROLE_DOCTOR,
            role_label="Profesional",
        )
        request = self._request(tenant=tenant, membership=membership, namespace="clinical", url_name="index")

        nav = build_navigation_model(request)

        self.assertEqual([item.label for item in nav.primary_items], ["Inicio", "Agenda", "Pacientes", "Atencion"])
        self.assertIsNone(nav.management_menu)

    def test_clinic_admin_gets_management_menu(self):
        tenant = SimpleNamespace(
            schema_name="clinica_a",
            has_capability=lambda capability: capability
            in {
                "appointments.basic",
                "patients.basic",
                "billing.basic",
                "crm.basic",
                "inventory.basic",
                "reports.basic",
                "automation.basic",
                "integrations.basic",
                "multi_site.basic",
            },
        )
        membership = SimpleNamespace(
            is_admin=True,
            role=TenantMembership.ROLE_CLINIC_ADMIN,
            role_label="Admin de clinica",
        )
        request = self._request(tenant=tenant, membership=membership, namespace="operations", url_name="integrations")

        nav = build_navigation_model(request)

        self.assertEqual([item.label for item in nav.primary_items], ["Inicio", "Agenda", "Pacientes", "Caja"])
        self.assertIsNotNone(nav.management_menu)
        self.assertTrue(nav.management_menu.active)
        self.assertIn("Reportes", [item.label for item in nav.management_menu.items])
