import json

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.contrib.auth.views import LoginView
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.generic import ListView, UpdateView, View
from django_tenants.utils import schema_context

from access.models import TenantMembership
from access.runtime import get_tenant_membership
from access.services import clear_active_access_context, set_consolidated_context, set_strict_tenant_context
from core.runtime_services import get_runtime_services_status, is_runtime_healthy, serialize_runtime_status
from governance.models import CorporateGroup, GroupMembership
from governance.services import resolve_group_tenant_detail_access
from identity.security import evaluate_login_throttle, register_login_failure, reset_login_throttle
from .defaults import (
    MODULE_ORDER_LABELS,
    PROFILE_CHOICES,
    resolve_dashboard_widgets,
    resolve_module_order,
    resolve_role_policies,
    build_profile_launchpad,
)
from .forms import (
    AddMemberForm,
    TenantAuthenticationForm,
    TenantCreateForm,
    TenantEditForm,
    TenantListFilterForm,
)
from .middleware import LOCAL_PREVIEW_SESSION_KEY, build_public_app_url
from .models import Client
from .observability import record_tenant_event
from .services import TenantProvisionError, assign_tenant_membership, build_tenant_launchpad, create_tenant
from .workspace_packs import build_workspace_pack


def _tenant_queryset():
    return Client.objects.prefetch_related("domains", "memberships__user")


def _profile_previews() -> list[dict]:
    return [
        {
            "key": profile,
            "label": label,
            **build_profile_launchpad(profile),
        }
        for profile, label in PROFILE_CHOICES
    ]


def _active_group_memberships_for_user(user):
    if user is None or not getattr(user, "is_authenticated", False):
        return GroupMembership.objects.none()
    return (
        GroupMembership.objects.select_related("group")
        .prefetch_related("group__tenant_links__tenant__domains")
        .filter(
            user=user,
            is_active=True,
            group__status=CorporateGroup.STATUS_ACTIVE,
            group__tenant_links__is_active=True,
            group__tenant_links__consolidation_mode__in=[
                CorporateGroup.MODE_AGGREGATE_ONLY,
                CorporateGroup.MODE_FULL,
            ],
        )
        .distinct()
        .order_by("group__name")
    )


def _tenant_detail_context(*, tenant, form):
    from binncrm.document_blueprints import get_document_blueprints
    from binncrm.object_engine import get_object_schema_catalog

    active_user_count = tenant.memberships.filter(is_active=True).count()
    with schema_context(tenant.schema_name):
        from binncrm.models import Document, ObjectRecord

        object_schema_catalog = get_object_schema_catalog(tenant=tenant)
        document_sizes = list(Document.objects.filter(is_active=True).values_list("file_size", flat=True))
        storage_bytes = sum(int(value or 0) for value in document_sizes)
        usage_summary = {
            "active_users": active_user_count,
            "user_limit": tenant.max_users,
            "storage_bytes": storage_bytes,
            "storage_label": _format_storage_label(storage_bytes),
            "storage_quota_mb": tenant.storage_quota_mb,
            "document_count": len(document_sizes),
            "object_record_count": ObjectRecord.objects.filter(is_active=True).count(),
        }

    return {
        "tenant": tenant,
        "domains": tenant.domains.all(),
        "memberships": tenant.memberships.select_related("user").order_by("user__username"),
        "form": form,
        "launchpad": build_tenant_launchpad(tenant),
        "workspace_pack": build_workspace_pack(
            profile=tenant.tenant_config.profile,
            labels=tenant.tenant_config.labels,
            feature_flags=tenant.tenant_config.feature_flags,
        ),
        "effective_document_blueprints": get_document_blueprints(
            tenant.tenant_config.profile,
            custom_blueprints=tenant.tenant_config.document_blueprints,
        ),
        "object_schema_catalog": object_schema_catalog,
        "usage_summary": usage_summary,
        "operational_events": tenant.operational_events.select_related("actor").order_by("-created_at")[:6],
    }


