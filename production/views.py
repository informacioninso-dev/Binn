from decimal import Decimal  # 👈 NUEVO

from django.contrib.auth.mixins import LoginRequiredMixin
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
)

from .services import (
    consume_raw_materials_for_operation,
    close_production_order,
    generate_production_plan_code,
)

from .forms import (
    BillOfMaterialForm,
    BillOfMaterialLineFormSet,
    ProductionOrderForm,
    ProductionOperationForm,
    ProductionPlanForm,
)

from inventory.models import Product, ProductType  # 👈 NUEVO (para lot_prefix_map)


class ProductionDashboardView(LoginRequiredMixin, TemplateView):
    template_name = "production/index.html"


# ---------------------------------------------------------
# BOM
# ---------------------------------------------------------

class BillOfMaterialListView(LoginRequiredMixin, ListView):
    model = BillOfMaterial
    template_name = "production/bom_list.html"
    context_object_name = "page"
    paginate_by = 20

    def get_queryset(self):
        return (
            BillOfMaterial.objects
            .select_related("product_finished")
            .order_by("product_finished__name", "revision")
        )


class BillOfMaterialCreateView(LoginRequiredMixin, View):
    template_name = "production/bom_form.html"
    success_url = reverse_lazy("production:bom_list")

    def get(self, request):
        form = BillOfMaterialForm()
        formset = BillOfMaterialLineFormSet()
        return render(
            request,
            self.template_name,
            {"form": form, "formset": formset},
        )

    def post(self, request):
        form = BillOfMaterialForm(request.POST)
        formset = BillOfMaterialLineFormSet(request.POST)

        if not (form.is_valid() and formset.is_valid()):
            messages.error(request, "Revisa los errores del formulario.")
            return render(
                request,
                self.template_name,
                {"form": form, "formset": formset},
            )

        with transaction.atomic():
            bom = form.save()
            formset.instance = bom
            formset.save()

        messages.success(request, "Plano de fabricación creado correctamente.")
        return redirect(self.success_url)


# ---------------------------------------------------------
# Órdenes de Producción
# ---------------------------------------------------------

class ProductionOrderListView(LoginRequiredMixin, ListView):
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


class ProductionOrderCreatePlanningView(LoginRequiredMixin, CreateView):
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

class ProductionOperationListView(LoginRequiredMixin, ListView):
    model = ProductionOperation
    template_name = "production/operations_list.html"
    context_object_name = "operations"
    paginate_by = 25

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

        status = self.request.GET.get("status")
        work_center_id = self.request.GET.get("work_center")

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


class ProductionOperationUpdateView(LoginRequiredMixin, UpdateView):
    model = ProductionOperation
    form_class = ProductionOperationForm
    template_name = "production/operation_form.html"

    def form_valid(self, form):
        # Guardamos cómo estaba la operación ANTES de cambiarla
        old_op = self.get_object()
        was_done_before = (old_op.status == ProductionOperationStatus.DONE)

        op: ProductionOperation = form.save(commit=False)

        # --- Manejo de tiempos ---
        if op.status == ProductionOperationStatus.IN_PROGRESS and op.started_at is None:
            op.started_at = timezone.now()

        if op.status == ProductionOperationStatus.DONE and op.finished_at is None:
            op.finished_at = timezone.now()

        op.updated_by = self.request.user
        op.save()

        # --- Consumo de MP con FEFO ---
        # Solo si AHORA está DONE y ANTES no lo estaba
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

        messages.success(self.request, "Operación de producción actualizada correctamente.")

        order = op.order

        # --- ¿Es la última operación de la OP? ---
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
                    f"{order.finished_lot.internal_lot if order.finished_lot else ''}."
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
        return ctx


class ProductionOrderDetailView(LoginRequiredMixin, DetailView):
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


class ProductionOrderExecutionView(LoginRequiredMixin, DetailView):
    """
    Motor de ejecución visual: muestra las operaciones en fila,
    resalta la actual y solo deja avanzar una por vez.
    """
    model = ProductionOrder
    template_name = "production/order_execute.html"
    context_object_name = "order"

    def get_object(self, queryset=None):
        """
        Cada vez que entramos a ejecutar, garantizamos que:
        - La OP tenga operaciones generadas (a partir de la ruta).
        - Pase a IN_PROGRESS si estaba en DRAFT.
        """
        order: ProductionOrder = super().get_object(queryset)

        # Si no tiene operaciones, las generamos acá (reemplaza la lógica de "liberar")
        if not order.operations.exists():
            from .models import ProductRouteStep, ProductionOperation

            steps = (
                ProductRouteStep.objects
                .filter(route=order.route, is_active=True)
                .order_by("sequence", "id")
            )

            if not steps.exists():
                messages.error(
                    self.request,
                    "La ruta seleccionada no tiene pasos activos; no se puede ejecutar la orden."
                )
                return order

            with transaction.atomic():
                for step in steps:
                    ProductionOperation.objects.create(
                        order=order,
                        step=step,
                        sequence=step.sequence,
                        status=ProductionOperationStatus.PENDING,
                        created_by=self.request.user,
                        updated_by=self.request.user,
                    )

                if order.status == ProductionOrderStatus.DRAFT:
                    order.status = ProductionOrderStatus.IN_PROGRESS
                    order.updated_by = self.request.user
                    order.save(update_fields=["status", "updated_by", "updated_at"])

                messages.success(
                    self.request,
                    f"Se generaron las operaciones de producción para la orden {order.code}."
                )

        return order

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        order: ProductionOrder = self.object

        ops = (
            order.operations
            .select_related("step", "step__work_center")
            .order_by("sequence", "id")
        )

        # Primer paso NO DONE → operación "actual"
        current_op = None
        for o in ops:
            if o.status != ProductionOperationStatus.DONE:
                current_op = o
                break

        ctx["operations"] = ops
        ctx["current_operation"] = current_op
        return ctx


# ---------------------------------------------------------
# Planes de Producción
# ---------------------------------------------------------

class ProductionPlanListView(LoginRequiredMixin, ListView):
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


class ProductionPlanCreateView(LoginRequiredMixin, CreateView):
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

    def form_valid(self, form):
        plan: ProductionPlan = form.save(commit=False)

        if not plan.manufacturing_date:
            plan.manufacturing_date = timezone.localdate()

        if not plan.code:
            plan.code = generate_production_plan_code(plan.manufacturing_date)

        plan.created_by = self.request.user
        plan.updated_by = self.request.user
        plan.save()

        messages.success(self.request, "Plan de producción creado correctamente.")
        return redirect(self.success_url)


class ProductionPlanUpdateView(LoginRequiredMixin, UpdateView):
    model = ProductionPlan
    form_class = ProductionPlanForm
    template_name = "production/plan_form.html"
    success_url = reverse_lazy("production:plans_list")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        products = Product.objects.filter(
            product_type=ProductType.FG,
            is_active=True,
        ).values("id", "lot_prefix")  # 👈 igual que arriba

        ctx["lot_prefix_map"] = {
            str(p["id"]): p["lot_prefix"] or "" for p in products
        }
        return ctx

    def form_valid(self, form):
        plan: ProductionPlan = form.save(commit=False)
        plan.updated_by = self.request.user
        plan.save()
        messages.success(self.request, "Plan de producción actualizado correctamente.")
        return redirect(self.success_url)


class ProductionOrderCreateFromPlanView(LoginRequiredMixin, CreateView):
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
