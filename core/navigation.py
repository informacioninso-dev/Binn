from dataclasses import dataclass

from django.urls import reverse

from access.runtime import get_active_group_membership, get_request_membership
from access.permissions import (
    CRM_ADMIN_ALLOWED_ROLES,
    PERMISSION_ACTIVITIES_VIEW,
    PERMISSION_COLLAB_EDIT,
    PERMISSION_COLLAB_VIEW,
    PERMISSION_COLLECTIONS_VIEW,
    PERMISSION_DEALS_VIEW,
    PERMISSION_DOCUMENTS_EDIT,
    PERMISSION_DOCUMENTS_VIEW,
    PERMISSION_ENTITIES_EDIT,
    PERMISSION_ENTITIES_VIEW,
    PERMISSION_OBJECTS_EDIT,
    PERMISSION_OBJECTS_VIEW,
    PERMISSION_PROPOSALS_EDIT,
    PERMISSION_PROPOSALS_VIEW,
    PERMISSION_REPORTS_VIEW,
    PERMISSION_COLLECTIONS_EDIT,
    PERMISSION_ACTIVITIES_EDIT,
    PERMISSION_DEALS_EDIT,
    request_has_tenant_permission,
)
from tenants.defaults import resolve_module_order
from tenants.defaults import PROFILE_BROKER
from tenants.defaults import PROFILE_CONDOMINIO
from tenants.defaults import PROFILE_RETAIL_MODA
from tenants.defaults import PROFILE_SERVICIOS


@dataclass(frozen=True)
class NavigationItem:
    label: str
    route: str
    active: bool = False
    icon: str = "spark"
    hint: str = ""


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


@dataclass(frozen=True)
class CommandPaletteItem:
    label: str
    href: str
    description: str = ""


@dataclass(frozen=True)
class CommandPaletteSection:
    label: str
    items: tuple[CommandPaletteItem, ...]


def build_navigation_model(request) -> NavigationModel:
    user = getattr(request, "user", None)
    tenant = getattr(request, "tenant", None)
    membership = getattr(request, "tenant_membership", None)
    resolver_match = getattr(request, "resolver_match", None)
    current_namespace = getattr(resolver_match, "namespace", "") or ""
    current_url_name = getattr(resolver_match, "url_name", "") or ""

    role_label = _build_role_label(request, user, membership)
    utility_items = _build_utility_items(user, tenant, current_namespace, current_url_name)

    if not getattr(user, "is_authenticated", False):
        return NavigationModel(role_label=role_label, primary_items=(), utility_items=utility_items)

    if tenant is None or tenant.schema_name == "public":
        primary_items = tuple(
            item
            for item in (
                _nav_item(
                    "Tenants",
                    "tenants:list",
                    current_namespace,
                    current_url_name,
                    icon="layers",
                    hint="Tenants",
                    namespaces=("tenants",),
                    url_names=("list", "create", "detail", "health", "edit", "toggle_active", "membership_toggle", "membership_delete", "return_to_platform"),
                )
                if getattr(user, "is_superuser", False)
                else None,
                _nav_item(
                    "Holdings",
                    "governance:group_list",
                    current_namespace,
                    current_url_name,
                    icon="chart",
                    hint="Holdings",
                    namespaces=("governance",),
                    url_names=(
                        "group_list",
                        "group_create",
                        "group_detail",
                        "group_edit",
                        "group_billing",
                        "group_membership_upsert",
                        "group_tenant_link_upsert",
                        "operational_access_request",
                        "operational_access_decide",
                    ),
                )
                if getattr(user, "is_superuser", False)
                else None,
            )
            if item is not None
        )
        return NavigationModel(role_label=role_label, primary_items=primary_items, utility_items=utility_items)

    labels = tenant.tenant_config.labels
    profile = getattr(getattr(tenant, "tenant_config", None), "profile", "")
    module_order = _module_order_for_tenant(tenant)
    primary_items: list[NavigationItem] = [
        _nav_item(
            "Inicio",
            "dashboard",
            current_namespace,
            current_url_name,
            icon="home",
            hint="Andon",
            url_names=("dashboard",),
        ),
    ]
    if profile == PROFILE_CONDOMINIO and tenant.has_capability("reports") and _can_access(request, PERMISSION_REPORTS_VIEW):
        primary_items.append(
            _nav_item(
                "Condominio",
                "binncrm:condominio_hub",
                current_namespace,
                current_url_name,
                icon="chart",
                hint="Mora y cobro",
                url_names=("condominio_hub",),
            )
        )
    if profile == PROFILE_BROKER and tenant.has_capability("reports") and _can_access(request, PERMISSION_REPORTS_VIEW):
        primary_items.append(
            _nav_item(
                "Broker",
                "binncrm:broker_hub",
                current_namespace,
                current_url_name,
                icon="chart",
                hint="Renovaciones",
                url_names=("broker_hub",),
            )
        )
    if profile == PROFILE_SERVICIOS and tenant.has_capability("reports") and _can_access(request, PERMISSION_REPORTS_VIEW):
        primary_items.append(
            _nav_item(
                "Servicios",
                "binncrm:services_hub",
                current_namespace,
                current_url_name,
                icon="chart",
                hint="Pipeline",
                url_names=("services_hub",),
            )
        )
    if profile == PROFILE_RETAIL_MODA and tenant.has_capability("reports") and _can_access(request, PERMISSION_REPORTS_VIEW):
        primary_items.append(
            _nav_item(
                "Retail",
                "binncrm:retail_hub",
                current_namespace,
                current_url_name,
                icon="chart",
                hint="Recompra",
                url_names=("retail_hub",),
            )
        )

    primary_item_map: dict[str, NavigationItem] = {}
    if tenant.has_capability("entities") and _can_access(request, PERMISSION_ENTITIES_VIEW):
        primary_item_map["entities"] = _nav_item(
            labels.get("entity_plural", "Contactos"),
            "binncrm:entities",
            current_namespace,
            current_url_name,
            icon="users",
            hint="Fichas",
            url_names=("entities", "entity_import", "entity_create", "entity_detail", "entity_edit"),
        )

    if tenant.has_capability("deals") and _can_access(request, PERMISSION_DEALS_VIEW):
        primary_item_map["deals"] = _nav_item(
            labels.get("deal_plural", "Oportunidades"),
            "binncrm:index",
            current_namespace,
            current_url_name,
            icon="pipeline",
            hint="Pipeline",
            url_names=("index", "deal_create", "deal_edit"),
        )

    for key in module_order:
        if key in primary_item_map:
            primary_items.append(primary_item_map[key])

    management_items = _build_management_items(request, tenant, current_namespace, current_url_name)
    management_menu = None
    if management_items:
        management_menu = NavigationMenu(
            label="Operar",
            items=tuple(management_items),
            active=any(item.active for item in management_items),
        )

    return NavigationModel(
        role_label=role_label,
        primary_items=tuple(primary_items),
        utility_items=utility_items,
        management_menu=management_menu,
    )


