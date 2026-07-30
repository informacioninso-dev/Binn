from datetime import timedelta

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.generic import View

from access.services import set_consolidated_context
from governance.models import CorporateGroup
from governance.services import record_governance_event, resolve_group_tenant_detail_access
from tenants.middleware import LOCAL_PREVIEW_SESSION_KEY
from tenants.workspace_packs import build_group_pack_mix

from .models import ConsolidationRun
from .services import (
    SNAPSHOT_STALE_AFTER,
    build_group_dashboard_rows,
    build_group_report_sections,
    ensure_group_snapshot_fresh,
    get_group_dashboard_access,
)


class CorporateGroupDashboardView(LoginRequiredMixin, View):
    template_name = "consolidation/group_dashboard.html"

    def get(self, request, pk):
        group = CorporateGroup.objects.filter(pk=pk, status=CorporateGroup.STATUS_ACTIVE).first()
        if group is None:
            messages.error(request, "Grupo corporativo no encontrado.")
            return redirect("dashboard")

        access = get_group_dashboard_access(group=group, user=request.user)
        if not access.allowed:
            messages.error(request, "No tienes permisos para ver este holding.")
            return redirect("dashboard")

        force_refresh = request.GET.get("refresh") == "1"
        snapshot = ensure_group_snapshot_fresh(group=group, actor=request.user, trigger="dashboard", force=force_refresh)
        rows = build_group_dashboard_rows(group=group, user=request.user)
        set_consolidated_context(request, group=group, tenant=None, reason="group_dashboard")
        request.session.pop(LOCAL_PREVIEW_SESSION_KEY, None)
        record_governance_event(
            event_type="group_dashboard_viewed",
            message=f"Se abrio el dashboard consolidado del grupo '{group.name}'.",
            actor=request.user,
            group=group,
            metadata={
                "force_refresh": str(force_refresh),
                "included_tenants_count": str(snapshot.included_tenants_count),
            },
        )
        return render(
            request,
            self.template_name,
            {
                "group": group,
                "group_membership": access.membership,
                "snapshot": snapshot,
                "summary_cards": _build_summary_cards(snapshot),
                "tenant_rows": rows,
                "profile_mix": build_group_pack_mix(tenant_rows=rows),
                "group_mode_label": _group_mode_label(group.consolidation_mode),
                "group_mode_copy": _group_mode_copy(group.consolidation_mode),
                "open_deal_amounts_display": _format_amounts(snapshot.open_deal_amounts),
                "outstanding_balance_amounts_display": _format_amounts(snapshot.outstanding_balance_amounts),
            },
        )


class CorporateGroupReportsView(LoginRequiredMixin, View):
    template_name = "consolidation/group_reports.html"

    def get(self, request, pk):
        group = CorporateGroup.objects.filter(pk=pk, status=CorporateGroup.STATUS_ACTIVE).first()
        if group is None:
            messages.error(request, "Grupo corporativo no encontrado.")
            return redirect("dashboard")

        access = get_group_dashboard_access(group=group, user=request.user)
        if not access.allowed:
            messages.error(request, "No tienes permisos para ver este holding.")
            return redirect("dashboard")

        force_refresh = request.GET.get("refresh") == "1"
        snapshot = ensure_group_snapshot_fresh(
            group=group,
            actor=request.user,
            trigger="group_reports",
            force=force_refresh,
        )
        rows = build_group_dashboard_rows(group=group, user=request.user)
        report_sections = build_group_report_sections(tenant_rows=rows)
        recent_runs = list(group.consolidation_runs.order_by("-started_at", "-id")[:6])
        run_status_summary = _build_run_status_summary(recent_runs)
        snapshot_freshness = _snapshot_freshness_badge(snapshot)

        set_consolidated_context(request, group=group, tenant=None, reason="group_reports")
        request.session.pop(LOCAL_PREVIEW_SESSION_KEY, None)
        record_governance_event(
            event_type="group_reports_viewed",
            message=f"Se abrieron los reportes corporativos del grupo '{group.name}'.",
            actor=request.user,
            group=group,
            metadata={
                "force_refresh": str(force_refresh),
                "included_tenants_count": str(snapshot.included_tenants_count),
                "runs_visible": str(len(recent_runs)),
                "failed_runs_visible": str(sum(1 for run in recent_runs if getattr(run, "status", "") == ConsolidationRun.STATUS_FAILED)),
            },
        )
        return render(
            request,
            self.template_name,
            {
                "group": group,
                "group_membership": access.membership,
                "snapshot": snapshot,
                "snapshot_freshness": snapshot_freshness,
                "report_sections": report_sections,
                "profile_mix": build_group_pack_mix(tenant_rows=rows),
                "recent_runs": recent_runs,
                "run_status_summary": run_status_summary,
            },
        )


