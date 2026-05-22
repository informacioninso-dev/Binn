from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.shortcuts import get_object_or_404, redirect, render
from django.views.generic import ListView, View

from access.runtime import get_active_group_membership
from access.services import set_consolidated_context
from tenants.middleware import LOCAL_PREVIEW_SESSION_KEY

from .forms import (
    BillingAccountForm,
    CorporateGroupForm,
    GroupMembershipAssignForm,
    GroupTenantAccessAssignForm,
    GroupTenantLinkForm,
    OperationalAccessGrantDecisionForm,
    OperationalAccessRequestForm,
)
from .models import CorporateGroup, GroupMembership, GroupTenantAccess, GroupTenantLink, OperationalAccessGrant
from .services import (
    can_manage_group,
    can_manage_group_access,
    can_manage_group_billing,
    build_group_usage_snapshot,
    can_allocate_group_seat,
    can_allocate_manager_assignment,
    can_request_operational_access,
    create_operational_access_request,
    decide_operational_access_request,
    get_group_membership,
    get_or_create_billing_account,
    record_governance_event,
)


def _group_queryset():
    return CorporateGroup.objects.select_related("owner").prefetch_related(
        "tenant_links__tenant__domains",
        "memberships__user",
        "tenant_accesses__tenant",
        "tenant_accesses__user",
        "events__actor",
        "operational_access_grants__tenant",
        "operational_access_grants__user",
        "operational_access_grants__requested_by",
        "operational_access_grants__decided_by",
    )


def _can_view_group(*, request, group) -> bool:
    if request.user.is_superuser:
        return True
    membership = get_group_membership(group=group, user=request.user)
    return bool(membership and membership.can_view_group_dashboard())


def _group_detail_context(
    *,
    request,
    group,
    membership_form=None,
    tenant_link_form=None,
    tenant_access_form=None,
    billing_form=None,
    access_request_form=None,
    decision_form=None,
):
    membership = None if request.user.is_superuser else get_group_membership(group=group, user=request.user)
    billing_account = get_or_create_billing_account(group=group)
    can_manage = can_manage_group(group=group, user=request.user, membership=membership)
    can_manage_billing_flag = can_manage_group_billing(group=group, user=request.user, membership=membership)
    can_request_access = can_request_operational_access(group=group, user=request.user, membership=membership)
    can_manage_group_access_flag = can_manage_group_access(group=group, user=request.user, membership=membership)
    usage_snapshot = build_group_usage_snapshot(group=group)

    return {
        "group": group,
        "group_membership": membership,
        "memberships": group.memberships.select_related("user").order_by("user__username"),
        "tenant_links": group.tenant_links.select_related("tenant").order_by("-is_primary", "tenant__name"),
        "tenant_accesses": group.tenant_accesses.select_related("tenant", "user", "granted_by").order_by("tenant__name", "user__username"),
        "billing_account": billing_account,
        "billing_form": billing_form or BillingAccountForm(instance=billing_account),
        "membership_form": membership_form or GroupMembershipAssignForm(group=group),
        "tenant_link_form": tenant_link_form or GroupTenantLinkForm(group=group),
        "tenant_access_form": tenant_access_form or GroupTenantAccessAssignForm(group=group),
        "access_request_form": access_request_form or OperationalAccessRequestForm(group=group),
        "decision_form": decision_form or OperationalAccessGrantDecisionForm(),
        "pending_grants": group.operational_access_grants.select_related(
            "tenant", "user", "requested_by", "decided_by"
        ).filter(status=OperationalAccessGrant.STATUS_PENDING),
        "recent_grants": group.operational_access_grants.select_related(
            "tenant", "user", "requested_by", "decided_by"
        )[:10],
        "recent_events": group.events.select_related("actor", "tenant")[:10],
        "usage_snapshot": usage_snapshot,
        "can_manage_group": can_manage,
        "can_manage_billing": can_manage_billing_flag,
        "can_manage_group_access": can_manage_group_access_flag,
        "can_manage_links": request.user.is_superuser,
        "can_manage_operational_grants": request.user.is_superuser,
        "can_request_operational_access": can_request_access,
    }


class SuperAdminRequiredMixin(UserPassesTestMixin):
    def test_func(self):
        return self.request.user.is_superuser


