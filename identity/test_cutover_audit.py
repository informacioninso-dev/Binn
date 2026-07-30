from __future__ import annotations

from contextlib import nullcontext
from io import StringIO
from types import SimpleNamespace
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase

from identity.cutover_audit import (
    STATUS_FRESH_READY,
    STATUS_LEGACY_RUNBOOK_REQUIRED,
    STATUS_MANUAL_REVIEW,
    AuthUserReference,
    run_identity_cutover_audit,
)


class _FakeCursor:
    def __init__(self, migration_rows=None):
        self.migration_rows = migration_rows or []
        self.last_sql = ""

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, sql, params=None):
        self.last_sql = sql

    def fetchall(self):
        if "FROM django_migrations" in self.last_sql:
            return list(self.migration_rows)
        return []


class _FakeIntrospection:
    def __init__(self, *, tables, constraints_by_table=None):
        self.tables = list(tables)
        self.constraints_by_table = constraints_by_table or {}

    def table_names(self, cursor):
        return list(self.tables)

    def get_constraints(self, cursor, table_name):
        return dict(self.constraints_by_table.get(table_name, {}))


class _FakeConnection:
    def __init__(self, *, tables, migration_rows=None, constraints_by_table=None):
        self._cursor = _FakeCursor(migration_rows=migration_rows)
        self.introspection = _FakeIntrospection(
            tables=tables,
            constraints_by_table=constraints_by_table,
        )

    def cursor(self):
        return self._cursor


class IdentityCutoverAuditTests(SimpleTestCase):
    def test_detects_fresh_ready_base_without_auth_user(self):
        connection = _FakeConnection(
            tables={"django_migrations", "identity_user", "access_tenantmembership"},
            migration_rows=[("0001_initial",), ("0002_extra",)],
        )

        audit = run_identity_cutover_audit(connection_obj=connection)

        self.assertEqual(audit.status, STATUS_FRESH_READY)
        self.assertFalse(audit.has_auth_user_table)
        self.assertEqual(audit.identity_migrations_applied, ("0001_initial", "0002_extra"))
        self.assertEqual(audit.auth_user_references, ())

    def test_detects_legacy_runbook_required_when_constraints_still_point_to_auth_user(self):
        connection = _FakeConnection(
            tables={"django_migrations", "identity_user", "auth_user", "access_tenantmembership"},
            migration_rows=[("0001_initial",)],
            constraints_by_table={
                "access_tenantmembership": {
                    "access_tenantmembership_user_id_fk": {
                        "columns": ["user_id"],
                        "foreign_key": ("auth_user", "id"),
                    }
                }
            },
        )

        audit = run_identity_cutover_audit(connection_obj=connection)

        self.assertEqual(audit.status, STATUS_LEGACY_RUNBOOK_REQUIRED)
        self.assertEqual(len(audit.auth_user_references), 1)
        self.assertEqual(audit.auth_user_references[0].table_name, "access_tenantmembership")
        self.assertTrue(audit.is_blocking)

    def test_detects_manual_review_when_auth_user_survives_without_active_constraints(self):
        connection = _FakeConnection(
            tables={"django_migrations", "identity_user", "auth_user"},
            migration_rows=[("0001_initial",)],
        )

        audit = run_identity_cutover_audit(connection_obj=connection)

        self.assertEqual(audit.status, STATUS_MANUAL_REVIEW)
        self.assertIn("revision manual", audit.recommended_next_step.lower())


class AuditIdentityCutoverCommandTests(SimpleTestCase):
    @patch("identity.management.commands.audit_identity_cutover.get_public_schema_name", return_value="public")
    @patch("identity.management.commands.audit_identity_cutover.schema_context", return_value=nullcontext())
    @patch("identity.management.commands.audit_identity_cutover.run_identity_cutover_audit")
    def test_command_prints_summary(self, run_audit, schema_context_mock, public_schema_mock):
        run_audit.return_value = SimpleNamespace(
            status=STATUS_FRESH_READY,
            summary="La base ya opera con identity_user y no expone auth_user.",
            recommended_next_step="Continuar sobre la base actual; no hace falta runbook legado.",
            has_identity_user_table=True,
            has_auth_user_table=False,
            identity_migrations_applied=("0001_initial",),
            auth_user_references=(),
            notes=(),
            is_blocking=False,
        )
        stdout = StringIO()

        call_command("audit_identity_cutover", stdout=stdout)

        output = stdout.getvalue()
        self.assertIn("FRESH_READY", output)
        self.assertIn("Ruta recomendada", output)
        self.assertIn("identity_user detectado: si", output)

    @patch("identity.management.commands.audit_identity_cutover.get_public_schema_name", return_value="public")
    @patch("identity.management.commands.audit_identity_cutover.schema_context", return_value=nullcontext())
    @patch("identity.management.commands.audit_identity_cutover.run_identity_cutover_audit")
    def test_command_strict_fails_on_blocking_audit(self, run_audit, schema_context_mock, public_schema_mock):
        run_audit.return_value = SimpleNamespace(
            status=STATUS_LEGACY_RUNBOOK_REQUIRED,
            summary="La base tiene identity_user, pero mantiene referencias activas a auth_user.",
            recommended_next_step="Ejecuta el runbook legado antes de seguir con trabajo de migraciones o despliegue.",
            has_identity_user_table=True,
            has_auth_user_table=True,
            identity_migrations_applied=("0001_initial",),
            auth_user_references=(
                AuthUserReference(
                    table_name="access_tenantmembership",
                    constraint_name="access_tenantmembership_user_id_fk",
                    columns=("user_id",),
                ),
            ),
            notes=("Se detectaron 1 referencias foraneas activas hacia auth_user.",),
            is_blocking=True,
        )

        with self.assertRaises(CommandError):
            call_command("audit_identity_cutover", "--strict")