class CorporateGroupTenantSwitchView(LoginRequiredMixin, View):
    def get(self, request, group_pk, tenant_pk):
        group = CorporateGroup.objects.filter(pk=group_pk, status=CorporateGroup.STATUS_ACTIVE).first()
        if group is None:
            messages.error(request, "Grupo corporativo no encontrado.")
            return redirect("dashboard")

        access = get_group_dashboard_access(group=group, user=request.user)
        if not access.allowed:
            messages.error(request, "No tienes permisos para usar este holding.")
            return redirect("dashboard")

        link = (
            group.tenant_links.select_related("tenant")
            .filter(tenant_id=tenant_pk, is_active=True, tenant__is_active=True)
            .first()
        )
        if link is None:
            messages.error(request, "La empresa no pertenece a este holding.")
            return redirect("consolidation:group_dashboard", pk=group.pk)

        detail_decision = resolve_group_tenant_detail_access(group=group, link=link, user=request.user)
        if not detail_decision.allowed:
            if detail_decision.reason == "missing_group_tenant_access":
                messages.error(request, "Tu usuario del holding todavia no tiene acceso asignado a esta empresa.")
            else:
                messages.error(request, "Esta empresa no permite drill-down corporativo.")
            return redirect("consolidation:group_dashboard", pk=group.pk)

        set_consolidated_context(request, group=group, tenant=link.tenant, reason="group_tenant_drilldown")
        record_governance_event(
            event_type="group_tenant_drilldown",
            message=f"Se abrio la empresa '{link.tenant.name}' desde el holding '{group.name}'.",
            actor=request.user,
            group=group,
            tenant=link.tenant,
            metadata={"effective_mode": link.effective_mode, "access_reason": detail_decision.reason},
        )
        return redirect("tenants:switch", pk=link.tenant.pk)


def _build_summary_cards(snapshot):
    return [
        {
            "label": "Empresas visibles",
            "value": snapshot.included_tenants_count,
            "copy": "Empresas que aportan datos al holding segun la politica efectiva.",
        },
        {
            "label": "Empresas bloqueadas",
            "value": snapshot.blocked_tenants_count,
            "copy": "Empresas ligadas al holding pero hermeticas por politica de Binn o del grupo.",
        },
        {
            "label": "Contactos consolidados",
            "value": snapshot.entity_count,
            "copy": "Volumen total visible desde el holding sin entrar al detalle de cada empresa.",
        },
        {
            "label": "Deals abiertos",
            "value": snapshot.open_deals_count,
            "copy": "Oportunidades activas en las empresas que si participan del consolidado.",
        },
        {
            "label": "Tareas pendientes",
            "value": snapshot.pending_activities_count,
            "copy": "Actividades abiertas en las empresas visibles para el holding.",
        },
        {
            "label": "Cobros abiertos",
            "value": snapshot.open_collections_count,
            "copy": "Compromisos de cobranza visibles dentro del alcance corporativo permitido.",
        },
    ]


def _group_mode_label(mode: str) -> str:
    mapping = {
        CorporateGroup.MODE_BLOCKED: "Holding bloqueado",
        CorporateGroup.MODE_AGGREGATE_ONLY: "Holding en solo agregados",
        CorporateGroup.MODE_FULL: "Holding con detalle habilitado",
    }
    return mapping.get(mode, mode)


def _group_mode_copy(mode: str) -> str:
    mapping = {
        CorporateGroup.MODE_BLOCKED: "El grupo existe, pero ninguna empresa comparte visibilidad corporativa.",
        CorporateGroup.MODE_AGGREGATE_ONLY: "El grupo opera como holding, pero no puede abrir detalle entre empresas.",
        CorporateGroup.MODE_FULL: "El grupo puede consolidar y abrir detalle, siempre que cada empresa tambien lo permita.",
    }
    return mapping.get(mode, "")




def _build_run_status_summary(recent_runs):
    counts = {
        ConsolidationRun.STATUS_SUCCEEDED: 0,
        ConsolidationRun.STATUS_RUNNING: 0,
        ConsolidationRun.STATUS_FAILED: 0,
    }
    for run in recent_runs or []:
        status = getattr(run, "status", "")
        if status in counts:
            counts[status] += 1
    return [
        {
            "label": "Corridas OK",
            "value": counts[ConsolidationRun.STATUS_SUCCEEDED],
            "tone": "bg-emerald-50 text-emerald-700",
        },
        {
            "label": "En progreso",
            "value": counts[ConsolidationRun.STATUS_RUNNING],
            "tone": "bg-sky-50 text-sky-700",
        },
        {
            "label": "Fallidas",
            "value": counts[ConsolidationRun.STATUS_FAILED],
            "tone": "bg-red-50 text-red-700",
        },
    ]


def _snapshot_freshness_badge(snapshot, *, now=None):
    now = now or timezone.now()
    synced_at = getattr(snapshot, "last_synced_at", None)
    if synced_at is None:
        return {
            "label": "Sin snapshot reciente",
            "tone": "bg-slate-100 text-slate-700",
        }

    age = now - synced_at
    if age <= timedelta(minutes=5):
        return {
            "label": "Actualizado hace instantes",
            "tone": "bg-emerald-50 text-emerald-700",
        }

    minutes = max(int(age.total_seconds() // 60), 1)
    if age <= SNAPSHOT_STALE_AFTER:
        return {
            "label": f"Actualizado hace {minutes} min",
            "tone": "bg-sky-50 text-sky-700",
        }
    return {
        "label": f"Desactualizado hace {minutes} min",
        "tone": "bg-amber-50 text-amber-700",
    }

def _format_amounts(raw_amounts: dict) -> str:
    if not raw_amounts:
        return "Sin montos consolidados."
    return " | ".join(f"{currency} {amount}" for currency, amount in sorted(raw_amounts.items()))