class CorporateGroupListView(LoginRequiredMixin, SuperAdminRequiredMixin, ListView):
    model = CorporateGroup
    template_name = "governance/group_list.html"
    context_object_name = "groups"
    paginate_by = 20

    def get_queryset(self):
        return _group_queryset().order_by("name")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        queryset = self.object_list
        context["summary"] = {
            "total": queryset.count(),
            "active": queryset.filter(status=CorporateGroup.STATUS_ACTIVE).count(),
            "islands": queryset.filter(operating_model=CorporateGroup.OPERATING_MODEL_ISLANDS).count(),
            "family": queryset.filter(operating_model=CorporateGroup.OPERATING_MODEL_FAMILY).count(),
        }
        return context


class CorporateGroupCreateView(LoginRequiredMixin, SuperAdminRequiredMixin, View):
    template_name = "governance/group_form.html"

    def get(self, request):
        return render(
            request,
            self.template_name,
            {
                "form": CorporateGroupForm(),
                "page_title": "Nuevo holding corporativo",
                "submit_label": "Crear holding",
            },
        )

    def post(self, request):
        form = CorporateGroupForm(request.POST)
        if not form.is_valid():
            return render(
                request,
                self.template_name,
                {
                    "form": form,
                    "page_title": "Nuevo holding corporativo",
                    "submit_label": "Crear holding",
                },
            )

        group = form.save()
        record_governance_event(
            event_type="corporate_group_created",
            message=f"Se creo el holding '{group.name}'.",
            actor=request.user,
            group=group,
            metadata={
                "operating_model": group.operating_model,
                "consolidation_mode": group.consolidation_mode,
            },
        )
        messages.success(request, f"Holding '{group.name}' creado.")
        return redirect("governance:group_detail", pk=group.pk)


class CorporateGroupEditView(LoginRequiredMixin, SuperAdminRequiredMixin, View):
    template_name = "governance/group_form.html"

    def get(self, request, pk):
        group = get_object_or_404(CorporateGroup, pk=pk)
        return render(
            request,
            self.template_name,
            {
                "form": CorporateGroupForm(instance=group),
                "group": group,
                "page_title": f"Editar {group.name}",
                "submit_label": "Guardar cambios",
            },
        )

    def post(self, request, pk):
        group = get_object_or_404(CorporateGroup, pk=pk)
        form = CorporateGroupForm(request.POST, instance=group)
        if not form.is_valid():
            return render(
                request,
                self.template_name,
                {
                    "form": form,
                    "group": group,
                    "page_title": f"Editar {group.name}",
                    "submit_label": "Guardar cambios",
                },
            )

        group = form.save()
        record_governance_event(
            event_type="corporate_group_updated",
            message=f"Se actualizo el holding '{group.name}'.",
            actor=request.user,
            group=group,
            metadata={
                "operating_model": group.operating_model,
                "consolidation_mode": group.consolidation_mode,
                "status": group.status,
            },
        )
        messages.success(request, "Holding actualizado.")
        return redirect("governance:group_detail", pk=group.pk)


class CorporateGroupDetailView(LoginRequiredMixin, View):
    template_name = "governance/group_detail.html"

    def get(self, request, pk):
        group = get_object_or_404(_group_queryset(), pk=pk)
        if not _can_view_group(request=request, group=group):
            messages.error(request, "No tienes permisos para ver este holding.")
            return redirect("dashboard")
        return render(request, self.template_name, _group_detail_context(request=request, group=group))


class CorporateGroupBillingUpdateView(LoginRequiredMixin, View):
    def post(self, request, pk):
        group = get_object_or_404(CorporateGroup, pk=pk)
        if not _can_view_group(request=request, group=group):
            messages.error(request, "No tienes permisos para ver este holding.")
            return redirect("dashboard")
        if not can_manage_group_billing(group=group, user=request.user):
            messages.error(request, "No tienes permisos para actualizar billing de este holding.")
            return redirect("governance:group_detail", pk=group.pk)

        billing_account = get_or_create_billing_account(group=group)
        form = BillingAccountForm(request.POST, instance=billing_account)
        if form.is_valid():
            form.save()
            record_governance_event(
                event_type="group_billing_updated",
                message=f"Se actualizo la cuenta de billing del holding '{group.name}'.",
                actor=request.user,
                group=group,
            )
            messages.success(request, "Billing actualizado.")
            return redirect("governance:group_detail", pk=group.pk)

        return render(
            request,
            "governance/group_detail.html",
            _group_detail_context(request=request, group=group, billing_form=form),
        )


