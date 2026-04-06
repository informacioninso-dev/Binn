from dataclasses import dataclass

from .models import Client


@dataclass(frozen=True)
class PlanDefinition:
    slug: str
    label: str
    description: str
    support_tier: str
    max_users: int | None
    max_admins: int | None
    storage_gb: int | None
    capabilities: frozenset[str]
    features: tuple[str, ...]

    @property
    def max_users_display(self) -> str:
        return "Ilimitado" if self.max_users is None else str(self.max_users)

    @property
    def max_admins_display(self) -> str:
        return "Ilimitado" if self.max_admins is None else str(self.max_admins)

    @property
    def storage_display(self) -> str:
        return "A convenir" if self.storage_gb is None else f"{self.storage_gb} GB"


PLAN_DEFINITIONS: dict[str, PlanDefinition] = {
    Client.PLAN_SHARED: PlanDefinition(
        slug=Client.PLAN_SHARED,
        label="Shared",
        description="Plan base para operar una clinica con CRM-ERP esencial y soporte estandar.",
        support_tier="Estandar",
        max_users=20,
        max_admins=3,
        storage_gb=25,
        capabilities=frozenset(
            {
                "patients.basic",
                "appointments.basic",
                "crm.basic",
                "billing.basic",
                "billing.ar",
                "clinical.basic",
                "inventory.basic",
                "purchases.basic",
                "reports.basic",
                "commissions.basic",
                "automation.basic",
                "support.standard",
            }
        ),
        features=(
            "Pacientes y agenda base",
            "Historia clinica, ordenes y recetas basicas",
            "Facturacion, cartera e inventario operativo",
            "Reportes de gestion, comisiones y automatizaciones base",
            "Gestion de usuarios y roles por clinica",
            "Dashboard operativo inicial",
            "Soporte en horario laboral",
        ),
    ),
    Client.PLAN_ENTERPRISE: PlanDefinition(
        slug=Client.PLAN_ENTERPRISE,
        label="Enterprise",
        description="Plan ampliado para operaciones con mayor volumen, control y acompanamiento.",
        support_tier="Prioritario",
        max_users=None,
        max_admins=10,
        storage_gb=250,
        capabilities=frozenset(
            {
                "patients.basic",
                "appointments.basic",
                "crm.basic",
                "billing.basic",
                "billing.ar",
                "clinical.basic",
                "inventory.basic",
                "purchases.basic",
                "reports.basic",
                "reports.advanced",
                "commissions.basic",
                "automation.basic",
                "multi_site.basic",
                "integrations.basic",
                "support.priority",
                "integrations.ready",
                "multi_site.ready",
            }
        ),
        features=(
            "Todo lo incluido en Shared",
            "Mayor control clinico y documental",
            "Compras e inventario con mas capacidad operativa",
            "Multi-sede, integraciones y analitica ampliada",
            "Mayor capacidad operativa y crecimiento",
            "Soporte prioritario",
            "Base para integraciones y reportes avanzados",
        ),
    ),
}


def get_plan_definition(plan: str | None) -> PlanDefinition:
    return PLAN_DEFINITIONS.get(plan or "", PLAN_DEFINITIONS[Client.PLAN_SHARED])
