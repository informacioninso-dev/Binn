import json
from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase

from core.preflight import PreflightCheck


class PlatformPreflightCommandTests(SimpleTestCase):
    @patch("core.management.commands.platform_preflight.run_platform_preflight")
    def test_command_can_emit_json_payload(self, run_platform_preflight_mock):
        run_platform_preflight_mock.return_value = [
            PreflightCheck(
                code="realtime_runtime",
                label="Realtime",
                status="warn",
                message="Realtime en memoria.",
            ),
            PreflightCheck(
                code="database_runtime",
                label="Base de datos",
                status="ok",
                message="Base de datos responde.",
            ),
        ]
        stdout = StringIO()

        call_command("platform_preflight", "--json", stdout=stdout)

        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["summary"], {"ok": 1, "warn": 1, "fail": 0})
        self.assertEqual(payload["checks"][0]["code"], "realtime_runtime")
        self.assertEqual(payload["checks"][1]["status"], "ok")

    @patch("core.management.commands.platform_preflight.run_platform_preflight")
    def test_command_can_fail_on_warn(self, run_platform_preflight_mock):
        run_platform_preflight_mock.return_value = [
            PreflightCheck(
                code="cache_runtime",
                label="Cache operativo",
                status="warn",
                message="LocMem en uso.",
            )
        ]

        with self.assertRaisesMessage(
            CommandError,
            "El preflight detecto warnings o checks bloqueantes.",
        ):
            call_command("platform_preflight", "--fail-on-warn")
