from django.core.management.base import BaseCommand, CommandError
from django.core.management import call_command
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django_tenants.utils import schema_context

from tenants.models import Client, Domain, TenantMembership


class Command(BaseCommand):
    help = "Crear un tenant (schema) y cargar seed basico."

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

        client = Client(schema_name=schema_name, name=name, plan=plan, is_active=True)
        client.save()
        Domain.objects.create(domain=domain, tenant=client, is_primary=True)

        call_command("migrate_schemas", schema_name=client.schema_name, interactive=False, verbosity=0)
        with schema_context(client.schema_name):
            call_command("seed_data", verbosity=0)
            try:
                from core.models import CompanyConfig
                config = CompanyConfig.get()
                if config:
                    config.legal_name = client.name
                    if not config.trade_name:
                        config.trade_name = client.name
                    config.save(update_fields=["legal_name", "trade_name"])
            except Exception:
                pass

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
                if admin_email and not user.email:
                    user.email = admin_email
                if admin_password:
                    user.set_password(admin_password)
                user.save()

            admin_group, _ = Group.objects.get_or_create(name="admin")
            user.groups.add(admin_group)
            TenantMembership.objects.get_or_create(
                tenant=client,
                user=user,
                defaults={"is_admin": True, "is_active": True},
            )

        self.stdout.write(self.style.SUCCESS(f"Tenant {client.schema_name} creado."))
