from django.core.management.base import BaseCommand

from tenants.models import Client, Domain


class Command(BaseCommand):
    help = "Crear/ajustar tenant publico (schema public) y sus dominios."

    def add_arguments(self, parser):
        parser.add_argument(
            "--domains",
            default="localhost,127.0.0.1",
            help="Lista separada por coma de dominios del portal publico.",
        )
        parser.add_argument(
            "--name",
            default="MediEcua Public",
            help="Nombre del tenant publico.",
        )

    def handle(self, *args, **options):
        name = options["name"].strip()
        domains = [d.strip().lower() for d in options["domains"].split(",") if d.strip()]
        if not domains:
            self.stdout.write(self.style.ERROR("Debes indicar al menos un dominio."))
            return

        public_tenant, created = Client.objects.get_or_create(
            schema_name="public",
            defaults={"name": name, "plan": Client.PLAN_SHARED, "is_active": True},
        )
        public_tenant.auto_create_schema = False
        public_tenant.name = name
        public_tenant.is_active = True
        public_tenant.save(update_fields=["name", "is_active"])

        assigned_domains = []
        for idx, domain_name in enumerate(domains):
            domain, domain_created = Domain.objects.get_or_create(
                domain=domain_name,
                defaults={"tenant": public_tenant, "is_primary": idx == 0},
            )
            if not domain_created and domain.tenant_id != public_tenant.id:
                self.stdout.write(
                    self.style.ERROR(
                        f"Dominio '{domain_name}' ya pertenece a otra clinica (schema {domain.tenant.schema_name})."
                    )
                )
                continue

            changed = False
            if domain.tenant_id != public_tenant.id:
                domain.tenant = public_tenant
                changed = True
            should_be_primary = idx == 0
            if domain.is_primary != should_be_primary:
                domain.is_primary = should_be_primary
                changed = True
            if changed:
                domain.save(update_fields=["tenant", "is_primary"])
            assigned_domains.append(domain.domain)

        # Refuerzo defensivo: garantiza exactamente un dominio primario.
        if assigned_domains:
            preferred_domain = assigned_domains[0]
            primary_domain = (
                Domain.objects.filter(tenant=public_tenant, domain=preferred_domain).first()
                or Domain.objects.filter(tenant=public_tenant, domain__in=assigned_domains).order_by("id").first()
            )
            if primary_domain:
                Domain.objects.filter(tenant=public_tenant).exclude(pk=primary_domain.pk).update(is_primary=False)
                if not primary_domain.is_primary:
                    primary_domain.is_primary = True
                    primary_domain.save(update_fields=["is_primary"])

        self.stdout.write(
            self.style.SUCCESS(
                f"Tenant publico listo (created={created}) con dominios: {', '.join(domains)}"
            )
        )
