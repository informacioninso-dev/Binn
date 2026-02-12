from django.shortcuts import render, redirect, get_object_or_404
from django.views import View
from django.views.generic import ListView, DetailView, TemplateView
from django.views.decorators.http import require_http_methods
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Q, Sum
from django.forms import modelformset_factory
from decimal import Decimal

from core.mixins import ModulePermissionMixin
from .models import (
    SaleOrder, SaleOrderLine, SaleOrderStatus,
    SaleDispatch, SaleDispatchLine,
    PickingOrder, PickingOrderStatus,
    PackingOrder, PackingOrderStatus,
    SaleInvoice, SaleInvoiceLine, InvoiceStatus,
    ReturnReason, SaleReturn, SaleReturnStatus,
    CreditNote, CreditNoteStatus,
    PriceList, PriceListItem,
)
from partners.models import Partner
from .forms import SaleOrderForm, SaleOrderLineForm
from .services import (
    confirm_order_service, check_dispatch_availability,
    create_picking, complete_picking,
    create_packing, complete_packing,
    create_dispatch,
    create_return, receive_return, approve_return, reject_return, issue_credit_note,
)


# ─── Index ──────────────────────────────────────────────────

class SalesIndexView(LoginRequiredMixin, ModulePermissionMixin, View):
    permission_required = "sales.view_saleorder"

    def get(self, request, *args, **kwargs):
        return redirect("sales:order_list")


# ─── Pedidos ────────────────────────────────────────────────

class SaleOrderListView(LoginRequiredMixin, ModulePermissionMixin, ListView):
    permission_required = "sales.view_saleorder"
    model = SaleOrder
    template_name = "sales/order_list.html"
    context_object_name = "orders"
    paginate_by = 20

    def get_queryset(self):
        qs = (
            SaleOrder.objects
            .select_related("client")
            .annotate(total_amount=Sum("lines__total_price"))
            .order_by("-created_at")
        )
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
        ctx = super().get_context_data(**kwargs)
        ctx["status_choices"] = SaleOrderStatus.choices
        return ctx


class SaleOrderDetailView(LoginRequiredMixin, ModulePermissionMixin, DetailView):
    permission_required = "sales.view_saleorder"
    model = SaleOrder
    template_name = "sales/order_detail.html"
    context_object_name = "order"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["total"] = self.object.get_total()
        return ctx


class SaleOrderCreateView(LoginRequiredMixin, ModulePermissionMixin, View):
    permission_required = "sales.add_saleorder"
    template_name = "sales/order_form.html"

    def _products_json(self):
        import json
        from inventory.models import Product, ProductType, Stock
        products = Product.objects.filter(is_active=True, product_type=ProductType.FG)
        stocks = {s.product_id: s.quantity for s in Stock.objects.filter(product__in=products)}
        data = {}
        for p in products:
            data[str(p.pk)] = {
                "unit_price": str(p.unit_price or 0),
                "code": p.code,
                "name": p.name,
                "stock": str(stocks.get(p.pk, 0)),
            }
        return json.dumps(data)

    def _partners_json(self):
        import json
        partners = Partner.objects.filter(is_active=True, is_customer=True)
        data = {}
        for p in partners:
            data[str(p.pk)] = {
                "address": p.address or "",
                "city": p.city or "",
                "phone": p.contact_phone or "",
                "email": p.contact_email or "",
            }
        return json.dumps(data)

    def get(self, request):
        form = SaleOrderForm()
        LineFormSet = modelformset_factory(
            SaleOrderLine, form=SaleOrderLineForm, extra=1,
        )
        line_formset = LineFormSet(queryset=SaleOrderLine.objects.none())
        return render(request, self.template_name, {
            "form": form,
            "line_formset": line_formset,
            "products_json": self._products_json(),
            "partners_json": self._partners_json(),
        })

    def post(self, request):
        form = SaleOrderForm(request.POST)
        LineFormSet = modelformset_factory(
            SaleOrderLine, form=SaleOrderLineForm, extra=1,
        )
        line_formset = LineFormSet(request.POST)

        if form.is_valid() and line_formset.is_valid():
            order = form.save()
            for lf in line_formset:
                if lf.cleaned_data and not lf.cleaned_data.get("DELETE"):
                    SaleOrderLine.objects.create(
                        order=order,
                        product=lf.cleaned_data["product"],
                        quantity=lf.cleaned_data["quantity"],
                        unit_price=lf.cleaned_data["unit_price"],
                        total_price=lf.cleaned_data["quantity"] * lf.cleaned_data["unit_price"],
                    )
            messages.success(request, "Pedido creado correctamente.")
            return redirect("sales:order_list")

        return render(request, self.template_name, {
            "form": form,
            "line_formset": line_formset,
            "products_json": self._products_json(),
            "partners_json": self._partners_json(),
        })


