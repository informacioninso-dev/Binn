# procurement/views.py
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db import transaction
from django.db.models import Q
from django.shortcuts import redirect, render, get_object_or_404
from django.urls import reverse_lazy, reverse
from django.views import View
from django.views.generic import ListView
from .models import PurchaseOrder, PurchaseOrderStatus, PurchaseOrderLine, RawMaterialReception, RawMaterialReceptionLine, ReceptionStatus
from django.core.serializers.json import DjangoJSONEncoder
from .forms import PurchaseOrderForm, PurchaseOrderLineFormSet,RawMaterialReceptionHeaderForm,RawMaterialReceptionLineFormSet, RawMaterialReceptionLineForm
from inventory.models import Product, ProductType
import json
from .services import create_raw_material_reception
from core.utils.unit_converter import UnitConverter


class PurchaseOrderListView(LoginRequiredMixin, ListView):
    model = PurchaseOrder
    template_name = "procurement/purchase_order_list.html"
    context_object_name = "orders"
    paginate_by = 20

    def get_queryset(self):
        qs = (
            PurchaseOrder.objects
            .select_related("supplier")
            .order_by("-order_date", "-id")
        )

        q = self.request.GET.get("q") or ""
        status = self.request.GET.get("status") or ""

        if q:
            qs = qs.filter(
                Q(number__icontains=q)
                | Q(supplier__trade_name__icontains=q)
                | Q(supplier__legal_name__icontains=q)
            )

        if status:
            qs = qs.filter(status=status)

        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["status_choices"] = PurchaseOrderStatus.choices
        return ctx

class PurchaseOrderCreateView(LoginRequiredMixin, View):
    template_name = "procurement/purchase_order_form.html"

    def get(self, request, *args, **kwargs):
        form = PurchaseOrderForm()
        line_formset = PurchaseOrderLineFormSet()
        line_formset.extra = 1

        # Catálogo de productos para el JS (unidad base, etc.)
        products = Product.objects.filter(is_active=True).select_related("base_unit")
        products_json = json.dumps(
            {
                str(p.id): {
                    "uom_code": getattr(p.base_unit, "code", ""),
                    "uom_name": getattr(p.base_unit, "name", ""),
                    "uom_factor": getattr(p.base_unit, "factor_to_base", 1), 
                    "base_unit_id": p.base_unit.id if p.base_unit else None, # Factor de conversión a unidad base
                }
                for p in products
            },
            cls=DjangoJSONEncoder,
        )

        return render(
            request,
            self.template_name,
            {
                "form": form,
                "line_formset": line_formset,
                "is_edit": False,
                "products_json": products_json,  # Pasamos el JSON con unidades base
            },
        )

    def post(self, request, *args, **kwargs):
        form = PurchaseOrderForm(request.POST)
        line_formset = PurchaseOrderLineFormSet(request.POST)

        # Catálogo de productos para el JS (con unidades base)
        products = Product.objects.filter(is_active=True).select_related("base_unit")
        products_json = json.dumps(
            {
                str(p.id): {
                    "uom_code": getattr(p.base_unit, "code", ""),
                    "uom_name": getattr(p.base_unit, "name", ""),
                    "uom_factor": getattr(p.base_unit, "factor_to_base", 1),
                }
                for p in products
            },
            cls=DjangoJSONEncoder,
        )

        if not (form.is_valid() and line_formset.is_valid()):
            messages.error(request, "Hay errores en la orden o en las líneas. Revisa los campos marcados.")
            return render(
                request,
                self.template_name,
                {
                    "form": form,
                    "line_formset": line_formset,
                    "is_edit": False,
                    "products_json": products_json,
                },
            )

        # Si todo está OK → guardamos con transacción
        with transaction.atomic():
            po: PurchaseOrder = form.save(commit=False)
            po.created_by = request.user
            po.save()

            for line_form in line_formset:
                if not line_form.cleaned_data or line_form.cleaned_data.get("DELETE"):
                    continue

                product = line_form.cleaned_data["product"]
                quantity_raw = line_form.cleaned_data["quantity"]
                unit = line_form.cleaned_data.get("unit")
                
                # Si no se seleccionó una unidad, asigna la unidad base del producto
                if not unit:
                    unit = product.base_unit

                # Guardar cantidad ORIGINAL y unidad ORIGINAL
                # La conversión a unidad base se hace al momento de recepcionar
                PurchaseOrderLine.objects.create(
                    order=po,
                    product=product,
                    description=line_form.cleaned_data.get("description") or "",
                    quantity=quantity_raw,  # ✅ Cantidad ORIGINAL (ej: 500 g)
                    unit=unit,              # ✅ Unidad ORIGINAL (ej: gramos)
                    unit_price=line_form.cleaned_data.get("unit_price") or 0,
                )

            # Recalcular total
            po.recalc_total()
            po.save(update_fields=["total_amount"])

        messages.success(request, f"Orden de compra {po.number} creada correctamente.")
        return redirect(reverse("procurement:order_list"))

