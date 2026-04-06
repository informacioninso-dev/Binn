from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render

from tenants.permissions import CRM_ALLOWED_ROLES, tenant_capability_required, tenant_role_required

from .forms import LeadForm
from .models import Lead, LeadStage


def _save_lead(form, request, *, success_message: str):
    lead = form.save(commit=False)
    if lead.pk:
        lead.updated_by = request.user
    else:
        lead.created_by = request.user
        lead.updated_by = request.user
    lead.save()
    messages.success(request, success_message)
    return redirect("crm:index")


@login_required
@tenant_capability_required("crm.basic")
@tenant_role_required(*CRM_ALLOWED_ROLES)
def index(request):
    q = (request.GET.get("q") or "").strip()
    stage = (request.GET.get("stage") or "").strip()

    leads = Lead.objects.select_related("assigned_to", "converted_patient")
    if q:
        leads = leads.filter(
            Q(full_name__icontains=q)
            | Q(phone__icontains=q)
            | Q(email__icontains=q)
            | Q(interested_service__icontains=q)
        )
    if stage:
        leads = leads.filter(stage=stage)

    context = {
        "leads": leads.order_by("stage", "full_name")[:100],
        "q": q,
        "stage": stage,
        "stage_choices": LeadStage.choices,
        "summary": {
            "new": Lead.objects.filter(stage=LeadStage.NEW, is_active=True).count(),
            "contacted": Lead.objects.filter(stage=LeadStage.CONTACTED, is_active=True).count(),
            "appointment": Lead.objects.filter(stage=LeadStage.APPOINTMENT, is_active=True).count(),
            "won": Lead.objects.filter(stage=LeadStage.WON).count(),
        },
    }
    return render(request, "crm/index.html", context)


@login_required
@tenant_capability_required("crm.basic")
@tenant_role_required(*CRM_ALLOWED_ROLES)
def create(request):
    if request.method == "POST":
        form = LeadForm(request.POST, tenant=request.tenant)
        if form.is_valid():
            return _save_lead(form, request, success_message="Lead registrado correctamente.")
    else:
        form = LeadForm(tenant=request.tenant, initial={"is_active": True, "stage": LeadStage.NEW})

    return render(
        request,
        "crm/form.html",
        {"form": form, "page_title": "Nuevo lead", "submit_label": "Guardar lead"},
    )


@login_required
@tenant_capability_required("crm.basic")
@tenant_role_required(*CRM_ALLOWED_ROLES)
def edit(request, pk):
    lead = get_object_or_404(Lead, pk=pk)
    if request.method == "POST":
        form = LeadForm(request.POST, instance=lead, tenant=request.tenant)
        if form.is_valid():
            return _save_lead(form, request, success_message="Lead actualizado correctamente.")
    else:
        form = LeadForm(instance=lead, tenant=request.tenant)

    return render(
        request,
        "crm/form.html",
        {
            "form": form,
            "lead": lead,
            "page_title": f"Editar lead: {lead.full_name}",
            "submit_label": "Guardar cambios",
        },
    )