@login_required
def confirm_order(request, pk):
    order = get_object_or_404(SaleOrder, pk=pk)
    order = confirm_order_service(order)
    messages.success(request, f"Pedido {order.code} confirmado.")
    return redirect("sales:order_list")


# ─── Picking ──────────────────────────────────────────────

class DispatchCheckView(LoginRequiredMixin, ModulePermissionMixin, View):
    """Verificar stock y crear picking."""
    permission_required = "sales.add_saledispatch"
    template_name = "sales/dispatch_check.html"

    def get(self, request, pk):
        order = get_object_or_404(
            SaleOrder.objects.select_related("client").prefetch_related("lines__product"),
            pk=pk,
        )
        if not order.can_start_picking:
            messages.error(request, "Este pedido no puede iniciar picking en su estado actual.")
            return redirect("sales:order_list")

        availability = check_dispatch_availability(order)
        all_ok = all(item["stock_ok"] for item in availability)

        return render(request, self.template_name, {
            "order": order,
            "availability": availability,
            "all_ok": all_ok,
        })


class PickingCreateView(LoginRequiredMixin, ModulePermissionMixin, View):
    """Crear orden de picking (genera guía de picking)."""
    permission_required = "sales.add_saledispatch"

    def post(self, request, pk):
        order = get_object_or_404(SaleOrder, pk=pk)
        try:
            picking = create_picking(order=order, user=request.user)
            messages.success(request, f"Picking {picking.code} creado. Proceda a recoger los productos.")
            return redirect("sales:picking_detail", pk=picking.pk)
        except Exception as e:
            messages.error(request, f"Error al crear picking: {e}")
            return redirect("sales:dispatch_check", pk=pk)


class PickingDetailView(LoginRequiredMixin, ModulePermissionMixin, View):
    """Guía de picking - operario marca lo recogido."""
    permission_required = "sales.view_saledispatch"
    template_name = "sales/picking_detail.html"

    def get(self, request, pk):
        picking = get_object_or_404(
            PickingOrder.objects.select_related("order__client")
            .prefetch_related("lines__product", "lines__lot"),
            pk=pk,
        )
        return render(request, self.template_name, {"picking": picking})

    def post(self, request, pk):
        """Completar picking con cantidades recogidas."""
        picking = get_object_or_404(
            PickingOrder.objects.prefetch_related("lines"),
            pk=pk,
        )

        picked_quantities = {}
        for pl in picking.lines.all():
            key = f"picked_{pl.pk}"
            val = request.POST.get(key)
            if val:
                picked_quantities[pl.pk] = Decimal(val)

        try:
            complete_picking(picking=picking, picked_quantities=picked_quantities, user=request.user)
            # Auto-crear packing
            packing = create_packing(picking=picking, user=request.user)
            messages.success(request, f"Picking completado. Packing {packing.code} creado.")
            return redirect("sales:packing_detail", pk=packing.pk)
        except Exception as e:
            messages.error(request, f"Error: {e}")
            return redirect("sales:picking_detail", pk=pk)


class PickingListView(LoginRequiredMixin, ModulePermissionMixin, ListView):
    permission_required = "sales.view_saledispatch"
    model = PickingOrder
    template_name = "sales/picking_list.html"
    context_object_name = "pickings"
    paginate_by = 20

    def get_queryset(self):
        qs = (
            PickingOrder.objects
            .select_related("order__client", "assigned_to")
            .order_by("-created_at")
        )
        q = self.request.GET.get("q", "").strip()
        if q:
            qs = qs.filter(
                Q(code__icontains=q)
                | Q(order__code__icontains=q)
                | Q(order__client__trade_name__icontains=q)
            )
        return qs


# ─── Packing ─────────────────────────────────────────────