class PurchaseOrderUpdateView(LoginRequiredMixin, View):
    template_name = "procurement/purchase_order_form.html"

    def get_object(self, pk):
        return get_object_or_404(PurchaseOrder, pk=pk)

    def get(self, request, pk, *args, **kwargs):
        po = self.get_object(pk)
        if po.status in (PurchaseOrderStatus.RECEIVED, PurchaseOrderStatus.CANCELLED):
            messages.error(request, f"La orden {po.number} está {po.get_status_display()} y no puede editarse.")
            return redirect("procurement:order_list")
        form = PurchaseOrderForm(instance=po)
        line_formset = PurchaseOrderLineFormSet(instance=po)

        products = Product.objects.filter(is_active=True).select_related("base_unit")
        products_json = json.dumps(
            {
                str(p.id): {
                    "uom_code": getattr(p.base_unit, "code", ""),
                    "uom_name": getattr(p.base_unit, "name", ""),
                    "base_unit_id": p.base_unit.id if p.base_unit else None,
                }
                for p in products
            },
            cls=DjangoJSONEncoder,
        )

        return render(
            request,
            self.template_name,
            {
                "object": po,
                "form": form,
                "line_formset": line_formset,
                "is_edit": True,
                "products_json": products_json,
            },
        )

    def post(self, request, pk, *args, **kwargs):
        po = self.get_object(pk)
        if po.status in (PurchaseOrderStatus.RECEIVED, PurchaseOrderStatus.CANCELLED):
            messages.error(request, f"La orden {po.number} está {po.get_status_display()} y no puede editarse.")
            return redirect("procurement:order_list")
        form = PurchaseOrderForm(request.POST, instance=po)
        line_formset = PurchaseOrderLineFormSet(request.POST, instance=po)

        products = Product.objects.filter(is_active=True).select_related("base_unit")
        products_json = json.dumps(
            {
                str(p.id): {
                    "uom_code": getattr(p.base_unit, "code", ""),
                    "uom_name": getattr(p.base_unit, "name", ""),
                }
                for p in products
            },
            cls=DjangoJSONEncoder,
        )

        if not (form.is_valid() and line_formset.is_valid()):
            messages.error(request, "Hay errores al actualizar la orden. Revisa los campos marcados.")
            return render(
                request,
                self.template_name,
                {
                    "object": po,
                    "form": form,
                    "line_formset": line_formset,
                    "is_edit": True,
                    "products_json": products_json,
                },
            )

        with transaction.atomic():
            po = form.save()

            # guardamos líneas (crea/actualiza/elimina según el formset)
            instances = line_formset.save(commit=False)

            # marcar para borrar los que vienen en deleted_objects
            for obj in line_formset.deleted_objects:
                obj.delete()

            for line in instances:
                line.order = po
                line.save()

            po.recalc_total()
            po.save(update_fields=["total_amount"])

        messages.success(request, f"Orden de compra {po.number} actualizada correctamente.")
        return redirect(reverse("procurement:order_list"))


# vistas para crear recepciones de materia prima con formulario y formset


