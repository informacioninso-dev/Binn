import logging

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.contrib.auth.views import LoginView
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.generic import ListView, UpdateView, View

from .forms import (
    AddMemberForm,
    TenantAuthenticationForm,
    TenantCreateForm,
    TenantEditForm,
    TenantListFilterForm,
)
from .models import Client, Domain, TenantMembership, TenantOperationalEvent
from .observability import (
    build_system_health_payload,
    build_tenant_diagnostics,
    diagnostics_to_payload,
    record_tenant_event,
)
from .services import TenantProvisionError, assign_tenant_membership, create_tenant


logger = logging.getLogger(__name__)


def _tenant_queryset():
    return Client.objects.prefetch_related("domains", "memberships__user")


def _load_tenant(pk):
    tenant = _tenant_queryset().filter(pk=pk).first()
    if tenant:
        _attach_tenant_operational_context(tenant)
    return tenant


def _attach_tenant_operational_context(tenant: Client) -> Client:
    domains = list(tenant.domains.all())
    memberships = list(tenant.memberships.all())
    diagnostics = build_tenant_diagnostics(tenant, domains=domains, memberships=memberships)
    tenant.diagnostics = diagnostics
    tenant.primary_domain_value = diagnostics.primary_domain
    return tenant


def _build_tenant_detail_context(tenant: Client, form: AddMemberForm) -> dict:
    recent_events = list(tenant.operational_events.select_related("actor")[:10])
    return {
        "tenant": tenant,
        "form": form,
        "diagnostics": tenant.diagnostics,
        "plan_definition": tenant.plan_definition,
        "recent_events": recent_events,
    }


class SuperAdminRequiredMixin(UserPassesTestMixin):
    def test_func(self):
        return self.request.user.is_superuser


class SystemHealthView(View):
    def get(self, request):
        tenant = getattr(request, "tenant", None)
        current_tenant = None
        if tenant and tenant.schema_name != settings.PUBLIC_SCHEMA_NAME:
            current_tenant = tenant

        payload, status_code = build_system_health_payload(tenant=current_tenant)
        return JsonResponse(payload, status=status_code)


class TenantHealthView(LoginRequiredMixin, SuperAdminRequiredMixin, View):
    def get(self, request, pk):
        tenant = _load_tenant(pk)
        if not tenant:
            return JsonResponse({"status": "error", "message": "Clinica no encontrada."}, status=404)

        payload = diagnostics_to_payload(tenant.diagnostics)
        payload["recent_events"] = [
            {
                "kind": event.kind,
                "severity": event.severity,
                "status": event.status,
                "code": event.code,
                "title": event.title,
                "message": event.message,
                "actor": getattr(event.actor, "username", ""),
                "created_at": event.created_at.isoformat(),
            }
            for event in tenant.operational_events.select_related("actor")[:10]
        ]
        status_code = 503 if tenant.diagnostics.status == TenantOperationalEvent.SEVERITY_ERROR else 200
        return JsonResponse(payload, status=status_code)


class TenantLoginView(LoginView):
    template_name = "auth/login.html"
    authentication_form = TenantAuthenticationForm

    def form_valid(self, form):
        user = form.get_user()
        tenant = getattr(self.request, "tenant", None)
        if tenant and tenant.schema_name == settings.PUBLIC_SCHEMA_NAME and not user.is_superuser:
            has_membership = TenantMembership.objects.filter(
                user=user,
                is_active=True,
                tenant__is_active=True,
            ).exists()
            if not has_membership:
                form.add_error(None, "No tienes clinicas activas asignadas.")
                return self.form_invalid(form)
        return super().form_valid(form)

    def get_success_url(self):
        redirect_to = self.get_redirect_url()
        if redirect_to:
            return redirect_to

        tenant = getattr(self.request, "tenant", None)
        if tenant and tenant.schema_name == settings.PUBLIC_SCHEMA_NAME:
            if self.request.user.is_superuser:
                return reverse("tenants:list")

            memberships = TenantMembership.objects.filter(
                user=self.request.user,
                is_active=True,
                tenant__is_active=True,
            ).select_related("tenant")

            if memberships.count() == 1:
                return reverse("tenants:switch", kwargs={"pk": memberships.first().tenant_id})
            return reverse("dashboard")

        return reverse("dashboard")


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

        tenants = [_attach_tenant_operational_context(tenant) for tenant in qs]

        alert_state = ""
        if self.filter_form.is_valid():
            alert_state = self.filter_form.cleaned_data.get("alert_state") or ""

        if alert_state == TenantListFilterForm.ALERT_OK:
            tenants = [tenant for tenant in tenants if not tenant.diagnostics.alerts]
        elif alert_state == TenantListFilterForm.ALERT_NEEDS_ATTENTION:
            tenants = [tenant for tenant in tenants if tenant.diagnostics.alerts]

        self.summary = {
            "total": len(tenants),
            "active": sum(1 for tenant in tenants if tenant.is_active),
            "with_alerts": sum(1 for tenant in tenants if tenant.diagnostics.alerts),
            "enterprise": sum(1 for tenant in tenants if tenant.plan == Client.PLAN_ENTERPRISE),
        }
        return tenants

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["filter_form"] = getattr(self, "filter_form", TenantListFilterForm())
        ctx["summary"] = getattr(self, "summary", {"total": 0, "active": 0, "with_alerts": 0, "enterprise": 0})
        return ctx


