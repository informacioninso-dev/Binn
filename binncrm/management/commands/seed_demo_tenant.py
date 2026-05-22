from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from binncrm.demo_seed import seed_tenant_demo
from tenants.models import Client


class Command(BaseCommand):
    help = "Carga datos de ejemplo dentro de un tenant para revisar el CRM con contenido real."

    def add_arguments(self, parser):
        parser.add_argument("schema_name", help="Schema del tenant a sembrar, por ejemplo: el_rosal")
        parser.add_argument(
            "--actor",
            dest="actor_username",
            help="Usuario global que quedara como creador/responsable de las actividades de demo.",
        )

    def handle(self, *args, **options):
        schema_name = (options["schema_name"] or "").strip().lower()
        tenant = Client.objects.filter(schema_name=schema_name).first()
        if tenant is None:
            raise CommandError(f"No existe un tenant con schema '{schema_name}'.")
        if tenant.schema_name == "public":
            raise CommandError("Debes indicar un tenant privado, no el schema public.")

        actor = self._resolve_actor(tenant, options.get("actor_username"))
        summary = seed_tenant_demo(tenant, actor=actor)

        self.stdout.write(self.style.SUCCESS(f"Seed cargada en '{tenant.schema_name}'"))
        self.stdout.write(f"Perfil: {summary['profile']}")
        self.stdout.write(f"Pipeline base: {summary['pipeline']}")
        for module_key in ("entities", "deals", "activities", "proposals", "collections", "documents", "object_records"):
            counts = summary["counts"][module_key]
            self.stdout.write(
                f"- {module_key}: {counts['total']} total ({counts['created']} creados, {counts['updated']} actualizados)"
            )
        if summary["notices"]:
            self.stdout.write("")
            self.stdout.write("Avisos:")
            for notice in summary["notices"]:
                self.stdout.write(f"- {notice}")

    def _resolve_actor(self, tenant, actor_username: str | None):
        if actor_username:
            user = get_user_model()._default_manager.filter(username__iexact=actor_username.strip()).first()
            if user is None:
                raise CommandError(f"No existe un usuario global con username '{actor_username}'.")
            return user

        membership = (
            tenant.memberships.filter(is_active=True)
            .select_related("user")
            .order_by("-is_admin", "id")
            .first()
        )
        return membership.user if membership else None
