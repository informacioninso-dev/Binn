from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.core.management.base import CommandError
from django.http import HttpResponse
from django.test import RequestFactory
from django.test import SimpleTestCase, TestCase

from core.middleware import LoginRequiredMiddleware
from tenants.auth_backends import TenantAwareBackend
from tenants.forms import AddMemberForm, TenantCreateForm
from tenants.management.commands.bootstrap_clinic import Command as BootstrapClinicCommand
from tenants.middleware import TenantAccessMiddleware
from tenants.observability import build_system_health_payload, build_tenant_diagnostics
from tenants.permissions import tenant_capability_required
from tenants.services import (
    TenantProvisionError,
    assign_tenant_membership,
    create_tenant,
    ensure_tenant_admin_membership,
)


class TenantAwareBackendTests(SimpleTestCase):
    def setUp(self):
        self.backend = TenantAwareBackend()

    def _user(self, *, is_superuser=False):
        user = MagicMock()
        user.is_superuser = is_superuser
        user.check_password.return_value = True
        return user

    @patch("tenants.auth_backends.TenantMembership.objects.filter")
    def test_superuser_can_authenticate_without_membership(self, membership_filter):
        tenant = SimpleNamespace(schema_name="clinica_a", is_active=True)
        request = SimpleNamespace(tenant=tenant)
        user = self._user(is_superuser=True)

        with (
            patch.object(self.backend, "_get_user_by_login", return_value=user),
            patch.object(self.backend, "user_can_authenticate", return_value=True),
        ):
            authenticated = self.backend.authenticate(request=request, username="admin", password="secret")

        self.assertIs(authenticated, user)
        membership_filter.assert_not_called()

    @patch("tenants.auth_backends.TenantMembership.objects.filter")
    def test_regular_user_requires_membership(self, membership_filter):
        tenant = SimpleNamespace(schema_name="clinica_a", is_active=True)
        request = SimpleNamespace(tenant=tenant)
        user = self._user(is_superuser=False)
        membership_filter.return_value.exists.return_value = False

        with (
            patch.object(self.backend, "_get_user_by_login", return_value=user),
            patch.object(self.backend, "user_can_authenticate", return_value=True),
        ):
            authenticated = self.backend.authenticate(request=request, username="usuario", password="secret")

        self.assertIsNone(authenticated)
        membership_filter.assert_called_once()

    @patch("tenants.auth_backends.TenantMembership.objects.filter")
    def test_regular_user_with_membership_can_authenticate(self, membership_filter):
        tenant = SimpleNamespace(schema_name="clinica_a", is_active=True)
        request = SimpleNamespace(tenant=tenant)
        user = self._user(is_superuser=False)
        membership_filter.return_value.exists.return_value = True

        with (
            patch.object(self.backend, "_get_user_by_login", return_value=user),
            patch.object(self.backend, "user_can_authenticate", return_value=True),
        ):
            authenticated = self.backend.authenticate(request=request, username="usuario", password="secret")

        self.assertIs(authenticated, user)
        membership_filter.assert_called_once()

    @patch("tenants.auth_backends.TenantMembership.objects.filter")
    def test_inactive_tenant_denies_authentication(self, membership_filter):
        tenant = SimpleNamespace(schema_name="clinica_a", is_active=False)
        request = SimpleNamespace(tenant=tenant)
        user = self._user(is_superuser=True)

        with (
            patch.object(self.backend, "_get_user_by_login", return_value=user),
            patch.object(self.backend, "user_can_authenticate", return_value=True),
        ):
            authenticated = self.backend.authenticate(request=request, username="admin", password="secret")

        self.assertIsNone(authenticated)
        membership_filter.assert_not_called()

    def test_ambiguous_case_insensitive_username_match_is_rejected(self):
        user_model = MagicMock()
        user_model.USERNAME_FIELD = "username"

        username_matches = MagicMock()
        username_matches.count.return_value = 2
        user_model._default_manager.filter.return_value.order_by.return_value = username_matches

        user = self.backend._get_user_by_login(user_model, "Admin")

        self.assertIsNone(user)


