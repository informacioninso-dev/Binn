# quality/views.py

from decimal import Decimal, InvalidOperation
from inventory.models import MovementTypes, InventoryMove,Lot
from procurement.models import  RawMaterialReception, ReceptionStatus ,RawMaterialReceptionLine
from production.models import ProductionOrder, ProductionOperation
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from core.mixins import ModulePermissionMixin
from django.db.models import Q
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse_lazy
from django.utils import timezone
from django.views.generic import (
    TemplateView,
    ListView,
    CreateView,
    DetailView,
    UpdateView,
    View,
)

from .forms import QAPlanForm, QualityInspectionForm, QAParameterTemplateFormSet , Lot
from .models import (
    QAPlan,
    QualityInspection,
    QAParameterTemplate,
    InspectionStage,LotStatus
)


# -------------------------------------------------------------------
# PANEL PRINCIPAL DE CALIDAD
# -------------------------------------------------------------------

class QualityIndexView(LoginRequiredMixin, ModulePermissionMixin, TemplateView):
    permission_required = "quality.view_qualityinspection"
    template_name = "quality/index.html"


# -------------------------------------------------------------------
# PLANES DE QA (CABECERA)
# -------------------------------------------------------------------

class QAPlanCreateView(LoginRequiredMixin, ModulePermissionMixin, CreateView):
    permission_required = "quality.add_qaplan"
    model = QAPlan
    form_class = QAPlanForm
    template_name = "quality/qa_plan_form.html"
    success_url = reverse_lazy("quality:qa_plan_list")

    def form_valid(self, form):
        messages.success(self.request, "Plan de calidad creado correctamente.")
        return super().form_valid(form)


class QAPlanUpdateView(LoginRequiredMixin, ModulePermissionMixin, UpdateView):
    permission_required = "quality.change_qaplan"
    model = QAPlan
    form_class = QAPlanForm
    template_name = "quality/qa_plan_form.html"
    success_url = reverse_lazy("quality:qa_plan_list")

    def form_valid(self, form):
        messages.success(self.request, "Plan de QA actualizado correctamente.")
        return super().form_valid(form)


class QAPlanListView(LoginRequiredMixin, ModulePermissionMixin, ListView):
    permission_required = "quality.view_qaplan"
    model = QAPlan
    template_name = "quality/qa_plan_list.html"
    context_object_name = "qa_plans"
    paginate_by = 20

    def get_queryset(self):
        qs = (
            QAPlan.objects
            .select_related("product", "work_center", "route_step")
            .order_by("stage", "product__name", "name")
        )
        q = self.request.GET.get("q", "").strip()
        stage = self.request.GET.get("stage", "").strip()
        if q:
            qs = qs.filter(
                Q(name__icontains=q)
                | Q(product__name__icontains=q)
                | Q(product__code__icontains=q)
            )
        if stage:
            qs = qs.filter(stage=stage)
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["stage_choices"] = InspectionStage.choices
        return ctx


# -------------------------------------------------------------------
# PARÁMETROS DE UN PLAN DE QA (FORMSET)
# -------------------------------------------------------------------

class QAPlanParametersView(LoginRequiredMixin, ModulePermissionMixin, View):
    permission_required = "quality.change_qaplan"
    """
    Permite gestionar (añadir / editar / eliminar) parámetros
    de un plan de QA específico.
    """
    template_name = "quality/qa_plan_parameters_form.html"

    def get_plan(self):
        return get_object_or_404(QAPlan, pk=self.kwargs["pk"])

    def get(self, request, pk):
        plan = self.get_plan()
        formset = QAParameterTemplateFormSet(instance=plan)
        return render(
            request,
            self.template_name,
            {
                "plan": plan,
                "formset": formset,
            },
        )

    def post(self, request, pk):
        plan = self.get_plan()
        formset = QAParameterTemplateFormSet(request.POST, instance=plan)

        if not formset.is_valid():
            messages.error(request, "Por favor corrige los errores en los parámetros.")
            return render(
                request,
                self.template_name,
                {
                    "plan": plan,
                    "formset": formset,
                },
            )

        formset.save()
        messages.success(self.request, "Parámetros del plan de calidad guardados correctamente.")
        return redirect("quality:qa_plan_list")


# -------------------------------------------------------------------
# CREACIÓN DE INSPECCIONES
# -------------------------------------------------------------------

