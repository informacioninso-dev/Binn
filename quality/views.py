# quality/views.py

from decimal import Decimal, InvalidOperation
from inventory.models import MovementTypes, InventoryMove, Lot
from procurement.models import RawMaterialReception, ReceptionStatus, RawMaterialReceptionLine
from production.models import ProductionOrder, ProductionOperation
from sales.models import SaleReturn, SaleReturnStatus
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

from django.contrib.auth.decorators import login_required
from .forms import QAPlanForm, QualityInspectionForm, QAParameterTemplateFormSet , Lot
from .models import (
    QAPlan,
    QualityInspection,
    QAParameterTemplate,
    InspectionStage, LotStatus,
    ProductRecall, RecallLot, RecallAffectedClient,
    RecallOrigin, RecallStatus, RecallSeverity,
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

        # ═══ CAMPOS DE TRAZABILIDAD - SIEMPRE AUTOMÁTICOS ═══
        # Estos campos NUNCA deben venir del formulario para garantizar integridad

        # Fecha/hora: SIEMPRE el momento actual de creación
        inspection.inspected_at = timezone.now()

        # Inspector: SIEMPRE el usuario autenticado actual
        inspection.inspected_by = self.request.user

        # Si el form tiene plan resuelto, lo amarramos
        if hasattr(form, "plan") and form.plan:
            inspection.plan = form.plan

        inspection.save()

        # Ejecutar liberación de lote (mueve a bodega destino + actualiza stock si APPROVED)
        lot = inspection.lot
        result = inspection.result
        if lot and result in (LotStatus.APPROVED, LotStatus.REJECTED, LotStatus.QUARANTINE):
            try:
                dest_loc = form.cleaned_data.get("destination_location")
                release_lot_by_qa(
                    user=self.request.user,
                    lot=lot,
                    result=result,
                    checklist=inspection.checklist,
                    notes=inspection.notes,
                    stage=inspection.stage,
                    destination_location=dest_loc,
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

        # 4) Devoluciones de cliente pendientes de inspección QA
        returns_pending_inspection = (
            SaleReturn.objects
            .filter(status=SaleReturnStatus.PENDING_INSPECTION)
            .select_related("client", "invoice", "reason")
            .prefetch_related("lines__product", "lines__lot")
            .order_by("-received_date")
        )

        ctx["raw_lots_pending"] = raw_lots_pending
        ctx["fg_lots_pending"] = fg_lots_pending
        ctx["wip_ops_pending"] = wip_ops_pending
        ctx["returns_pending_inspection"] = returns_pending_inspection
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
      - Ubicación actual (bodegas y clientes)
      - Despachos realizados
      - Devoluciones
      - Lista de issues detectados
    """
    model = Lot
    template_name = "quality/audit_lot.html"
    context_object_name = "lot"

    def get_context_data(self, **kwargs):
        from inventory.models import LotBalance
        from sales.models import SaleDispatchLine, SaleReturn, SaleReturnLine
        from decimal import Decimal

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
            mp_lots = list(
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

        # 5) UBICACIÓN ACTUAL - Balances en bodegas
        lot_balances = list(
            LotBalance.objects
            .filter(lot=lot, qty__gt=0)
            .select_related("warehouse")
            .order_by("warehouse__name")
        )
        ctx["lot_balances"] = lot_balances
        ctx["total_in_warehouse"] = sum(b.qty for b in lot_balances)

        # 6) DESPACHOS A CLIENTES - Quién recibió este lote
        dispatch_lines = (
            SaleDispatchLine.objects
            .filter(lot=lot)
            .select_related(
                "dispatch",
                "dispatch__order",
                "dispatch__order__client",
                "product",
            )
            .order_by("-dispatch__dispatched_date")
        )
        ctx["dispatch_lines"] = dispatch_lines
        ctx["total_dispatched"] = sum(dl.quantity for dl in dispatch_lines)

        # Construir lista de clientes con info de despacho
        clients_dispatched = []
        for dl in dispatch_lines:
            dispatch = dl.dispatch
            order_sale = dispatch.order
            client = order_sale.client
            clients_dispatched.append({
                "client": client,
                "client_name": client.legal_name or client.trade_name,
                "dispatch_code": dispatch.code,
                "dispatch_date": dispatch.dispatched_date,
                "quantity": dl.quantity,
                "delivery_address": order_sale.delivery_address or client.address,
                "delivery_city": order_sale.delivery_city or client.city,
            })
        ctx["clients_dispatched"] = clients_dispatched

        # 7) DEVOLUCIONES - Si el lote fue devuelto
        return_lines = list(
            SaleReturnLine.objects
            .filter(lot=lot)
            .select_related(
                "return_doc",
                "return_doc__client",
                "return_doc__reason",
                "product",
            )
            .order_by("-return_doc__received_date")
        )
        ctx["return_lines"] = return_lines
        ctx["total_returned"] = sum(rl.quantity_returned for rl in return_lines)

        # 8) Enriquecer MP con datos de recepción y QA para el template
        mp_lots_enriched = []
        for mp_lot in mp_lots:
            mp_lots_enriched.append({
                "lot": mp_lot,
                "reception": receptions_by_lot.get(mp_lot.id),
                "qa_inspections": qa_raw_by_lot.get(mp_lot.id, []),
            })
        ctx["mp_lots_enriched"] = mp_lots_enriched

        # 9) Issues / alertas para auditoría
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


# ─── Retiro de Mercado ──────────────────────────────────────────


class ProductRecallListView(LoginRequiredMixin, ModulePermissionMixin, ListView):
    permission_required = "quality.view_productrecall"
    model = ProductRecall
    template_name = "quality/recall_list.html"
    context_object_name = "recalls"
    paginate_by = 20

    def get_queryset(self):
        from .models import RecallStatus
        qs = (
            ProductRecall.objects
            .select_related("product", "origin")
            .prefetch_related("lots", "affected_clients")
            .order_by("-recall_date")
        )
        q = self.request.GET.get("q", "").strip()
        status = self.request.GET.get("status", "").strip()
        if q:
            qs = qs.filter(
                Q(code__icontains=q)
                | Q(product__name__icontains=q)
                | Q(product__code__icontains=q)
            )
        if status:
            qs = qs.filter(status=status)
        return qs

    def get_context_data(self, **kwargs):
        from .models import RecallStatus
        ctx = super().get_context_data(**kwargs)
        ctx["status_choices"] = RecallStatus.choices
        return ctx


class ProductRecallCreateView(LoginRequiredMixin, ModulePermissionMixin, View):
    permission_required = "quality.view_productrecall"  # Usar view para crear también
    template_name = "quality/recall_form.html"

    def get(self, request):
        from inventory.models import Product, ProductType
        from .models import RecallOrigin, RecallSeverity

        # Paso 1: Mostrar selección de origen y producto
        selected_origin_id = request.GET.get("origin")
        selected_product_id = request.GET.get("product")

        origins = RecallOrigin.objects.filter(is_active=True).order_by("origin_type", "name")
        products = Product.objects.filter(
            product_type=ProductType.FG,
            is_active=True
        ).order_by("name")

        context = {
            "origins": origins,
            "products": products,
            "severity_choices": RecallSeverity.choices,
            "selected_origin": None,
            "selected_product": None,
            "lots_info": [],
        }

        # Si ya se seleccionó origen y producto, cargar lotes
        if selected_origin_id and selected_product_id:
            from .services import get_lots_for_product

            try:
                context["selected_origin"] = RecallOrigin.objects.get(pk=selected_origin_id)
                context["selected_product"] = Product.objects.get(pk=selected_product_id)
                context["lots_info"] = get_lots_for_product(context["selected_product"])
            except (RecallOrigin.DoesNotExist, Product.DoesNotExist):
                pass

        return render(request, self.template_name, context)

    def post(self, request):
        from inventory.models import Product
        from .models import RecallOrigin, RecallSeverity
        from .services import create_recall

        origin_id = request.POST.get("origin_id")
        product_id = request.POST.get("product_id")
        lot_ids = request.POST.getlist("lot_ids")
        reason = request.POST.get("reason", "").strip()
        description = request.POST.get("description", "").strip()
        severity = request.POST.get("severity", RecallSeverity.MEDIUM)

        if not all([origin_id, product_id, lot_ids, reason]):
            messages.error(request, "Complete todos los campos requeridos.")
            return redirect(request.path)

        try:
            origin = RecallOrigin.objects.get(pk=origin_id)
            product = Product.objects.get(pk=product_id)

            recall = create_recall(
                product=product,
                origin=origin,
                reason=reason,
                description=description,
                severity=severity,
                selected_lot_ids=lot_ids,
                user=request.user,
            )

            affected_clients = recall.affected_clients.count()
            messages.success(
                request,
                f"Retiro {recall.code} creado. {affected_clients} cliente(s) afectado(s) identificado(s).",
            )
            return redirect("quality:recall_detail", pk=recall.pk)

        except Exception as e:
            messages.error(request, str(e))
            return redirect(request.path)


class ProductRecallDetailView(LoginRequiredMixin, ModulePermissionMixin, DetailView):
    permission_required = "quality.view_productrecall"
    model = ProductRecall
    template_name = "quality/recall_detail.html"
    context_object_name = "recall"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        recall = self.object

        ctx["affected_lots"] = recall.lots.select_related("lot")
        ctx["affected_clients"] = (
            recall.affected_clients
            .select_related("recall_lot", "client")
            .order_by("notified", "-quantity_dispatched")
        )
        ctx["stats"] = {
            "total_clients": recall.affected_clients.count(),
            "notified_clients": recall.affected_clients.filter(notified=True).count(),
            "recovered_clients": recall.affected_clients.filter(recovered=True).count(),
        }
        return ctx


@login_required
def activate_recall_view(request, pk):
    from .services import activate_recall

    recall = get_object_or_404(ProductRecall, pk=pk)
    try:
        activate_recall(recall=recall, user=request.user)
        messages.success(request, f"Retiro {recall.code} activado.")
    except Exception as e:
        messages.error(request, str(e))
    return redirect("quality:recall_detail", pk=pk)


@login_required
def start_notification_view(request, pk):
    from .services import start_notification

    recall = get_object_or_404(ProductRecall, pk=pk)
    try:
        start_notification(recall=recall, user=request.user)
        messages.success(request, f"Proceso de notificación iniciado para {recall.code}.")
    except Exception as e:
        messages.error(request, str(e))
    return redirect("quality:recall_detail", pk=pk)


@login_required
def mark_notified_view(request, pk, client_pk):
    from .models import RecallAffectedClient
    from .services import mark_client_notified

    recall = get_object_or_404(ProductRecall, pk=pk)
    affected = get_object_or_404(RecallAffectedClient, pk=client_pk, recall=recall)

    method = request.POST.get("notification_method", "Manual")
    try:
        mark_client_notified(
            affected_client=affected,
            notification_method=method,
            user=request.user,
        )
        messages.success(request, f"Cliente {affected.client_name} marcado como notificado.")
    except Exception as e:
        messages.error(request, str(e))
    return redirect("quality:recall_detail", pk=pk)


@login_required
def mark_recovered_view(request, pk, client_pk):
    from .models import RecallAffectedClient
    from .services import mark_client_recovered
    from decimal import Decimal

    recall = get_object_or_404(ProductRecall, pk=pk)
    affected = get_object_or_404(RecallAffectedClient, pk=client_pk, recall=recall)

    qty = request.POST.get("quantity_recovered", "0")
    notes = request.POST.get("recovery_notes", "")
    try:
        mark_client_recovered(
            affected_client=affected,
            quantity_recovered=Decimal(qty),
            recovery_notes=notes,
            user=request.user,
        )
        messages.success(request, f"Producto recuperado de {affected.client_name}.")
    except Exception as e:
        messages.error(request, str(e))
    return redirect("quality:recall_detail", pk=pk)


@login_required
def complete_recall_view(request, pk):
    from .services import complete_recall

    recall = get_object_or_404(ProductRecall, pk=pk)
    corrective_action = request.POST.get("corrective_action", "")
    try:
        complete_recall(
            recall=recall,
            corrective_action=corrective_action,
            user=request.user,
        )
        messages.success(request, f"Retiro {recall.code} completado.")
    except Exception as e:
        messages.error(request, str(e))
    return redirect("quality:recall_detail", pk=pk)


class RecallLotAuditView(LoginRequiredMixin, ModulePermissionMixin, DetailView):
    """
    Vista de auditoría de un lote dentro de un retiro de mercado.
    Muestra la trazabilidad completa del lote: MP, producción, QA, despachos.
    """
    permission_required = "quality.view_productrecall"
    model = RecallLot
    template_name = "quality/recall_lot_audit.html"
    context_object_name = "recall_lot"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        recall_lot = self.object
        lot = recall_lot.lot

        # Reutilizar la lógica de auditoría existente
        from production.models import ProductionOrder

        # Orden de producción que generó este lote
        order = (
            ProductionOrder.objects
            .select_related("product", "route", "bom")
            .prefetch_related("operations__step", "operations__input_lot", "operations__output_lot")
            .filter(finished_lot=lot)
            .first()
        )
        ctx["order"] = order

        # Operaciones de producción
        operations = []
        if order:
            operations = (
                order.operations
                .select_related("step", "input_lot", "output_lot")
                .order_by("sequence", "id")
            )
        ctx["operations"] = operations

        # QA del lote
        qa_inspections = (
            QualityInspection.objects
            .filter(lot=lot)
            .select_related("inspected_by", "plan")
            .order_by("-inspected_at")
        )
        ctx["qa_inspections"] = qa_inspections

        # Clientes que recibieron este lote
        ctx["clients"] = recall_lot.clients.select_related("client").order_by("-quantity_dispatched")

        return ctx