def _format_storage_label(storage_bytes: int) -> str:
    if storage_bytes <= 0:
        return "0 MB"
    if storage_bytes >= 1024 * 1024 * 1024:
        return f"{storage_bytes / (1024 * 1024 * 1024):,.2f} GB"
    return f"{storage_bytes / (1024 * 1024):,.2f} MB"


def _redirect_to_tenant_host(request, tenant):
    domain = tenant.domains.filter(is_primary=True).first() or tenant.domains.first()
    if not domain:
        messages.error(request, "El tenant no tiene dominio configurado.")
        return redirect("dashboard")

    current_host = request.get_host().split(":")[0].lower()
    if settings.DEBUG and current_host in {"localhost", "127.0.0.1"}:
        request.session[LOCAL_PREVIEW_SESSION_KEY] = tenant.schema_name
        return redirect(f"{request.scheme}://{request.get_host()}/?_tenant={tenant.schema_name}")

    host = request.get_host()
    port = ""
    if ":" in host:
        port = ":" + host.split(":")[-1]
    return redirect(f"{request.scheme}://{domain.domain}{port}/")


def _can_manage_tenant_access(*, tenant, user) -> bool:
    if user is None or not getattr(user, "is_authenticated", False):
        return False
    if getattr(user, "is_superuser", False):
        return True
    membership = get_tenant_membership(tenant=tenant, user=user)
    if membership is None or not membership.is_active:
        return False
    return bool(membership.is_admin or membership.role in {TenantMembership.ROLE_OWNER, TenantMembership.ROLE_MANAGER})


class SuperAdminRequiredMixin(UserPassesTestMixin):
    def test_func(self):
        return self.request.user.is_superuser


class SystemHealthView(View):
    def get(self, request):
        return JsonResponse({"status": "ok"}, status=200)


class SystemRuntimeHealthView(LoginRequiredMixin, SuperAdminRequiredMixin, View):
    def get(self, request):
        tenant = getattr(request, "tenant", None)
        services = get_runtime_services_status()
        status_code = 200 if is_runtime_healthy(services) else 503
        payload = {
            "status": "ok" if status_code == 200 else "error",
            "tenant": getattr(tenant, "schema_name", "public"),
            "services": serialize_runtime_status(services),
        }
        return JsonResponse(payload, status=status_code)


class TenantHealthView(LoginRequiredMixin, SuperAdminRequiredMixin, View):
    def get(self, request, pk):
        tenant = Client.objects.filter(pk=pk).first()
        if not tenant:
            return JsonResponse({"status": "error", "message": "Tenant no encontrado."}, status=404)

        payload = {
            "status": "ok",
            "tenant": {
                "id": tenant.pk,
                "name": tenant.name,
                "schema_name": tenant.schema_name,
                "profile": tenant.tenant_config.profile,
                "is_active": tenant.is_active,
                "allow_consolidation": tenant.allow_consolidation,
            },
            "members": tenant.memberships.filter(is_active=True).count(),
            "domains": list(tenant.domains.values_list("domain", flat=True)),
        }
        return JsonResponse(payload)


