from __future__ import annotations

from types import SimpleNamespace

from django.core.cache import cache
from django.test import RequestFactory, SimpleTestCase, override_settings

from .security import evaluate_login_throttle, register_login_failure, reset_login_throttle


@override_settings(
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "identity-tests"}},
    LOGIN_RATE_LIMIT_ATTEMPTS=3,
    LOGIN_RATE_LIMIT_WINDOW_SECONDS=60,
    LOGIN_RATE_LIMIT_LOCKOUT_SECONDS=120,
)
class LoginThrottleTests(SimpleTestCase):
    def setUp(self):
        super().setUp()
        cache.clear()
        self.factory = RequestFactory()

    def _request(self):
        request = self.factory.post("/accounts/login/", data={"username": "demo", "password": "bad"})
        request.tenant = SimpleNamespace(schema_name="public")
        request.META["REMOTE_ADDR"] = "127.0.0.1"
        return request

    def test_login_throttle_locks_after_configured_failures(self):
        request = self._request()

        first = register_login_failure(request=request, login_value="demo")
        second = register_login_failure(request=request, login_value="demo")
        third = register_login_failure(request=request, login_value="demo")
        decision = evaluate_login_throttle(request=request, login_value="demo")

        self.assertTrue(first.allowed)
        self.assertTrue(second.allowed)
        self.assertFalse(third.allowed)
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.retry_after_seconds, 120)

    def test_reset_login_throttle_clears_lock(self):
        request = self._request()

        for _ in range(3):
            register_login_failure(request=request, login_value="demo")

        reset_login_throttle(request=request, login_value="demo")
        decision = evaluate_login_throttle(request=request, login_value="demo")

        self.assertTrue(decision.allowed)