class PackingDetailView(LoginRequiredMixin, ModulePermissionMixin, View):
    """Registro de empaque - peso, cajas, asignación de caja por línea."""
    permission_required = "sales.view_saledispatch"
    template_name = "sales/packing_detail.html"

    def get(self, request, pk):
        packing = get_object_or_404(
            PackingOrder.objects.select_related("order__client", "picking")
            .prefetch_related("lines__product", "lines__lot"),
            pk=pk,
        )
        return render(request, self.template_name, {"packing": packing})

    def post(self, request, pk):
        """Completar packing."""
        packing = get_object_or_404(PackingOrder, pk=pk)

        packing_data = {
            "num_boxes": int(request.POST.get("num_boxes", 0) or 0),
            "gross_weight": Decimal(request.POST.get("gross_weight", 0) or 0),
            "net_weight": Decimal(request.POST.get("net_weight", 0) or 0),
            "notes": request.POST.get("notes", ""),
            "box_assignments": {},
        }

        # Recoger asignaciones de caja
        for pl in packing.lines.all():
            box_key = f"box_{pl.pk}"
            box_val = request.POST.get(box_key)
            if box_val:
                packing_data["box_assignments"][str(pl.pk)] = box_val

        try:
            complete_packing(packing=packing, packing_data=packing_data, user=request.user)
            messages.success(request, f"Packing {packing.code} completado. Listo para despachar.")
            return redirect("sales:dispatch_confirm", pk=packing.order.pk)
        except Exception as e:
            messages.error(request, f"Error: {e}")
            return redirect("sales:packing_detail", pk=pk)


# ─── Despacho ────────────────────────────────────────────

class DispatchConfirmView(LoginRequiredMixin, ModulePermissionMixin, View):
    """Confirmación final de despacho - genera guía de remisión."""
    permission_required = "sales.add_saledispatch"
    template_name = "sales/dispatch_confirm.html"

    def get(self, request, pk):
        order = get_object_or_404(
            SaleOrder.objects.select_related("client"),
            pk=pk,
        )
        packing = (
            order.packings
            .filter(status=PackingOrderStatus.COMPLETED)
            .select_related("picking")
            .prefetch_related("lines__product", "lines__lot")
            .first()
        )
        if not packing:
            messages.error(request, "No hay packing completado para este pedido.")
            return redirect("sales:order_list")

        return render(request, self.template_name, {
            "order": order,
            "packing": packing,
        })

    def post(self, request, pk):
        order = get_object_or_404(SaleOrder, pk=pk)
        try:
            dispatch = create_dispatch(order=order, user=request.user)
            messages.success(request, f"Despacho {dispatch.code} creado. Stock descontado.")
            return redirect("sales:dispatch_list")
        except Exception as e:
            messages.error(request, f"Error al despachar: {e}")
            return redirect("sales:dispatch_confirm", pk=pk)


class DispatchListView(LoginRequiredMixin, ModulePermissionMixin, ListView):
    permission_required = "sales.view_saledispatch"
    model = SaleDispatch
    template_name = "sales/dispatch_list.html"
    context_object_name = "dispatches"
    paginate_by = 20

    def get_queryset(self):
        qs = (
            SaleDispatch.objects
            .select_related("order__client")
            .order_by("-dispatched_date")
        )
        q = self.request.GET.get("q", "").strip()
        if q:
            qs = qs.filter(
                Q(code__icontains=q)
                | Q(order__code__icontains=q)
                | Q(order__client__trade_name__icontains=q)
            )
        return qs


# ─── Facturación ─────────────────────────────────────────

class InvoiceListView(LoginRequiredMixin, ModulePermissionMixin, ListView):
    permission_required = "sales.view_saleinvoice"
    model = SaleInvoice
    template_name = "sales/invoice_list.html"
    context_object_name = "invoices"
    paginate_by = 20

    def get_queryset(self):
        qs = (
            SaleInvoice.objects
            .select_related("order__client")
            .order_by("-issue_date")
        )
        q = self.request.GET.get("q", "").strip()
        status = self.request.GET.get("status", "").strip()
        if q:
            qs = qs.filter(
                Q(sequential__icontains=q)
                | Q(access_key__icontains=q)
                | Q(buyer_legal_name__icontains=q)
                | Q(order__code__icontains=q)
            )
        if status:
            qs = qs.filter(status=status)
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["status_choices"] = InvoiceStatus.choices
        return ctx