class TenantLoginView(LoginView):
    template_name = "auth/login.html"
    authentication_form = TenantAuthenticationForm

    def post(self, request, *args, **kwargs):
        login_value = self._submitted_login_value()
        if login_value:
            decision = evaluate_login_throttle(request=request, login_value=login_value)
            if not decision.allowed:
                request._skip_login_failure_tracking = True
                form = self.get_form()
                form.add_error(
                    None,
                    (
                        "Demasiados intentos fallidos. "
                        f"Espera {decision.retry_after_seconds} segundos antes de volver a intentar."
                    ),
                )
                return self.form_invalid(form)
        return super().post(request, *args, **kwargs)

    def form_valid(self, form):
        user = form.get_user()
        tenant = getattr(self.request, "tenant", None)
        if tenant and tenant.schema_name == "public" and not user.is_superuser:
            has_membership = TenantMembership.objects.filter(
                user=user,
                is_active=True,
                tenant__is_active=True,
            ).exists()
            has_group_access = _active_group_memberships_for_user(user).exists()
            if not has_membership and not has_group_access:
                form.add_error(None, "No tienes tenants activos asignados.")
                return self.form_invalid(form)
        login_value = self._submitted_login_value()
        if login_value:
            reset_login_throttle(request=self.request, login_value=login_value)
        return super().form_valid(form)

    def form_invalid(self, form):
        if not getattr(self.request, "_skip_login_failure_tracking", False):
            login_value = self._submitted_login_value()
            password = (self.request.POST.get("password") or "").strip()
            if login_value and password:
                decision = register_login_failure(request=self.request, login_value=login_value)
                if not decision.allowed:
                    form.add_error(
                        None,
                        (
                            "Demasiados intentos fallidos. "
                            f"Espera {decision.retry_after_seconds} segundos antes de volver a intentar."
                        ),
                    )
        return super().form_invalid(form)

    def get_success_url(self):
        redirect_to = self.get_redirect_url()
        if redirect_to:
            return redirect_to

        tenant = getattr(self.request, "tenant", None)
        if tenant and tenant.schema_name == "public":
            if self.request.user.is_superuser:
                return reverse("tenants:list")

            memberships = TenantMembership.objects.filter(
                user=self.request.user,
                is_active=True,
                tenant__is_active=True,
            ).select_related("tenant")
            group_memberships = _active_group_memberships_for_user(self.request.user)

            if memberships.count() == 1 and not group_memberships.exists():
                return reverse("tenants:switch", kwargs={"pk": memberships.first().tenant_id})
            if memberships.count() == 0 and group_memberships.count() == 1:
                return reverse("governance:group_switch", kwargs={"pk": group_memberships.first().group_id})
            return reverse("tenants:access_list")

        return reverse("dashboard")

    def _submitted_login_value(self) -> str:
        return (self.request.POST.get("username") or "").strip()


class TenantAccessListView(LoginRequiredMixin, ListView):
    model = TenantMembership
    template_name = "tenants/my_tenants.html"
    context_object_name = "memberships"

    def get_queryset(self):
        qs = TenantMembership.objects.select_related("tenant").prefetch_related("tenant__domains").filter(
            is_active=True,
            tenant__is_active=True,
        )
        if self.request.user.is_superuser:
            return qs.order_by("tenant__name")
        return qs.filter(user=self.request.user).order_by("tenant__name")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["group_memberships"] = _active_group_memberships_for_user(self.request.user)
        return ctx


class TenantAccessAdminView(LoginRequiredMixin, View):
    def get(self, request, pk):
        tenant = _tenant_queryset().filter(pk=pk, is_active=True).first()
        if not tenant:
            messages.error(request, "Tenant no encontrado.")
            return redirect("dashboard")
        if not _can_manage_tenant_access(tenant=tenant, user=request.user):
            messages.error(request, "No tienes permisos para administrar accesos de esta empresa.")
            return redirect("tenants:access_list")

        return render(
            request,
            "tenants/tenant_access_admin.html",
            {
                "tenant": tenant,
                "memberships": tenant.memberships.select_related("user").order_by("user__username"),
                "form": AddMemberForm(),
            },
        )

    def post(self, request, pk):
        tenant = _tenant_queryset().filter(pk=pk, is_active=True).first()
        if not tenant:
            messages.error(request, "Tenant no encontrado.")
            return redirect("dashboard")
        if not _can_manage_tenant_access(tenant=tenant, user=request.user):
            messages.error(request, "No tienes permisos para administrar accesos de esta empresa.")
            return redirect("tenants:access_list")

        form = AddMemberForm(request.POST)
        if form.is_valid():
            try:
                result = assign_tenant_membership(
                    tenant=tenant,
                    username=form.cleaned_data["username"],
                    role=form.cleaned_data["role"],
                )
            except TenantProvisionError as exc:
                form.add_error(None, str(exc))
            else:
                record_tenant_event(
                    tenant=tenant,
                    actor=request.user,
                    title="Acceso local actualizado",
                    message=f"Se actualizo el acceso de '{result.user.username}' en la empresa.",
                    code="tenant_membership_upserted",
                    metadata={"username": result.user.username, "role": result.membership.role},
                )
                messages.success(request, f"Acceso de '{result.user.username}' actualizado.")
                return redirect("tenants:access_admin", pk=tenant.pk)

        return render(
            request,
            "tenants/tenant_access_admin.html",
            {
                "tenant": tenant,
                "memberships": tenant.memberships.select_related("user").order_by("user__username"),
                "form": form,
            },
        )


