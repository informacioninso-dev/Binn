from django.core.management.base import BaseCommand, CommandError
from django.core.management import call_command
from django.contrib.auth import get_user_model
from django_tenants.utils import schema_context

from tenants.models import Client, Domain, TenantMembership


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
        schema_name = options["schema_name"].strip().lower()
        name = options["name"].strip()
        domain = options["domain"].strip().lower()
        plan = options["plan"]

        if schema_name == "public":
            raise CommandError("El schema 'public' esta reservado.")

        if Client.objects.filter(schema_name=schema_name).exists():
            raise CommandError(f"Ya existe una clinica con schema '{schema_name}'.")
        if Domain.objects.filter(domain=domain).exists():
            raise CommandError(f"Ya existe un dominio '{domain}'.")

        client = None
        try:
            client = Client(schema_name=schema_name, name=name, plan=plan, is_active=True)
            client.save()
            Domain.objects.create(domain=domain, tenant=client, is_primary=True)
        except Exception as exc:
            if client and getattr(client, "pk", None):
                self._safe_drop_client(client)
            raise CommandError(f"No se pudo crear la clinica '{schema_name}': {exc}") from exc

        try:
            with schema_context(client.schema_name):
                call_command("seed_data", verbosity=0)
        except Exception as exc:
            self._safe_drop_client(client)
            raise CommandError(
                f"No se pudo inicializar la clinica '{client.schema_name}'. Se revirtio la creacion: {exc}"
            ) from exc

        admin_user = options.get("admin_user")
        admin_email = options.get("admin_email")
        admin_password = options.get("admin_password")

        if admin_user:
            User = get_user_model()
            user, created = User.objects.get_or_create(
                username=admin_user,
                defaults={"email": admin_email or "", "is_staff": True},
            )
            if created or admin_password:
                user.is_staff = True
                if admin_email:
                    user.email = admin_email
                if admin_password:
                    user.set_password(admin_password)
                user.save()

            TenantMembership.objects.get_or_create(
                tenant=client,
                user=user,
                defaults={"is_admin": True, "is_active": True},
            )

        self.stdout.write(self.style.SUCCESS(f"Clinica {client.schema_name} creada."))

    def _safe_drop_client(self, client):
        try:
            client.delete(force_drop=True)
        except Exception as cleanup_exc:
            self.stderr.write(
                self.style.WARNING(
                    f"No se pudo eliminar completamente la clinica '{client.schema_name}': {cleanup_exc}"
                )
            )