class InvoiceCreateView(LoginRequiredMixin, ModulePermissionMixin, View):
    permission_required = "sales.add_saleinvoice"

    def post(self, request, pk):
        from .invoice_service import create_invoice
        order = get_object_or_404(SaleOrder, pk=pk)
        try:
            invoice = create_invoice(order=order, user=request.user)
            messages.success(request, f"Factura {invoice.full_number} creada.")
            return redirect("sales:invoice_detail", pk=invoice.pk)
        except Exception as e:
            messages.error(request, f"Error al facturar: {e}")
            return redirect("sales:order_list")


class InvoiceDetailView(LoginRequiredMixin, ModulePermissionMixin, DetailView):
    permission_required = "sales.view_saleinvoice"
    model = SaleInvoice
    template_name = "sales/invoice_detail.html"
    context_object_name = "invoice"

    def get_queryset(self):
        return (
            SaleInvoice.objects
            .select_related("order__client", "dispatch")
            .prefetch_related("lines__product")
        )


class InvoiceSendSRIView(LoginRequiredMixin, ModulePermissionMixin, View):
    permission_required = "sales.change_saleinvoice"

    def post(self, request, pk):
        from .sri_service import sign_xml, send_to_sri
        invoice = get_object_or_404(SaleInvoice, pk=pk)

        try:
            if invoice.status == InvoiceStatus.DRAFT:
                sign_xml(invoice)
                invoice.refresh_from_db()

            if invoice.status == InvoiceStatus.SIGNED:
                send_to_sri(invoice)
                invoice.refresh_from_db()

            if invoice.status == InvoiceStatus.AUTHORIZED:
                messages.success(request, f"Factura {invoice.full_number} autorizada por el SRI.")
            elif invoice.status == InvoiceStatus.REJECTED:
                messages.error(request, f"Factura rechazada: {invoice.sri_response}")
            else:
                messages.info(request, f"Estado: {invoice.get_status_display()}")

        except Exception as e:
            messages.error(request, f"Error SRI: {e}")

        return redirect("sales:invoice_detail", pk=pk)


class InvoiceRIDEView(LoginRequiredMixin, ModulePermissionMixin, View):
    permission_required = "sales.view_saleinvoice"

    def get(self, request, pk):
        from django.http import HttpResponse
        from .invoice_service import generate_ride_pdf
        invoice = get_object_or_404(
            SaleInvoice.objects.select_related("order__client")
            .prefetch_related("lines__product"),
            pk=pk,
        )
        pdf_data = generate_ride_pdf(invoice)
        response = HttpResponse(pdf_data, content_type="application/pdf")
        response["Content-Disposition"] = f'inline; filename="RIDE_{invoice.full_number}.pdf"'
        return response


# ─── Guías de Remisión ────────────────────────────────────

from .models import GuiaRemision, GuiaRemisionStatus


class GuiaRemisionListView(LoginRequiredMixin, ModulePermissionMixin, ListView):
    permission_required = "sales.view_guiaremision"
    model = GuiaRemision
    template_name = "sales/guia_list.html"
    context_object_name = "guias"
    paginate_by = 20

    def get_queryset(self):
        qs = (
            GuiaRemision.objects
            .select_related("dispatch__order__client", "carrier")
            .order_by("-issue_date")
        )
        q = self.request.GET.get("q", "").strip()
        status = self.request.GET.get("status", "").strip()
        if q:
            from django.db.models import Q
            qs = qs.filter(
                Q(sequential__icontains=q)
                | Q(recipient_legal_name__icontains=q)
                | Q(dispatch__code__icontains=q)
            )
        if status:
            qs = qs.filter(status=status)
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["status_choices"] = GuiaRemisionStatus.choices
        return ctx