class RawMaterialReceptionCreateView(LoginRequiredMixin, View):
    template_name = "procurement/reception_form.html"

    def _get_po(self, request):
        """
        Devuelve la OC si viene por GET (?po=) o por POST (hidden).
        """
        po_id = request.GET.get("po") or request.POST.get("purchase_order_id")
        if not po_id:
            return None
        try:
            return (
                PurchaseOrder.objects
                .select_related("supplier")
                .prefetch_related("lines__product")
                .get(pk=po_id)
            )
        except PurchaseOrder.DoesNotExist:
            return None
        
    def _build_products_json(self):
        """
        Catálogo de productos RAW activos para el JS.
        """
        products = (
            Product.objects
            .filter(product_type=ProductType.RAW, is_active=True)
            .select_related("base_unit")
            .order_by("name")
        )

        data = []
        for p in products:
            data.append({
                "id": p.id,
                "code": p.code,
                "name": p.name,
                "base_unit": getattr(p.base_unit, "code", ""),
                "base_unit_id": p.base_unit.id if p.base_unit else None,
                "unit_price": str(p.unit_price or 0),
            })
        return json.dumps(data, ensure_ascii=False)

    # ---------- GET ----------

    def get(self, request, *args, **kwargs):
        po = self._get_po(request)

        initial_header = {}
        initial_lines = []

        if po:
            partner = po.supplier
            trade = getattr(partner, "trade_name", "") or ""
            legal = getattr(partner, "legal_name", "") or ""
            tax_id = (
                getattr(partner, "tax_id", "")
                or getattr(partner, "ruc", "")
                or getattr(partner, "tax_number", "")
                or getattr(partner, "identification", "")
            )

            initial_header.update({
                "supplier_name": trade or legal,
                "supplier_ruc": tax_id,
                "document_type": "Orden de compra",
                "document_number": po.number,
            })

            for line in po.lines.all():
                if not line.product:
                    continue

                # line.quantity = cantidad ORIGINAL (ej: 500)
                # line.unit = unidad ORIGINAL (ej: gramos)
                # No necesita conversión, ya está en la unidad del usuario
                initial_lines.append({
                    "product": line.product,
                    "product_code": line.product.code,
                    "unit": line.unit,
                    "expected_quantity": line.quantity,
                    "received_quantity": line.quantity,
                    "unit_cost": line.unit_price,
                })

        header_form = RawMaterialReceptionHeaderForm(initial=initial_header)
        line_formset = RawMaterialReceptionLineFormSet(
            initial=initial_lines,
            prefix="lines",
        )

        context = {
            "header_form": header_form,
            "line_formset": line_formset,
            "purchase_order": po,
            "products_json": self._build_products_json(),
        }
        return render(request, self.template_name, context)
    # ---------- POST ----------
    def post(self, request, *args, **kwargs):
        po = self._get_po(request)

        # Opción A: una sola recepción por OC
        if po:
            if po.status in [PurchaseOrderStatus.CANCELLED, PurchaseOrderStatus.RECEIVED]:
                messages.error(
                    request,
                    f"La orden de compra {po.number} ya no puede ser recepcionada.",
                )
                return redirect("procurement:order_list")

            has_active_reception = (
                RawMaterialReception.objects
                .filter(purchase_order=po)
                .exclude(status=ReceptionStatus.CANCELLED)
                .exists()
            )
            if has_active_reception:
                messages.error(
                    request,
                    f"La orden de compra {po.number} ya tiene una recepción registrada.",
                )
                return redirect("procurement:order_list")

        header_form = RawMaterialReceptionHeaderForm(request.POST)
        line_formset = RawMaterialReceptionLineFormSet(
            request.POST,
            prefix="lines",
        )

        if not header_form.is_valid() or not line_formset.is_valid():
            return render(
                request,
                self.template_name,
                {
                    "header_form": header_form,
                    "line_formset": line_formset,
                    "purchase_order": po,
                    "products_json": self._build_products_json(),
                },
            )

        # Armamos los diccionarios para el service
        header_data = header_form.cleaned_data.copy()
        lines_data = []

        for form in line_formset:
            cd = form.cleaned_data
            if not cd:
                continue
            if cd.get("DELETE"):
                continue

            # Opcional: saltar líneas sin producto o sin cantidad recibida
            if not cd.get("product") or not cd.get("received_quantity"):
                continue

            lines_data.append(cd)

        if not lines_data:
            messages.error(request, "Debes ingresar al menos una línea de producto con cantidad recibida.")
            return render(
                request,
                self.template_name,
                {
                    "header_form": header_form,
                    "line_formset": line_formset,
                    "purchase_order": po,
                    "products_json": self._build_products_json(),
                },
            )

        with transaction.atomic():
            # 🔥 Usamos el service que CREA recepción, líneas, LOTES y movimientos
            reception = create_raw_material_reception(
                user=request.user,
                header_data=header_data,
                lines_data=lines_data,
            )

            # Amarrar la OC a la recepción y marcarla como recibida
            if po:
                reception.purchase_order = po
                reception.save(update_fields=["purchase_order"])

                po.status = PurchaseOrderStatus.RECEIVED
                po.save(update_fields=["status"])

        messages.success(
            request,
            f"Recepción {reception.code} registrada correctamente. "
            "Los lotes han sido creados en Cuarentena para control de calidad."
        )
        return redirect("procurement:receptions_list")
    
# vistas para listar recepciones de materia prima 
class RawMaterialReceptionListView(LoginRequiredMixin, ListView):
    model = RawMaterialReception
    template_name = "procurement/receptions_list.html"
    context_object_name = "page"
    
    paginate_by = 20

    def get_queryset(self):
        return RawMaterialReception.objects.order_by("-reception_date", "-id")