class BootstrapClinicCommandTests(SimpleTestCase):
    @patch("tenants.management.commands.bootstrap_clinic.create_tenant")
    def test_wraps_provision_errors(self, create_tenant_mock):
        create_tenant_mock.side_effect = TenantProvisionError("fallo controlado")

        command = BootstrapClinicCommand()
        with self.assertRaises(CommandError):
            command.handle(
                schema_name="clinica_a",
                name="Clinica A",
                domain="clinica-a.example.com",
                plan="shared",
                admin_user=None,
                admin_email=None,
                admin_password=None,
            )


class TenantCreateFormTests(SimpleTestCase):
    def test_schema_and_subdomain_are_normalized(self):
        form = TenantCreateForm(
            data={
                "name": "El Rosal",
                "schema_name": "El-Rosal",
                "subdomain": "El_rosal",
                "plan": "shared",
                "admin_username": "",
                "admin_email": "",
                "admin_password": "",
            }
        )

        self.assertTrue(form.is_valid())
        self.assertEqual(form.cleaned_data["schema_name"], "el_rosal")
        self.assertEqual(form.cleaned_data["subdomain"], "el-rosal.localhost")

    @patch("tenants.forms.get_user_model")
    def test_existing_admin_user_can_be_reused_without_password(self, get_user_model):
        user_model = MagicMock()
        user_model._default_manager.filter.return_value.count.return_value = 1
        get_user_model.return_value = user_model

        form = TenantCreateForm(
            data={
                "name": "Clinica A",
                "schema_name": "clinica_a",
                "subdomain": "clinica-a",
                "plan": "shared",
                "admin_username": "admin",
                "admin_email": "admin@example.com",
                "admin_password": "",
            }
        )

        self.assertTrue(form.is_valid())

    @patch("tenants.forms.get_user_model")
    def test_new_admin_user_requires_password(self, get_user_model):
        user_model = MagicMock()
        user_model._default_manager.filter.return_value.count.return_value = 0
        get_user_model.return_value = user_model

        form = TenantCreateForm(
            data={
                "name": "Clinica A",
                "schema_name": "clinica_a",
                "subdomain": "clinica-a",
                "plan": "shared",
                "admin_username": "admin",
                "admin_email": "admin@example.com",
                "admin_password": "",
            }
        )

        self.assertFalse(form.is_valid())
        self.assertIn("admin_password", form.errors)

    @patch("tenants.forms.get_user_model")
    def test_ambiguous_admin_username_is_rejected(self, get_user_model):
        user_model = MagicMock()
        user_model._default_manager.filter.return_value.count.return_value = 2
        get_user_model.return_value = user_model

        form = TenantCreateForm(
            data={
                "name": "Clinica A",
                "schema_name": "clinica_a",
                "subdomain": "clinica-a",
                "plan": "shared",
                "admin_username": "Admin",
                "admin_email": "admin@example.com",
                "admin_password": "NuevaClave123",
            }
        )

        self.assertFalse(form.is_valid())
        self.assertIn("admin_username", form.errors)


class AddMemberFormTests(SimpleTestCase):
    @patch("tenants.forms.get_user_model")
    def test_existing_global_user_is_valid(self, get_user_model):
        user_model = MagicMock()
        user_model._default_manager.filter.return_value.count.return_value = 1
        get_user_model.return_value = user_model

        form = AddMemberForm(
            data={
                "username": "admin",
                "role": "clinic_admin",
            }
        )

        self.assertTrue(form.is_valid())

    @patch("tenants.forms.get_user_model")
    def test_unknown_user_is_rejected(self, get_user_model):
        user_model = MagicMock()
        user_model._default_manager.filter.return_value.count.return_value = 0
        get_user_model.return_value = user_model

        form = AddMemberForm(
            data={
                "username": "fantasma",
                "role": "assistant",
            }
        )

        self.assertFalse(form.is_valid())
        self.assertIn("username", form.errors)

    @patch("tenants.forms.get_user_model")
    def test_ambiguous_user_is_rejected(self, get_user_model):
        user_model = MagicMock()
        user_model._default_manager.filter.return_value.count.return_value = 2
        get_user_model.return_value = user_model

        form = AddMemberForm(
            data={
                "username": "Admin",
                "role": "assistant",
            }
        )

        self.assertFalse(form.is_valid())
        self.assertIn("username", form.errors)