class TenantListView(LoginRequiredMixin, SuperAdminRequiredMixin, ListView):
    model = Client
    template_name = "tenants/tenant_list.html"
    context_object_name = "tenants"
    paginate_by = 20

    def get_queryset(self):
        self.filter_form = TenantListFilterForm(self.request.GET or None)
        qs = _tenant_queryset().order_by("name")

        if self.filter_form.is_valid():
            q = (self.filter_form.cleaned_data.get("q") or "").strip()
            if q:
                qs = qs.filter(
                    Q(name__icontains=q)
                    | Q(schema_name__icontains=q)
                    | Q(domains__domain__icontains=q)
                ).distinct()

            plan = self.filter_form.cleaned_data.get("plan")
            if plan:
                qs = qs.filter(plan=plan)

            status = self.filter_form.cleaned_data.get("status")
            if status == TenantListFilterForm.STATUS_ACTIVE:
                qs = qs.filter(is_active=True)
            elif status == TenantListFilterForm.STATUS_INACTIVE:
                qs = qs.filter(is_active=False)

        self.summary = {
            "total": qs.count(),
            "active": qs.filter(is_active=True).count(),
            "shared": qs.filter(plan=Client.PLAN_SHARED).count(),
            "enterprise": qs.filter(plan=Client.PLAN_ENTERPRISE).count(),
        }
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["filter_form"] = getattr(self, "filter_form", TenantListFilterForm())
        ctx["summary"] = getattr(self, "summary", {"total": 0, "active": 0, "shared": 0, "enterprise": 0})
        return ctx


class TenantCreateView(LoginRequiredMixin, SuperAdminRequiredMixin, View):
    template_name = "tenants/tenant_form.html"

    def get(self, request):
        return render(
            request,
            self.template_name,
            {
                "form": TenantCreateForm(),
                "profile_previews": _profile_previews(),
            },
        )

    def post(self, request):
        form = TenantCreateForm(request.POST)
        if not form.is_valid():
            return render(
                request,
                self.template_name,
                {
                    "form": form,
                    "profile_previews": _profile_previews(),
                },
            )

        try:
            result = create_tenant(
                schema_name=form.cleaned_data["schema_name"],
                name=form.cleaned_data["name"],
                domain=form.cleaned_data["subdomain"],
                plan=form.cleaned_data["plan"],
                profile=form.cleaned_data["profile"],
                admin_username=form.cleaned_data.get("admin_username", ""),
                admin_email=form.cleaned_data.get("admin_email", ""),
                admin_password=form.cleaned_data.get("admin_password", ""),
            )
        except TenantProvisionError as exc:
            messages.error(request, str(exc))
            return render(
                request,
                self.template_name,
                {
                    "form": form,
                    "profile_previews": _profile_previews(),
                },
            )

        for notice in result.notices:
            messages.info(request, notice)

        record_tenant_event(
            tenant=result.client,
            actor=request.user,
            title="Tenant creado",
            message=f"Se creo el tenant '{result.client.name}' con perfil {result.client.tenant_config.get_profile_display()}.",
            code="tenant_created",
            metadata={
                "plan": result.client.plan,
                "profile": result.client.tenant_config.profile,
                "enabled_capabilities": [item["key"] for item in result.launchpad.get("enabled_capabilities", [])],
                "pipelines": [pipeline["key"] for pipeline in result.launchpad.get("pipelines", [])],
            },
        )
        messages.success(request, f"Tenant '{result.client.name}' creado correctamente.")
        return redirect("tenants:list")


