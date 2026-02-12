import json
from decimal import Decimal

from django.contrib.auth.mixins import LoginRequiredMixin
from core.mixins import ModulePermissionMixin
from django.views.generic import (
    TemplateView,
    ListView,
    CreateView,
    UpdateView,
    DetailView,
    View,
)
from django.urls import reverse_lazy
from django.contrib import messages
from django.utils import timezone
from django.db.models import Q
from django.shortcuts import render, redirect, get_object_or_404
from django.db import transaction
from django.core.exceptions import ValidationError

from .models import (
    BillOfMaterial,
    ProductionOrder,
    ProductionOrderOrigin,
    ProductionOrderStatus,
    ProductionOperationStatus,
    ProductionOperation,
    ProductionPlan,
    ProductionPlanStatus,
    ProductionPlanRawLot,
    WorkCenter,
    ProductRoute,
)

from .services import (
    consume_raw_materials_for_operation,
    close_production_order,
    generate_production_plan_code,
    log_operation_status_change,
    link_wip_lots_on_done,
    generate_material_transfers,
    confirm_material_transfer,
    estimate_production_duration,
    schedule_production_order,
    get_operation_phase,
    populate_component_details_from_transfers,
    calculate_theoretical_yield,
)
from django.contrib.auth import get_user_model

from .forms import (
    BillOfMaterialForm,
    BillOfMaterialLineFormSet,
    ProductionOrderForm,
    ProductionOperationForm,
    ProductionPlanForm,
    WorkCenterForm,
    ProductRouteForm,
    ProductRouteStepFormSet,
    MaterialTransferConfirmForm,
    OperationComponentDetailFormSet,
)

from django.http import JsonResponse
from django.db.models import Sum, Subquery, OuterRef, F
from django.db.models.functions import Coalesce

from inventory.models import Product, ProductType, Lot, LotStatus, LotBalance


class ProductionDashboardView(LoginRequiredMixin, ModulePermissionMixin, View):
    permission_required = "production.view_productionorder"

    def get(self, request, *args, **kwargs):
        return redirect("production:orders_list")


# ---------------------------------------------------------
# BOM
# ---------------------------------------------------------

class BillOfMaterialListView(LoginRequiredMixin, ModulePermissionMixin, ListView):
    permission_required = "production.view_billofmaterial"
    model = BillOfMaterial
    template_name = "production/bom_list.html"
    context_object_name = "page"
    paginate_by = 20

    def get_queryset(self):
        qs = (
            BillOfMaterial.objects
            .select_related("product_finished")
            .order_by("product_finished__name", "revision")
        )
        q = self.request.GET.get("q", "").strip()
        if q:
            qs = qs.filter(
                Q(product_finished__code__icontains=q)
                | Q(product_finished__name__icontains=q)
                | Q(description__icontains=q)
            )
        return qs


class BillOfMaterialCreateView(LoginRequiredMixin, ModulePermissionMixin, View):
    permission_required = "production.add_billofmaterial"
    template_name = "production/bom_form.html"
    success_url = reverse_lazy("production:bom_list")

    def _build_components_json(self):
        products = (
            Product.objects
            .filter(product_type__in=[ProductType.RAW, ProductType.SEMI], is_active=True)
            .select_related("base_unit")
            .order_by("name")
        )
        data = {}
        for p in products:
            data[str(p.id)] = {
                "unit_code": getattr(p.base_unit, "code", ""),
                "unit_name": getattr(p.base_unit, "name", ""),
            }
        return json.dumps(data, ensure_ascii=False)

    def get(self, request):
        form = BillOfMaterialForm()
        formset = BillOfMaterialLineFormSet()
        return render(
            request,
            self.template_name,
            {"form": form, "formset": formset, "components_json": self._build_components_json()},
        )

    def post(self, request):
        form = BillOfMaterialForm(request.POST)
        formset = BillOfMaterialLineFormSet(request.POST)

        if not (form.is_valid() and formset.is_valid()):
            messages.error(request, "Revisa los errores del formulario.")
            return render(
                request,
                self.template_name,
                {"form": form, "formset": formset, "components_json": self._build_components_json()},
            )

        with transaction.atomic():
            bom = form.save(commit=False)
            bom.created_by = request.user
            bom.updated_by = request.user
            bom.save()
            formset.instance = bom
            formset.save()

        messages.success(request, "Plano de fabricación creado correctamente.")
        return redirect(self.success_url)


class BillOfMaterialUpdateView(LoginRequiredMixin, ModulePermissionMixin, View):
    """Vista para editar un BOM existente - Control de cambio de diseño."""
    permission_required = "production.change_billofmaterial"
    template_name = "production/bom_form.html"
    success_url = reverse_lazy("production:bom_list")

    def _build_components_json(self):
        products = (
            Product.objects
            .filter(product_type__in=[ProductType.RAW, ProductType.SEMI], is_active=True)
            .select_related("base_unit")
            .order_by("name")
        )
        data = {}
        for p in products:
            data[str(p.id)] = {
                "unit_code": getattr(p.base_unit, "code", ""),
                "unit_name": getattr(p.base_unit, "name", ""),
            }
        return json.dumps(data, ensure_ascii=False)

    def _get_bom(self, pk):
        return get_object_or_404(BillOfMaterial, pk=pk)

    def get(self, request, pk):
        bom = self._get_bom(pk)
        form = BillOfMaterialForm(instance=bom)
        formset = BillOfMaterialLineFormSet(instance=bom)
        return render(
            request,
            self.template_name,
            {
                "form": form,
                "formset": formset,
                "object": bom,
                "components_json": self._build_components_json(),
            },
        )

    def post(self, request, pk):
        bom = self._get_bom(pk)
        form = BillOfMaterialForm(request.POST, instance=bom)
        formset = BillOfMaterialLineFormSet(request.POST, instance=bom)

        if not (form.is_valid() and formset.is_valid()):
            messages.error(request, "Revisa los errores del formulario.")
            return render(
                request,
                self.template_name,
                {
                    "form": form,
                    "formset": formset,
                    "object": bom,
                    "components_json": self._build_components_json(),
                },
            )

        with transaction.atomic():
            bom = form.save(commit=False)
            bom.updated_by = request.user
            bom.save()
            formset.save()

        messages.success(request, "Plano de fabricación actualizado correctamente.")
        return redirect(self.success_url)