class TenantProvisionServiceTests(SimpleTestCase):
    @patch("tenants.services.Domain")
    @patch("tenants.services.Client")
    def test_rejects_invalid_plan_before_creating_records(self, client_cls, domain_cls):
        with self.assertRaises(TenantProvisionError):
            create_tenant(
                schema_name="clinica_a",
                name="Clinica A",
                domain="clinica-a.example.com",
                plan="gold",
            )

        client_cls.assert_not_called()
        domain_cls.assert_not_called()

    @patch("tenants.services.Domain")
    @patch("tenants.services.Client")
    def test_rejects_invalid_domain_before_creating_records(self, client_cls, domain_cls):
        with self.assertRaises(TenantProvisionError):
            create_tenant(
                schema_name="clinica_a",
                name="Clinica A",
                domain="clinica_a",
                plan="shared",
            )

        client_cls.assert_not_called()
        domain_cls.assert_not_called()

    @patch("tenants.services.schema_context")
    @patch("tenants.services.call_command")
    @patch("tenants.services.Domain")
    @patch("tenants.services.Client")
    def test_rolls_back_when_seed_fails(self, client_cls, domain_cls, call_command, schema_context):
        client_cls.objects.filter.return_value.exists.return_value = False
        domain_cls.objects.filter.return_value.exists.return_value = False

        client = MagicMock()
        client.schema_name = "clinica_a"
        client.pk = 1
        client_cls.return_value = client

        schema_context.return_value = MagicMock()
        call_command.side_effect = RuntimeError("seed failed")

        with self.assertRaises(TenantProvisionError):
            create_tenant(
                schema_name="clinica_a",
                name="Clinica A",
                domain="clinica-a.example.com",
                plan="shared",
            )

        client.delete.assert_called_once_with(force_drop=True)

    @patch("tenants.services.Domain")
    @patch("tenants.services.Client")
    def test_rolls_back_when_domain_create_fails(self, client_cls, domain_cls):
        client_cls.objects.filter.return_value.exists.return_value = False
        domain_cls.objects.filter.return_value.exists.return_value = False
        domain_cls.objects.create.side_effect = RuntimeError("domain conflict")

        client = MagicMock()
        client.schema_name = "clinica_a"
        client.pk = 1
        client_cls.return_value = client

        with self.assertRaises(TenantProvisionError):
            create_tenant(
                schema_name="clinica_a",
                name="Clinica A",
                domain="clinica-a.example.com",
                plan="shared",
            )

        client.delete.assert_called_once_with(force_drop=True)

    @patch("tenants.services.TenantMembership.objects.get_or_create")
    @patch("tenants.services.get_user_model")
    def test_existing_user_keeps_global_credentials(self, get_user_model, membership_get_or_create):
        user_model = MagicMock()
        existing_user = MagicMock()
        existing_user.email = "admin@actual.example"
        username_matches = user_model._default_manager.filter.return_value.order_by.return_value
        username_matches.count.return_value = 1
        username_matches.first.return_value = existing_user
        get_user_model.return_value = user_model

        membership = MagicMock()
        membership.is_admin = True
        membership.is_active = True
        membership_get_or_create.return_value = (membership, True)

        notices = ensure_tenant_admin_membership(
            tenant=SimpleNamespace(),
            username="admin",
            email="nuevo@example.com",
            password="NuevaClave123",
        )

        existing_user.set_password.assert_not_called()
        existing_user.save.assert_not_called()
        self.assertEqual(
            notices,
            [
                "El usuario 'admin' ya existia; su contrasena global no fue modificada.",
                "El usuario 'admin' ya existia; su correo global no fue modificado.",
            ],
        )

    @patch("tenants.services.TenantMembership.objects.get_or_create")
    @patch("tenants.services.get_user_model")
    def test_assign_membership_requires_existing_global_user(self, get_user_model, membership_get_or_create):
        user_model = MagicMock()
        username_matches = user_model._default_manager.filter.return_value.order_by.return_value
        username_matches.count.return_value = 0
        username_matches.first.return_value = None
        get_user_model.return_value = user_model

        with self.assertRaises(TenantProvisionError):
            assign_tenant_membership(
                tenant=SimpleNamespace(),
                username="nuevo",
                role="clinic_admin",
            )

        membership_get_or_create.assert_not_called()

    @patch("tenants.services.TenantMembership.objects.get_or_create")
    @patch("tenants.services.get_user_model")
    def test_assign_membership_updates_local_role_without_touching_global_flags(
        self,
        get_user_model,
        membership_get_or_create,
    ):
        user_model = MagicMock()
        existing_user = MagicMock()
        existing_user.is_staff = False
        username_matches = user_model._default_manager.filter.return_value.order_by.return_value
        username_matches.count.return_value = 1
        username_matches.first.return_value = existing_user
        get_user_model.return_value = user_model

        membership = MagicMock()
        membership.is_admin = False
        membership.is_active = False
        membership_get_or_create.return_value = (membership, False)

        result = assign_tenant_membership(
            tenant=SimpleNamespace(),
            username="admin",
            role="clinic_admin",
        )

        self.assertFalse(result.membership_created)
        membership.save.assert_called_once_with(update_fields=["role", "is_admin", "is_active"])
        existing_user.save.assert_not_called()
        self.assertFalse(existing_user.is_staff)

    @patch("tenants.services.TenantMembership.objects.get_or_create")
    @patch("tenants.services.get_user_model")
    def test_new_admin_user_is_deleted_if_membership_assignment_fails(
        self,
        get_user_model,
        membership_get_or_create,
    ):
        user_model = MagicMock()
        username_matches = user_model._default_manager.filter.return_value.order_by.return_value
        username_matches.count.return_value = 0
        username_matches.first.return_value = None
        created_user = MagicMock()
        user_model._default_manager.create_user.return_value = created_user
        get_user_model.return_value = user_model
        membership_get_or_create.side_effect = RuntimeError("membership failed")

        with self.assertRaises(TenantProvisionError):
            ensure_tenant_admin_membership(
                tenant=SimpleNamespace(),
                username="nuevo_admin",
                email="nuevo@onne.local",
                password="Temporal123",
            )

        created_user.delete.assert_called_once()


