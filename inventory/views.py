# inventory/views.py
import json
from django.contrib.auth.mixins import LoginRequiredMixin
from core.mixins import ModulePermissionMixin
from django.urls import reverse_lazy
from django.views.generic import ListView, CreateView, UpdateView, View
from django.contrib import messages
from django.views.generic import ListView, FormView
from django.shortcuts import get_object_or_404, redirect, render
from django.core.exceptions import ValidationError
from .services import (
register_inventory_move, transfer_lot)
from .models import (
    Product, 
    InventoryMove, 
    Lot,  )
from .forms import ( 
    ProductForm, 
    InventoryMoveForm,

    LotLocationUpdateForm, 
    LotTransferForm)
from procurement.models import PurchaseOrder, PurchaseOrderStatus, PurchaseOrderLine, Partner
import json

################################################################
# vistas para gestionar productos
################################################################
class ProductListView(LoginRequiredMixin, ModulePermissionMixin, ListView):
    permission_required = "inventory.view_product"

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

# vistas para crear/editar productos
class ProductCreateView(LoginRequiredMixin, ModulePermissionMixin, CreateView):
    permission_required = "inventory.add_product"

    model = Product
    form_class = ProductForm
    template_name = "inventory/product_form.html"
    success_url = reverse_lazy("inventory:index")

    def form_valid(self, form):
        messages.success(self.request, "Producto creado correctamente.")
        return super().form_valid(form)
    

# vistas para crear/editar productos
class ProductUpdateView(LoginRequiredMixin, ModulePermissionMixin, UpdateView):
    permission_required = "inventory.change_product"

    model = Product
    form_class = ProductForm
    template_name = "inventory/product_form.html"
    success_url = reverse_lazy("inventory:index")

    def form_valid(self, form):
        messages.success(self.request, "Producto actualizado correctamente.")
        return super().form_valid(form)

# vista para activar/inactivar productos
class ProductToggleActiveView(LoginRequiredMixin, ModulePermissionMixin, View):
    permission_required = "inventory.change_product"

    """Activar/Inactivar (mejor que borrar)."""
    success_url = reverse_lazy("inventory:index")

    def post(self, request, pk):
        obj = get_object_or_404(Product, pk=pk)
        obj.is_active = not obj.is_active
        obj.save(update_fields=["is_active"])
        state = "activado" if obj.is_active else "inactivado"
        messages.success(request, f"Producto {state} correctamente.")
        return redirect(self.success_url)

# vistas para gestionar movimientos de inventario
class InventoryMoveListView(LoginRequiredMixin, ModulePermissionMixin, ListView):
    permission_required = "inventory.view_inventorymove"

    model = InventoryMove
    template_name = "inventory/movements_list.html"
    context_object_name = "page"
    paginate_by = 20

    def get_queryset(self):
        from django.db.models import Q
        qs = InventoryMove.objects.select_related("product", "lot", "unit_displayed").order_by("-date")
        q = self.request.GET.get("q", "").strip()
        product_id = self.request.GET.get("product")
        move_type = self.request.GET.get("type", "").strip()
        if q:
            qs = qs.filter(
                Q(product__name__icontains=q)
                | Q(product__code__icontains=q)
                | Q(reference__icontains=q)
            )
        if product_id:
            qs = qs.filter(product_id=product_id)
        if move_type:
            qs = qs.filter(movement_type=move_type)
        return qs

    def get_context_data(self, **kwargs):
        from .models import MovementTypes
        ctx = super().get_context_data(**kwargs)
        ctx["type_choices"] = MovementTypes.choices
        return ctx

from django.contrib import messages
from django.urls import reverse_lazy
from django.views.generic import FormView
from django.core.exceptions import ValidationError
from .services import register_inventory_move  # Asegúrate de importar el servicio
from .forms import InventoryMoveForm

