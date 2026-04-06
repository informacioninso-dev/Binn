from dataclasses import dataclass

from tenants.models import TenantMembership
from tenants.permissions import (
    BILLING_ALLOWED_ROLES,
    CLINICAL_ALLOWED_ROLES,
    CRM_ALLOWED_ROLES,
    INVENTORY_ALLOWED_ROLES,
    OPERATIONS_ADMIN_ALLOWED_ROLES,
    OPERATIONS_REPORT_ALLOWED_ROLES,
)


@dataclass(frozen=True)
class NavigationItem:
    label: str
    route: str
    active: bool = False


@dataclass(frozen=True)
class NavigationMenu:
    label: str
    items: tuple[NavigationItem, ...]
    active: bool = False


@dataclass(frozen=True)
class NavigationModel:
    role_label: str
    primary_items: tuple[NavigationItem, ...]
    utility_items: tuple[NavigationItem, ...]
    management_menu: NavigationMenu | None = None


def build_navigation_model(request) -> NavigationModel:
    user = getattr(request, "user", None)
    tenant = getattr(request, "tenant", None)
    membership = getattr(request, "tenant_membership", None)
    resolver_match = getattr(request, "resolver_match", None)
    current_namespace = getattr(resolver_match, "namespace", "") or ""
    current_url_name = getattr(resolver_match, "url_name", "") or ""

    role_label = _build_role_label(user, membership)
    utility_items = _build_utility_items(user, tenant, current_namespace, current_url_name)

    if not getattr(user, "is_authenticated", False):
        return NavigationModel(role_label=role_label, primary_items=(), utility_items=utility_items)

    if tenant is None or tenant.schema_name == "public":
        primary_items = tuple(
            item
            for item in (
                _nav_item("Mis clinicas", "dashboard", current_namespace, current_url_name, url_names=("dashboard",)),
                _nav_item("Clinicas", "tenants:list", current_namespace, current_url_name, namespaces=("tenants",))
                if getattr(user, "is_superuser", False)
                else None,
            )
            if item is not None
        )
        return NavigationModel(role_label=role_label, primary_items=primary_items, utility_items=utility_items)

    primary_items: list[NavigationItem] = [
        _nav_item("Inicio", "dashboard", current_namespace, current_url_name, url_names=("dashboard",)),
    ]

    if tenant.has_capability("appointments.basic"):
        primary_items.append(
            _nav_item("Agenda", "appointments:index", current_namespace, current_url_name, namespaces=("appointments",))
        )

    if tenant.has_capability("patients.basic"):
        primary_items.append(
            _nav_item("Pacientes", "patients:index", current_namespace, current_url_name, namespaces=("patients",))
        )

    if tenant.has_capability("clinical.basic") and _can_access(user, membership, CLINICAL_ALLOWED_ROLES):
        primary_items.append(
            _nav_item("Atencion", "clinical:index", current_namespace, current_url_name, namespaces=("clinical",))
        )

    if tenant.has_capability("billing.basic") and _can_access(user, membership, BILLING_ALLOWED_ROLES):
        primary_items.append(
            _nav_item("Caja", "billing:index", current_namespace, current_url_name, namespaces=("billing",))
        )

    management_items = _build_management_items(user, tenant, membership, current_namespace, current_url_name)
    management_menu = None
    if management_items:
        management_menu = NavigationMenu(
            label="Administracion",
            items=tuple(management_items),
            active=any(item.active for item in management_items),
        )

    return NavigationModel(
        role_label=role_label,
        primary_items=tuple(primary_items),
        utility_items=utility_items,
        management_menu=management_menu,
    )


def _build_role_label(user, membership) -> str:
    if getattr(user, "is_authenticated", False):
        if getattr(user, "is_superuser", False):
            return "Superadmin"
        if membership is not None:
            return membership.role_label
    return ""


def _build_utility_items(user, tenant, current_namespace: str, current_url_name: str) -> tuple[NavigationItem, ...]:
    items = []
    if getattr(user, "is_authenticated", False):
        items.append(
            _nav_item(
                "Clave",
                "password_change",
                current_namespace,
                current_url_name,
                url_names=("password_change", "password_change_done"),
            )
        )
    return tuple(items)


def _build_management_items(user, tenant, membership, current_namespace: str, current_url_name: str) -> list[NavigationItem]:
    items: list[NavigationItem] = []

    if tenant.has_capability("crm.basic") and _can_access(user, membership, CRM_ALLOWED_ROLES):
        items.append(
            _nav_item("Seguimiento", "crm:index", current_namespace, current_url_name, namespaces=("crm",))
        )

    if (
        tenant.has_capability("inventory.basic") or tenant.has_capability("purchases.basic")
    ) and _can_access(user, membership, INVENTORY_ALLOWED_ROLES):
        items.append(
            _nav_item("Inventario", "inventory:index", current_namespace, current_url_name, namespaces=("inventory",))
        )

    if tenant.has_capability("reports.basic") and _can_access(user, membership, OPERATIONS_REPORT_ALLOWED_ROLES):
        items.append(
            _nav_item("Reportes", "operations:index", current_namespace, current_url_name, url_names=("index",))
        )

    if tenant.has_capability("multi_site.basic") and _can_access(user, membership, OPERATIONS_ADMIN_ALLOWED_ROLES):
        items.append(
            _nav_item(
                "Sedes",
                "operations:locations",
                current_namespace,
                current_url_name,
                url_names=("locations", "location_create"),
            )
        )

    if tenant.has_capability("automation.basic") and _can_access(user, membership, OPERATIONS_ADMIN_ALLOWED_ROLES):
        items.append(
            _nav_item(
                "Automatizaciones",
                "operations:automations",
                current_namespace,
                current_url_name,
                url_names=("automations", "automation_create", "automation_run"),
            )
        )

    if tenant.has_capability("integrations.basic") and _can_access(user, membership, OPERATIONS_ADMIN_ALLOWED_ROLES):
        items.append(
            _nav_item(
                "Integraciones",
                "operations:integrations",
                current_namespace,
                current_url_name,
                url_names=("integrations", "integration_create"),
            )
        )

    return items


def _nav_item(label: str, route: str, current_namespace: str, current_url_name: str, *, namespaces=(), url_names=()) -> NavigationItem:
    return NavigationItem(
        label=label,
        route=route,
        active=_is_active(current_namespace, current_url_name, namespaces=namespaces, url_names=url_names),
    )


def _is_active(current_namespace: str, current_url_name: str, *, namespaces=(), url_names=()) -> bool:
    return current_namespace in namespaces or current_url_name in url_names


def _can_access(user, membership, allowed_roles) -> bool:
    if getattr(user, "is_superuser", False):
        return True
    if membership is None:
        return False
    if membership.is_admin:
        return True
    return membership.role in allowed_roles
