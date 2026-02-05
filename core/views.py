from django.contrib.auth.decorators import login_required
from django.shortcuts import render
# core/views.py
from django.views.generic import TemplateView, ListView
from django.contrib.auth.mixins import LoginRequiredMixin
from core.mixins import ModulePermissionMixin
from .models import Warehouse, WarehouseType,TaxScheme,Location,Unit,UnitCategory
from .forms import WarehouseForm, TaxSchemeForm, LocationForm, UnitForm, CompanyConfigForm
from django.db import models
from django.views.generic import View,TemplateView
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages

@login_required
def dashboard(request):
    from django.utils import timezone
    from django.db.models import Sum, Count, Q
    from inventory.models import Product, Stock, InventoryMove
    from sales.models import SaleOrder, SaleInvoice
    from procurement.models import PurchaseOrder, RawMaterialReception
    from production.models import ProductionOrder
    from quality.models import QualityInspection

    now = timezone.now()
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    # --- KPIs ---
    products_active = Product.objects.filter(is_active=True).count()
    pedidos_pendientes = 0  # TODO: implementar cuando exista módulo de pedidos

    sales_month = SaleOrder.objects.filter(created_at__gte=month_start).count()
    sales_month_total = (
        SaleOrder.objects.filter(created_at__gte=month_start)
        .exclude(status='CANCELED')
        .aggregate(t=Sum('invoices__total_amount'))['t'] or 0
    )

    pending_invoices = SaleInvoice.objects.exclude(
        status__in=['DISPATCHED', 'CANCELED']
    ).count()

    oc_pending = PurchaseOrder.objects.exclude(
        status__in=['RECEIVED', 'CANCELLED']
    ).count()

    receptions_qa = RawMaterialReception.objects.filter(status='UNDER_QA').count()

    op_open = ProductionOrder.objects.filter(
        status__in=['DRAFT', 'RELEASED', 'IN_PROGRESS']
    ).count()

    qa_pending = QualityInspection.objects.filter(result='PENDING').count()

    # --- Últimos movimientos de inventario ---
    last_moves = (
        InventoryMove.objects
        .select_related('product', 'warehouse')
        .order_by('-date')[:10]
    )

    ctx = {
        'products_active': products_active,
        'pedidos_pendientes': pedidos_pendientes,
        'sales_month': sales_month,
        'sales_month_total': sales_month_total,
        'pending_invoices': pending_invoices,
        'oc_pending': oc_pending,
        'receptions_qa': receptions_qa,
        'op_open': op_open,
        'qa_pending': qa_pending,
        'last_moves': last_moves,
    }
    return render(request, 'pages/dashboard.html', ctx)

##########################################################
# vista general del modulo
##########################################################
class SettingsView(LoginRequiredMixin, ModulePermissionMixin, TemplateView):
    permission_required = "core.view_warehouse"
    template_name = "core/settings.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)

        ctx["warehouse_count"] = Warehouse.objects.count()
        ctx["location_count"] = Location.objects.count()
        ctx["unit_count"] = Unit.objects.count()
        ctx["taxscheme_count"] = TaxScheme.objects.count()

        # muestras rápidas para el dashboard de config
        ctx["warehouses"] = Warehouse.objects.all().order_by("code")[:5]
        ctx["locations"] = (
            Location.objects.select_related("warehouse")
            .order_by("warehouse__code", "code")[:5]
        )
        ctx["units"] = Unit.objects.all().order_by("code")[:5]
        ctx["taxschemes"] = TaxScheme.objects.all().order_by("code")[:5]
        return ctx

###############################################################
# Vista para configurar esquema tributario
###############################################################

class TaxSchemeCreateView(LoginRequiredMixin, ModulePermissionMixin, View):
    permission_required = "core.add_taxscheme"
    template_name = 'core/taxscheme_form.html'

    def get(self, request):
        form = TaxSchemeForm()
        return render(request, self.template_name, {'form': form})

    def post(self, request):
        form = TaxSchemeForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "Esquema tributario creado exitosamente.")
            return redirect('core:taxscheme_list')
        messages.error(request, "Hubo un error al crear el esquema tributario.")
        return render(request, self.template_name, {'form': form})


