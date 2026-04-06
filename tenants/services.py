import re
from dataclasses import dataclass, field
from typing import Any

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django_tenants.utils import schema_context

from .models import Client, Domain, TenantMembership


class TenantProvisionError(Exception):
    pass


_SCHEMA_RE = re.compile(r"^[a-z][a-z0-9_]{2,62}$")
_DOMAIN_LABEL_RE = re.compile(r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$")
_VALID_PLANS = {choice[0] for choice in Client.PLAN_CHOICES}


@dataclass
class TenantProvisionResult:
    client: Client
    notices: list[str] = field(default_factory=list)


@dataclass
class TenantMembershipAssignmentResult:
    user: Any
    membership: TenantMembership
    membership_created: bool
    notices: list[str] = field(default_factory=list)


def create_tenant(
    *,
    schema_name: str,
    name: str,
    domain: str,
    plan: str,
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

    _validate_tenant_request(schema_name=schema_name, domain=domain, plan=plan)

    existing_admin = _get_existing_user(admin_username)
    if admin_username and existing_admin is None and not admin_password:
        raise TenantProvisionError("Debes indicar una contrasena para crear el admin inicial.")

    client = None
    try:
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
    except Exception as exc:
        if client and getattr(client, "pk", None):
            _safe_drop_client(client)
        raise TenantProvisionError(f"No se pudo crear la clinica '{schema_name}': {exc}") from exc

    try:
        with schema_context(client.schema_name):
            call_command("seed_data", verbosity=0)
    except Exception as exc:
        _safe_drop_client(client)
        raise TenantProvisionError(
            f"No se pudo inicializar la clinica '{client.schema_name}'. Se revirtio la creacion: {exc}"
        ) from exc

    notices: list[str] = []
    if admin_username:
        try:
            notices = ensure_tenant_admin_membership(
                tenant=client,
                username=admin_username,
                email=admin_email,
                password=admin_password,
                existing_user=existing_admin,
            )
        except Exception as exc:
            _safe_drop_client(client)
            if isinstance(exc, TenantProvisionError):
                raise
            raise TenantProvisionError(
                f"No se pudo configurar el admin inicial de '{client.schema_name}'. "
                f"Se revirtio la creacion: {exc}"
            ) from exc

    return TenantProvisionResult(client=client, notices=notices)


def assign_tenant_membership(
    *,
    tenant: Client,
    username: str,
    role: str = TenantMembership.ROLE_ASSISTANT,
) -> TenantMembershipAssignmentResult:
    username = (username or "").strip()
    if not username:
        raise TenantProvisionError("Debes indicar un usuario.")
    if role not in {choice[0] for choice in TenantMembership.ROLE_CHOICES}:
        raise TenantProvisionError("Debes indicar un rol valido para la clinica.")

    user = _get_existing_user(username)
    if user is None:
        raise TenantProvisionError("El usuario no existe. Crealo desde la administracion global.")

    is_admin = role == TenantMembership.ROLE_CLINIC_ADMIN
    membership, membership_created = TenantMembership.objects.get_or_create(
        tenant=tenant,
        user=user,
        defaults={"role": role, "is_admin": is_admin, "is_active": True},
    )

    membership_fields = []
    if membership.role != role:
        membership.role = role
        membership_fields.append("role")
    if is_admin and not membership.is_admin:
        membership.is_admin = True
        membership_fields.append("is_admin")
    if not is_admin and membership.is_admin:
        membership.is_admin = False
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
                "role": TenantMembership.ROLE_CLINIC_ADMIN,
                "is_admin": True,
                "is_active": True,
            },
        )

        changed_fields = []
        if membership.role != TenantMembership.ROLE_CLINIC_ADMIN:
            membership.role = TenantMembership.ROLE_CLINIC_ADMIN
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
        raise TenantProvisionError(f"Ya existe una clinica con schema '{schema_name}'.")
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
            f"No se pudo eliminar completamente la clinica '{client.schema_name}': {exc}"
        ) from exc
