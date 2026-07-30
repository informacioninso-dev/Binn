from __future__ import annotations

from dataclasses import dataclass

from django.db import connection

STATUS_EMPTY_BOOTSTRAP = "empty_bootstrap"
STATUS_FRESH_READY = "fresh_ready"
STATUS_LEGACY_RUNBOOK_REQUIRED = "legacy_runbook_required"
STATUS_MANUAL_REVIEW = "manual_review"

BLOCKING_AUDIT_STATUSES = {
    STATUS_LEGACY_RUNBOOK_REQUIRED,
    STATUS_MANUAL_REVIEW,
}


@dataclass(frozen=True)
class AuthUserReference:
    table_name: str
    constraint_name: str
    columns: tuple[str, ...]
    referenced_table: str = "auth_user"
    referenced_column: str = "id"


@dataclass(frozen=True)
class IdentityCutoverAudit:
    status: str
    summary: str
    recommended_next_step: str
    has_identity_user_table: bool
    has_auth_user_table: bool
    has_django_migrations_table: bool
    identity_migrations_applied: tuple[str, ...]
    auth_user_references: tuple[AuthUserReference, ...]
    notes: tuple[str, ...]

    @property
    def is_blocking(self) -> bool:
        return self.status in BLOCKING_AUDIT_STATUSES


def run_identity_cutover_audit(*, connection_obj=None) -> IdentityCutoverAudit:
    connection_obj = connection_obj or connection

    with connection_obj.cursor() as cursor:
        table_names = {str(name) for name in connection_obj.introspection.table_names(cursor)}
        has_identity_user_table = "identity_user" in table_names
        has_auth_user_table = "auth_user" in table_names
        has_django_migrations_table = "django_migrations" in table_names
        identity_migrations_applied = _load_identity_migrations(
            cursor,
            has_django_migrations_table=has_django_migrations_table,
        )
        auth_user_references = _collect_auth_user_references(
            connection_obj,
            cursor,
            table_names=table_names,
        )

    notes: list[str] = []
    if not has_django_migrations_table:
        notes.append("No se detecto la tabla django_migrations; la base podria no estar inicializada por completo.")
    if has_identity_user_table and not identity_migrations_applied:
        notes.append("Existe identity_user, pero no aparecen migraciones del app identity registradas en django_migrations.")
    if auth_user_references:
        notes.append(f"Se detectaron {len(auth_user_references)} referencias foraneas activas hacia auth_user.")

    if has_identity_user_table and not has_auth_user_table:
        summary = "La base ya opera con identity_user y no expone auth_user."
        recommended = "Continuar sobre la base actual; no hace falta runbook legado."
        status = STATUS_FRESH_READY
    elif not has_identity_user_table and not has_auth_user_table:
        summary = "No se detectaron auth_user ni identity_user; parece una base vacia o aun no inicializada."
        recommended = "Bootstrapea una base fresca y corre migraciones desde cero."
        status = STATUS_EMPTY_BOOTSTRAP
    elif not has_identity_user_table and has_auth_user_table:
        summary = "La base todavia depende de auth_user y no tiene identity_user."
        recommended = "No sigas con migraciones sensibles aqui sin rebuild fresco o runbook legado."
        status = STATUS_LEGACY_RUNBOOK_REQUIRED
    elif auth_user_references:
        summary = "La base tiene identity_user, pero mantiene referencias activas a auth_user."
        recommended = "Ejecuta el runbook legado antes de seguir con trabajo de migraciones o despliegue."
        status = STATUS_LEGACY_RUNBOOK_REQUIRED
    else:
        summary = "La base tiene auth_user e identity_user sin referencias foraneas activas hacia auth_user."
        recommended = "Haz revision manual antes de borrar auth_user o dar por cerrado el cutover."
        status = STATUS_MANUAL_REVIEW
        notes.append("Este estado suele indicar una migracion manual parcial o una base vieja con residuos historicos.")

    return IdentityCutoverAudit(
        status=status,
        summary=summary,
        recommended_next_step=recommended,
        has_identity_user_table=has_identity_user_table,
        has_auth_user_table=has_auth_user_table,
        has_django_migrations_table=has_django_migrations_table,
        identity_migrations_applied=identity_migrations_applied,
        auth_user_references=auth_user_references,
        notes=tuple(notes),
    )


def _load_identity_migrations(cursor, *, has_django_migrations_table: bool) -> tuple[str, ...]:
    if not has_django_migrations_table:
        return ()
    cursor.execute("SELECT name FROM django_migrations WHERE app = %s ORDER BY name", ["identity"])
    return tuple(str(row[0]) for row in cursor.fetchall())


def _collect_auth_user_references(connection_obj, cursor, *, table_names: set[str]) -> tuple[AuthUserReference, ...]:
    references: list[AuthUserReference] = []
    for table_name in sorted(table_names):
        if table_name == "auth_user":
            continue
        constraints = connection_obj.introspection.get_constraints(cursor, table_name)
        for constraint_name, metadata in constraints.items():
            foreign_key = metadata.get("foreign_key")
            if not foreign_key or foreign_key[0] != "auth_user":
                continue
            references.append(
                AuthUserReference(
                    table_name=table_name,
                    constraint_name=str(constraint_name),
                    columns=tuple(str(column) for column in metadata.get("columns", ()) or ()),
                    referenced_column=str(foreign_key[1] or "id"),
                )
            )
    return tuple(references)
