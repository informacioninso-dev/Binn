from types import SimpleNamespace
from unittest.mock import patch

from django.core.exceptions import PermissionDenied
from django.test import SimpleTestCase

from access.contracts import AccessDecision, AccessSubject, ActiveSessionContext, SessionScope
from access.permissions import ensure_request_tenant_permission, request_has_tenant_permission
from access.services import load_active_session_context, resolve_request_access


class ActiveSessionContextLoadingTests(SimpleTestCase):
    @patch("access.services.ensure_active_access_context")
    def test_load_active_session_context_maps_context_record(self, ensure_context_mock):
        ensure_context_mock.return_value = SimpleNamespace(
            scope=SessionScope.CONSOLIDATED.value,
            active_tenant_id=9,
            corporate_group_id=14,
            impersonator_id=3,
            reason="group_switch",
        )

        context = load_active_session_context(SimpleNamespace())

        self.assertEqual(
            context,
            ActiveSessionContext(
                scope=SessionScope.CONSOLIDATED,
                tenant_id=9,
                corporate_group_id=14,
                impersonator_user_id=3,
                reason="group_switch",
            ),
        )

    @patch("access.services.ensure_active_access_context", return_value=None)
    def test_load_active_session_context_returns_none_without_record(self, ensure_context_mock):
        self.assertIsNone(load_active_session_context(SimpleNamespace()))


class AccessResolutionTests(SimpleTestCase):
    @patch("access.services.RequestAccessResolver")
    def test_resolve_request_access_caches_decisions_per_permission(self, resolver_class_mock):
        decision = AccessDecision(
            allowed=True,
            scope=SessionScope.STRICT_ISOLATION,
            tenant_id=5,
            reason="direct_membership",
        )
        resolver = resolver_class_mock.return_value
        resolver.resolve.return_value = decision
        request = SimpleNamespace(
            access_subject=AccessSubject(user_id=7, active=True),
            active_session_context=ActiveSessionContext(scope=SessionScope.STRICT_ISOLATION, tenant_id=5),
            tenant=SimpleNamespace(pk=5),
            user=SimpleNamespace(is_authenticated=True),
        )

        first = resolve_request_access(request, "entities.view")
        second = resolve_request_access(request, "entities.view")

        self.assertIs(first, decision)
        self.assertIs(second, decision)
        resolver_class_mock.assert_called_once_with(request)
        resolver.resolve.assert_called_once_with(
            subject=request.access_subject,
            context=request.active_session_context,
            target_tenant_id=5,
            permission_code="entities.view",
        )


class PermissionGuardTests(SimpleTestCase):
    @patch("access.permissions.get_request_membership")
    @patch("access.permissions.resolve_request_access")
    def test_request_has_tenant_permission_uses_resolver_before_membership_lookup(
        self,
        resolve_access_mock,
        membership_mock,
    ):
        resolve_access_mock.return_value = AccessDecision(
            allowed=True,
            scope=SessionScope.STRICT_ISOLATION,
            tenant_id=11,
            reason="resolved",
        )
        membership_mock.side_effect = AssertionError("membership lookup should not run")
        request = SimpleNamespace(
            user=SimpleNamespace(is_superuser=False),
            tenant=SimpleNamespace(pk=11),
        )

        allowed = request_has_tenant_permission(request, "deals.edit")

        self.assertTrue(allowed)

    @patch("access.permissions.request_has_tenant_permission", return_value=False)
    @patch("access.permissions.get_request_membership", return_value=None)
    def test_ensure_request_tenant_permission_raises_when_permission_is_missing(
        self,
        membership_mock,
        permission_mock,
    ):
        request = SimpleNamespace(
            tenant=SimpleNamespace(has_capability=lambda capability: True),
            tenant_membership=None,
            user=SimpleNamespace(is_authenticated=True, is_superuser=False),
        )

        with self.assertRaises(PermissionDenied) as raised:
            ensure_request_tenant_permission(request, "collections.edit", capability="collections")

        self.assertEqual(str(raised.exception), "missing_permission")