class TenantCreateView(LoginRequiredMixin, SuperAdminRequiredMixin, View):
    template_name = "tenants/tenant_form.html"

    def get(self, request):
        return render(request, self.template_name, {"form": TenantCreateForm()})

    def post(self, request):
        form = TenantCreateForm(request.POST)
        if not form.is_valid():
            return render(request, self.template_name, {"form": form})

        try:
            result = create_tenant(
                schema_name=form.cleaned_data["schema_name"],
                name=form.cleaned_data["name"],
                domain=form.cleaned_data["subdomain"],
                plan=form.cleaned_data["plan"],
                admin_username=form.cleaned_data.get("admin_username", ""),
                admin_email=form.cleaned_data.get("admin_email", ""),
                admin_password=form.cleaned_data.get("admin_password", ""),
            )
        except TenantProvisionError as exc:
            logger.warning("Fallo al crear clinica.", extra={"tenant_schema": form.cleaned_data.get("schema_name", "public")})
            messages.error(request, str(exc))
            return render(request, self.template_name, {"form": form})

        for notice in result.notices:
            messages.info(request, notice)

        record_tenant_event(
            tenant=result.client,
            actor=request.user,
            title="Clinica creada",
            message=f"Se creo la clinica '{result.client.name}' con plan {result.client.get_plan_display()}.",
            code="tenant_created",
            metadata={"plan": result.client.plan},
        )
        messages.success(request, f"Clinica '{result.client.name}' creada correctamente.")
        return redirect("tenants:list")


class TenantEditView(LoginRequiredMixin, SuperAdminRequiredMixin, UpdateView):
    model = Client
    form_class = TenantEditForm
    template_name = "tenants/tenant_edit.html"

    def form_valid(self, form):
        previous_values = {field: getattr(self.object, field) for field in form.changed_data}
        response = super().form_valid(form)

        if form.changed_data:
            changes = {
                field: {
                    "before": str(previous_values[field]),
                    "after": str(getattr(self.object, field)),
                }
                for field in form.changed_data
            }
            record_tenant_event(
                tenant=self.object,
                actor=self.request.user,
                title="Clinica actualizada",
                message=f"Se actualizaron {len(form.changed_data)} campos de configuracion.",
                code="tenant_updated",
                metadata={"changes": changes},
            )

        return response

    def get_success_url(self):
        messages.success(self.request, f"Clinica '{self.object.name}' actualizada.")
        return self.object.get_absolute_url()

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["domains"] = self.object.domains.all()
        diagnostics = build_tenant_diagnostics(
            self.object,
            domains=self.object.domains.all(),
            memberships=self.object.memberships.all(),
        )
        ctx["diagnostics"] = diagnostics
        ctx["plan_definition"] = diagnostics.plan_definition
        return ctx


class TenantDetailView(LoginRequiredMixin, SuperAdminRequiredMixin, View):
    def get(self, request, pk):
        tenant = _load_tenant(pk)
        if not tenant:
            messages.error(request, "Clinica no encontrada.")
            return redirect("tenants:list")
        return render(
            request,
            "tenants/tenant_detail.html",
            _build_tenant_detail_context(tenant, AddMemberForm()),
        )

    def post(self, request, pk):
        tenant = _load_tenant(pk)
        if not tenant:
            messages.error(request, "Clinica no encontrada.")
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
                return render(
                    request,
                    "tenants/tenant_detail.html",
                    _build_tenant_detail_context(tenant, form),
                )

            title = "Miembro agregado" if result.membership_created else "Membresia actualizada"
            record_tenant_event(
                tenant=tenant,
                actor=request.user,
                title=title,
                message=(
                    f"Se asigno el usuario '{result.user.username}' a la clinica."
                    if result.membership_created
                    else f"Se actualizaron permisos locales de '{result.user.username}'."
                ),
                code="membership_upserted",
                metadata={
                    "username": result.user.username,
                    "role": result.membership.role,
                    "is_admin": result.membership.is_admin,
                    "is_active": result.membership.is_active,
                },
            )

            if result.membership_created:
                messages.success(request, f"Usuario '{result.user.username}' agregado.")
            else:
                messages.success(request, f"Acceso de '{result.user.username}' actualizado.")
            return redirect("tenants:detail", pk=tenant.pk)

        return render(
            request,
            "tenants/tenant_detail.html",
            _build_tenant_detail_context(tenant, form),
        )