def build_command_palette_model(request) -> tuple[CommandPaletteSection, ...]:
    user = getattr(request, "user", None)
    tenant = getattr(request, "tenant", None)
    if not getattr(user, "is_authenticated", False):
        return ()

    navigation_section: list[CommandPaletteItem] = []
    create_section: list[CommandPaletteItem] = []
    account_section: list[CommandPaletteItem] = []

    nav = build_navigation_model(request)
    for item in (*nav.primary_items, *(nav.management_menu.items if nav.management_menu else ())):
        navigation_section.append(
            CommandPaletteItem(
                label=item.label,
                href=reverse(item.route),
                description=item.hint or "Ir al modulo",
            )
        )

    if tenant is not None and tenant.schema_name != "public":
        if any(
            _can_access(request, permission_code)
            for permission_code in (
                PERMISSION_ENTITIES_VIEW,
                PERMISSION_DEALS_VIEW,
                PERMISSION_ACTIVITIES_VIEW,
                PERMISSION_DOCUMENTS_VIEW,
                PERMISSION_PROPOSALS_VIEW,
                PERMISSION_COLLECTIONS_VIEW,
            )
        ):
            navigation_section.insert(
                0,
                CommandPaletteItem(
                    label="Buscar en CRM",
                    href=reverse("binncrm:global_search"),
                    description="Buscar fichas, deals, actividades, cobranzas y documentos",
                ),
            )
        if getattr(tenant.tenant_config, "custom_objects", []) and _can_access(request, PERMISSION_OBJECTS_VIEW):
            create_section.append(
                CommandPaletteItem(
                    label="Abrir objetos custom",
                    href=reverse("binncrm:custom_object_catalog"),
                    description="Entrar al catalogo flexible del tenant",
                )
            )
            if _can_access(request, PERMISSION_OBJECTS_EDIT):
                for object_definition in list(getattr(tenant.tenant_config, "custom_objects", []) or [])[:4]:
                    create_section.append(
                        CommandPaletteItem(
                            label=f"Nuevo en {object_definition['label']}",
                            href=reverse("binncrm:custom_object_record_create", kwargs={"object_key": object_definition["key"]}),
                            description="Crear registro custom sin migraciones",
                        )
                    )
        if tenant.has_capability("entities") and _can_access(request, PERMISSION_ENTITIES_EDIT):
            create_section.append(
                CommandPaletteItem(
                    label=f"Nueva {tenant.get_label('entity_singular', 'Entidad')}",
                    href=reverse("binncrm:entity_create"),
                    description="Crear ficha base",
                )
            )
        if tenant.has_capability("deals") and _can_access(request, PERMISSION_DEALS_EDIT):
            create_section.append(
                CommandPaletteItem(
                    label=f"Nuevo {tenant.get_label('deal_singular', 'Deal')}",
                    href=reverse("binncrm:deal_create"),
                    description="Abrir oportunidad o caso",
                )
            )
            if _can_manage_tenant_settings(request):
                create_section.append(
                    CommandPaletteItem(
                        label="Configurar pipelines",
                        href=reverse("binncrm:pipeline_settings"),
                        description="Ajustar flujos y etapas de esta empresa",
                    )
                )
        if tenant.has_capability("activities") and _can_access(request, PERMISSION_ACTIVITIES_EDIT):
            create_section.append(
                CommandPaletteItem(
                    label=f"Nueva {tenant.get_label('activity_singular', 'Actividad')}",
                    href=reverse("binncrm:activity_create"),
                    description="Registrar seguimiento o tarea",
                )
            )
        if tenant.has_capability("proposals") and _can_access(request, PERMISSION_PROPOSALS_EDIT):
            create_section.append(
                CommandPaletteItem(
                    label=f"Nueva {tenant.get_label('proposal_singular', 'Propuesta')}",
                    href=reverse("binncrm:proposal_create"),
                    description="Emitir propuesta o cotizacion",
                )
            )
        if tenant.has_capability("collections") and _can_access(request, PERMISSION_COLLECTIONS_EDIT):
            create_section.append(
                CommandPaletteItem(
                    label=f"Nueva {tenant.get_label('collection_singular', 'Cobranza')}",
                    href=reverse("binncrm:collection_create"),
                    description="Registrar seguimiento de cobro",
                )
            )
        if tenant.has_capability("documents") and _can_access(request, PERMISSION_DOCUMENTS_EDIT):
            create_section.append(
                CommandPaletteItem(
                    label=f"Nuevo {tenant.get_label('document_singular', 'Documento')}",
                    href=reverse("binncrm:document_create"),
                    description="Subir o registrar soporte",
                )
            )
        if tenant.has_capability("collab") and _can_access(request, PERMISSION_COLLAB_VIEW):
            create_section.append(
                CommandPaletteItem(
                    label="Abrir colaboracion",
                    href=reverse("collab:inbox"),
                    description="Entrar a conversaciones internas",
                )
            )

    for item in nav.utility_items:
        account_section.append(CommandPaletteItem(label=item.label, href=reverse(item.route), description="Cuenta"))

    sections = []
    if navigation_section:
        sections.append(CommandPaletteSection(label="Ir a", items=tuple(navigation_section)))
    if create_section:
        sections.append(CommandPaletteSection(label="Crear", items=tuple(create_section)))
    if account_section:
        sections.append(CommandPaletteSection(label="Cuenta", items=tuple(account_section)))
    return tuple(sections)