# ---------------------------------------------------------
# AJAX: Cálculo FEFO de materias primas para plan
# ---------------------------------------------------------

class PlanCalculateMaterialsView(LoginRequiredMixin, ModulePermissionMixin, View):
    permission_required = "production.view_productionplan"
    """
    Endpoint AJAX que calcula las materias primas requeridas
    para un plan de producción usando FEFO.
    """

    def get(self, request):
        product_id = request.GET.get("product_id")
        quantity = request.GET.get("quantity")

        if not product_id or not quantity:
            return JsonResponse({"error": "Faltan parámetros (product_id, quantity)."}, status=400)

        try:
            quantity = Decimal(quantity)
            if quantity <= 0:
                raise ValueError
        except (ValueError, Exception):
            return JsonResponse({"error": "La cantidad debe ser un número mayor a cero."}, status=400)

        # Buscar producto
        try:
            product = Product.objects.get(pk=product_id, product_type=ProductType.FG, is_active=True)
        except Product.DoesNotExist:
            return JsonResponse({"error": "Producto terminado no encontrado."}, status=404)

        # Buscar BOM activo
        bom = (
            BillOfMaterial.objects
            .filter(product_finished=product, is_active=True)
            .prefetch_related("lines__component__base_unit")
            .order_by("-revision")
            .first()
        )
        if not bom:
            return JsonResponse({
                "error": f"No hay plano de fabricación (BOM) activo para {product.name}.",
            }, status=404)

        materials = []
        errors = []

        for line in bom.lines.select_related("component__base_unit").order_by("sequence"):
            component = line.component
            unit = component.base_unit
            required_qty = (line.quantity * quantity * (1 + line.scrap_rate)).quantize(Decimal("0.0001"))

            # Subconsulta: cantidad reservada por planes activos
            exclude_plan_id = request.GET.get("exclude_plan_id")
            reserved_qs = (
                ProductionPlanRawLot.objects
                .filter(lot=OuterRef("pk"), plan__status=ProductionPlanStatus.ACTIVE)
            )
            if exclude_plan_id:
                reserved_qs = reserved_qs.exclude(plan_id=int(exclude_plan_id))
            reserved_qs = reserved_qs.values("lot").annotate(total=Sum("quantity_planned")).values("total")

            # FEFO: lotes aprobados del componente, descontando reservas
            approved_lots = (
                Lot.objects
                .filter(product=component, status=LotStatus.APPROVED)
                .annotate(qty_available=Sum("balances__qty"))
                .annotate(qty_reserved=Coalesce(Subquery(reserved_qs), Decimal("0")))
                .annotate(qty_effective=F("qty_available") - F("qty_reserved"))
                .filter(qty_effective__gt=0)
                .order_by("expiry_date", "created_at")
            )

            # Seleccionar el primer lote con suficiente cantidad efectiva
            selected_lot = None
            for lot in approved_lots:
                if lot.qty_effective >= required_qty:
                    selected_lot = lot
                    break

            if selected_lot:
                materials.append({
                    "component_id": component.id,
                    "component_code": component.code,
                    "component_name": component.name,
                    "lot_id": selected_lot.id,
                    "lot_number": selected_lot.lot_number,
                    "qty_required": str(required_qty),
                    "qty_available": str(selected_lot.qty_effective.quantize(Decimal("0.0001"))),
                    "expiry_date": selected_lot.expiry_date.strftime("%d/%m/%Y") if selected_lot.expiry_date else "Sin fecha",
                    "unit_code": unit.code if unit else "",
                    "sufficient": True,
                })
            else:
                # Calcular total disponible en todos los lotes
                total_available = sum(l.qty_effective for l in approved_lots)
                materials.append({
                    "component_id": component.id,
                    "component_code": component.code,
                    "component_name": component.name,
                    "lot_id": None,
                    "lot_internal": "—",
                    "lot_supplier": "—",
                    "qty_required": str(required_qty),
                    "qty_available": str(total_available.quantize(Decimal("0.0001")) if total_available else "0"),
                    "expiry_date": "—",
                    "unit_code": unit.code if unit else "",
                    "sufficient": False,
                })
                errors.append(
                    f"{component.code} - {component.name}: se requieren {required_qty} {unit.code} "
                    f"pero no hay un lote individual con suficiente stock (total disponible: {total_available})."
                )

        return JsonResponse({
            "bom_revision": bom.revision,
            "materials": materials,
            "errors": errors,
        })


# ---------------------------------------------------------
# Órdenes de Producción
# ---------------------------------------------------------

class ProductionOrderListView(LoginRequiredMixin, ModulePermissionMixin, ListView):
    permission_required = "production.view_productionorder"
    model = ProductionOrder
    template_name = "production/orders_list.html"
    context_object_name = "page"
    paginate_by = 20

    def get_queryset(self):
        qs = (
            ProductionOrder.objects
            .select_related("product", "route", "bom", "plan")
            .order_by("-id")
        )

        q = self.request.GET.get("q")
        status = self.request.GET.get("status")

        if q:
            qs = qs.filter(
                Q(code__icontains=q)
                | Q(product__name__icontains=q)
                | Q(product__code__icontains=q)
                | Q(plan__code__icontains=q)
            )

        if status:
            qs = qs.filter(status=status)

        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["status_choices"] = ProductionOrderStatus.choices
        return ctx