class GuiaRemisionCreateView(LoginRequiredMixin, ModulePermissionMixin, View):
    permission_required = "sales.add_guiaremision"
    template_name = "sales/guia_create.html"

    def get(self, request, dispatch_pk):
        from partners.models import Partner

        dispatch = get_object_or_404(
            SaleDispatch.objects.select_related("order__client"),
            pk=dispatch_pk,
        )
        existing = GuiaRemision.objects.filter(dispatch=dispatch).first()
        if existing:
            messages.warning(request, f"Ya existe guía {existing.full_number} para este despacho.")
            return redirect("sales:guia_detail", pk=existing.pk)

        carriers = Partner.objects.filter(is_carrier=True, is_active=True)
        related_invoice = dispatch.invoices.order_by("-issue_date").first() if hasattr(dispatch, "invoices") else None

        return render(request, self.template_name, {
            "dispatch": dispatch,
            "carriers": carriers,
            "related_invoice": related_invoice,
        })

    def post(self, request, dispatch_pk):
        from .guia_service import create_guia
        from partners.models import Partner
        from datetime import date

        dispatch = get_object_or_404(SaleDispatch, pk=dispatch_pk)

        try:
            carrier = get_object_or_404(Partner, pk=request.POST.get("carrier"), is_carrier=True)
            guia = create_guia(
                dispatch=dispatch,
                carrier=carrier,
                transport_start_date=date.fromisoformat(request.POST.get("transport_start_date")),
                transport_end_date=date.fromisoformat(request.POST.get("transport_end_date")),
                transfer_reason=request.POST.get("transfer_reason", "Venta"),
                route=request.POST.get("route", ""),
                supporting_invoice=dispatch.invoices.order_by("-issue_date").first() if hasattr(dispatch, "invoices") else None,
                user=request.user,
            )
            messages.success(request, f"Guía de remisión {guia.full_number} creada.")
            return redirect("sales:guia_detail", pk=guia.pk)
        except Exception as e:
            messages.error(request, f"Error al crear guía: {e}")
            return redirect("sales:guia_create", dispatch_pk=dispatch_pk)


class GuiaRemisionDetailView(LoginRequiredMixin, ModulePermissionMixin, DetailView):
    permission_required = "sales.view_guiaremision"
    model = GuiaRemision
    template_name = "sales/guia_detail.html"
    context_object_name = "guia"

    def get_queryset(self):
        return (
            GuiaRemision.objects
            .select_related("dispatch__order__client", "carrier", "order")
            .prefetch_related("lines__product")
        )


class GuiaRemisionSendSRIView(LoginRequiredMixin, ModulePermissionMixin, View):
    permission_required = "sales.change_guiaremision"

    def post(self, request, pk):
        from .sri_service import sign_xml, send_to_sri

        guia = get_object_or_404(GuiaRemision, pk=pk)

        try:
            if guia.status == GuiaRemisionStatus.DRAFT:
                sign_xml(guia)
                guia.refresh_from_db()

            if guia.status == GuiaRemisionStatus.SIGNED:
                send_to_sri(guia)
                guia.refresh_from_db()

            if guia.status == GuiaRemisionStatus.AUTHORIZED:
                messages.success(request, f"Guía {guia.full_number} autorizada por el SRI.")
            elif guia.status == GuiaRemisionStatus.REJECTED:
                messages.error(request, f"Guía rechazada: {guia.sri_response}")
            else:
                messages.info(request, f"Estado: {guia.get_status_display()}")

        except Exception as e:
            messages.error(request, f"Error SRI: {e}")

        return redirect("sales:guia_detail", pk=pk)


class GuiaRemisionRIDEView(LoginRequiredMixin, ModulePermissionMixin, View):
    permission_required = "sales.view_guiaremision"

    def get(self, request, pk):
        from django.http import HttpResponse
        from .guia_service import generate_guia_ride_pdf

        guia = get_object_or_404(
            GuiaRemision.objects.select_related("dispatch__order__client", "carrier")
            .prefetch_related("lines__product"),
            pk=pk,
        )
        pdf_data = generate_guia_ride_pdf(guia)
        response = HttpResponse(pdf_data, content_type="application/pdf")
        response["Content-Disposition"] = f'inline; filename="RIDE_GR_{guia.full_number}.pdf"'
        return response


# ─── Devoluciones ──────────────────────────────────────────

