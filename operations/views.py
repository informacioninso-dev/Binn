from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q, Sum
from django.shortcuts import get_object_or_404, redirect, render

from tenants.observability import record_tenant_event
from tenants.permissions import (
    OPERATIONS_ADMIN_ALLOWED_ROLES,
    OPERATIONS_COMMISSION_ALLOWED_ROLES,
    OPERATIONS_REPORT_ALLOWED_ROLES,
    tenant_capability_required,
    tenant_role_required,
)

from .forms import (
    AutomationRuleForm,
    CommissionGenerationForm,
    CommissionSchemeForm,
    IntegrationConnectionForm,
    LocationForm,
)
from .models import (
    AutomationRun,
    AutomationRunStatus,
    AutomationRule,
    CommissionRecord,
    CommissionRecordStatus,
    CommissionScheme,
    IntegrationConnection,
    Location,
)
from .services import build_operations_dashboard, execute_automation_rule, generate_commission_records


def _save_with_audit(instance, request):
    if instance.pk:
        instance.updated_by = request.user
    else:
        instance.created_by = request.user
        instance.updated_by = request.user
    instance.save()
    return instance


@login_required
@tenant_capability_required("reports.basic")
@tenant_role_required(*OPERATIONS_REPORT_ALLOWED_ROLES)
def index(request):
    context = build_operations_dashboard(tenant=request.tenant)
    context["has_advanced_reports"] = request.tenant.has_capability("reports.advanced")
    return render(request, "operations/index.html", context)


@login_required
@tenant_capability_required("multi_site.basic")
@tenant_role_required(*OPERATIONS_ADMIN_ALLOWED_ROLES)
def location_list(request):
    q = (request.GET.get("q") or "").strip()
    locations = Location.objects.all()
    if q:
        locations = locations.filter(Q(code__icontains=q) | Q(name__icontains=q) | Q(address__icontains=q))

    context = {
        "q": q,
        "locations": locations.order_by("name")[:100],
        "summary": {
            "active": Location.objects.filter(is_active=True).count(),
            "inactive": Location.objects.filter(is_active=False).count(),
            "appointments": Location.objects.aggregate(total=Count("appointments"))["total"] or 0,
            "revenue": Location.objects.aggregate(total=Sum("invoices__paid_amount"))["total"] or 0,
        },
    }
    return render(request, "operations/locations.html", context)


@login_required
@tenant_capability_required("multi_site.basic")
@tenant_role_required(*OPERATIONS_ADMIN_ALLOWED_ROLES)
def location_create(request):
    if request.method == "POST":
        form = LocationForm(request.POST)
        if form.is_valid():
            location = form.save(commit=False)
            _save_with_audit(location, request)
            record_tenant_event(
                tenant=request.tenant,
                actor=request.user,
                title="Sede creada",
                message=f"Se registro la sede {location.name}.",
                code="location_created",
                metadata={"location_id": location.pk, "location_code": location.code},
            )
            messages.success(request, "Sede registrada correctamente.")
            return redirect("operations:locations")
    else:
        form = LocationForm(initial={"is_active": True})

    return render(
        request,
        "operations/form.html",
        {"form": form, "page_title": "Nueva sede", "submit_label": "Guardar sede", "back_url": "operations:locations"},
    )


