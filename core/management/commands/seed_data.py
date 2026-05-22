from django.core.management.base import BaseCommand

from tenants.models import Client
from tenants.services import sync_tenant_object_schemas, sync_tenant_pipelines


class Command(BaseCommand):
    help = "Crea la estructura inicial del tenant Binn."

    def add_arguments(self, parser):
        parser.add_argument("--tenant-id", dest="tenant_id", type=int)

    def handle(self, *args, **options):
        tenant_id = options.get("tenant_id")
        tenant = Client.objects.filter(pk=tenant_id).first() if tenant_id else None
        if tenant is None:
            self.stdout.write(self.style.WARNING("Seed omitido: no se encontro el tenant."))
            return

        notices = sync_tenant_pipelines(tenant)
        notices.extend(sync_tenant_object_schemas(tenant))
        for notice in notices:
            self.stdout.write(self.style.WARNING(notice))

        self.stdout.write(self.style.SUCCESS("Seed base ejecutado correctamente."))
