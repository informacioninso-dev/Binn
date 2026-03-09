from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.core.management.base import CommandError
from django.test import SimpleTestCase

from tenants.auth_backends import TenantAwareBackend
from tenants.management.commands.bootstrap_clinic import Command as BootstrapClinicCommand


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


class BootstrapClinicCommandTests(SimpleTestCase):
    @patch("tenants.management.commands.bootstrap_clinic.schema_context")
    @patch("tenants.management.commands.bootstrap_clinic.call_command")
    @patch("tenants.management.commands.bootstrap_clinic.Domain")
    @patch("tenants.management.commands.bootstrap_clinic.Client")
    def test_rolls_back_when_seed_fails(self, client_cls, domain_cls, call_command, schema_context):
        client_cls.objects.filter.return_value.exists.return_value = False
        domain_cls.objects.filter.return_value.exists.return_value = False

        client = MagicMock()
        client.schema_name = "clinica_a"
        client.pk = 1
        client_cls.return_value = client

        schema_context.return_value = MagicMock()
        call_command.side_effect = RuntimeError("seed failed")

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

        client.delete.assert_called_once_with(force_drop=True)

    @patch("tenants.management.commands.bootstrap_clinic.call_command")
    @patch("tenants.management.commands.bootstrap_clinic.Domain")
    @patch("tenants.management.commands.bootstrap_clinic.Client")
    def test_rolls_back_when_domain_create_fails(self, client_cls, domain_cls, call_command):
        client_cls.objects.filter.return_value.exists.return_value = False
        domain_cls.objects.filter.return_value.exists.return_value = False
        domain_cls.objects.create.side_effect = RuntimeError("domain conflict")

        client = MagicMock()
        client.schema_name = "clinica_a"
        client.pk = 1
        client_cls.return_value = client

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

        call_command.assert_not_called()
        client.delete.assert_called_once_with(force_drop=True)