class ProductionOrderCreatePlanningView(LoginRequiredMixin, ModulePermissionMixin, CreateView):
    permission_required = "production.add_productionorder"
    model = ProductionOrder
    form_class = ProductionOrderForm
    template_name = "production/orders_form.html"
    success_url = reverse_lazy("production:orders_list")

    def form_valid(self, form):
        op = form.save(commit=False)

        if hasattr(op, "created_by"):
            op.created_by = self.request.user
        if hasattr(op, "updated_by"):
            op.updated_by = self.request.user

        op.origin_type = ProductionOrderOrigin.PLANNING
        op.origin_reference = "Planificación manual"

        op.save()

        messages.success(
            self.request,
            f"Orden de producción {op.code} creada correctamente."
        )
        return redirect(self.success_url)


# ---------------------------------------------------------
# Operaciones de Producción (motor paso a paso)
# ---------------------------------------------------------

class ProductionOperationListView(LoginRequiredMixin, ModulePermissionMixin, ListView):
    permission_required = "production.view_productionoperation"
    model = ProductionOperation
    template_name = "production/operations_list.html"
    context_object_name = "operations"
    paginate_by = 20

    def get_queryset(self):
        qs = (
            ProductionOperation.objects
            .select_related(
                "order",
                "step",
                "step__work_center",
            )
            .order_by("order__code", "sequence")
        )

        q = self.request.GET.get("q", "").strip()
        status = self.request.GET.get("status")
        work_center_id = self.request.GET.get("work_center")

        if q:
            qs = qs.filter(
                Q(order__code__icontains=q)
                | Q(order__product__name__icontains=q)
                | Q(order__product__code__icontains=q)
                | Q(step__name__icontains=q)
            )

        if status:
            qs = qs.filter(status=status)

        if work_center_id:
            qs = qs.filter(step__work_center_id=work_center_id)

        return qs

    def get_context_data(self, **kwargs):
        from .models import WorkCenter

        ctx = super().get_context_data(**kwargs)
        ctx["status_choices"] = ProductionOperationStatus.choices
        ctx["work_centers"] = WorkCenter.objects.filter(is_active=True).order_by("code")
        ctx["current_status"] = self.request.GET.get("status") or ""
        ctx["current_wc"] = self.request.GET.get("work_center") or ""
        return ctx