class QualityInspectionCreateView(LoginRequiredMixin, ModulePermissionMixin, CreateView):
    permission_required = "quality.add_qualityinspection"
    model = QualityInspection
    form_class = QualityInspectionForm
    template_name = "quality/quality_inspection_form.html"
    success_url = reverse_lazy("quality:inspection_list")

    def get_initial(self):
        """
        Inicializa lote, etapa, operación y fecha/hora de inspección
        a partir de los parámetros GET (lot, stage, operation).
        """
        initial = super().get_initial()

        lot_id = self.request.GET.get("lot")
        stage = self.request.GET.get("stage")
        operation_id = self.request.GET.get("operation")

        if lot_id:
            initial["lot"] = lot_id

        valid_stages = {choice[0] for choice in InspectionStage.choices}
        if stage in valid_stages:
            initial["stage"] = stage

        if operation_id:
            initial["operation"] = operation_id

        if not initial.get("inspected_at"):
            initial["inspected_at"] = timezone.now()

        return initial

    def get_form_kwargs(self):
        """
        Resuelve el plan de QA aplicable en función de:
          - lote (producto)
          - etapa (RAW / WIP / FG)
          - operación (para obtener route_step y work_center)
        y se lo pasa al formulario como kwarg `plan`.
        """
        kwargs = super().get_form_kwargs()

        lot = None
        stage = None
        operation = None

        lot_id = self.request.POST.get("lot") or self.request.GET.get("lot")
        stage_val = self.request.POST.get("stage") or self.request.GET.get("stage")
        op_id = self.request.POST.get("operation") or self.request.GET.get("operation")

        # Lote (con producto)
        if lot_id:
            try:
                lot = Lot.objects.select_related("product").get(pk=lot_id)
            except Lot.DoesNotExist:
                lot = None

        # Etapa
        valid_stages = {choice[0] for choice in InspectionStage.choices}
        if stage_val in valid_stages:
            stage = stage_val

        # Operación de producción (para WIP)
        if op_id:
            try:
                operation = (
                    ProductionOperation.objects
                    .select_related("step", "step__work_center")
                    .get(pk=op_id)
                )
            except ProductionOperation.DoesNotExist:
                operation = None

        route_step = operation.step if operation else None
        work_center = route_step.work_center if route_step else None

        # Resolvemos el plan más aplicable
        plan = None
        if lot and stage:
            plan = QAPlan.get_applicable_plan(
                product=lot.product,
                stage=stage,
                work_center=work_center,
                route_step=route_step,
            )

        # DEBUG opcional
        # print(
        #     "DEBUG QA >>> lot:", lot,
        #     "stage:", stage,
        #     "route_step:", route_step,
        #     "work_center:", work_center,
        #     "plan:", plan,
        # )

        # Pasamos el plan al formulario
        kwargs["plan"] = plan
        return kwargs

    def get_context_data(self, **kwargs):
        """
        Añadimos `qa_plan` al contexto para mostrar en el template
        el resumen del plan aplicado.
        """
        ctx = super().get_context_data(**kwargs)
        form = ctx.get("form")
        if form and hasattr(form, "plan"):
            ctx["qa_plan"] = form.plan
        return ctx

    def form_valid(self, form):
        """
        Amarra:
          - usuario que inspecciona
          - plan aplicado (ya viene en el form)
          - checklist estructurado
        Luego ejecuta release_lot_by_qa para mover lote y actualizar stock.
        """
        from inventory.services import release_lot_by_qa

        inspection: QualityInspection = form.save(commit=False)

        # Usuario que ejecuta la inspección
        inspection.inspected_by = self.request.user

        # Si el form tiene plan resuelto, lo amarramos
        if hasattr(form, "plan") and form.plan:
            inspection.plan = form.plan

        # Si por alguna razón no se setea inspected_at, lo ponemos ahora
        if not inspection.inspected_at:
            inspection.inspected_at = timezone.now()

        inspection.save()

        # Ejecutar liberación de lote (mueve a bodega destino + actualiza stock si APPROVED)
        lot = inspection.lot
        result = inspection.result
        if lot and result in (LotStatus.APPROVED, LotStatus.REJECTED, LotStatus.QUARANTINE):
            try:
                release_lot_by_qa(
                    user=self.request.user,
                    lot=lot,
                    result=result,
                    checklist=inspection.checklist,
                    notes=inspection.notes,
                    stage=inspection.stage,
                )
                if result == LotStatus.APPROVED:
                    messages.success(
                        self.request,
                        f"Lote {lot.internal_lot} APROBADO. Stock actualizado y movido a bodega destino."
                    )
                elif result == LotStatus.REJECTED:
                    messages.warning(
                        self.request,
                        f"Lote {lot.internal_lot} RECHAZADO. Movido a bodega de baja."
                    )
                else:
                    messages.info(
                        self.request,
                        f"Lote {lot.internal_lot} permanece en CUARENTENA."
                    )
            except Exception as e:
                messages.error(self.request, f"Error al liberar lote: {e}")
        else:
            messages.success(self.request, "Inspección de calidad registrada correctamente.")

        return redirect(self.success_url)


