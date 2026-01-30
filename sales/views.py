from django.shortcuts import render, redirect
from django.http import HttpResponse
from .models import SaleOrder, SaleOrderStatus
from .forms import SaleOrderForm, SaleOrderLineForm
from django.views.generic import ListView, DetailView, CreateView,TemplateView
from partners.models import Partner
from inventory.models import Product
from django.urls import reverse_lazy
from .services import confirm_order_service, add_product_to_order
from django.forms import modelformset_factory
from django.contrib.auth.mixins import LoginRequiredMixin
from core.mixins import ModulePermissionMixin
from django.db.models import Q, Sum
from django.shortcuts import render, redirect
from django.views import View
from .models import SaleOrder, SaleOrderLine, Product
from django.contrib import messages



class SalesIndexView(LoginRequiredMixin, ModulePermissionMixin, TemplateView):
    permission_required = "sales.view_saleorder"
    template_name = "sales/index.html"


class SaleOrderCreateView(View):
    template_name = 'sales/order_form.html'

    def get(self, request, *args, **kwargs):
        form = SaleOrderForm()
        SaleOrderLineFormSet = modelformset_factory(SaleOrderLine, form=SaleOrderLineForm, extra=1)
        line_formset = SaleOrderLineFormSet(queryset=SaleOrderLine.objects.none())
        
        context = {
            'form': form,
            'line_formset': line_formset,
        }
        return render(request, self.template_name, context)

    def post(self, request, *args, **kwargs):
        form = SaleOrderForm(request.POST)
        SaleOrderLineFormSet = modelformset_factory(SaleOrderLine, form=SaleOrderLineForm, extra=1)
        line_formset = SaleOrderLineFormSet(request.POST)

        if form.is_valid() and line_formset.is_valid():
            order = form.save(commit=False)
            order.save()

            for line_form in line_formset:
                if line_form.cleaned_data:
                    product = line_form.cleaned_data['product']
                    quantity = line_form.cleaned_data['quantity']
                    unit_price = line_form.cleaned_data['unit_price']
                    total_price = quantity * unit_price
                    SaleOrderLine.objects.create(
                        order=order,
                        product=product,
                        quantity=quantity,
                        unit_price=unit_price,
                        total_price=total_price
                    )

            messages.success(request, "Pedido creado correctamente.")
            return redirect('sales:order_list')

        context = {
            'form': form,
            'line_formset': line_formset,
        }
        return render(request, self.template_name, context)


class SaleOrderDetailView(LoginRequiredMixin, ModulePermissionMixin, DetailView):
    permission_required = "sales.view_saleorder"
    model = SaleOrder
    template_name = 'sales/order_detail.html'
    context_object_name = 'order'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # Sumar el total de la proforma
        context['total'] = self.object.get_total()
        return context
def add_product_to_order_view(request, pk):
    order = SaleOrder.objects.get(pk=pk)
    product_id = request.POST.get('product_id')
    quantity = request.POST.get('quantity')
    unit_price = request.POST.get('unit_price')
    
    # Llamamos al servicio para agregar el producto
    add_product_to_order(order, product_id, quantity, unit_price)
    return redirect('sales:order_detail', pk=pk)


# Lista de pedidos
class SaleOrderListView(LoginRequiredMixin, ModulePermissionMixin, ListView):
    permission_required = "sales.view_saleorder"
    model = SaleOrder
    template_name = 'sales/order_list.html'
    context_object_name = 'page'
    paginate_by = 10

    def get_queryset(self):
        qs = SaleOrder.objects.select_related("client").order_by("-created_at")
        q = self.request.GET.get("q", "").strip()
        status = self.request.GET.get("status", "").strip()
        if q:
            qs = qs.filter(
                Q(code__icontains=q)
                | Q(client__trade_name__icontains=q)
                | Q(client__legal_name__icontains=q)
            )
        if status:
            qs = qs.filter(status=status)
        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["status_choices"] = SaleOrderStatus.choices
        for order in context['page']:
            order.total_amount = order.saleorderline_set.aggregate(
                total_amount=Sum('total_price')
            )['total_amount'] or 0
        return context

# Crear nuevo pedido
class SaleOrderCreateView(LoginRequiredMixin, ModulePermissionMixin, CreateView):
    permission_required = "sales.add_saleorder"
    model = SaleOrder
    form_class = SaleOrderForm
    template_name = 'sales/order_form.html'
    success_url = reverse_lazy('sales:order_list')

def confirm_order(request, pk):
    order = SaleOrder.objects.get(pk=pk)
    order = confirm_order_service(order)  # Usamos el servicio
    return redirect('sales:order_list')