class ProductionOperationUpdateView(LoginRequiredMixin, ModulePermissionMixin, UpdateView):
    permission_required = "production.change_productionoperation"
    model = ProductionOperation
    form_class = ProductionOperationForm
    template_name = "production/operation_form.html"

    def get_form(self, form_class=None):
        form = super().get_form(form_class)
        op: ProductionOperation = self.object

        # Pre-seleccionar operario actual si no tiene uno asignado
        if not op.operator:
            form.initial["operator"] = self.request.user.pk

        # Pre-cargar fecha inicio: 1s después de la última transferencia confirmada
        if not op.started_at:
            from .models import MaterialTransfer, MaterialTransferStatus
            last_transfer = (
                MaterialTransfer.objects
                .filter(order=op.order)
                .exclude(status=MaterialTransferStatus.PENDING)
                .order_by("-confirmed_at")
                .first()
            )
            if last_transfer and last_transfer.confirmed_at:
                from datetime import timedelta
                start = last_transfer.confirmed_at + timedelta(seconds=1)
                form.initial["started_at"] = start.strftime("%Y-%m-%dT%H:%M")

        # Pre-cargar fecha fin: hora actual
        if not op.finished_at:
            form.initial["finished_at"] = timezone.now().strftime("%Y-%m-%dT%H:%M")

        return form

    def form_valid(self, form):
        old_op = self.get_object()
        old_status = old_op.status
        was_done_before = (old_status == ProductionOperationStatus.DONE)

        op: ProductionOperation = form.save(commit=False)
        order = op.order
        new_status = op.status

        # --- Bloqueo Paso 0: transferencias de MP deben estar confirmadas ---
        if op.status in (ProductionOperationStatus.IN_PROGRESS, ProductionOperationStatus.DONE):
            is_first_op = not order.operations.filter(sequence__lt=op.sequence).exists()
            if is_first_op:
                from .models import MaterialTransfer, MaterialTransferStatus
                pending = MaterialTransfer.objects.filter(
                    order=order, status=MaterialTransferStatus.PENDING
                ).exists()
                if pending:
                    messages.error(
                        self.request,
                        "No se puede iniciar la producción: hay transferencias de materia prima pendientes. "
                        "Confirma todas las transferencias antes de avanzar."
                    )
                    return redirect(self.get_success_url())

        # --- Bloqueo QA: si el paso anterior requiere QA y está en HOLD, no avanzar ---
        if op.status in (ProductionOperationStatus.IN_PROGRESS, ProductionOperationStatus.DONE):
            prev_op = (
                order.operations
                .filter(sequence__lt=op.sequence)
                .order_by("-sequence", "-id")
                .select_related("step")
                .first()
            )
            if prev_op and prev_op.step.requires_qa and prev_op.status != ProductionOperationStatus.DONE:
                messages.error(
                    self.request,
                    f"El paso anterior «{prev_op.step.name}» requiere aprobación QA antes de avanzar."
                )
                return redirect(self.get_success_url())

        # --- Manejo de tiempos ---
        if op.status == ProductionOperationStatus.IN_PROGRESS and op.started_at is None:
            op.started_at = timezone.now()

        if op.status == ProductionOperationStatus.DONE and op.finished_at is None:
            op.finished_at = timezone.now()

        # --- Asignar operador automáticamente si no se seleccionó ---
        if not op.operator:
            op.operator = self.request.user

        # --- Cambiar OP a IN_PROGRESS si estaba RELEASED ---
        if order.status == ProductionOrderStatus.RELEASED and op.status == ProductionOperationStatus.IN_PROGRESS:
            order.status = ProductionOrderStatus.IN_PROGRESS
            order.updated_by = self.request.user
            order.save(update_fields=["status", "updated_by", "updated_at"])

        op.updated_by = self.request.user

        # --- Guardar detalles de componentes (pre/at conversión) ---
        phase = get_operation_phase(op)
        if phase in ("pre_conversion", "at_conversion"):
            component_formset = OperationComponentDetailFormSet(
                self.request.POST, instance=op, prefix="components"
            )
            if component_formset.is_valid():
                component_formset.save()
                # En pre-conversión: calcular quantity_output agregado
                if phase == "pre_conversion":
                    from django.db.models import Sum as DjSum
                    agg = op.component_details.aggregate(total=DjSum("quantity_output"))["total"]
                    if agg and agg > 0:
                        op.quantity_output = agg

        op.save()

        # --- Log de auditoría ISO 13485 ---
        if old_status != new_status:
            log_operation_status_change(
                operation=op,
                from_status=old_status,
                to_status=new_status,
                user=self.request.user,
                notes=op.notes,
            )

        # --- Consumo de MP ---
        if op.status == ProductionOperationStatus.DONE and not was_done_before:
            try:
                consume_raw_materials_for_operation(
                    operation=op,
                    user=self.request.user,
                )
                messages.success(
                    self.request,
                    "Se consumió la materia prima según el BOM utilizando FEFO."
                )
            except ValidationError as e:
                messages.error(
                    self.request,
                    f"La operación se guardó, pero hubo un problema al consumir MP: {e}"
                )
            except Exception as e:
                messages.error(
                    self.request,
                    f"Ocurrió un error inesperado al consumir MP: {e}"
                )

        # --- WIP lot tracking ---
        if op.status == ProductionOperationStatus.DONE and not was_done_before:
            try:
                link_wip_lots_on_done(operation=op, user=self.request.user)
            except Exception as e:
                messages.warning(
                    self.request,
                    f"No se pudo crear lote WIP: {e}"
                )

        # --- Si el paso requiere QA y se marcó DONE, ponerlo en HOLD automáticamente ---
        if (
            op.status == ProductionOperationStatus.DONE
            and not was_done_before
            and op.step.requires_qa
        ):
            op.status = ProductionOperationStatus.HOLD
            op.save(update_fields=["status"])
            log_operation_status_change(
                operation=op,
                from_status=ProductionOperationStatus.DONE,
                to_status=ProductionOperationStatus.HOLD,
                user=self.request.user,
                notes="Auto-HOLD: paso requiere QA",
            )
            messages.info(
                self.request,
                f"El paso «{op.step.name}» requiere aprobación QA. Se puso en espera."
            )
        else:
            messages.success(self.request, "Operación de producción actualizada correctamente.")

        # --- ¿Es la última operación y está DONE? ---
        last_op = (
            order.operations
            .order_by("-sequence", "-id")
            .first()
        )

        if last_op and last_op.pk == op.pk and op.status == ProductionOperationStatus.DONE:
            try:
                close_production_order(order=order, user=self.request.user)
                messages.success(
                    self.request,
                    f"La orden {order.code} ha sido cerrada y se generó el lote de producto terminado "
                    f"{order.finished_lot.lot_number if order.finished_lot else ''}."
                )
            except ValidationError as e:
                messages.warning(
                    self.request,
                    f"La operación se guardó, pero la orden no se pudo cerrar automáticamente: {e}"
                )

        return redirect(self.get_success_url())

    def get_success_url(self):
        # Volver al panel de ejecución de la OP
        return reverse_lazy("production:orders_execute", kwargs={"pk": self.object.order.pk})

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        op: ProductionOperation = self.object
        ctx["operation"] = op
        ctx["order"] = op.order

        # Fase de la operación (pre_conversion, at_conversion, post_conversion)
        phase = get_operation_phase(op)
        ctx["operation_phase"] = phase

        if phase in ("pre_conversion", "at_conversion"):
            # Auto-poblar detalles si no existen (primera vez)
            if not op.component_details.exists():
                populate_component_details_from_transfers(op, self.request.user)

            # Formset de componentes
            if self.request.method == "POST":
                ctx["component_formset"] = OperationComponentDetailFormSet(
                    self.request.POST, instance=op, prefix="components"
                )
            else:
                ctx["component_formset"] = OperationComponentDetailFormSet(
                    instance=op, prefix="components"
                )

            # Rendimiento teórico en punto de conversión
            if phase == "at_conversion":
                ctx["theoretical_yield"] = calculate_theoretical_yield(op)

        return ctx


class ProductionOrderDetailView(LoginRequiredMixin, ModulePermissionMixin, DetailView):
    permission_required = "production.view_productionorder"
    model = ProductionOrder
    template_name = "production/order_detail.html"
    context_object_name = "order"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        order: ProductionOrder = self.object

        ops = (
            order.operations
            .select_related("step", "step__work_center", "input_lot", "output_lot")
            .order_by("sequence", "id")
        )

        ctx["operations"] = ops
        return ctx


class ProductionOrderReleaseView(LoginRequiredMixin, ModulePermissionMixin, View):
    permission_required = "production.change_productionorder"
    """
    Acción explícita: liberar una OP (DRAFT → RELEASED).
    Genera las operaciones a partir de la ruta y cambia estado.
    """

    def post(self, request, pk):
        order = get_object_or_404(ProductionOrder, pk=pk)

        if order.status != ProductionOrderStatus.DRAFT:
            messages.error(request, "Solo se pueden liberar órdenes en estado Borrador.")
            return redirect("production:orders_list")

        if not order.route:
            messages.error(request, "La orden no tiene ruta de producción asignada.")
            return redirect("production:orders_list")

        from .models import ProductRouteStep

        steps = (
            ProductRouteStep.objects
            .filter(route=order.route, is_active=True)
            .order_by("sequence", "id")
        )

        if not steps.exists():
            messages.error(request, "La ruta seleccionada no tiene pasos activos.")
            return redirect("production:orders_list")

        with transaction.atomic():
            for step in steps:
                ProductionOperation.objects.create(
                    order=order,
                    step=step,
                    sequence=step.sequence,
                    status=ProductionOperationStatus.PENDING,
                    created_by=request.user,
                    updated_by=request.user,
                )

            order.status = ProductionOrderStatus.RELEASED
            order.updated_by = request.user
            order.save(update_fields=["status", "updated_by", "updated_at"])

            # Planificar fechas de cada operación
            schedule_production_order(order=order)

            # Generar transferencias de MP automáticamente
            transfers = generate_material_transfers(order=order, user=request.user)

        tf_msg = f" Se generaron {len(transfers)} transferencias de MP." if transfers else ""
        messages.success(request, f"Orden {order.code} liberada. Se generaron {steps.count()} operaciones.{tf_msg}")
        return redirect("production:orders_execute", pk=order.pk)