@login_required
@tenant_capability_required("commissions.basic")
@tenant_role_required(*OPERATIONS_COMMISSION_ALLOWED_ROLES)
def commission_list(request):
    status = (request.GET.get("status") or "").strip()
    q = (request.GET.get("q") or "").strip()
    records = CommissionRecord.objects.select_related(
        "provider",
        "appointment__patient",
        "scheme",
        "source_invoice",
    )
    if status:
        records = records.filter(status=status)
    if q:
        records = records.filter(
            Q(provider__username__icontains=q)
            | Q(appointment__patient__first_name__icontains=q)
            | Q(appointment__patient__last_name__icontains=q)
            | Q(scheme__name__icontains=q)
        )

    context = {
        "q": q,
        "status": status,
        "status_choices": CommissionRecordStatus.choices,
        "records": records.order_by("-period_end", "-id")[:100],
        "schemes": CommissionScheme.objects.filter(is_active=True).order_by("name")[:12],
        "generation_form": CommissionGenerationForm(),
        "summary": {
            "pending": CommissionRecord.objects.filter(status=CommissionRecordStatus.PENDING).count(),
            "approved": CommissionRecord.objects.filter(status=CommissionRecordStatus.APPROVED).count(),
            "paid": CommissionRecord.objects.filter(status=CommissionRecordStatus.PAID).count(),
            "pending_amount": (
                CommissionRecord.objects.filter(status=CommissionRecordStatus.PENDING).aggregate(total=Sum("commission_amount"))[
                    "total"
                ]
                or 0
            ),
        },
    }
    return render(request, "operations/commissions.html", context)


@login_required
@tenant_capability_required("commissions.basic")
@tenant_role_required(*OPERATIONS_COMMISSION_ALLOWED_ROLES)
def commission_generate(request):
    if request.method != "POST":
        return redirect("operations:commissions")

    form = CommissionGenerationForm(request.POST)
    if not form.is_valid():
        for _, errors in form.errors.items():
            for error in errors:
                messages.error(request, error)
        return redirect("operations:commissions")

    period_start = form.cleaned_data["period_start"]
    period_end = form.cleaned_data["period_end"]
    processed = generate_commission_records(
        tenant=request.tenant,
        period_start=period_start,
        period_end=period_end,
        actor=request.user,
    )
    record_tenant_event(
        tenant=request.tenant,
        actor=request.user,
        title="Comisiones recalculadas",
        message=f"Se procesaron {processed} registros entre {period_start} y {period_end}.",
        code="commissions_generated",
        metadata={
            "period_start": period_start.isoformat(),
            "period_end": period_end.isoformat(),
            "processed": processed,
        },
    )
    messages.success(request, f"Comisiones procesadas: {processed}.")
    return redirect("operations:commissions")


@login_required
@tenant_capability_required("commissions.basic")
@tenant_role_required(*OPERATIONS_ADMIN_ALLOWED_ROLES)
def commission_scheme_create(request):
    if request.method == "POST":
        form = CommissionSchemeForm(request.POST)
        if form.is_valid():
            scheme = form.save(commit=False)
            _save_with_audit(scheme, request)
            record_tenant_event(
                tenant=request.tenant,
                actor=request.user,
                title="Esquema de comision creado",
                message=f"Se registro el esquema {scheme.name}.",
                code="commission_scheme_created",
                metadata={"scheme_id": scheme.pk},
            )
            messages.success(request, "Esquema de comision registrado.")
            return redirect("operations:commissions")
    else:
        form = CommissionSchemeForm(initial={"is_active": True})

    return render(
        request,
        "operations/form.html",
        {
            "form": form,
            "page_title": "Nuevo esquema de comision",
            "submit_label": "Guardar esquema",
            "back_url": "operations:commissions",
        },
    )


@login_required
@tenant_capability_required("automation.basic")
@tenant_role_required(*OPERATIONS_ADMIN_ALLOWED_ROLES)
def automation_list(request):
    q = (request.GET.get("q") or "").strip()
    rules = AutomationRule.objects.prefetch_related("runs")
    if q:
        rules = rules.filter(Q(name__icontains=q) | Q(trigger__icontains=q) | Q(target_role__icontains=q))

    context = {
        "q": q,
        "rules": rules.order_by("name")[:100],
        "recent_runs": AutomationRun.objects.select_related("rule").order_by("-executed_at", "-id")[:12],
        "summary": {
            "active_rules": AutomationRule.objects.filter(is_active=True).count(),
            "inactive_rules": AutomationRule.objects.filter(is_active=False).count(),
            "warning_runs": AutomationRun.objects.filter(status=AutomationRunStatus.WARNING).count(),
            "error_runs": AutomationRun.objects.filter(status=AutomationRunStatus.ERROR).count(),
        },
    }
    return render(request, "operations/automations.html", context)


