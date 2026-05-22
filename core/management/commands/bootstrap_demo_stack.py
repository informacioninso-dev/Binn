from __future__ import annotations

from dataclasses import dataclass

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from binncrm.demo_seed import seed_tenant_demo
from governance.models import CorporateGroup, GroupMembership, GroupTenantAccess, GroupTenantLink
from governance.services import get_or_create_billing_account, record_governance_event
from tenants.models import Client
from tenants.observability import record_tenant_event
from tenants.services import TenantProvisionError, create_tenant, ensure_tenant_admin_membership


@dataclass(frozen=True)
class DemoTenantSpec:
    schema_name: str
    subdomain: str
    name: str
    profile: str
    mode: str


DEMO_TENANTS = [
    DemoTenantSpec("demo", "demo", "Demo Servicios", "servicios", CorporateGroup.MODE_FULL),
    DemoTenantSpec("brokerlab", "broker", "Demo Broker", "broker", CorporateGroup.MODE_AGGREGATE_ONLY),
    DemoTenantSpec("condolab", "condominio", "Demo Condominio", "condominio", CorporateGroup.MODE_BLOCKED),
    DemoTenantSpec("marketlab", "marketing", "Demo Marketing", "marketing", CorporateGroup.MODE_FULL),
]


class Command(BaseCommand):
    help = "Provisiona un stack demo/staging con varios tenants sembrados y un holding listo para mostrar."

    def add_arguments(self, parser):
        parser.add_argument("--admin-user", default="admin")
        parser.add_argument("--admin-email", default="admin@binn.local")
        parser.add_argument("--admin-password", default="")
        parser.add_argument("--base-domain", default=settings.TENANT_BASE_DOMAIN)
        parser.add_argument("--skip-holding", action="store_true")

    def handle(self, *args, **options):
        admin_user = (options["admin_user"] or "").strip()
        admin_email = (options["admin_email"] or "").strip()
        admin_password = (options["admin_password"] or "").strip()
        base_domain = (options["base_domain"] or settings.TENANT_BASE_DOMAIN).strip().lower()

        owner = self._ensure_demo_owner(admin_user=admin_user, admin_email=admin_email, admin_password=admin_password)
        tenants = []
        for spec in DEMO_TENANTS:
            tenant = self._ensure_demo_tenant(spec=spec, base_domain=base_domain, admin_user=admin_user, admin_email=admin_email, admin_password=admin_password)
            seed_summary = seed_tenant_demo(tenant, actor=owner)
            tenants.append((spec, tenant, seed_summary))
            self.stdout.write(
                self.style.SUCCESS(
                    f"[{tenant.schema_name}] seed OK -> entidades {seed_summary['counts']['entities']['total']} | deals {seed_summary['counts']['deals']['total']}"
                )
            )

        if not options["skip_holding"]:
            group = self._ensure_demo_holding(owner=owner, tenants=tenants)
            self.stdout.write(self.style.SUCCESS(f"Holding demo listo: {group.name}"))

        self.stdout.write(self.style.SUCCESS("Stack demo listo."))

    def _ensure_demo_owner(self, *, admin_user: str, admin_email: str, admin_password: str):
        user_model = get_user_model()
        owner = user_model._default_manager.filter(username__iexact=admin_user).first()
        if owner is not None:
            return owner
        if not admin_password:
            raise CommandError("El usuario demo no existe. Usa --admin-password para crearlo.")
        owner = user_model._default_manager.create_superuser(
            username=admin_user,
            email=admin_email,
            password=admin_password,
        )
        self.stdout.write(self.style.WARNING(f"Se creo el superadmin global '{admin_user}'."))
        return owner

    def _ensure_demo_tenant(self, *, spec: DemoTenantSpec, base_domain: str, admin_user: str, admin_email: str, admin_password: str):
        tenant = Client.objects.filter(schema_name=spec.schema_name).first()
        domain = f"{spec.subdomain}.{base_domain}"
        if tenant is None:
            try:
                result = create_tenant(
                    schema_name=spec.schema_name,
                    name=spec.name,
                    domain=domain,
                    plan=Client.PLAN_SHARED,
                    profile=spec.profile,
                    admin_username=admin_user,
                    admin_email=admin_email,
                    admin_password=admin_password,
                )
            except TenantProvisionError as exc:
                raise CommandError(str(exc)) from exc
            tenant = result.client
            self.stdout.write(self.style.SUCCESS(f"Tenant demo creado: {tenant.schema_name} -> {domain}"))
        else:
            ensure_tenant_admin_membership(
                tenant=tenant,
                username=admin_user,
                email=admin_email,
                password=admin_password,
            )
            record_tenant_event(
                tenant=tenant,
                title="Demo stack refrescado",
                message="El tenant fue sincronizado como parte del bootstrap demo.",
                code="demo_stack_bootstrap",
            )
            self.stdout.write(self.style.WARNING(f"Tenant demo reutilizado: {tenant.schema_name}"))
        return tenant

    def _ensure_demo_holding(self, *, owner, tenants: list[tuple[DemoTenantSpec, Client, dict]]):
        group, _ = CorporateGroup.objects.get_or_create(
            slug="binn-demo-holding",
            defaults={
                "name": "Binn Demo Holding",
                "status": CorporateGroup.STATUS_ACTIVE,
                "operating_model": CorporateGroup.OPERATING_MODEL_FAMILY,
                "consolidation_mode": CorporateGroup.MODE_FULL,
                "owner": owner,
                "notes": "Holding demo para staging y demos comerciales.",
            },
        )
        group.name = "Binn Demo Holding"
        group.status = CorporateGroup.STATUS_ACTIVE
        group.operating_model = CorporateGroup.OPERATING_MODEL_FAMILY
        group.consolidation_mode = CorporateGroup.MODE_FULL
        group.owner = owner
        group.notes = "Holding demo para staging y demos comerciales."
        group.save(update_fields=["name", "status", "operating_model", "consolidation_mode", "owner", "notes", "updated_at"])

        membership, _ = GroupMembership.objects.get_or_create(
            group=group,
            user=owner,
            defaults={"role": GroupMembership.ROLE_OWNER, "is_active": True},
        )
        if membership.role != GroupMembership.ROLE_OWNER or not membership.is_active:
            membership.role = GroupMembership.ROLE_OWNER
            membership.is_active = True
            membership.save(update_fields=["role", "is_active", "updated_at"])

        for spec, tenant, _seed in tenants:
            link, _ = GroupTenantLink.objects.get_or_create(
                group=group,
                tenant=tenant,
                defaults={
                    "consolidation_mode": spec.mode,
                    "is_primary": spec.schema_name == "demo",
                    "is_active": True,
                },
            )
            link.consolidation_mode = spec.mode
            link.is_primary = spec.schema_name == "demo"
            link.is_active = True
            link.save(update_fields=["consolidation_mode", "is_primary", "is_active", "updated_at"])

            if spec.mode == CorporateGroup.MODE_FULL:
                access, _ = GroupTenantAccess.objects.get_or_create(
                    group=group,
                    tenant=tenant,
                    user=owner,
                    defaults={"role": GroupTenantAccess.ROLE_OWNER, "is_active": True, "granted_by": owner},
                )
                if access.role != GroupTenantAccess.ROLE_OWNER or not access.is_active or access.granted_by_id != owner.id:
                    access.role = GroupTenantAccess.ROLE_OWNER
                    access.is_active = True
                    access.granted_by = owner
                    access.save(update_fields=["role", "is_active", "granted_by", "updated_at"])

        billing_account = get_or_create_billing_account(group=group)
        billing_account.billing_name = "Binn Demo Holding"
        billing_account.billing_email = owner.email or "admin@binn.local"
        billing_account.status = billing_account.STATUS_ACTIVE
        billing_account.seat_limit = 50
        billing_account.manager_limit = 12
        billing_account.storage_limit_mb = 51200
        billing_account.enforce_limits = True
        billing_account.save(
            update_fields=[
                "billing_name",
                "billing_email",
                "status",
                "seat_limit",
                "manager_limit",
                "storage_limit_mb",
                "enforce_limits",
                "updated_at",
            ]
        )

        record_governance_event(
            event_type="demo_stack_bootstrap",
            message="Se refresco el holding demo con tenants multi-vertical y modos mixtos.",
            actor=owner,
            group=group,
            metadata={
                "tenants": [spec.schema_name for spec, _tenant, _seed in tenants],
                "modes": {spec.schema_name: spec.mode for spec, _tenant, _seed in tenants},
            },
        )
        return group
