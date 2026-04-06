from django.core.management.base import BaseCommand, CommandError

from tenants.models import Client
from tenants.observability import record_tenant_event
from tenants.services import TenantProvisionError, create_tenant


class Command(BaseCommand):
    help = "Crear una clinica (tenant schema), migrarla y asignar admin opcional."

    def add_arguments(self, parser):
        parser.add_argument("schema_name")
        parser.add_argument("name")
        parser.add_argument("domain")
        parser.add_argument("--plan", default=Client.PLAN_SHARED)
        parser.add_argument("--admin-user", dest="admin_user")
        parser.add_argument("--admin-email", dest="admin_email")
        parser.add_argument("--admin-password", dest="admin_password")

    def handle(self, *args, **options):
        try:
            result = create_tenant(
                schema_name=options["schema_name"],
                name=options["name"],
                domain=options["domain"],
                plan=options["plan"],
                admin_username=options.get("admin_user") or "",
                admin_email=options.get("admin_email") or "",
                admin_password=options.get("admin_password") or "",
            )
        except TenantProvisionError as exc:
            raise CommandError(str(exc)) from exc

        for notice in result.notices:
            self.stdout.write(self.style.WARNING(notice))

        record_tenant_event(
            tenant=result.client,
            title="Clinica creada por comando",
            message="Se provisiono la clinica desde bootstrap_clinic.",
            code="tenant_created_cli",
        )
        self.stdout.write(self.style.SUCCESS(f"Clinica {result.client.schema_name} creada."))