def _build_role_label(request, user, membership) -> str:
    if getattr(user, "is_authenticated", False):
        if getattr(user, "is_superuser", False):
            return "Superadmin"
        if membership is not None:
            return membership.role_label
        active_context = getattr(request, "active_session_context", None)
        if active_context is not None and active_context.corporate_group_id:
            group_membership = get_active_group_membership(group_id=active_context.corporate_group_id, user=user)
            if group_membership is not None:
                return f"Grupo - {group_membership.get_role_display()}"
    return ""


def _build_utility_items(user, tenant, current_namespace: str, current_url_name: str) -> tuple[NavigationItem, ...]:
    items = []
    if (
        getattr(user, "is_authenticated", False)
        and tenant is not None
        and getattr(tenant, "schema_name", "") != "public"
    ):
        items.append(
            _nav_item(
                "Cambiar espacio" if not getattr(user, "is_superuser", False) else "Volver a Tenants",
                "tenants:return_to_platform",
                current_namespace,
                current_url_name,
                icon="return",
                hint="Cambiar espacio",
                namespaces=("tenants",),
                url_names=("return_to_platform",),
            )
        )
    if getattr(user, "is_authenticated", False):
        items.append(
            _nav_item(
                "Cambiar clave",
                "password_change",
                current_namespace,
                current_url_name,
                icon="lock",
                hint="Seguridad",
                url_names=("password_change", "password_change_done"),
            )
        )
    return tuple(items)