# -------------------------------------------------------------------
# LISTADO Y DETALLE DE INSPECCIONES
# -------------------------------------------------------------------

class QualityInspectionListView(LoginRequiredMixin, ModulePermissionMixin, ListView):
    permission_required = "quality.view_qualityinspection"
    model = QualityInspection
    template_name = "quality/quality_inspection_list.html"
    context_object_name = "inspections"
    paginate_by = 20

    def get_queryset(self):
        qs = (
            QualityInspection.objects
            .select_related("lot", "lot__product", "operation", "inspected_by", "plan")
            .order_by("-inspected_at")
        )
        q = self.request.GET.get("q", "").strip()
        result = self.request.GET.get("result", "").strip()
        stage = self.request.GET.get("stage", "").strip()
        if q:
            qs = qs.filter(
                Q(lot__internal_lot__icontains=q)
                | Q(lot__product__name__icontains=q)
                | Q(lot__product__code__icontains=q)
            )
        if result:
            qs = qs.filter(result=result)
        if stage:
            qs = qs.filter(stage=stage)
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["stage_choices"] = InspectionStage.choices
        ctx["result_choices"] = LotStatus.choices
        return ctx


class QualityInspectionDetailView(LoginRequiredMixin, ModulePermissionMixin, DetailView):
    permission_required = "quality.view_qualityinspection"
    model = QualityInspection
    template_name = "quality/quality_inspection_detail.html"
    context_object_name = "inspection"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        inspection: QualityInspection = self.object
        plan = inspection.plan

        parameters_rows = []

        if plan:
            checklist = inspection.checklist or {}

            # Recorremos los parámetros definidos en el plan en orden
            for param in plan.parameters.all():
                data = checklist.get(param.code, {}) or {}
                value = data.get("value")

                within_limits = None

                # Solo tiene sentido evaluar límites para numéricos con min/max
                if (
                    value is not None
                    and param.data_type == QAParameterTemplate.DataType.NUMBER
                    and (param.min_value is not None or param.max_value is not None)
                ):
                    try:
                        v = Decimal(str(value))
                        ok_min = param.min_value is None or v >= param.min_value
                        ok_max = param.max_value is None or v <= param.max_value
                        within_limits = ok_min and ok_max
                    except (InvalidOperation, TypeError):
                        within_limits = None

                parameters_rows.append(
                    {
                        "param": param,
                        "value": value,
                        "within_limits": within_limits,
                    }
                )

        total = len(parameters_rows)
        ok_count = sum(1 for r in parameters_rows if r["within_limits"] is True)
        out_count = sum(1 for r in parameters_rows if r["within_limits"] is False)

        ctx["qa_plan"] = plan
        ctx["parameters"] = parameters_rows
        ctx["params_total"] = total
        ctx["params_ok"] = ok_count
        ctx["params_out"] = out_count
        return ctx


# -------------------------------------------------------------------
# LOTES / OPERACIONES PENDIENTES DE QA
# -------------------------------------------------------------------