class ProductionOrderExecutionView(LoginRequiredMixin, ModulePermissionMixin, DetailView):
    permission_required = "production.change_productionorder"
    """
    Motor de ejecución visual: muestra las operaciones en fila,
    resalta la actual y solo deja avanzar una por vez.
    La OP debe estar previamente liberada (RELEASED o IN_PROGRESS).
    """
    model = ProductionOrder
    template_name = "production/order_execute.html"
    context_object_name = "order"

    def get_object(self, queryset=None):
        order: ProductionOrder = super().get_object(queryset)

        if order.status == ProductionOrderStatus.DRAFT:
            messages.warning(
                self.request,
                "Esta orden está en Borrador. Debes liberarla antes de ejecutar."
            )

        return order

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        order: ProductionOrder = self.object

        from django.db.models import Prefetch
        from .models import OperationComponentDetail

        ops = (
            order.operations
            .select_related(
                "step", "step__work_center",
                "input_lot", "output_lot",
                "operator",
            )
            .prefetch_related(
                Prefetch(
                    "component_details",
                    queryset=OperationComponentDetail.objects.select_related(
                        "component", "component__base_unit", "bom_line"
                    ),
                )
            )
            .order_by("sequence", "id")
        )

        # Primer paso no completado → operación "actual"
        current_op = None
        for o in ops:
            if o.status not in (ProductionOperationStatus.DONE,):
                current_op = o
                break

        # Anotar fase en cada operación para el template
        for o in ops:
            o.phase = get_operation_phase(o)

        # Audit log: todos los cambios de estado de esta OP
        from .models import OperationStatusLog
        status_logs = (
            OperationStatusLog.objects
            .filter(operation__order=order)
            .select_related("operation", "changed_by")
            .order_by("-changed_at")[:50]
        )

        # Transferencias de MP
        from .models import MaterialTransfer, MaterialTransferStatus
        transfers = (
            MaterialTransfer.objects
            .filter(order=order)
            .select_related("component", "component__base_unit", "lot", "from_warehouse", "to_warehouse")
            .order_by("component__code")
        )
        total_transfers = transfers.count()
        pending_transfers_count = sum(
            1 for t in transfers if t.status == MaterialTransferStatus.PENDING
        )
        all_transfers_confirmed = total_transfers > 0 and pending_transfers_count == 0

        ctx["operations"] = ops
        ctx["current_operation"] = current_op
        ctx["status_logs"] = status_logs
        ctx["transfers"] = transfers
        ctx["total_transfers"] = total_transfers
        ctx["pending_transfers_count"] = pending_transfers_count
        ctx["all_transfers_confirmed"] = all_transfers_confirmed
        return ctx


# ---------------------------------------------------------
# Planes de Producción
# ---------------------------------------------------------

class ProductionPlanListView(LoginRequiredMixin, ModulePermissionMixin, ListView):
    permission_required = "production.view_productionplan"
    model = ProductionPlan
    template_name = "production/plan_list.html"
    context_object_name = "page"
    paginate_by = 20

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["plan_status_choices"] = ProductionPlanStatus.choices
        return ctx

    def get_queryset(self):
        qs = (
            ProductionPlan.objects
            .select_related("product")
            .order_by("-manufacturing_date", "product__name", "lot_code")
        )

        q = self.request.GET.get("q")
        status = self.request.GET.get("status")

        if q:
            qs = qs.filter(
                Q(code__icontains=q) |
                Q(product__code__icontains=q) |
                Q(product__name__icontains=q) |
                Q(lot_code__icontains=q)
            )

        if status:
            qs = qs.filter(status=status)

        return qs


class ProductionPlanCreateView(LoginRequiredMixin, ModulePermissionMixin, CreateView):
    permission_required = "production.add_productionplan"
    model = ProductionPlan
    form_class = ProductionPlanForm
    template_name = "production/plan_form.html"
    success_url = reverse_lazy("production:plans_list")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        products = Product.objects.filter(
            product_type=ProductType.FG,
            is_active=True,
        ).values("id", "lot_prefix")  # 👈 cambia "lot_prefix" si tu campo se llama distinto

        ctx["lot_prefix_map"] = {
            str(p["id"]): p["lot_prefix"] or "" for p in products
        }
        return ctx

    def _save_raw_lots(self, plan, request):
        """Guarda los lotes de MP seleccionados por FEFO como ProductionPlanRawLot."""
        count = int(request.POST.get("raw_lots_count", 0))
        # Limpiar raw_lots anteriores
        plan.raw_lots.all().delete()
        for i in range(count):
            component_id = request.POST.get(f"raw_lot_component_{i}")
            lot_id = request.POST.get(f"raw_lot_id_{i}")
            qty = request.POST.get(f"raw_lot_qty_{i}")
            if component_id and lot_id:
                ProductionPlanRawLot.objects.create(
                    plan=plan,
                    component_id=int(component_id),
                    lot_id=int(lot_id),
                    quantity_planned=Decimal(qty) if qty else None,
                )

    def form_valid(self, form):
        plan: ProductionPlan = form.save(commit=False)

        if not plan.manufacturing_date:
            plan.manufacturing_date = timezone.localdate()

        if not plan.code:
            plan.code = generate_production_plan_code(plan.manufacturing_date)

        plan.created_by = self.request.user
        plan.updated_by = self.request.user
        plan.save()

        self._save_raw_lots(plan, self.request)

        messages.success(self.request, "Plan de producción creado correctamente.")
        return redirect(self.success_url)


