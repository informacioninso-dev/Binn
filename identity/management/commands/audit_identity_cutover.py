from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError
from django_tenants.utils import get_public_schema_name, schema_context

from identity.cutover_audit import (
    STATUS_EMPTY_BOOTSTRAP,
    STATUS_FRESH_READY,
    run_identity_cutover_audit,
)


class Command(BaseCommand):
    help = "Audita si la base compartida ya esta en cutover limpio hacia identity.User o si requiere runbook legado."

    def add_arguments(self, parser):
        parser.add_argument(
            "--strict",
            action="store_true",
            help="Devuelve error si la auditoria detecta un estado que requiere runbook o revision manual.",
        )

    def handle(self, *args, **options):
        public_schema = get_public_schema_name()
        with schema_context(public_schema):
            audit = run_identity_cutover_audit()

        style = self._style_for_status(audit.status)
        self.stdout.write(style(f"[{audit.status.upper()}] {audit.summary}"))
        self.stdout.write(f"Ruta recomendada: {audit.recommended_next_step}")
        self.stdout.write(f"- schema auditado: {public_schema}")
        self.stdout.write(f"- identity_user detectado: {'si' if audit.has_identity_user_table else 'no'}")
        self.stdout.write(f"- auth_user detectado: {'si' if audit.has_auth_user_table else 'no'}")
        self.stdout.write(
            f"- migraciones identity registradas: {', '.join(audit.identity_migrations_applied) if audit.identity_migrations_applied else 'ninguna'}"
        )

        if audit.auth_user_references:
            self.stdout.write("Referencias activas a auth_user:")
            for reference in audit.auth_user_references:
                columns = ", ".join(reference.columns) if reference.columns else "sin columnas reportadas"
                self.stdout.write(f"- {reference.table_name} -> {columns} ({reference.constraint_name})")

        if audit.notes:
            self.stdout.write("Notas:")
            for note in audit.notes:
                self.stdout.write(f"- {note}")

        if options["strict"] and audit.is_blocking:
            raise CommandError("La auditoria detecto una base que requiere runbook legado o revision manual.")

    def _style_for_status(self, status: str):
        if status == STATUS_FRESH_READY:
            return self.style.SUCCESS
        if status == STATUS_EMPTY_BOOTSTRAP:
            return self.style.NOTICE
        return self.style.WARNING