class InventoryMoveCreateView(LoginRequiredMixin, ModulePermissionMixin, FormView):
    permission_required = "inventory.add_inventorymove"

    template_name = "inventory/movements_form.html"
    form_class = InventoryMoveForm
    success_url = reverse_lazy("inventory:movements_list")

    def form_valid(self, form):
        product = form.cleaned_data["product"]
        quantity = form.cleaned_data["quantity"]
        movement_type = form.cleaned_data["movement_type"]
        
        # Verificar si el producto tiene una unidad base
        if not product.base_unit:
            form.add_error("product", "El producto no tiene una unidad base asignada.")
            return self.form_invalid(form)

        # Obtener el factor de conversión a la unidad base
        factor_to_base = product.base_unit.factor_to_base
        
        # Ajustar la cantidad usando el factor de conversión
        adjusted_quantity = quantity * factor_to_base
        
        # Asegurarse de que el stock sea suficiente para el movimiento de salida
        if movement_type == "OUT":  # Verificación solo para salida
            current_stock = product.stock.quantity
            if adjusted_quantity > current_stock:
                form.add_error("quantity", f"Cantidad insuficiente en stock. Disponible: {current_stock}.")
                return self.form_invalid(form)

        try:
            # Llamar al servicio para registrar el movimiento
            register_inventory_move(
                user=self.request.user,
                product=product,
                movement_type=movement_type,
                quantity=adjusted_quantity,
                unit_cost=form.cleaned_data["unit_cost"],
                reference=form.cleaned_data["reference"],
                area=form.cleaned_data["area"],
                notes=form.cleaned_data["notes"],
            )
        except ValidationError as e:
            form.add_error(None, e.message)
            return self.form_invalid(form)

        messages.success(self.request, "Movimiento registrado correctamente.")
        return super().form_valid(form)

    def form_invalid(self, form):
        messages.error(self.request, "Hubo un error al registrar el movimiento.")
        return super().form_invalid(form)





# vista para actualizar bodega y ubicación de un lote

class LotLocationUpdateView(LoginRequiredMixin, ModulePermissionMixin, UpdateView):
    permission_required = "inventory.change_lot"

    model = Lot
    form_class = LotLocationUpdateForm
    template_name = "inventory/lot_location_form.html"
    
    # Para poder usar ?warehouse=ID y actualizar el combo de ubicaciones
    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        if self.request.method == "GET" and "warehouse" in self.request.GET:
            # Hacemos que el form se considere 'bound' con GET
            kwargs["data"] = self.request.GET
        return kwargs

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, "Bodega y ubicación actualizadas correctamente.")
        return response

    def get_success_url(self):
        # Cuando tengas un detalle de lote, puedes mandarlo allá.
        # Por ahora te regreso al index de inventario.
        return reverse_lazy("inventory:index")


###################### Vista de Transferencia ######################

class LotTransferView(LoginRequiredMixin, ModulePermissionMixin, View):
    permission_required = "inventory.change_lot"
    template_name = "inventory/lot_transfer_form.html"

    def get(self, request, pk):
        # Mejor usar get_object_or_404 para manejar errores 404 si el lote no existe
        lot = get_object_or_404(Lot, pk=pk)
        form = LotTransferForm(initial={"lot": lot})
        return render(request, self.template_name, {"form": form, "lot": lot})

    def post(self, request, pk):
        # Usamos get_object_or_404 también aquí para manejar el caso si el lote no existe
        lot = get_object_or_404(Lot, pk=pk)
        form = LotTransferForm(request.POST)

        if form.is_valid():
            warehouse = form.cleaned_data["warehouse"]
            location = form.cleaned_data.get("location")
            notes = request.POST.get("notes")

            try:
                # Llamamos al servicio para transferir el lote
                move = transfer_lot(
                    user=request.user,
                    lot=lot,
                    new_warehouse=warehouse,
                    new_location=location,
                    notes=notes,
                )
                # Si todo es exitoso, mostramos mensaje de éxito
                messages.success(request, f"El lote {lot.internal_lot} ha sido transferido exitosamente.")
                return redirect("inventory:lot_detail", pk=lot.pk)
            except ValidationError as e:
                # Si hay error, lo mostramos
                messages.error(request, str(e))
                return render(request, self.template_name, {"form": form, "lot": lot})

        return render(request, self.template_name, {"form": form, "lot": lot})