class CorporateGroupMembershipUpsertView(LoginRequiredMixin, View):
    def post(self, request, pk):
        group = get_object_or_404(CorporateGroup, pk=pk)
        if not _can_view_group(request=request, group=group):
            messages.error(request, "No tienes permisos para ver este holding.")
            return redirect("dashboard")
        if not can_manage_group(group=group, user=request.user):
            messages.error(request, "No tienes permisos para administrar miembros de este holding.")
            return redirect("governance:group_detail", pk=group.pk)

        form = GroupMembershipAssignForm(request.POST, group=group)
        if form.is_valid():
            current_membership = GroupMembership.objects.filter(group=group, user=form.user).first()
            if form.cleaned_data["is_active"] and not can_allocate_group_seat(group=group, current_membership=current_membership):
                form.add_error(None, "El holding ya alcanzo su limite de licencias activas.")
                return render(
                    request,
                    "governance/group_detail.html",
                    _group_detail_context(request=request, group=group, membership_form=form),
                )
            membership, created = GroupMembership.objects.update_or_create(
                group=group,
                user=form.user,
                defaults={
                    "role": form.cleaned_data["role"],
                    "is_active": form.cleaned_data["is_active"],
                },
            )
            action = "creo" if created else "actualizo"
            record_governance_event(
                event_type="group_membership_upserted",
                message=f"Se {action} la membresia global de '{membership.user.username}' en el holding '{group.name}'.",
                actor=request.user,
                group=group,
                metadata={"username": membership.user.username, "role": membership.role},
            )
            messages.success(request, "Membresia de grupo actualizada.")
            return redirect("governance:group_detail", pk=group.pk)

        return render(
            request,
            "governance/group_detail.html",
            _group_detail_context(request=request, group=group, membership_form=form),
        )


class CorporateGroupTenantLinkUpsertView(LoginRequiredMixin, SuperAdminRequiredMixin, View):
    def post(self, request, pk):
        group = get_object_or_404(CorporateGroup, pk=pk)
        form = GroupTenantLinkForm(request.POST, group=group)
        if form.is_valid():
            tenant = form.cleaned_data["tenant"]
            link, created = GroupTenantLink.objects.update_or_create(
                group=group,
                tenant=tenant,
                defaults={
                    "consolidation_mode": form.cleaned_data["consolidation_mode"],
                    "is_primary": form.cleaned_data["is_primary"],
                    "is_active": form.cleaned_data["is_active"],
                },
            )
            if link.is_primary:
                GroupTenantLink.objects.filter(group=group).exclude(pk=link.pk).update(is_primary=False)
            action = "creo" if created else "actualizo"
            record_governance_event(
                event_type="group_tenant_link_upserted",
                message=f"Se {action} el vinculo de '{tenant.name}' dentro del holding '{group.name}'.",
                actor=request.user,
                group=group,
                tenant=tenant,
                metadata={"consolidation_mode": link.consolidation_mode, "is_primary": str(link.is_primary)},
            )
            messages.success(request, "Vinculo de empresa actualizado.")
            return redirect("governance:group_detail", pk=group.pk)

        return render(
            request,
            "governance/group_detail.html",
            _group_detail_context(request=request, group=group, tenant_link_form=form),
        )