class ProductionPlanUpdateView(LoginRequiredMixin, ModulePermissionMixin, UpdateView):
    permission_required = "production.change_productionplan"
    model = ProductionPlan
    form_class = ProductionPlanForm
    template_name = "production/plan_form.html"
    success_url = reverse_lazy("production:plans_list")

    def dispatch(self, request, *args, **kwargs):
        plan = self.get_object()
        if plan.status == ProductionPlanStatus.CANCELED:
            messages.error(request, "No se puede editar un plan anulado.")
            return redirect("production:plans_list")
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        products = Product.objects.filter(
            product_type=ProductType.FG,
            is_active=True,
        ).values("id", "lot_prefix")

        ctx["lot_prefix_map"] = {
            str(p["id"]): p["lot_prefix"] or "" for p in products
        }
        ctx["plan_id"] = self.object.pk
        return ctx

    def _save_raw_lots(self, plan, request):
        """Guarda los lotes de MP seleccionados por FEFO como ProductionPlanRawLot."""
        count = int(request.POST.get("raw_lots_count", 0))
        plan.raw_lots.all().delete()
        for i in range(count):
            component_id = request.POST.get(f"raw_lot_component_{i}")
            lot_id = request.POST.get(f"raw_lot_id_{i}")
            qty = request.POST.get(f"raw_lot_qty_{i}")
            if component_id and lot_id:
                ProductionPlanRawLot.objects.create(
                    plan=plan,
                    component_id=int(component_id),
                    lot_id=int(lot_id),
                    quantity_planned=Decimal(qty) if qty else None,
                )

    def form_valid(self, form):
        plan: ProductionPlan = form.save(commit=False)
        plan.updated_by = self.request.user
        plan.save()

        self._save_raw_lots(plan, self.request)

        messages.success(self.request, "Plan de producción actualizado correctamente.")
        return redirect(self.success_url)


class ProductionPlanCancelView(LoginRequiredMixin, ModulePermissionMixin, View):
    permission_required = "production.change_productionplan"
    """Anula un plan de producción y libera las reservas de MP."""

    def post(self, request, pk):
        plan = get_object_or_404(ProductionPlan, pk=pk)

        if plan.orders.exists():
            messages.error(request, "No se puede anular: ya tiene órdenes de producción.")
            return redirect("production:plans_list")

        if plan.status != ProductionPlanStatus.ACTIVE:
            messages.error(request, "Solo se pueden anular planes activos.")
            return redirect("production:plans_list")

        plan.raw_lots.all().delete()  # libera reservas
        plan.status = ProductionPlanStatus.CANCELED
        plan.updated_by = request.user
        plan.save(update_fields=["status", "updated_by", "updated_at"])

        messages.success(request, f"Plan {plan.code} anulado. Materias primas liberadas.")
        return redirect("production:plans_list")


class ProductionOrderCreateFromPlanView(LoginRequiredMixin, ModulePermissionMixin, CreateView):
    permission_required = "production.add_productionorder"
    """
    Crea una OP a partir de un Plan de Producción:
    - Amarra plan → order.plan
    - Usa quantity_pending
    - Valida que no te pases del plan
    """
    model = ProductionOrder
    form_class = ProductionOrderForm
    template_name = "production/orders_form.html"
    success_url = reverse_lazy("production:orders_list")

    def dispatch(self, request, *args, **kwargs):
        self.plan = get_object_or_404(ProductionPlan, pk=self.kwargs["plan_id"])
        return super().dispatch(request, *args, **kwargs)

    def get_initial(self):
        initial = super().get_initial()
        initial["product"] = self.plan.product
        initial["quantity_planned"] = self.plan.quantity_pending
        if self.plan.manufacturing_date:
            initial["start_date"] = self.plan.manufacturing_date.strftime("%Y-%m-%d")

        # BOM: revisión más alta activa para el producto del plan
        bom = (
            BillOfMaterial.objects
            .filter(product_finished=self.plan.product, is_active=True)
            .order_by("-revision")
            .first()
        )
        if bom:
            initial["bom"] = bom

        return initial

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["plan"] = self.plan
        return ctx

    def form_valid(self, form):
        op: ProductionOrder = form.save(commit=False)

        op.plan = self.plan
        op.origin_type = ProductionOrderOrigin.PLANNING
        op.origin_reference = self.plan.code
        op.start_date = self.plan.manufacturing_date

        qty = op.quantity_planned or Decimal("0")
        if qty <= 0:
            form.add_error("quantity_planned", "La cantidad debe ser mayor a cero.")
            return self.form_invalid(form)

        if qty > self.plan.quantity_pending:
            form.add_error(
                "quantity_planned",
                f"No puedes planificar {qty} unidades. "
                f"Pendientes en el plan: {self.plan.quantity_pending}."
            )
            return self.form_invalid(form)

        if hasattr(op, "created_by"):
            op.created_by = self.request.user
        if hasattr(op, "updated_by"):
            op.updated_by = self.request.user

        op.save()

        # Si luego de crear esta OP el plan queda en cero, lo marcamos COMPLETED
        if self.plan.quantity_pending <= 0:
            self.plan.status = ProductionPlanStatus.COMPLETED
            self.plan.updated_by = self.request.user
            self.plan.save(update_fields=["status", "updated_by", "updated_at"])

        messages.success(
            self.request,
            f"Orden de producción {op.code} creada desde el plan {self.plan.code}."
        )
        return redirect(self.success_url)


# ---------------------------------------------------------
# Estaciones de trabajo (WorkCenter)
# ---------------------------------------------------------

class WorkCenterListView(LoginRequiredMixin, ModulePermissionMixin, ListView):
    permission_required = "production.view_workcenter"
    model = WorkCenter
    template_name = "production/workcenter_list.html"
    context_object_name = "page"
    paginate_by = 20

    def get_queryset(self):
        qs = WorkCenter.objects.order_by("code")
        q = self.request.GET.get("q", "").strip()
        if q:
            qs = qs.filter(Q(code__icontains=q) | Q(name__icontains=q))
        return qs