class TaxSchemeListView(LoginRequiredMixin, ModulePermissionMixin, View):
    permission_required = "core.view_taxscheme"
    template_name = 'core/taxscheme_list.html'

    def get(self, request):
        qs = TaxScheme.objects.all()
        q = request.GET.get("q", "").strip()
        if q:
            qs = qs.filter(
                models.Q(code__icontains=q) | models.Q(name__icontains=q)
            )
        return render(request, self.template_name, {'schemes': qs})

###############################################################
# Vista para configurar  unidades
###############################################################

class UnitCreateView(LoginRequiredMixin, ModulePermissionMixin, View):
    permission_required = "core.add_unit"
    template_name = 'core/unit_form.html'

    def get(self, request):
        form = UnitForm()
        return render(request, self.template_name, {'form': form})

    def post(self, request):
        form = UnitForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "Unidad creada exitosamente.")
            return redirect('core:unit_list')
        messages.error(request, "Hubo un error al crear la unidad.")
        return render(request, self.template_name, {'form': form})


class UnitListView(LoginRequiredMixin, ModulePermissionMixin, View):
    permission_required = "core.view_unit"
    template_name = 'core/unit_list.html'

    def get(self, request):
        qs = Unit.objects.all()
        q = request.GET.get("q", "").strip()
        if q:
            qs = qs.filter(
                models.Q(code__icontains=q) | models.Q(name__icontains=q)
            )
        return render(request, self.template_name, {'units': qs})


###############################################################
# Vista para configurar bodegas y ubicaciones
###############################################################

class WarehouseCreateView(LoginRequiredMixin, ModulePermissionMixin, View):
    permission_required = "core.add_warehouse"
    template_name = 'core/warehouse_form.html'

    def get(self, request):
        form = WarehouseForm()
        return render(request, self.template_name, {'form': form})

    def post(self, request):
        form = WarehouseForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "Bodega creada exitosamente.")
            return redirect('core:warehouse_list')
        messages.error(request, "Hubo un error al crear la bodega.")
        return render(request, self.template_name, {'form': form})


class WarehouseListView(LoginRequiredMixin, ModulePermissionMixin, View):
    permission_required = "core.view_warehouse"
    template_name = 'core/warehouse_list.html'

    def get(self, request):
        qs = Warehouse.objects.all()
        q = request.GET.get("q", "").strip()
        if q:
            qs = qs.filter(
                models.Q(code__icontains=q) | models.Q(name__icontains=q)
            )
        return render(request, self.template_name, {'warehouses': qs})

class LocationCreateView(LoginRequiredMixin, ModulePermissionMixin, View):
    permission_required = "core.add_location"
    template_name = 'core/location_form.html'

    def get(self, request):
        form = LocationForm()
        return render(request, self.template_name, {'form': form})

    def post(self, request):
        form = LocationForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "Ubicación creada exitosamente.")
            return redirect('core:location_list')
        messages.error(request, "Hubo un error al crear la ubicación.")
        return render(request, self.template_name, {'form': form})

class LocationListView(LoginRequiredMixin, ModulePermissionMixin, View):
    permission_required = "core.view_location"
    template_name = 'core/location_list.html'

    def get(self, request):
        qs = Location.objects.all()
        q = request.GET.get("q", "").strip()
        if q:
            qs = qs.filter(
                models.Q(code__icontains=q) | models.Q(name__icontains=q)
            )
        return render(request, self.template_name, {'locations': qs})


###############################################################
# Vista para configurar datos de empresa (SRI)
###############################################################
from .models import CompanyConfig


class CompanyConfigView(LoginRequiredMixin, ModulePermissionMixin, View):
    permission_required = "core.view_warehouse"
    template_name = "core/company_config.html"

    def get(self, request):
        config = CompanyConfig.objects.first()
        form = CompanyConfigForm(instance=config)
        return render(request, self.template_name, {"form": form, "config": config})

    def post(self, request):
        config = CompanyConfig.objects.first()
        form = CompanyConfigForm(request.POST, request.FILES, instance=config)
        if form.is_valid():
            obj = form.save(commit=False)
            if not obj.pk:
                obj.created_by = request.user
            obj.updated_by = request.user
            obj.save()
            messages.success(request, "Configuración de empresa guardada.")
            return redirect("core:company_config")
        messages.error(request, "Revise los campos marcados.")
        return render(request, self.template_name, {"form": form, "config": config})