class TenantEditView(LoginRequiredMixin, SuperAdminRequiredMixin, UpdateView):
    model = Client
    form_class = TenantEditForm
    template_name = "tenants/tenant_edit.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["profile_previews"] = _profile_previews()
        return ctx

    def form_valid(self, form):
        previous_values = {field: getattr(self.object, field, "") for field in form.changed_data if hasattr(self.object, field)}
        previous_config = {
            "profile": self.object.tenant_config.profile,
            "feature_flags_json": self.object.tenant_config.feature_flags,
            "labels_json": self.object.tenant_config.labels,
            "entity_fields_json": self.object.tenant_config.entity_fields,
            "custom_objects_json": self.object.tenant_config.custom_objects,
            "module_order_json": self.object.tenant_config.module_order,
            "dashboard_widgets_json": self.object.tenant_config.dashboard_widgets,
            "role_policies_json": self.object.tenant_config.role_policies,
            "document_blueprints_json": self.object.tenant_config.document_blueprints,
            "pipeline_templates_json": self.object.tenant_config.pipeline_templates,
        }
        response = super().form_valid(form)

        for notice in getattr(form, "sync_notices", []):
            messages.info(self.request, notice)

        record_tenant_event(
            tenant=self.object,
            actor=self.request.user,
            title="Tenant actualizado",
            message="Se actualizaron datos base del tenant.",
            code="tenant_updated",
            metadata={
                "changes": {
                    field: {
                        "before": self._serialize_change_value(field, previous_values, previous_config),
                        "after": self._serialize_change_value(field, None, None),
                    }
                    for field in form.changed_data
                }
            },
        )
        return response

    def get_success_url(self):
        messages.success(self.request, f"Tenant '{self.object.name}' actualizado.")
        return self.object.get_absolute_url()

def _serialize_change_value(self, field, previous_values, previous_config):
    config = self.object.tenant_config
    label_field_map = {
        "brand_name": "brand_name",
        "dashboard_title": "dashboard_title",
        "entity_singular": "entity_singular",
        "entity_plural": "entity_plural",
        "deal_singular": "deal_singular",
        "deal_plural": "deal_plural",
    }
    if field == "profile":
        return previous_config["profile"] if previous_config is not None else config.profile
    if field in {
        "feature_flags_json",
        "labels_json",
        "entity_fields_json",
        "custom_objects_json",
        "module_order_json",
        "dashboard_widgets_json",
        "role_policies_json",
        "document_blueprints_json",
        "pipeline_templates_json",
    }:
        source = previous_config[field] if previous_config is not None else getattr(config, field.replace("_json", ""))
        return json.dumps(source, ensure_ascii=True, sort_keys=isinstance(source, dict))
    if field == "enabled_modules":
        source_flags = previous_config["feature_flags_json"] if previous_config is not None else config.feature_flags
        enabled = [key for key in MODULE_ORDER_LABELS if source_flags.get(key, False)]
        return json.dumps(enabled, ensure_ascii=True)
    if field == "extra_features":
        source_flags = previous_config["feature_flags_json"] if previous_config is not None else config.feature_flags
        enabled = [key for key in ("kanban", "fiscal_lookup") if source_flags.get(key, False)]
        return json.dumps(enabled, ensure_ascii=True)
    if field == "module_order_csv":
        source_order = previous_config["module_order_json"] if previous_config is not None else config.module_order
        source_flags = previous_config["feature_flags_json"] if previous_config is not None else config.feature_flags
        visible_order = [key for key in resolve_module_order(source_order) if source_flags.get(key, False)]
        return json.dumps(visible_order, ensure_ascii=True)
    if field == "dashboard_widgets_selected":
        source_widgets = previous_config["dashboard_widgets_json"] if previous_config is not None else config.dashboard_widgets
        return json.dumps(resolve_dashboard_widgets(source_widgets), ensure_ascii=True)
    if field in label_field_map:
        source_labels = previous_config["labels_json"] if previous_config is not None else config.labels
        return str(source_labels.get(label_field_map[field], ""))
    if field == "manager_access_mode":
        source_policies = previous_config["role_policies_json"] if previous_config is not None else config.role_policies
        return "full" if "*" in resolve_role_policies(source_policies)["manager"] else "custom"
    if field.endswith("_permissions"):
        source_policies = previous_config["role_policies_json"] if previous_config is not None else config.role_policies
        role_key = field.replace("_permissions", "")
        return json.dumps(resolve_role_policies(source_policies)[role_key], ensure_ascii=True)
    return str(previous_values.get(field, "")) if previous_values is not None else str(getattr(self.object, field, ""))