class WorkCenterCreateView(LoginRequiredMixin, ModulePermissionMixin, CreateView):
    permission_required = "production.add_workcenter"
    model = WorkCenter
    form_class = WorkCenterForm
    template_name = "production/workcenter_form.html"
    success_url = reverse_lazy("production:workcenters_list")

    def form_valid(self, form):
        obj = form.save(commit=False)
        obj.created_by = self.request.user
        obj.updated_by = self.request.user
        obj.save()
        messages.success(self.request, f"Estación de trabajo «{obj.name}» creada.")
        return redirect(self.success_url)


class WorkCenterUpdateView(LoginRequiredMixin, ModulePermissionMixin, UpdateView):
    permission_required = "production.change_workcenter"
    model = WorkCenter
    form_class = WorkCenterForm
    template_name = "production/workcenter_form.html"
    success_url = reverse_lazy("production:workcenters_list")

    def form_valid(self, form):
        obj = form.save(commit=False)
        obj.updated_by = self.request.user
        obj.save()
        messages.success(self.request, f"Estación de trabajo «{obj.name}» actualizada.")
        return redirect(self.success_url)


# ---------------------------------------------------------
# Rutas de producción (ProductRoute + Steps)
# ---------------------------------------------------------

class ProductRouteListView(LoginRequiredMixin, ModulePermissionMixin, ListView):
    permission_required = "production.view_productroute"
    model = ProductRoute
    template_name = "production/route_list.html"
    context_object_name = "page"
    paginate_by = 20

    def get_queryset(self):
        qs = ProductRoute.objects.select_related("product").order_by("product__name", "name")
        q = self.request.GET.get("q", "").strip()
        if q:
            qs = qs.filter(
                Q(name__icontains=q) | Q(product__code__icontains=q) | Q(product__name__icontains=q)
            )
        return qs


class ProductRouteCreateView(LoginRequiredMixin, ModulePermissionMixin, View):
    permission_required = "production.add_productroute"
    template_name = "production/route_form.html"
    success_url = reverse_lazy("production:routes_list")

    def get(self, request):
        form = ProductRouteForm()
        formset = ProductRouteStepFormSet()
        return render(request, self.template_name, {"form": form, "formset": formset})

    def post(self, request):
        form = ProductRouteForm(request.POST)
        formset = ProductRouteStepFormSet(request.POST)
        if form.is_valid() and formset.is_valid():
            with transaction.atomic():
                route = form.save(commit=False)
                route.created_by = request.user
                route.updated_by = request.user
                route.save()
                formset.instance = route
                formset.save()
            messages.success(request, f"Ruta «{route.name}» creada.")
            return redirect(self.success_url)
        return render(request, self.template_name, {"form": form, "formset": formset})


class ProductRouteUpdateView(LoginRequiredMixin, ModulePermissionMixin, View):
    permission_required = "production.change_productroute"
    template_name = "production/route_form.html"
    success_url = reverse_lazy("production:routes_list")

    def _get_route(self, pk):
        return get_object_or_404(ProductRoute, pk=pk)

    def get(self, request, pk):
        route = self._get_route(pk)
        form = ProductRouteForm(instance=route)
        formset = ProductRouteStepFormSet(instance=route)
        return render(request, self.template_name, {"form": form, "formset": formset, "object": route})

    def post(self, request, pk):
        route = self._get_route(pk)
        form = ProductRouteForm(request.POST, instance=route)
        formset = ProductRouteStepFormSet(request.POST, instance=route)
        if form.is_valid() and formset.is_valid():
            with transaction.atomic():
                route = form.save(commit=False)
                route.updated_by = request.user
                route.save()
                formset.save()
            messages.success(request, f"Ruta «{route.name}» actualizada.")
            return redirect(self.success_url)
        return render(request, self.template_name, {"form": form, "formset": formset, "object": route})


# ---------------------------------------------------------
# Transferencias de material (MP → Estación de producción)
# ---------------------------------------------------------

class MaterialTransferListView(LoginRequiredMixin, ModulePermissionMixin, DetailView):
    permission_required = "production.view_productionorder"
    model = ProductionOrder
    template_name = "production/order_transfers.html"
    context_object_name = "order"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        from .models import MaterialTransfer
        ctx["transfers"] = (
            MaterialTransfer.objects
            .filter(order=self.object)
            .select_related("component", "lot", "from_warehouse", "to_warehouse", "confirmed_by")
            .order_by("component__code")
        )
        ctx["confirm_form"] = MaterialTransferConfirmForm()
        return ctx


class MaterialTransferConfirmView(LoginRequiredMixin, ModulePermissionMixin, View):
    permission_required = "production.change_productionorder"

    def post(self, request, pk):
        from .models import MaterialTransfer
        transfer = get_object_or_404(MaterialTransfer, pk=pk)
        form = MaterialTransferConfirmForm(request.POST)

        if not form.is_valid():
            messages.error(request, "Datos inválidos. Revisa la cantidad.")
            return redirect("production:order_transfers", pk=transfer.order.pk)

        try:
            confirm_material_transfer(
                transfer=transfer,
                quantity_confirmed=form.cleaned_data["quantity_confirmed"],
                user=request.user,
                notes=form.cleaned_data.get("notes", ""),
            )
            if transfer.quantity_confirmed != transfer.quantity_requested:
                messages.warning(
                    request,
                    f"Transferencia confirmada con DESVIACIÓN: "
                    f"solicitado {transfer.quantity_requested}, confirmado {transfer.quantity_confirmed}."
                )
            else:
                messages.success(request, f"Transferencia de {transfer.component.code} confirmada.")
        except ValidationError as e:
            messages.error(request, str(e))

        # Si viene de la vista de ejecución, redirigir allá
        next_url = request.POST.get("next") or request.GET.get("next")
        if next_url:
            return redirect(next_url)
        return redirect("production:order_transfers", pk=transfer.order.pk)