class SaleReturnListView(LoginRequiredMixin, ModulePermissionMixin, ListView):
    permission_required = "sales.view_salereturn"
    model = SaleReturn
    template_name = "sales/return_list.html"
    context_object_name = "returns"
    paginate_by = 20

    def get_queryset(self):
        qs = (
            SaleReturn.objects
            .select_related("client", "invoice", "reason", "credit_note")
            .order_by("-return_date")
        )
        q = self.request.GET.get("q", "").strip()
        status = self.request.GET.get("status", "").strip()
        if q:
            qs = qs.filter(
                Q(code__icontains=q)
                | Q(invoice__sequential__icontains=q)
                | Q(client__trade_name__icontains=q)
                | Q(client__identification__icontains=q)
            )
        if status:
            qs = qs.filter(status=status)
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["status_choices"] = SaleReturnStatus.choices
        return ctx

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["status_choices"] = SaleReturnStatus.choices
        return ctx


class SaleReturnDetailView(LoginRequiredMixin, ModulePermissionMixin, DetailView):
    permission_required = "sales.view_salereturn"
    model = SaleReturn
    template_name = "sales/return_detail.html"
    context_object_name = "return_doc"

    def get_queryset(self):
        return (
            SaleReturn.objects
            .select_related("client", "invoice", "reason", "credit_note")
            .prefetch_related("lines__product", "lines__lot")
        )


class SaleReturnCreateView(LoginRequiredMixin, ModulePermissionMixin, View):
    """
    Vista de creación de devolución con flujo de 3 pasos:
    1. Seleccionar cliente
    2. Seleccionar factura del cliente
    3. Seleccionar productos y motivo
    """
    permission_required = "sales.add_salereturn"
    template_name = "sales/return_form.html"

    def _get_clients_with_invoices(self):
        """Clientes que tienen facturas."""
        return (
            Partner.objects
            .filter(sale_orders__invoices__isnull=False)
            .distinct()
            .order_by("trade_name")
        )

    def _get_reasons(self):
        return ReturnReason.objects.filter(is_active=True).order_by("reason_type", "name")

    def get(self, request):
        client_id = request.GET.get("client")
        invoice_id = request.GET.get("invoice")

        ctx = {
            "clients": self._get_clients_with_invoices(),
            "reasons": self._get_reasons(),
            "selected_client": None,
            "selected_invoice": None,
            "invoices": [],
        }

        if client_id:
            ctx["selected_client"] = get_object_or_404(Partner, pk=client_id)
            ctx["invoices"] = (
                SaleInvoice.objects
                .filter(order__client_id=client_id)
                .select_related("order")
                .order_by("-issue_date")
            )

        if invoice_id:
            ctx["selected_invoice"] = get_object_or_404(
                SaleInvoice.objects.select_related("order__client")
                .prefetch_related("lines__product"),
                pk=invoice_id,
            )
            if not ctx["selected_client"]:
                ctx["selected_client"] = ctx["selected_invoice"].order.client
                ctx["invoices"] = (
                    SaleInvoice.objects
                    .filter(order__client=ctx["selected_client"])
                    .select_related("order")
                    .order_by("-issue_date")
                )

        return render(request, self.template_name, ctx)

    def post(self, request):
        action = request.POST.get("action", "")

        # Step 1: Seleccionar cliente
        if action == "select_client":
            client_id = request.POST.get("client_id")
            if client_id:
                return redirect(f"{request.path}?client={client_id}")
            messages.error(request, "Seleccione un cliente.")
            return redirect(request.path)

        # Step 2: Seleccionar factura
        if action == "select_invoice":
            invoice_id = request.POST.get("invoice_id")
            client_id = request.POST.get("client_id")
            if invoice_id:
                return redirect(f"{request.path}?client={client_id}&invoice={invoice_id}")
            messages.error(request, "Seleccione una factura.")
            return redirect(f"{request.path}?client={client_id}")

        # Step 3: Crear devolución
        invoice_id = request.POST.get("invoice_id")
        reason_id = request.POST.get("reason_id")
        reason_notes = request.POST.get("reason_notes", "").strip()

        if not invoice_id or not reason_id:
            messages.error(request, "Debe seleccionar factura y motivo.")
            return redirect(request.path)

        invoice = get_object_or_404(
            SaleInvoice.objects.select_related("order__client"),
            pk=invoice_id,
        )
        reason = get_object_or_404(ReturnReason, pk=reason_id)
        client = invoice.order.client

        # Recopilar líneas
        lines_data = []
        for key, value in request.POST.items():
            if key.startswith("qty_") and value:
                line_id = int(key.split("_")[1])
                qty = Decimal(value)
                if qty > 0:
                    lines_data.append({
                        "invoice_line_id": line_id,
                        "quantity_returned": qty,
                    })

        if not lines_data:
            messages.error(request, "Debe indicar al menos un producto a devolver.")
            return redirect(f"{request.path}?client={client.pk}&invoice={invoice_id}")

        try:
            return_doc = create_return(
                client=client,
                invoice=invoice,
                reason=reason,
                reason_notes=reason_notes,
                lines_data=lines_data,
                user=request.user,
            )
            messages.success(request, f"Devolución {return_doc.code} creada exitosamente.")
            return redirect("sales:return_detail", pk=return_doc.pk)
        except Exception as e:
            messages.error(request, str(e))
            return redirect(f"{request.path}?client={client.pk}&invoice={invoice_id}")