class TenantObservabilityTests(TestCase):
    def test_diagnostics_reports_missing_domain_and_admin(self):
        tenant = SimpleNamespace(pk=1, name="Clinica A", schema_name="clinica_a", plan="shared", is_active=True)
        diagnostics = build_tenant_diagnostics(tenant, domains=[], memberships=[])

        self.assertEqual(diagnostics.status, "error")
        self.assertTrue(any(alert.code == "missing_domain" for alert in diagnostics.alerts))
        self.assertTrue(any(alert.code == "missing_active_admin" for alert in diagnostics.alerts))

    def test_diagnostics_reports_plan_limit_overrun(self):
        tenant = SimpleNamespace(pk=2, name="Clinica B", schema_name="clinica_b", plan="shared", is_active=True)
        domains = [SimpleNamespace(domain="clinica-b.localhost", is_primary=True)]
        memberships = [
            SimpleNamespace(is_active=True, is_admin=(index == 0))
            for index in range(21)
        ]

        diagnostics = build_tenant_diagnostics(tenant, domains=domains, memberships=memberships)

        self.assertEqual(diagnostics.status, "warning")
        self.assertTrue(any(alert.code == "plan_user_limit_exceeded" for alert in diagnostics.alerts))

    def test_system_health_payload_for_tenant_uses_diagnostics_status(self):
        tenant = SimpleNamespace(pk=3, name="Clinica C", schema_name="clinica_c", plan="shared", is_active=False)
        diagnostics = SimpleNamespace(
            tenant=tenant,
            status="error",
            alerts=("a", "b", "c", "d"),
        )

        with (
            patch("tenants.observability.connection.cursor") as cursor_mock,
            patch("tenants.observability.build_tenant_diagnostics", return_value=diagnostics),
        ):
            cursor = MagicMock()
            cursor_mock.return_value.__enter__.return_value = cursor

            payload, status_code = build_system_health_payload(tenant=tenant)

        self.assertEqual(status_code, 503)
        self.assertEqual(payload["tenant"]["schema_name"], "clinica_c")
        self.assertEqual(payload["alerts_count"], 4)


class LoginRequiredMiddlewareTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.middleware = LoginRequiredMiddleware(lambda request: HttpResponse("ok"))

    def test_health_endpoint_is_public(self):
        request = self.factory.get("/health/")
        request.user = SimpleNamespace(is_authenticated=False)

        response = self.middleware(request)

        self.assertEqual(response.status_code, 200)


class TenantCapabilityRequiredTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()

    @patch("tenants.permissions.messages.error")
    def test_redirects_when_plan_does_not_include_capability(self, error_message):
        @tenant_capability_required("billing.basic")
        def protected_view(request):
            return HttpResponse("ok")

        request = self.factory.get("/billing/")
        request.tenant = SimpleNamespace(has_capability=lambda capability: False)

        response = protected_view(request)

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, "/")
        error_message.assert_called_once()


class TenantAccessMiddlewareTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.middleware = TenantAccessMiddleware(lambda request: HttpResponse("ok"))

    @patch("tenants.middleware.messages.error")
    @patch("tenants.middleware.build_public_app_url", return_value="https://portal.example.com/")
    @patch("tenants.middleware.TenantMembership.objects.filter")
    def test_missing_membership_redirects_without_logging_out(
        self,
        membership_filter,
        public_url,
        error_message,
    ):
        request = self.factory.get("/")
        request.tenant = SimpleNamespace(schema_name="clinica_a", is_active=True)
        request.user = SimpleNamespace(is_authenticated=True, is_superuser=False)
        membership_filter.return_value.first.return_value = None

        response = self.middleware(request)

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, "https://portal.example.com/")
        membership_filter.assert_called_once()
        public_url.assert_called_once_with(request, "dashboard")
        error_message.assert_called_once()

    @patch("tenants.middleware.TenantMembership.objects.filter")
    def test_active_membership_is_attached_to_request(self, membership_filter):
        request = self.factory.get("/")
        membership = SimpleNamespace()
        request.tenant = SimpleNamespace(schema_name="clinica_a", is_active=True)
        request.user = SimpleNamespace(is_authenticated=True, is_superuser=False)
        membership_filter.return_value.first.return_value = membership

        response = self.middleware(request)

        self.assertEqual(response.status_code, 200)
        self.assertIs(request.tenant_membership, membership)

    @patch("tenants.middleware.messages.error")
    @patch("tenants.middleware.build_public_app_url", return_value="https://portal.example.com/")
    @patch("tenants.middleware.TenantMembership.objects.filter")
    def test_inactive_tenant_redirects_before_membership_check(
        self,
        membership_filter,
        public_url,
        error_message,
    ):
        request = self.factory.get("/")
        request.tenant = SimpleNamespace(schema_name="clinica_a", is_active=False)
        request.user = SimpleNamespace(is_authenticated=True, is_superuser=False)

        response = self.middleware(request)

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, "https://portal.example.com/")
        membership_filter.assert_not_called()
        public_url.assert_called_once_with(request, "dashboard")
        error_message.assert_called_once()