class PendingLotsQAView(LoginRequiredMixin, ModulePermissionMixin, TemplateView):
    permission_required = "quality.view_qualityinspection"
    """
    Panel de Lotes / QA pendientes:
      - MP (RAW) sin inspección final de RAW
      - Operaciones WIP con requires_qa=True sin inspección final
      - Producto terminado (FG) sin inspección final de FG
    """
    template_name = "quality/pending_lots.html"

    def get_context_data(self, **kwargs):
        from inventory.models import Lot as LotModel
        from inventory.models import ProductType as ProdTypeModel

        ctx = super().get_context_data(**kwargs)

        # Resultados que consideramos "finales" para sacar de pendientes
        final_results = [
            LotStatus.APPROVED,
            LotStatus.REJECTED,
            LotStatus.QUARANTINE,
        ]

        # 1) Lotes de materia prima (RAW) con QA pendiente
        raw_lots_pending = (
            LotModel.objects
            .filter(product__product_type=ProdTypeModel.RAW)
            .exclude(
                inspections__stage=InspectionStage.RAW,
                inspections__result__in=final_results,
            )
            .distinct()
            .select_related("product")
            .order_by("product__name", "internal_lot")
        )

        # 2) Lotes de producto terminado (FG) con QA pendiente
        fg_lots_pending = (
            LotModel.objects
            .filter(product__product_type=ProdTypeModel.FG)
            .exclude(
                inspections__stage=InspectionStage.FG,
                inspections__result__in=final_results,
            )
            .distinct()
            .select_related("product")
            .order_by("product__name", "internal_lot")
        )

        # 3) Operaciones WIP con QA requerido y sin inspección final
        wip_ops_pending = (
            ProductionOperation.objects
            .filter(step__requires_qa=True)
            .exclude(inspections__result__in=final_results)
            .select_related(
                "order",
                "step",
                "step__work_center",
                "input_lot",
                "input_lot__product",
            )
            .order_by("order__code", "sequence")
        )

        ctx["raw_lots_pending"] = raw_lots_pending
        ctx["fg_lots_pending"] = fg_lots_pending
        ctx["wip_ops_pending"] = wip_ops_pending
        return ctx

# -------------------------------------------------------------------
# RECEPCIONES DE MATERIA PRIMA PENDIENTES DE QA
# -------------------------------------------------------------------


class ReceptionQAListView(LoginRequiredMixin, ModulePermissionMixin, ListView):
    permission_required = "quality.view_qualityinspection"
    """
    Lista de recepciones de materia prima pendientes de inspección (UNDER_QA)
    """
    model = RawMaterialReception
    template_name = "quality/receptions_qa_list.html"
    context_object_name = "receptions"
    paginate_by = 20

    def get_queryset(self):
        return (
            RawMaterialReception.objects
            .filter(status=ReceptionStatus.UNDER_QA)
            .order_by("-reception_date", "-id")
        )


class ReceptionQADetailView(LoginRequiredMixin, ModulePermissionMixin, DetailView):
    permission_required = "quality.view_qualityinspection"
    """
    Detalle de una recepción para revisarla en calidad.
    """
    model = RawMaterialReception
    template_name = "quality/reception_qa_detail.html"
    context_object_name = "reception"


class ReceptionQAActionView(LoginRequiredMixin, ModulePermissionMixin, View):
    permission_required = "quality.change_qualityinspection"
    """
    Acción de aprobar o rechazar una recepción.
    Se llama vía POST con ?action=approve o ?action=reject
    """
    def post(self, request, pk):
        reception = get_object_or_404(RawMaterialReception, pk=pk)

        # Solo permitimos actuar si sigue en UNDER_QA
        if reception.status != ReceptionStatus.UNDER_QA:
            messages.error(request, "Esta recepción ya fue procesada en calidad.")
            return redirect("quality:receptions_qa_detail", pk=reception.pk)

        action = request.GET.get("action")
        if action not in ["approve", "reject"]:
            messages.error(request, "Acción no válida.")
            return redirect("quality:receptions_qa_detail", pk=reception.pk)

        if action == "approve":
            # 👉 Aquí luego podemos crear lotes, movimientos, etc.
            reception.status = ReceptionStatus.COMPLETED
            messages.success(
                request,
                f"Recepción {reception.code} aprobada por Calidad."
            )
        else:
            reception.status = ReceptionStatus.CANCELLED
            messages.warning(
                request,
                f"Recepción {reception.code} rechazada / anulada por Calidad."
            )

        reception.save(update_fields=["status"])
        return redirect("quality:receptions_qa_list")