@login_required
def receive_return_view(request, pk):
    """Recepción del producto devuelto - lo envía a cuarentena."""
    return_doc = get_object_or_404(SaleReturn, pk=pk)
    try:
        receive_return(return_doc=return_doc, user=request.user)
        messages.success(request, f"Devolución {return_doc.code} recibida. Producto en cuarentena para inspección.")
    except Exception as e:
        messages.error(request, str(e))
    return redirect("sales:return_detail", pk=pk)


@login_required
def approve_return_view(request, pk):
    """QA aprueba la devolución - producto ingresa a stock."""
    return_doc = get_object_or_404(SaleReturn, pk=pk)
    try:
        approve_return(return_doc=return_doc, user=request.user)
        messages.success(request, f"Devolución {return_doc.code} aprobada. Producto ingresó a stock.")
    except Exception as e:
        messages.error(request, str(e))
    return redirect("sales:return_detail", pk=pk)


@login_required
def reject_return_view(request, pk):
    """QA rechaza la devolución - producto va a bodega de baja."""
    return_doc = get_object_or_404(SaleReturn, pk=pk)
    rejection_notes = request.POST.get("rejection_notes", "")
    try:
        reject_return(return_doc=return_doc, rejection_notes=rejection_notes, user=request.user)
        messages.success(request, f"Devolución {return_doc.code} rechazada. Producto dado de baja.")
    except Exception as e:
        messages.error(request, str(e))
    return redirect("sales:return_detail", pk=pk)


@login_required
def issue_credit_note_view(request, pk):
    """Emitir nota de crédito para devolución aprobada."""
    return_doc = get_object_or_404(SaleReturn, pk=pk)
    try:
        cn = issue_credit_note(return_doc=return_doc, user=request.user)
        messages.success(request, f"Nota de crédito {cn.full_number} generada.")
    except Exception as e:
        messages.error(request, str(e))
    return redirect("sales:return_detail", pk=pk)


# ─── Notas de Crédito ─────────────────────────────────────

class CreditNoteListView(LoginRequiredMixin, ModulePermissionMixin, ListView):
    permission_required = "sales.view_creditnote"
    model = CreditNote
    template_name = "sales/credit_note_list.html"
    context_object_name = "credit_notes"
    paginate_by = 20

    def get_queryset(self):
        return (
            CreditNote.objects
            .select_related("invoice__order__client")
            .order_by("-issue_date")
        )


# ─── Listas de Precios ────────────────────────────────────

class PriceListListView(LoginRequiredMixin, ModulePermissionMixin, ListView):
    permission_required = "sales.view_pricelist"
    template_name = "sales/pricelist_list.html"
    context_object_name = "pricelists"
    paginate_by = 20

    def get_queryset(self):
        return PriceList.objects.all().order_by("-created_at")


class PriceListDetailView(LoginRequiredMixin, ModulePermissionMixin, DetailView):
    permission_required = "sales.view_pricelist"
    template_name = "sales/pricelist_detail.html"
    context_object_name = "pricelist"

    def get_queryset(self):
        return PriceList.objects.all()

    def get_context_data(self, **kwargs):
        from decimal import Decimal
        context = super().get_context_data(**kwargs)
        items = PriceListItem.objects.filter(
            price_list=self.object
        ).select_related("product").order_by("product__code")

        # Calcular porcentaje de diferencia para cada item
        items_with_diff = []
        for item in items:
            base_price = item.product.unit_price or Decimal("0")
            list_price = item.unit_price

            if base_price > 0:
                # Calcular diferencia porcentual: (lista - base) / base * 100
                diff_percent = ((list_price - base_price) / base_price * 100)
            else:
                diff_percent = Decimal("0")

            # Agregar el porcentaje calculado al objeto
            item.diff_percent = diff_percent
            items_with_diff.append(item)

        context["items"] = items_with_diff
        return context


