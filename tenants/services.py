import re
from dataclasses import dataclass, field
from typing import Any

from django.contrib.auth import get_user_model
from django_tenants.utils import get_public_schema_name, schema_context

from access.models import TenantMembership

from .defaults import PROFILE_GENERAL, build_profile_launchpad
from .models import Client, Domain, TenantConfig
from .observability import record_tenant_event


class TenantProvisionError(Exception):
    pass


_SCHEMA_RE = re.compile(r"^[a-z][a-z0-9_]{2,62}$")
_DOMAIN_LABEL_RE = re.compile(r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$")
_VALID_PLANS = {choice[0] for choice in Client.PLAN_CHOICES}


@dataclass
class TenantProvisionResult:
    client: Client
    notices: list[str] = field(default_factory=list)
    launchpad: dict = field(default_factory=dict)


@dataclass
class TenantMembershipAssignmentResult:
    user: Any
    membership: TenantMembership
    membership_created: bool
    notices: list[str] = field(default_factory=list)


def build_tenant_launchpad(tenant: Client) -> dict:
    config = tenant.tenant_config
    return build_profile_launchpad(
        config.profile,
        feature_flags=config.feature_flags,
        labels=config.labels,
        entity_fields=config.entity_fields,
        custom_objects=config.custom_objects,
        module_order=config.module_order,
        dashboard_widgets=config.dashboard_widgets,
        role_policies=config.role_policies,
        document_blueprints=config.document_blueprints,
        pipeline_templates=config.pipeline_templates,
    )


def sync_tenant_pipelines(tenant: Client) -> list[str]:
    notices: list[str] = []
    configured_keys = []

    with schema_context(tenant.schema_name):
        from binncrm.models import Pipeline

        for position, pipeline_config in enumerate(tenant.pipeline_templates, start=1):
            key = pipeline_config["key"]
            configured_keys.append(key)
            pipeline, created = Pipeline.objects.get_or_create(
                key=key,
                defaults={
                    "name": pipeline_config["label"],
                    "stages": pipeline_config["stages"],
                    "position": position,
                    "is_default": position == 1,
                    "is_active": True,
                },
            )
            if not created:
                pipeline.name = pipeline_config["label"]
                pipeline.stages = pipeline_config["stages"]
                pipeline.position = position
                pipeline.is_default = position == 1
                pipeline.is_active = True
                pipeline.save(update_fields=["name", "stages", "position", "is_default", "is_active"])

        stale_pipelines = Pipeline.objects.exclude(key__in=configured_keys) if configured_keys else Pipeline.objects.all()
        for pipeline in stale_pipelines.order_by("position", "name"):
            if pipeline.deals.exists():
                notices.append(
                    f"El pipeline '{pipeline.name}' sigue activo porque tiene deals historicos vinculados."
                )
                continue
            if pipeline.is_active or pipeline.is_default:
                pipeline.is_active = False
                pipeline.is_default = False
                pipeline.save(update_fields=["is_active", "is_default"])

    return notices


def sync_tenant_object_schemas(tenant: Client) -> list[str]:
    from binncrm.object_engine import sync_tenant_object_schemas as sync_object_engine

    return sync_object_engine(tenant)


def create_tenant(
    *,
    schema_name: str,
    name: str,
    domain: str,
    plan: str,
    profile: str = PROFILE_GENERAL,
    admin_username: str = "",
    admin_email: str = "",
    admin_password: str = "",
) -> TenantProvisionResult:
    schema_name = _normalize_schema_name(schema_name)
    name = (name or "").strip()
    domain = _normalize_domain(domain)
    plan = (plan or "").strip().lower()
    admin_username = (admin_username or "").strip()
    admin_email = (admin_email or "").strip()
    admin_password = (admin_password or "").strip()

    if any([admin_username, admin_email, admin_password]) and not admin_username:
        raise TenantProvisionError("Debes indicar el usuario del admin inicial.")

    with schema_context(get_public_schema_name()):
        _validate_tenant_request(schema_name=schema_name, domain=domain, plan=plan)
        existing_admin = _get_existing_user(admin_username)
        if admin_username and existing_admin is None and not admin_password:
            raise TenantProvisionError("Debes indicar una contrasena para crear el admin inicial.")

    client = None
    launchpad = {}
    try:
        with schema_context(get_public_schema_name()):
            client = Client(
                schema_name=schema_name,
                name=name,
                plan=plan,
                is_active=True,
            )
            client.save()
            Domain.objects.create(
                domain=domain,
                tenant=client,
                is_primary=True,
            )
            config = TenantConfig.objects.filter(tenant=client).first() or TenantConfig(tenant=client)
            config.profile = profile
            config.apply_profile_defaults(overwrite=True)
            config.save()
            launchpad = build_tenant_launchpad(client)
            record_tenant_event(
                tenant=client,
                title="Perfil aplicado",
                message=f"Se cargaron labels, modulos y estructuras base del perfil {config.get_profile_display()}.",
                code="tenant_profile_applied",
                metadata={
                    "profile": config.profile,
                    "enabled_capabilities": [item["key"] for item in launchpad["enabled_capabilities"]],
                    "hidden_capabilities": [item["key"] for item in launchpad["hidden_capabilities"]],
                },
            )
    except Exception as exc:
        if client and getattr(client, "pk", None):
            _safe_drop_client(client)
        raise TenantProvisionError(f"No se pudo crear el tenant '{schema_name}': {exc}") from exc

    try:
        notices = _build_launchpad_notices(launchpad)
        notices.extend(sync_tenant_pipelines(client))
        notices.extend(sync_tenant_object_schemas(client))
        record_tenant_event(
            tenant=client,
            title="Pipelines iniciales listos",
            message=f"Se sincronizaron {len(launchpad['pipelines'])} pipelines base para el tenant.",
            code="tenant_pipelines_seeded",
            metadata={"pipelines": [pipeline["key"] for pipeline in launchpad["pipelines"]]},
        )
    except Exception as exc:
        _safe_drop_client(client)
        raise TenantProvisionError(
            f"No se pudo inicializar el tenant '{client.schema_name}'. Se revirtio la creacion: {exc}"
        ) from exc

    if admin_username:
        try:
            with schema_context(get_public_schema_name()):
                notices.extend(
                    ensure_tenant_admin_membership(
                        tenant=client,
                        username=admin_username,
                        email=admin_email,
                        password=admin_password,
                        existing_user=existing_admin,
                    )
                )
                record_tenant_event(
                    tenant=client,
                    title="Admin inicial listo",
                    message=f"El usuario '{admin_username}' quedo asignado como owner del tenant.",
                    code="tenant_initial_admin_ready",
                    metadata={"username": admin_username},
                )
        except Exception as exc:
            _safe_drop_client(client)
            if isinstance(exc, TenantProvisionError):
                raise
            raise TenantProvisionError(
                f"No se pudo configurar el admin inicial de '{client.schema_name}'. "
                f"Se revirtio la creacion: {exc}"
            ) from exc

    return TenantProvisionResult(client=client, notices=notices, launchpad=launchpad)


def _build_launchpad_notices(launchpad: dict) -> list[str]:
    if not launchpad:
        return []

    enabled_modules = ", ".join(item["label"] for item in launchpad["enabled_capabilities"][:4])
    notices = [f"{launchpad['headline']}. Modulos visibles: {enabled_modules}."]

    if launchpad["pipelines"]:
        pipeline_summary = ", ".join(
            f"{pipeline['label']} ({pipeline['summary']})" for pipeline in launchpad["pipelines"][:2]
        )
        notices.append(f"Pipelines iniciales: {pipeline_summary}.")

    return notices


def assign_tenant_membership(
    *,
    tenant: Client,
    username: str,
    role: str = TenantMembership.ROLE_OPERATOR,
) -> TenantMembershipAssignmentResult:
    username = (username or "").strip()
    if not username:
        raise TenantProvisionError("Debes indicar un usuario.")
    if role not in {choice[0] for choice in TenantMembership.ROLE_CHOICES}:
        raise TenantProvisionError("Debes indicar un rol valido para este tenant.")

    user = _get_existing_user(username)
    if user is None:
        raise TenantProvisionError("El usuario no existe. Crealo desde la administracion global.")

    is_admin = role in {TenantMembership.ROLE_OWNER, TenantMembership.ROLE_MANAGER}
    existing_membership = TenantMembership.objects.filter(tenant=tenant, user=user).first()
    if (
        (existing_membership is None or not existing_membership.is_active)
        and tenant.memberships.filter(is_active=True).count() >= tenant.max_users
    ):
        raise TenantProvisionError(
            f"El tenant '{tenant.name}' ya alcanzo su limite de {tenant.max_users} usuarios activos."
        )
    membership, membership_created = TenantMembership.objects.get_or_create(
        tenant=tenant,
        user=user,
        defaults={"role": role, "is_admin": is_admin, "is_active": True},
    )

    membership_fields = []
    if membership.role != role:
        membership.role = role
        membership_fields.append("role")
    if is_admin != membership.is_admin:
        membership.is_admin = is_admin
        membership_fields.append("is_admin")
    if not membership.is_active:
        membership.is_active = True
        membership_fields.append("is_active")
    if membership_fields:
        membership.save(update_fields=membership_fields)

    return TenantMembershipAssignmentResult(
        user=user,
        membership=membership,
        membership_created=membership_created,
        notices=[],
    )


def ensure_tenant_admin_membership(
    *,
    tenant: Client,
    username: str,
    email: str = "",
    password: str = "",
    existing_user=None,
) -> list[str]:
    username = (username or "").strip()
    email = (email or "").strip()
    password = (password or "").strip()

    if not username:
        return []

    notices: list[str] = []
    user = existing_user or _get_existing_user(username)
    user_model = get_user_model()
    user_created = False

    if user is None:
        if not password:
            raise TenantProvisionError("Debes indicar una contrasena para crear el admin inicial.")

        user = user_model._default_manager.create_user(
            username=username,
            email=email,
            password=password,
        )
        user_created = True
    else:
        if password:
            notices.append(
                f"El usuario '{username}' ya existia; su contrasena global no fue modificada."
            )
        if email and email != (getattr(user, "email", "") or ""):
            notices.append(
                f"El usuario '{username}' ya existia; su correo global no fue modificado."
            )

    try:
        membership, _ = TenantMembership.objects.get_or_create(
            tenant=tenant,
            user=user,
            defaults={
                "role": TenantMembership.ROLE_OWNER,
                "is_admin": True,
                "is_active": True,
            },
        )

        changed_fields = []
        if membership.role != TenantMembership.ROLE_OWNER:
            membership.role = TenantMembership.ROLE_OWNER
            changed_fields.append("role")
        if not membership.is_admin:
            membership.is_admin = True
            changed_fields.append("is_admin")
        if not membership.is_active:
            membership.is_active = True
            changed_fields.append("is_active")
        if changed_fields:
            membership.save(update_fields=changed_fields)
    except Exception as exc:
        if user_created:
            try:
                user.delete()
            except Exception as cleanup_exc:
                raise TenantProvisionError(
                    "No se pudo asignar el admin inicial y tampoco limpiar el usuario global recien creado: "
                    f"{cleanup_exc}"
                ) from exc
        raise TenantProvisionError(f"No se pudo asignar el admin inicial: {exc}") from exc

    return notices


def _validate_tenant_request(*, schema_name: str, domain: str, plan: str) -> None:
    if schema_name == "public":
        raise TenantProvisionError("El schema 'public' esta reservado.")
    if not _SCHEMA_RE.match(schema_name):
        raise TenantProvisionError("Schema invalido. Usa letras, numeros y guion bajo; min 3 caracteres.")
    labels = domain.split(".")
    if len(labels) < 2 or any(not _DOMAIN_LABEL_RE.match(label) for label in labels):
        raise TenantProvisionError("Dominio invalido. Usa un dominio completo con letras, numeros y guiones.")
    if plan not in _VALID_PLANS:
        raise TenantProvisionError(f"Plan invalido: '{plan}'.")
    if Client.objects.filter(schema_name=schema_name).exists():
        raise TenantProvisionError(f"Ya existe un tenant con schema '{schema_name}'.")
    if Domain.objects.filter(domain=domain).exists():
        raise TenantProvisionError(f"Ya existe un dominio '{domain}'.")


def _get_existing_user(username: str):
    username = (username or "").strip()
    if not username:
        return None

    user_model = get_user_model()
    users = user_model._default_manager.filter(username__iexact=username).order_by("id")
    user_count = users.count()
    if user_count == 0:
        return None
    if user_count > 1:
        raise TenantProvisionError(
            f"Hay varios usuarios globales que coinciden con '{username}'. Corrige ese conflicto antes de continuar."
        )
    return users.first()


def _normalize_schema_name(value: str) -> str:
    value = (value or "").strip().lower()
    value = re.sub(r"[\s-]+", "_", value)
    value = re.sub(r"[^a-z0-9_]", "", value)
    return value


def _normalize_domain(value: str) -> str:
    value = (value or "").strip().lower()
    value = value.replace("https://", "").replace("http://", "").strip("/")
    value = value.split("/", 1)[0]

    labels = []
    for raw_label in value.split("."):
        label = re.sub(r"[\s_]+", "-", raw_label)
        label = re.sub(r"[^a-z0-9-]", "-", label)
        label = re.sub(r"-{2,}", "-", label).strip("-")
        labels.append(label)
    return ".".join(labels)


def _safe_drop_client(client: Client) -> None:
    try:
        client.delete(force_drop=True)
    except Exception as exc:
        raise TenantProvisionError(
            f"No se pudo eliminar completamente el tenant '{client.schema_name}': {exc}"
        ) from exc