class TenantToggleActiveView(LoginRequiredMixin, SuperAdminRequiredMixin, View):
    def post(self, request, pk):
        tenant = Client.objects.filter(pk=pk).first()
        if not tenant:
            messages.error(request, "Clinica no encontrada.")
            return redirect("tenants:list")
        tenant.is_active = not tenant.is_active
        tenant.save(update_fields=["is_active"])
        estado = "activada" if tenant.is_active else "desactivada"
        record_tenant_event(
            tenant=tenant,
            actor=request.user,
            title=f"Clinica {estado}",
            message=f"El superadmin dejo la clinica en estado {estado}.",
            code="tenant_toggled",
            severity=(
                TenantOperationalEvent.SEVERITY_INFO
                if tenant.is_active
                else TenantOperationalEvent.SEVERITY_WARNING
            ),
            metadata={"is_active": tenant.is_active},
        )
        messages.success(request, f"Clinica '{tenant.name}' {estado}.")
        return redirect("tenants:detail", pk=tenant.pk)


class MembershipToggleView(LoginRequiredMixin, SuperAdminRequiredMixin, View):
    def post(self, request, pk):
        membership = TenantMembership.objects.select_related("tenant", "user").filter(pk=pk).first()
        if not membership:
            messages.error(request, "Membresia no encontrada.")
            return redirect("tenants:list")
        membership.is_active = not membership.is_active
        membership.save(update_fields=["is_active"])
        estado = "activado" if membership.is_active else "desactivado"
        record_tenant_event(
            tenant=membership.tenant,
            actor=request.user,
            title="Estado de miembro actualizado",
            message=f"El usuario '{membership.user.username}' quedo {estado} en la clinica.",
            code="membership_toggled",
            severity=(
                TenantOperationalEvent.SEVERITY_INFO
                if membership.is_active
                else TenantOperationalEvent.SEVERITY_WARNING
            ),
            metadata={"username": membership.user.username, "is_active": membership.is_active},
        )
        messages.success(request, f"Usuario '{membership.user.username}' {estado}.")
        return redirect("tenants:detail", pk=membership.tenant.pk)


class MembershipDeleteView(LoginRequiredMixin, SuperAdminRequiredMixin, View):
    def post(self, request, pk):
        membership = TenantMembership.objects.select_related("tenant", "user").filter(pk=pk).first()
        if not membership:
            messages.error(request, "Membresia no encontrada.")
            return redirect("tenants:list")
        tenant_pk = membership.tenant.pk
        username = membership.user.username
        tenant = membership.tenant
        membership.delete()
        record_tenant_event(
            tenant=tenant,
            actor=request.user,
            title="Miembro removido",
            message=f"Se removio al usuario '{username}' de la clinica.",
            code="membership_removed",
            severity=TenantOperationalEvent.SEVERITY_WARNING,
            metadata={"username": username},
        )
        messages.success(request, f"Usuario '{username}' removido de la clinica.")
        return redirect("tenants:detail", pk=tenant_pk)


class TenantSwitchView(LoginRequiredMixin, View):
    def get(self, request, pk):
        tenant = Client.objects.filter(pk=pk, is_active=True).prefetch_related("domains").first()
        if not tenant:
            messages.error(request, "Clinica no encontrada.")
            return redirect("dashboard")

        if not request.user.is_superuser:
            has_membership = TenantMembership.objects.filter(
                tenant=tenant,
                user=request.user,
                is_active=True,
            ).exists()
            if not has_membership:
                messages.error(request, "No tienes acceso a esta clinica.")
                return redirect("dashboard")

        domain = tenant.domains.filter(is_primary=True).first() or tenant.domains.first()
        if not domain:
            logger.error(
                "Clinica sin dominio configurado intento ser abierta.",
                extra={"tenant_schema": tenant.schema_name, "actor_id": getattr(request.user, "pk", "-") or "-"},
            )
            messages.error(request, "La clinica no tiene dominio configurado.")
            return redirect("dashboard")

        host = request.get_host()
        port = ""
        if ":" in host:
            port = ":" + host.split(":")[-1]
        return redirect(f"{request.scheme}://{domain.domain}{port}/")