def _build_management_items(request, tenant, current_namespace: str, current_url_name: str) -> list[NavigationItem]:
    labels = tenant.tenant_config.labels
    module_order = _module_order_for_tenant(tenant)
    item_map: dict[str, NavigationItem] = {}

    if getattr(tenant.tenant_config, "custom_objects", []) and _can_access(request, PERMISSION_OBJECTS_VIEW):
        item_map["objects"] = _nav_item(
            "Objetos",
            "binncrm:custom_object_catalog",
            current_namespace,
            current_url_name,
            icon="layers",
            hint="Custom",
            url_names=("custom_object_catalog", "custom_object_records", "custom_object_record_detail", "custom_object_record_create", "custom_object_record_edit"),
        )

    if tenant.has_capability("activities") and _can_access(request, PERMISSION_ACTIVITIES_VIEW):
        item_map["activities"] = _nav_item(
            labels.get("activity_plural", "Actividades"),
            "binncrm:activities",
            current_namespace,
            current_url_name,
            icon="pulse",
            hint="Agenda",
            url_names=("activities", "activity_create"),
        )

    if tenant.has_capability("collab") and _can_access(request, PERMISSION_COLLAB_VIEW):
        item_map["collab"] = _nav_item(
            "Colaboracion",
            "collab:inbox",
            current_namespace,
            current_url_name,
            icon="chat",
            hint="Inbox",
            namespaces=("collab",),
            url_names=("inbox", "conversation_detail"),
        )

    if tenant.has_capability("documents") and _can_access(request, PERMISSION_DOCUMENTS_VIEW):
        item_map["documents"] = _nav_item(
            labels.get("document_plural", "Documentos"),
            "binncrm:documents",
            current_namespace,
            current_url_name,
            icon="file",
            hint="Soportes",
            url_names=("documents", "document_create", "document_edit"),
        )

    if tenant.has_capability("proposals") and _can_access(request, PERMISSION_PROPOSALS_VIEW):
        item_map["proposals"] = _nav_item(
            labels.get("proposal_plural", "Propuestas"),
            "binncrm:proposals",
            current_namespace,
            current_url_name,
            icon="spark",
            hint="Cotizar",
            url_names=("proposals", "proposal_create", "proposal_edit"),
        )

    if tenant.has_capability("collections") and _can_access(request, PERMISSION_COLLECTIONS_VIEW):
        item_map["collections"] = _nav_item(
            labels.get("collection_plural", "Cobranzas"),
            "binncrm:collections",
            current_namespace,
            current_url_name,
            icon="wallet",
            hint="Cobrar",
            url_names=("collections", "collection_create", "collection_edit"),
        )

    if tenant.has_capability("reports") and _can_access(request, PERMISSION_REPORTS_VIEW):
        item_map["reports"] = _nav_item(
            "Reportes",
            "binncrm:reports",
            current_namespace,
            current_url_name,
            icon="chart",
            hint="Alertas",
            url_names=("reports",),
        )

    items: list[NavigationItem] = []
    for key in module_order:
        if key in item_map:
            items.append(item_map[key])
    for key, item in item_map.items():
        if key not in module_order:
            items.append(item)
    return items


def _nav_item(
    label: str,
    route: str,
    current_namespace: str,
    current_url_name: str,
    *,
    icon: str = "spark",
    hint: str = "",
    namespaces=(),
    url_names=(),
) -> NavigationItem:
    return NavigationItem(
        label=label,
        route=route,
        active=_is_active(current_namespace, current_url_name, namespaces=namespaces, url_names=url_names),
        icon=icon,
        hint=hint,
    )


def _is_active(current_namespace: str, current_url_name: str, *, namespaces=(), url_names=()) -> bool:
    if url_names:
        return current_url_name in url_names
    return current_namespace in namespaces


def _can_access(request, permission_code: str) -> bool:
    return request_has_tenant_permission(request, permission_code)


def _can_manage_tenant_settings(request) -> bool:
    user = getattr(request, "user", None)
    if getattr(user, "is_superuser", False):
        return True
    membership = getattr(request, "tenant_membership", None) or get_request_membership(request)
    if membership is None or not getattr(membership, "is_active", True):
        return False
    return getattr(membership, "role", "") in CRM_ADMIN_ALLOWED_ROLES


def _module_order_for_tenant(tenant) -> list[str]:
    configured_order = getattr(tenant, "module_order", None)
    if configured_order is None:
        configured_order = getattr(getattr(tenant, "tenant_config", None), "module_order", [])
    return resolve_module_order(configured_order)