@login_required
@tenant_capability_required("automation.basic")
@tenant_role_required(*OPERATIONS_ADMIN_ALLOWED_ROLES)
def automation_create(request):
    if request.method == "POST":
        form = AutomationRuleForm(request.POST)
        if form.is_valid():
            rule = form.save(commit=False)
            _save_with_audit(rule, request)
            record_tenant_event(
                tenant=request.tenant,
                actor=request.user,
                title="Automatizacion creada",
                message=f"Se creo la regla {rule.name}.",
                code="automation_rule_created",
                metadata={"rule_id": rule.pk, "trigger": rule.trigger, "channel": rule.channel},
            )
            messages.success(request, "Regla de automatizacion registrada.")
            return redirect("operations:automations")
    else:
        form = AutomationRuleForm(initial={"is_active": True})

    return render(
        request,
        "operations/form.html",
        {
            "form": form,
            "page_title": "Nueva automatizacion",
            "submit_label": "Guardar regla",
            "back_url": "operations:automations",
        },
    )


@login_required
@tenant_capability_required("automation.basic")
@tenant_role_required(*OPERATIONS_ADMIN_ALLOWED_ROLES)
def automation_run(request, pk):
    if request.method != "POST":
        return redirect("operations:automations")

    rule = get_object_or_404(AutomationRule, pk=pk)
    run = execute_automation_rule(rule, actor=request.user)
    severity = "warning" if run.status == "WARNING" else "error" if run.status == "ERROR" else "info"
    record_tenant_event(
        tenant=request.tenant,
        actor=request.user,
        title="Automatizacion ejecutada",
        message=f"{rule.name}: {run.summary}",
        code="automation_rule_executed",
        severity=severity,
        metadata={"rule_id": rule.pk, "run_id": run.pk, "status": run.status},
    )
    if run.status == "ERROR":
        messages.error(request, run.summary)
    elif run.status == "WARNING":
        messages.warning(request, run.summary)
    else:
        messages.success(request, run.summary)
    return redirect("operations:automations")


@login_required
@tenant_capability_required("integrations.basic")
@tenant_role_required(*OPERATIONS_ADMIN_ALLOWED_ROLES)
def integration_list(request):
    q = (request.GET.get("q") or "").strip()
    integrations = IntegrationConnection.objects.all()
    if q:
        integrations = integrations.filter(Q(name__icontains=q) | Q(provider__icontains=q) | Q(endpoint__icontains=q))

    context = {
        "q": q,
        "integrations": integrations.order_by("name")[:100],
        "summary": {
            "active": IntegrationConnection.objects.filter(is_active=True).count(),
            "testing": IntegrationConnection.objects.filter(status="TESTING").count(),
            "error": IntegrationConnection.objects.filter(status="ERROR").count(),
            "configured": IntegrationConnection.objects.filter(status="CONFIGURED").count(),
        },
    }
    return render(request, "operations/integrations.html", context)


@login_required
@tenant_capability_required("integrations.basic")
@tenant_role_required(*OPERATIONS_ADMIN_ALLOWED_ROLES)
def integration_create(request):
    if request.method == "POST":
        form = IntegrationConnectionForm(request.POST)
        if form.is_valid():
            integration = form.save(commit=False)
            _save_with_audit(integration, request)
            record_tenant_event(
                tenant=request.tenant,
                actor=request.user,
                title="Integracion registrada",
                message=f"Se registro la integracion {integration.name}.",
                code="integration_created",
                metadata={"integration_id": integration.pk, "provider": integration.provider},
            )
            messages.success(request, "Integracion registrada correctamente.")
            return redirect("operations:integrations")
    else:
        form = IntegrationConnectionForm(initial={"is_active": True})

    return render(
        request,
        "operations/form.html",
        {
            "form": form,
            "page_title": "Nueva integracion",
            "submit_label": "Guardar integracion",
            "back_url": "operations:integrations",
        },
    )
