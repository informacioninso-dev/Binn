from django.contrib.auth.decorators import login_required # Asegura que el usuario esté autenticado
from django.shortcuts import render # Importa la función para renderizar plantillas
# core/views.py
from django.views.generic import TemplateView, ListView
from django.contrib.auth.mixins import LoginRequiredMixin
from .models import Warehouse, WarehouseType,TaxScheme,Location,Unit,UnitCategory
from .forms import WarehouseForm,TaxSchemeForm,LocationForm,UnitForm
from django.views.generic import View,TemplateView
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages

@login_required # Asegura que solo usuarios autenticados puedan acceder a la vista
def dashboard(request):
    # Datos simulados para los KPIs y movimientos recientes (del backend o base de datos):
    # Carga la vista de dashboard y renderiza a el html

    data = {
        'stock_total': 1250,
        'sales_this_month': '$ 13.250',
        'pending_invoices': 7,
        'open_work_orders': 3,
        'last_movements': [], 
    }

    #  Contexto para pasar a la plantilla
    ctx = {
        'kpi_stock_total': data['stock_total'],
        'kpi_ventas_mes': data['sales_this_month'],
        'kpi_facturas_pendientes': data['pending_invoices'],
        'kpi_op_abiertas': data['open_work_orders'],
        'movimientos': data['last_movements'],
    }
    return render(request, 'pages/dashboard.html', ctx)

##########################################################
# vista general del modulo
##########################################################
class SettingsView(LoginRequiredMixin, TemplateView):
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

class TaxSchemeCreateView(View):
    template_name = 'core/taxscheme_form.html'

    def get(self, request):
        form = TaxSchemeForm()
        return render(request, self.template_name, {'form': form})

    def post(self, request):
        form = TaxSchemeForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "Esquema tributario creado exitosamente.")
            return redirect('core:taxscheme_list')  # Redirigir a la lista de esquemas tributarios
        messages.error(request, "Hubo un error al crear el esquema tributario.")
        return render(request, self.template_name, {'form': form})


class TaxSchemeListView(View):
    template_name = 'core/taxscheme_list.html'

    def get(self, request):
        schemes = TaxScheme.objects.all()
        return render(request, self.template_name, {'schemes': schemes})

###############################################################
# Vista para configurar  unidades
###############################################################

class UnitCreateView(View):
    template_name = 'core/unit_form.html'

    def get(self, request):
        form = UnitForm()
        return render(request, self.template_name, {'form': form})

    def post(self, request):
        form = UnitForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "Unidad creada exitosamente.")
            return redirect('core:unit_list')  # Redirigir a la lista de unidades
        messages.error(request, "Hubo un error al crear la unidad.")
        return render(request, self.template_name, {'form': form})


class UnitListView(View):
    template_name = 'core/unit_list.html'

    def get(self, request):
        units = Unit.objects.all()
        return render(request, self.template_name, {'units': units})




###############################################################
# Vista para configurar bodegas y ubicaciones
###############################################################

class WarehouseCreateView(View):
    template_name = 'core/warehouse_form.html'

    def get(self, request):
        form = WarehouseForm()
        return render(request, self.template_name, {'form': form})

    def post(self, request):
        form = WarehouseForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "Bodega creada exitosamente.")
            return redirect('core:warehouse_list')  # Redirigir a la lista de bodegas
        messages.error(request, "Hubo un error al crear la bodega.")
        return render(request, self.template_name, {'form': form})
    


class WarehouseListView(View):
    template_name = 'core/warehouse_list.html'

    def get(self, request):
        warehouses = Warehouse.objects.all()
        return render(request, self.template_name, {'warehouses': warehouses})

class LocationCreateView(View):
    template_name = 'core/location_form.html'

    def get(self, request):
        form = LocationForm()
        return render(request, self.template_name, {'form': form})

    def post(self, request):
        form = LocationForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "Ubicación creada exitosamente.")
            return redirect('core:location_list')  # Redirigir a la lista de ubicaciones
        messages.error(request, "Hubo un error al crear la ubicación.")
        return render(request, self.template_name, {'form': form})

class LocationListView(View):
    template_name = 'core/location_list.html'

    def get(self, request):
        locations = Location.objects.all()
        return render(request, self.template_name, {'locations': locations})
