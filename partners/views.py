# partners/views.py
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.decorators import login_required
from core.mixins import ModulePermissionMixin
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse_lazy
from django.views.generic import ListView, CreateView, UpdateView, DetailView

from .models import Partner, SupplierProduct
from .forms import PartnerForm


class PartnerListView(LoginRequiredMixin, ModulePermissionMixin, ListView):
    permission_required = "partners.view_partner"

    model = Partner
    template_name = "partners/partner_list.html"
    context_object_name = "partners"
    paginate_by = 20

    def get_queryset(self):
        qs = Partner.objects.all().order_by("trade_name", "legal_name")
        q = self.request.GET.get("q")
        if q:
            qs = qs.filter(
                Q(trade_name__icontains=q)
                | Q(legal_name__icontains=q)
                | Q(code__icontains=q)
                | Q(identification__icontains=q)
            )
        # Más adelante si quieres, puedes filtrar solo activos:
        # qs = qs.filter(is_active=True)
        return qs


class PartnerCreateView(LoginRequiredMixin, ModulePermissionMixin, CreateView):
    permission_required = "partners.add_partner"

    model = Partner
    form_class = PartnerForm
    template_name = "partners/partner_form.html"
    success_url = reverse_lazy("partners:index")

    def form_valid(self, form):
        messages.success(self.request, "Socio creado correctamente.")
        return super().form_valid(form)


class PartnerUpdateView(LoginRequiredMixin, ModulePermissionMixin, UpdateView):
    permission_required = "partners.change_partner"

    model = Partner
    form_class = PartnerForm
    template_name = "partners/partner_form.html"
    success_url = reverse_lazy("partners:index")

    def form_valid(self, form):
        messages.success(self.request, "Socio actualizado correctamente.")
        return super().form_valid(form)


class PartnerCatalogView(LoginRequiredMixin, ModulePermissionMixin, DetailView):
    """Vista de catálogo de productos del proveedor"""
    permission_required = "partners.view_partner"
    model = Partner
    template_name = "partners/partner_catalog.html"
    context_object_name = "partner"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # Obtener productos que este proveedor vende
        context["catalog_items"] = SupplierProduct.objects.filter(
            supplier=self.object
        ).select_related("product").order_by("product__code")
        return context


@login_required
def partner_catalog_add_product(request, partner_pk):
    """Agregar o actualizar producto en catálogo del proveedor"""
    from inventory.models import Product
    from decimal import Decimal

    if request.method != "POST":
        return redirect("partners:catalog", pk=partner_pk)

    partner = get_object_or_404(Partner, pk=partner_pk)
    product_id = request.POST.get("product_id")
    supplier_unit_price = request.POST.get("supplier_unit_price")
    minimum_order_quantity = request.POST.get("minimum_order_quantity", 1)
    lead_time_days = request.POST.get("lead_time_days", 0)
    supplier_product_code = request.POST.get("supplier_product_code", "")

    try:
        product = Product.objects.get(pk=product_id)

        # Crear o actualizar
        obj, created = SupplierProduct.objects.update_or_create(
            supplier=partner,
            product=product,
            defaults={
                "supplier_unit_price": Decimal(supplier_unit_price),
                "minimum_order_quantity": Decimal(minimum_order_quantity),
                "lead_time_days": int(lead_time_days),
                "supplier_product_code": supplier_product_code,
                "updated_by": request.user,
            }
        )

        # Establecer created_by solo si se creó
        if created and hasattr(obj, 'created_by'):
            obj.created_by = request.user
            obj.save(update_fields=['created_by'])

        if created:
            messages.success(request, f"Producto {product.code} agregado al catálogo.")
        else:
            messages.success(request, f"Producto {product.code} actualizado en el catálogo.")

    except (Product.DoesNotExist, ValueError) as e:
        messages.error(request, f"Error al agregar producto: {e}")

    return redirect("partners:catalog", pk=partner_pk)


@login_required
def partner_catalog_delete_product(request, partner_pk, item_pk):
    """Eliminar producto del catálogo del proveedor"""
    if request.method != "POST":
        return redirect("partners:catalog", pk=partner_pk)

    item = get_object_or_404(SupplierProduct, pk=item_pk, supplier_id=partner_pk)
    product_code = item.product.code
    item.delete()

    messages.success(request, f"Producto {product_code} eliminado del catálogo.")
    return redirect("partners:catalog", pk=partner_pk)


@login_required
def suggest_partner_code(request):
    """
    Endpoint AJAX para sugerir código de partner basado en tipo y país.
    """
    from django.http import JsonResponse

    is_supplier = request.GET.get('is_supplier') == 'true'
    is_customer = request.GET.get('is_customer') == 'true'
    is_public_entity = request.GET.get('is_public_entity') == 'true'
    country = request.GET.get('country', '').upper()

    # Determinar prefijo según tipo
    if is_public_entity:
        type_prefix = "ENT"
    elif is_supplier:
        type_prefix = "PROV"
    elif is_customer:
        type_prefix = "CLI"
    else:
        type_prefix = "SOC"  # Socio genérico

    # Mapeo de países a códigos ISO
    country_codes = {
        "ECUADOR": "ECU",
        "MÉXICO": "MEX",
        "MEXICO": "MEX",
        "PERÚ": "PER",
        "PERU": "PER",
        "COLOMBIA": "COL",
        "CHILE": "CHL",
        "ARGENTINA": "ARG",
        "BRASIL": "BRA",
        "BRAZIL": "BRA",
        "ESTADOS UNIDOS": "USA",
        "UNITED STATES": "USA",
        "USA": "USA",
        "CHINA": "CHN",
        "ESPAÑA": "ESP",
        "SPAIN": "ESP",
    }

    country_code = country_codes.get(country, "INT")  # INT = Internacional

    # Construir prefijo: PROV-ECU o CLI-MEX, etc.
    prefix = f"{type_prefix}-{country_code}"

    # Contar partners existentes con ese prefijo
    existing_count = Partner.objects.filter(
        code__istartswith=prefix
    ).count()

    # Sugerir siguiente número
    next_number = existing_count + 1
    suggested_code = f"{prefix}-{next_number:03d}"  # 001, 002, etc.

    return JsonResponse({
        "suggested_code": suggested_code,
        "prefix": prefix,
        "count": existing_count
    })