class CorporateGroupTenantAccessUpsertView(LoginRequiredMixin, View):
    def post(self, request, pk):
        group = get_object_or_404(CorporateGroup, pk=pk)
        if not _can_view_group(request=request, group=group):
            messages.error(request, "No tienes permisos para ver este holding.")
            return redirect("dashboard")
        if not can_manage_group_access(group=group, user=request.user):
            messages.error(request, "No tienes permisos para administrar accesos por empresa en este holding.")
            return redirect("governance:group_detail", pk=group.pk)

        form = GroupTenantAccessAssignForm(request.POST, group=group)
        if form.is_valid():
            tenant = form.link.tenant
            current_access = GroupTenantAccess.objects.filter(group=group, tenant=tenant, user=form.user).first()
            if (
                form.cleaned_data["is_active"]
                and not can_allocate_manager_assignment(
                    group=group,
                    current_access=current_access,
                    target_role=form.cleaned_data["role"],
                )
            ):
                form.add_error(None, "El holding ya alcanzo su limite de managers asignables.")
                return render(
                    request,
                    "governance/group_detail.html",
                    _group_detail_context(request=request, group=group, tenant_access_form=form),
                )
            access, created = GroupTenantAccess.objects.update_or_create(
                group=group,
                tenant=tenant,
                user=form.user,
                defaults={
                    "role": form.cleaned_data["role"],
                    "is_active": form.cleaned_data["is_active"],
                    "granted_by": request.user,
                },
            )
            action = "creo" if created else "actualizo"
            record_governance_event(
                event_type="group_tenant_access_upserted",
                message=f"Se {action} el acceso de '{form.user.username}' a '{tenant.name}' dentro del holding '{group.name}'.",
                actor=request.user,
                group=group,
                tenant=tenant,
                metadata={"username": form.user.username, "role": access.role, "is_active": str(access.is_active)},
            )
            messages.success(request, "Acceso por empresa actualizado.")
            return redirect("governance:group_detail", pk=group.pk)

        return render(
            request,
            "governance/group_detail.html",
            _group_detail_context(request=request, group=group, tenant_access_form=form),
        )


class GroupTenantAccessToggleView(LoginRequiredMixin, View):
    def post(self, request, access_pk):
        tenant_access = get_object_or_404(GroupTenantAccess.objects.select_related("group", "tenant", "user"), pk=access_pk)
        group = tenant_access.group
        if not _can_view_group(request=request, group=group):
            messages.error(request, "No tienes permisos para ver este holding.")
            return redirect("dashboard")
        if not can_manage_group_access(group=group, user=request.user):
            messages.error(request, "No tienes permisos para administrar accesos por empresa en este holding.")
            return redirect("governance:group_detail", pk=group.pk)

        tenant_access.is_active = not tenant_access.is_active
        tenant_access.granted_by = request.user
        tenant_access.save(update_fields=["is_active", "granted_by", "updated_at"])
        record_governance_event(
            event_type="group_tenant_access_toggled",
            message=f"Se {'activo' if tenant_access.is_active else 'desactivo'} el acceso de '{tenant_access.user.username}' a '{tenant_access.tenant.name}'.",
            actor=request.user,
            group=group,
            tenant=tenant_access.tenant,
            metadata={"username": tenant_access.user.username, "role": tenant_access.role, "is_active": str(tenant_access.is_active)},
        )
        messages.success(request, "Estado del acceso actualizado.")
        return redirect("governance:group_detail", pk=group.pk)


class GroupTenantAccessDeleteView(LoginRequiredMixin, View):
    def post(self, request, access_pk):
        tenant_access = get_object_or_404(GroupTenantAccess.objects.select_related("group", "tenant", "user"), pk=access_pk)
        group = tenant_access.group
        if not _can_view_group(request=request, group=group):
            messages.error(request, "No tienes permisos para ver este holding.")
            return redirect("dashboard")
        if not can_manage_group_access(group=group, user=request.user):
            messages.error(request, "No tienes permisos para administrar accesos por empresa en este holding.")
            return redirect("governance:group_detail", pk=group.pk)

        username = tenant_access.user.username
        tenant_name = tenant_access.tenant.name
        tenant = tenant_access.tenant
        tenant_access.delete()
        record_governance_event(
            event_type="group_tenant_access_deleted",
            message=f"Se elimino el acceso de '{username}' a '{tenant_name}' dentro del holding '{group.name}'.",
            actor=request.user,
            group=group,
            tenant=tenant,
            metadata={"username": username},
        )
        messages.success(request, "Acceso eliminado.")
        return redirect("governance:group_detail", pk=group.pk)