@login_required
def pricelist_create(request):
    from .models import PriceList, PriceListItem
    from inventory.models import Product, ProductType

    if request.method == "POST":
        # Crear la lista de precios
        code = request.POST.get("code")
        name = request.POST.get("name")
        currency = request.POST.get("currency", "USD")
        description = request.POST.get("description", "")
        is_active = request.POST.get("is_active") == "on"

        pricelist = PriceList.objects.create(
            code=code,
            name=name,
            currency=currency,
            description=description,
            is_active=is_active,
            created_by=request.user,
            updated_by=request.user,
        )

        messages.success(request, f"Lista de precios '{pricelist.name}' creada correctamente.")
        return redirect("sales:pricelist_detail", pk=pricelist.pk)

    # GET: mostrar formulario
    from inventory.models import Product, ProductType
    products = Product.objects.filter(
        is_active=True,
        product_type=ProductType.FG
    ).order_by("code")

    return render(request, "sales/pricelist_form.html", {
        "products": products,
    })


@login_required
def pricelist_update(request, pk):
    from .models import PriceList
    pricelist = get_object_or_404(PriceList, pk=pk)

    if request.method == "POST":
        pricelist.code = request.POST.get("code")
        pricelist.name = request.POST.get("name")
        pricelist.currency = request.POST.get("currency", "USD")
        pricelist.description = request.POST.get("description", "")
        pricelist.is_active = request.POST.get("is_active") == "on"
        pricelist.updated_by = request.user
        pricelist.save()

        messages.success(request, f"Lista de precios '{pricelist.name}' actualizada.")
        return redirect("sales:pricelist_detail", pk=pricelist.pk)

    return render(request, "sales/pricelist_form.html", {
        "pricelist": pricelist,
    })


@login_required
def pricelist_item_add(request, pk):
    from .models import PriceList, PriceListItem
    from inventory.models import Product

    pricelist = get_object_or_404(PriceList, pk=pk)

    if request.method == "POST":
        product_id = request.POST.get("product_id")
        unit_price = request.POST.get("unit_price")

        product = get_object_or_404(Product, pk=product_id)

        # Verificar si ya existe
        existing = PriceListItem.objects.filter(
            price_list=pricelist,
            product=product
        ).first()

        if existing:
            existing.unit_price = unit_price
            existing.updated_by = request.user
            existing.save()
            messages.success(request, f"Precio actualizado para '{product.name}'")
        else:
            PriceListItem.objects.create(
                price_list=pricelist,
                product=product,
                unit_price=unit_price,
                created_by=request.user,
                updated_by=request.user,
            )
            messages.success(request, f"Producto '{product.name}' agregado a la lista")

        return redirect("sales:pricelist_detail", pk=pricelist.pk)

    # GET: redirigir al detalle
    return redirect("sales:pricelist_detail", pk=pricelist.pk)


@login_required
def pricelist_item_delete(request, pk, item_pk):
    from .models import PriceList, PriceListItem

    pricelist = get_object_or_404(PriceList, pk=pk)
    item = get_object_or_404(PriceListItem, pk=item_pk, price_list=pricelist)

    product_name = item.product.name
    item.delete()

    messages.success(request, f"Producto '{product_name}' eliminado de la lista")
    return redirect("sales:pricelist_detail", pk=pricelist.pk)


# ─── AJAX Endpoints ───────────────────────────────────────

@login_required
@require_http_methods(["GET"])
def get_client_prices(request, client_id):
    """
    Endpoint AJAX para obtener precios de productos para un cliente.
    Retorna un diccionario con los precios personalizados o base.
    """
    from django.http import JsonResponse
    from .pricing_service import get_pricelist_for_products

    try:
        prices = get_pricelist_for_products(client_id)
        return JsonResponse(prices)
    except Exception as e:
        return JsonResponse({"error": str(e)}, status=400)