class TenantDetailView(LoginRequiredMixin, SuperAdminRequiredMixin, View):
    def get(self, request, pk):
        tenant = _tenant_queryset().filter(pk=pk).first()
        if not tenant:
            messages.error(request, "Tenant no encontrado.")
            return redirect("tenants:list")

        return render(request, "tenants/tenant_detail.html", _tenant_detail_context(tenant=tenant, form=AddMemberForm()))

    def post(self, request, pk):
        tenant = _tenant_queryset().filter(pk=pk).first()
        if not tenant:
            messages.error(request, "Tenant no encontrado.")
            return redirect("tenants:list")

        form = AddMemberForm(request.POST)
        if form.is_valid():
            try:
                result = assign_tenant_membership(
                    tenant=tenant,
                    username=form.cleaned_data["username"],
                    role=form.cleaned_data["role"],
                )
            except TenantProvisionError as exc:
                form.add_error(None, str(exc))
            else:
                record_tenant_event(
                    tenant=tenant,
                    actor=request.user,
                    title="Miembro actualizado",
                    message=f"Se asigno el usuario '{result.user.username}' al tenant.",
                    code="membership_upserted",
                    metadata={"username": result.user.username, "role": result.membership.role},
                )
                messages.success(request, f"Acceso de '{result.user.username}' actualizado.")
                return redirect("tenants:detail", pk=tenant.pk)

        return render(request, "tenants/tenant_detail.html", _tenant_detail_context(tenant=tenant, form=form))


class TenantToggleActiveView(LoginRequiredMixin, SuperAdminRequiredMixin, View):
    def post(self, request, pk):
        tenant = Client.objects.filter(pk=pk).first()
        if not tenant:
            messages.error(request, "Tenant no encontrado.")
            return redirect("tenants:list")
        tenant.is_active = not tenant.is_active
        tenant.save(update_fields=["is_active"])
        estado = "activado" if tenant.is_active else "desactivado"
        messages.success(request, f"Tenant '{tenant.name}' {estado}.")
        return redirect("tenants:detail", pk=tenant.pk)


class MembershipToggleView(LoginRequiredMixin, View):
    def post(self, request, pk):
        membership = TenantMembership.objects.select_related("tenant", "user").filter(pk=pk).first()
        if not membership:
            messages.error(request, "Membresia no encontrada.")
            return redirect("tenants:list")
        if not _can_manage_tenant_access(tenant=membership.tenant, user=request.user):
            messages.error(request, "No tienes permisos para administrar accesos de esta empresa.")
            return redirect("tenants:access_list")
        if not membership.is_active and membership.tenant.memberships.filter(is_active=True).count() >= membership.tenant.max_users:
            messages.error(
                request,
                f"El tenant '{membership.tenant.name}' ya alcanzo su limite de {membership.tenant.max_users} usuarios activos.",
            )
            target_view = "tenants:detail" if request.user.is_superuser else "tenants:access_admin"
            return redirect(target_view, pk=membership.tenant.pk)
        membership.is_active = not membership.is_active
        membership.save(update_fields=["is_active"])
        estado = "activado" if membership.is_active else "desactivado"
        messages.success(request, f"Usuario '{membership.user.username}' {estado}.")
        target_view = "tenants:detail" if request.user.is_superuser else "tenants:access_admin"
        return redirect(target_view, pk=membership.tenant.pk)


