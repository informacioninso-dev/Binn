from django.contrib.auth.mixins import LoginRequiredMixin
from django.urls import reverse_lazy
from django.views.generic import ListView, CreateView, UpdateView, View
from django.shortcuts import redirect, get_object_or_404
from django.contrib import messages

from .models import Product
from .forms import ProductForm

class ProductListView(LoginRequiredMixin, ListView):
    model = Product
    template_name = "inventory/index.html"
    context_object_name = "page"
    paginate_by = 20

    def get_queryset(self):
        qs = Product.objects.filter(is_active=True).order_by("name")
        q = self.request.GET.get("q")
        if q:
            qs = qs.filter(name__icontains=q) | qs.filter(code__icontains=q)
        return qs

class ProductCreateView(LoginRequiredMixin, CreateView):
    model = Product
    form_class = ProductForm
    template_name = "inventory/form.html"
    success_url = reverse_lazy("inventory:index")

    def form_valid(self, form):
        messages.success(self.request, "Producto creado correctamente.")
        return super().form_valid(form)

class ProductUpdateView(LoginRequiredMixin, UpdateView):
    model = Product
    form_class = ProductForm
    template_name = "inventory/form.html"
    success_url = reverse_lazy("inventory:index")

    def form_valid(self, form):
        messages.success(self.request, "Producto actualizado correctamente.")
        return super().form_valid(form)

class ProductToggleActiveView(LoginRequiredMixin, View):
    """Activar/Inactivar (mejor que borrar)."""
    success_url = reverse_lazy("inventory:index")

    def post(self, request, pk):
        obj = get_object_or_404(Product, pk=pk)
        obj.is_active = not obj.is_active
        obj.save(update_fields=["is_active"])
        state = "activado" if obj.is_active else "inactivado"
        messages.success(request, f"Producto {state} correctamente.")
        return redirect(self.success_url)