class OperationalAccessRequestCreateView(LoginRequiredMixin, View):
    def post(self, request, pk):
        group = get_object_or_404(CorporateGroup, pk=pk)
        if not _can_view_group(request=request, group=group):
            messages.error(request, "No tienes permisos para ver este holding.")
            return redirect("dashboard")
        if not can_request_operational_access(group=group, user=request.user):
            messages.error(request, "Tu rol actual no puede solicitar acceso operativo.")
            return redirect("governance:group_detail", pk=group.pk)

        form = OperationalAccessRequestForm(request.POST, group=group)
        if form.is_valid():
            try:
                grant, created = create_operational_access_request(
                    group=group,
                    tenant=form.link.tenant,
                    user=request.user,
                    requested_by=request.user,
                    justification=form.cleaned_data.get("justification", ""),
                    expires_at=form.cleaned_data.get("expires_at"),
                )
            except ValueError as exc:
                form.add_error(None, str(exc))
                return render(
                    request,
                    "governance/group_detail.html",
                    _group_detail_context(request=request, group=group, access_request_form=form),
                )
            if created:
                record_governance_event(
                    event_type="operational_access_requested",
                    message=f"Se solicito acceso operativo a '{form.link.tenant.name}' desde el holding '{group.name}'.",
                    actor=request.user,
                    group=group,
                    tenant=form.link.tenant,
                    metadata={"grant_id": str(grant.pk)},
                )
                messages.success(request, "Solicitud de acceso operativo enviada.")
            else:
                messages.info(request, "Ya existia una solicitud pendiente o aprobada para esta empresa.")
            return redirect("governance:group_detail", pk=group.pk)

        return render(
            request,
            "governance/group_detail.html",
            _group_detail_context(request=request, group=group, access_request_form=form),
        )


class OperationalAccessGrantDecisionView(LoginRequiredMixin, SuperAdminRequiredMixin, View):
    def post(self, request, grant_pk):
        grant = get_object_or_404(
            OperationalAccessGrant.objects.select_related("group", "tenant", "user"),
            pk=grant_pk,
        )
        form = OperationalAccessGrantDecisionForm(request.POST)
        if form.is_valid():
            grant.expires_at = form.cleaned_data.get("expires_at")
            grant.save(update_fields=["expires_at", "updated_at"])
            try:
                decide_operational_access_request(
                    grant=grant,
                    actor=request.user,
                    status=form.cleaned_data["status"],
                    decision_note=form.cleaned_data.get("decision_note", ""),
                )
            except ValueError as exc:
                form.add_error(None, str(exc))
                return render(
                    request,
                    "governance/group_detail.html",
                    _group_detail_context(request=request, group=grant.group, decision_form=form),
                )
            record_governance_event(
                event_type="operational_access_decided",
                message=f"Se tomo una decision sobre el acceso operativo a '{grant.tenant.name}'.",
                actor=request.user,
                group=grant.group,
                tenant=grant.tenant,
                metadata={"grant_id": str(grant.pk), "status": grant.status},
            )
            messages.success(request, "Decision registrada.")
            return redirect("governance:group_detail", pk=grant.group.pk)

        return render(
            request,
            "governance/group_detail.html",
            _group_detail_context(request=request, group=grant.group, decision_form=form),
        )


class CorporateGroupSwitchView(LoginRequiredMixin, View):
    def get(self, request, pk):
        group = CorporateGroup.objects.filter(pk=pk, status=CorporateGroup.STATUS_ACTIVE).first()
        if group is None:
            messages.error(request, "Grupo corporativo no encontrado.")
            return redirect("dashboard")

        if not request.user.is_superuser:
            membership = get_active_group_membership(group_id=group.pk, user=request.user)
            if membership is None:
                messages.error(request, "No tienes acceso a este grupo corporativo.")
                return redirect("dashboard")

        set_consolidated_context(request, group=group, tenant=None, reason="group_switch")
        request.session.pop(LOCAL_PREVIEW_SESSION_KEY, None)
        record_governance_event(
            event_type="group_context_switched",
            message=f"Se activo el contexto consolidado del grupo '{group.name}'.",
            actor=request.user,
            group=group,
            metadata={"group_mode": group.consolidation_mode, "operating_model": group.operating_model},
        )
        return redirect("consolidation:group_dashboard", pk=group.pk)