# ---------------------------------------------------------
# Estimación de tiempo de producción (AJAX)
# ---------------------------------------------------------

class EstimateProductionTimeView(LoginRequiredMixin, ModulePermissionMixin, View):
    permission_required = "production.view_productionorder"
    """
    GET /production/estimate-time/?product_id=X&quantity=Y
    Retorna JSON con estimación de duración por paso y total.
    """
    def get(self, request):
        from inventory.models import Product
        product_id = request.GET.get("product_id")
        quantity = request.GET.get("quantity")

        if not product_id or not quantity:
            return JsonResponse({"error": "product_id y quantity son requeridos."}, status=400)

        try:
            product = Product.objects.get(pk=product_id)
            quantity = Decimal(quantity)
        except (Product.DoesNotExist, Exception):
            return JsonResponse({"error": "Producto no encontrado o cantidad inválida."}, status=400)

        route = (
            ProductRoute.objects
            .filter(product=product, is_active=True)
            .first()
        )
        if not route:
            return JsonResponse({"error": f"No hay ruta de producción activa para {product.code}."}, status=404)

        result = estimate_production_duration(route=route, quantity=quantity)
        result["estimated_end_date"] = result["estimated_end_date"].isoformat()
        result["start_date"] = result["start_date"].isoformat()
        return JsonResponse(result)


# ─── DIAGRAMA DE GANTT DE PRODUCCIÓN ───────────────────────────────

class ProductionGanttView(LoginRequiredMixin, ModulePermissionMixin, TemplateView):
    permission_required = "production.view_productionorder"
    """
    Vista de diagrama de Gantt para visualización de órdenes de producción.
    Muestra timeline de operaciones por orden o por work center.
    """
    template_name = "production/gantt.html"

    def get_context_data(self, **kwargs):
        from datetime import timedelta

        ctx = super().get_context_data(**kwargs)

        # Filtros
        view_mode = self.request.GET.get("view", "order")  # order o workcenter
        status_filter = self.request.GET.get("status", "active")  # active, all
        date_from = self.request.GET.get("date_from", "")
        date_to = self.request.GET.get("date_to", "")

        # Query base: órdenes activas o todas
        if status_filter == "active":
            orders = ProductionOrder.objects.filter(
                status__in=[ProductionOrderStatus.RELEASED, ProductionOrderStatus.IN_PROGRESS]
            )
        else:
            orders = ProductionOrder.objects.all()

        # Filtro por fecha
        if date_from:
            orders = orders.filter(start_date__gte=date_from)
        if date_to:
            orders = orders.filter(start_date__lte=date_to)

        orders = orders.select_related("product", "finished_lot").order_by("start_date")

        # Generar datos para Gantt
        gantt_tasks = []

        for order in orders:
            operations = order.operations.select_related(
                "step", "step__work_center", "input_lot", "output_lot"
            ).order_by("sequence")

            for op in operations:
                # Calcular fechas
                if op.started_at:
                    start_date = op.started_at.date() if hasattr(op.started_at, 'date') else op.started_at
                elif op.planned_start:
                    start_date = op.planned_start.date() if hasattr(op.planned_start, 'date') else op.planned_start
                else:
                    start_date = order.start_date

                if op.finished_at:
                    end_date = op.finished_at.date() if hasattr(op.finished_at, 'date') else op.finished_at
                elif op.planned_end:
                    end_date = op.planned_end.date() if hasattr(op.planned_end, 'date') else op.planned_end
                else:
                    # Estimar duración
                    duration_hours = op.step.duration_hours or 1
                    end_date = start_date + timedelta(hours=duration_hours)

                # Calcular progreso basado en cantidades
                if op.quantity_input and op.quantity_input > 0:
                    progress = int((op.quantity_output or 0) / op.quantity_input * 100)
                else:
                    # Sin cantidades, usar estado de la operación
                    progress = {
                        ProductionOperationStatus.PENDING: 0,
                        ProductionOperationStatus.IN_PROGRESS: 50,
                        ProductionOperationStatus.PAUSED: 50,
                        ProductionOperationStatus.DONE: 100,
                    }.get(op.status, 0)

                # Clase CSS según estado
                status_class = {
                    ProductionOperationStatus.PENDING: "gantt-pending",
                    ProductionOperationStatus.IN_PROGRESS: "gantt-in-progress",
                    ProductionOperationStatus.DONE: "gantt-completed",
                    ProductionOperationStatus.PAUSED: "gantt-paused",
                }.get(op.status, "gantt-pending")

                # Nombre de la tarea
                if view_mode == "workcenter":
                    task_name = f"{order.code} - {op.step.name}"
                else:
                    task_name = f"{op.step.name} ({op.step.work_center.name if op.step.work_center else 'Sin WC'})"

                # Dependencies (operación anterior en la misma orden)
                prev_op = operations.filter(sequence__lt=op.sequence).order_by("-sequence").first()
                dependencies = f"op-{prev_op.id}" if prev_op else ""

                gantt_tasks.append({
                    "id": f"op-{op.id}",
                    "name": task_name,
                    "start": start_date.strftime("%Y-%m-%d"),
                    "end": end_date.strftime("%Y-%m-%d"),
                    "progress": progress,
                    "dependencies": dependencies,
                    "custom_class": status_class,
                    # Metadata para tooltip
                    "order_code": order.code,
                    "operation_id": op.id,
                    "work_center": op.step.work_center.name if op.step.work_center else "N/A",
                    "status": op.get_status_display(),
                })

        ctx["gantt_data"] = json.dumps(gantt_tasks, ensure_ascii=False)
        ctx["view_mode"] = view_mode
        ctx["status_filter"] = status_filter
        ctx["date_from"] = date_from
        ctx["date_to"] = date_to
        ctx["work_centers"] = WorkCenter.objects.filter(is_active=True).order_by("name")

        return ctx