class MembershipDeleteView(LoginRequiredMixin, View):
    def post(self, request, pk):
        membership = TenantMembership.objects.select_related("tenant", "user").filter(pk=pk).first()
        if not membership:
            messages.error(request, "Membresia no encontrada.")
            return redirect("tenants:list")
        if not _can_manage_tenant_access(tenant=membership.tenant, user=request.user):
            messages.error(request, "No tienes permisos para administrar accesos de esta empresa.")
            return redirect("tenants:access_list")
        tenant_pk = membership.tenant.pk
        username = membership.user.username
        membership.delete()
        messages.success(request, f"Usuario '{username}' removido del tenant.")
        target_view = "tenants:detail" if request.user.is_superuser else "tenants:access_admin"
        return redirect(target_view, pk=tenant_pk)


class TenantSwitchView(LoginRequiredMixin, View):
    def get(self, request, pk):
        tenant = Client.objects.filter(pk=pk, is_active=True).prefetch_related("domains").first()
        if not tenant:
            messages.error(request, "Tenant no encontrado.")
            return redirect("dashboard")

        group = None
        group_access_reason = ""
        if not request.user.is_superuser:
            membership = get_tenant_membership(tenant=tenant, user=request.user)
            if membership is None:
                active_context = getattr(request, "active_session_context", None)
                group_id = getattr(active_context, "corporate_group_id", None)
                if group_id:
                    group = CorporateGroup.objects.filter(pk=group_id, status=CorporateGroup.STATUS_ACTIVE).first()
                link = None
                if group is not None:
                    link = (
                        group.tenant_links.select_related("tenant")
                        .filter(tenant=tenant, is_active=True, tenant__is_active=True)
                        .first()
                    )
                detail_decision = None
                if group is not None and link is not None:
                    detail_decision = resolve_group_tenant_detail_access(group=group, link=link, user=request.user)
                if detail_decision is None or not detail_decision.allowed:
                    if detail_decision is not None and detail_decision.reason == "missing_group_tenant_access":
                        messages.error(request, "Tu usuario del holding todavia no tiene acceso asignado a esta empresa.")
                    else:
                        messages.error(request, "No tienes acceso a este tenant.")
                    return redirect("dashboard")
                group_access_reason = detail_decision.reason

            if membership is None:
                set_consolidated_context(request, group=group, tenant=tenant, reason="group_tenant_switch")
                record_tenant_event(
                    tenant=tenant,
                    actor=request.user,
                    title="Contexto corporativo activo",
                    message=f"Se activo el tenant '{tenant.name}' desde el holding '{group.name}'.",
                    code="tenant_context_switched_from_group",
                    metadata={"group_id": group.pk, "access_reason": group_access_reason},
                )
            else:
                set_strict_tenant_context(request, tenant=tenant, reason="tenant_switch")
                record_tenant_event(
                    tenant=tenant,
                    actor=request.user,
                    title="Contexto activo actualizado",
                    message=f"Se activo el tenant '{tenant.name}' como contexto de trabajo.",
                    code="tenant_context_switched",
                )
        else:
            set_strict_tenant_context(request, tenant=tenant, reason="tenant_switch")
            record_tenant_event(
                tenant=tenant,
                actor=request.user,
                title="Contexto activo actualizado",
                message=f"Se activo el tenant '{tenant.name}' como contexto de trabajo.",
                code="tenant_context_switched",
            )

        return _redirect_to_tenant_host(request, tenant)


class ReturnToPlatformView(LoginRequiredMixin, View):
    def get(self, request):
        request.session.pop(LOCAL_PREVIEW_SESSION_KEY, None)
        clear_active_access_context(request, reason="return_to_platform")

        current_host = request.get_host().split(":")[0].lower()
        if settings.DEBUG and current_host in {"localhost", "127.0.0.1"}:
            target = reverse("tenants:list") if request.user.is_superuser else reverse("tenants:access_list")
            return redirect(f"{request.scheme}://{request.get_host()}{target}?_tenant=public")

        return redirect(build_public_app_url(request, "tenants:list" if request.user.is_superuser else "tenants:access_list"))