class LotAuditView(LoginRequiredMixin, ModulePermissionMixin, DetailView):
    permission_required = "quality.view_qualityinspection"
    """
    Panel de trazabilidad / auditoría por lote terminado (FG).

    Muestra:
      - Lote
      - Orden de producción asociada (finished_lot)
      - Operaciones de producción
      - QA del FG
      - MP consumida (movimientos OUT con referencia = código de OP)
      - Recepciones y QA RAW de los lotes de MP
      - Lista de issues detectados
    """
    model = Lot
    template_name = "quality/audit_lot.html"
    context_object_name = "lot"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        lot: Lot = self.object

        # 1) Orden de producción que generó este lote (finished_lot)
        order = (
            ProductionOrder.objects
            .select_related("product", "route", "bom")
            .prefetch_related("operations__step", "operations__input_lot", "operations__output_lot")
            .filter(finished_lot=lot)
            .first()
        )
        ctx["order"] = order

        # 2) Operaciones de producción
        operations = []
        if order:
            operations = (
                order.operations
                .select_related("step", "input_lot", "output_lot")
                .order_by("sequence", "id")
            )
        ctx["operations"] = operations

        # 3) QA del lote terminado (FG)
        qa_fg = (
            QualityInspection.objects
            .filter(lot=lot, stage=InspectionStage.FG)
            .select_related("inspected_by", "plan")
            .order_by("-inspected_at")
        )
        ctx["qa_fg"] = qa_fg

        # 4) Movimientos vinculados a la OP (IN/OUT) por referencia = código de OP
        moves = []
        moves_mp = []
        mp_lot_ids = set()
        mp_lots = []
        receptions_by_lot: dict[int, RawMaterialReception] = {}
        qa_raw_by_lot: dict[int, list[QualityInspection]] = {}

        if order:
            moves = (
                InventoryMove.objects
                .filter(reference=order.code)
                .select_related("product", "lot", "warehouse")
                .order_by("movement_type", "product__name", "lot__internal_lot")
            )
            ctx["moves"] = moves

            # Solo consumos de MP (OUT con lote)
            moves_mp = [
                m for m in moves
                if m.movement_type == MovementTypes.OUT and m.lot_id
            ]
            ctx["moves_mp"] = moves_mp

            mp_lot_ids = {m.lot_id for m in moves_mp if m.lot_id}
            mp_lots = (
                Lot.objects
                .filter(id__in=mp_lot_ids)
                .select_related("product", "warehouse")
            )
            ctx["mp_lots"] = mp_lots

            # 4.1) Mapear recepciones por lote de MP (según internal_lot)
            internal_lots = [l.internal_lot for l in mp_lots if l.internal_lot]
            rec_lines = (
                RawMaterialReceptionLine.objects
                .filter(internal_lot__in=internal_lots)
                .select_related("reception", "reception__purchase_order")
            )

            rec_by_internal: dict[str, RawMaterialReception] = {}
            for ln in rec_lines:
                rec_by_internal.setdefault(ln.internal_lot, ln.reception)

            for l in mp_lots:
                rec = rec_by_internal.get(l.internal_lot)
                if rec:
                    receptions_by_lot[l.id] = rec

            ctx["receptions_by_lot"] = receptions_by_lot

            # 4.2) QA RAW por lote de MP
            raw_inspections = (
                QualityInspection.objects
                .filter(lot_id__in=mp_lot_ids, stage=InspectionStage.RAW)
                .select_related("inspected_by", "plan", "lot")
                .order_by("-inspected_at")
            )
            for ins in raw_inspections:
                qa_raw_by_lot.setdefault(ins.lot_id, []).append(ins)

        ctx["qa_raw_by_lot"] = qa_raw_by_lot

        # 5) Issues / alertas para auditoría
        issues: list[str] = []

        if not order:
            issues.append(
                "El lote no está vinculado a ninguna orden de producción (finished_lot)."
            )

        if order and not order.bom:
            issues.append("La orden de producción no tiene un BOM asociado.")

        if order and not operations:
            issues.append("La orden de producción no tiene operaciones generadas.")

        if not qa_fg.exists():
            issues.append(
                "El lote de producto terminado no tiene inspección de calidad en etapa FG."
            )

        # Lotes de MP sin QA RAW
        for l in mp_lots:
            inspections = qa_raw_by_lot.get(l.id, [])
            if not inspections:
                issues.append(
                    f"El lote de materia prima {l.internal_lot} ({l.product.code}) "
                    "no tiene inspección de calidad en etapa RAW."
                )

        ctx["issues"] = issues
        return ctx

class LotAuditSearchView(LoginRequiredMixin, ModulePermissionMixin, TemplateView):
    permission_required = "quality.view_qualityinspection"
    """
    Pantalla de entrada al panel de auditoría:
    permite buscar un lote por código interno y redirige a audit_lot.
    """
    template_name = "quality/audit_search.html"

    def post(self, request, *args, **kwargs):
        code = request.POST.get("internal_lot", "").strip()

        if not code:
            messages.error(request, "Ingresa un código de lote para continuar.")
            return self.get(request, *args, **kwargs)

        lot = (
            Lot.objects
            .select_related("product")
            .filter(internal_lot__iexact=code)
            .first()
        )

        if not lot:
            messages.error(
                request,
                f"No se encontró ningún lote con código interno «{code}»."
            )
            return self.get(request, *args, **kwargs)

        # Redirige al panel de auditoría REAL, que sí pide pk
        return redirect("quality:audit_lot", pk=lot.pk)