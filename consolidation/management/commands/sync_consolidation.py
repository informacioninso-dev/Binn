from django.core.management.base import BaseCommand, CommandError

from governance.models import CorporateGroup
from tenants.models import Client

from consolidation.services import sync_group_snapshot, sync_tenant_snapshot


class Command(BaseCommand):
    help = "Sincroniza snapshots de consolidacion para un tenant, un holding o todos los holdings."

    def add_arguments(self, parser):
        parser.add_argument("--group-id", type=int)
        parser.add_argument("--tenant-id", type=int)
        parser.add_argument("--all-groups", action="store_true")
        parser.add_argument("--trigger", default="management_command")

    def handle(self, *args, **options):
        group_id = options.get("group_id")
        tenant_id = options.get("tenant_id")
        all_groups = options.get("all_groups")
        trigger = options.get("trigger") or "management_command"

        if not any([group_id, tenant_id, all_groups]):
            raise CommandError("Debes usar --group-id, --tenant-id o --all-groups.")

        if tenant_id:
            tenant = Client.objects.filter(pk=tenant_id).first()
            if tenant is None:
                raise CommandError(f"Tenant {tenant_id} no encontrado.")
            snapshot = sync_tenant_snapshot(tenant=tenant, trigger=trigger)
            self.stdout.write(self.style.SUCCESS(f"Snapshot del tenant '{tenant.name}' sincronizado ({snapshot.snapshot_date})."))

        if group_id:
            group = CorporateGroup.objects.filter(pk=group_id).first()
            if group is None:
                raise CommandError(f"Grupo {group_id} no encontrado.")
            snapshot = sync_group_snapshot(group=group, trigger=trigger)
            self.stdout.write(self.style.SUCCESS(f"Snapshot del holding '{group.name}' sincronizado con {snapshot.included_tenants_count} empresas visibles."))

        if all_groups:
            groups = CorporateGroup.objects.filter(status=CorporateGroup.STATUS_ACTIVE).order_by("name")
            for group in groups:
                snapshot = sync_group_snapshot(group=group, trigger=trigger)
                self.stdout.write(self.style.SUCCESS(f"[{group.pk}] {group.name}: {snapshot.included_tenants_count} empresas visibles."))
