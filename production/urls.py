# production/urls
from django.urls import path
from .views import (
    ProductionDashboardView,
    BillOfMaterialListView,
    BillOfMaterialCreateView,
    BillOfMaterialUpdateView,
    ProductionOrderListView,
    ProductionOrderCreatePlanningView,
    ProductionOperationUpdateView,
    ProductionOperationListView,
    ProductionOrderDetailView,
    ProductionOrderExecutionView,
    ProductionPlanListView,
    ProductionPlanCreateView,
    ProductionPlanUpdateView,
    ProductionOrderCreateFromPlanView,
    ProductionOrderReleaseView,
    PlanCalculateMaterialsView,
    ProductionPlanCancelView,
    WorkCenterListView,
    WorkCenterCreateView,
    WorkCenterUpdateView,
    ProductRouteListView,
    ProductRouteCreateView,
    ProductRouteUpdateView,
    MaterialTransferListView,
    MaterialTransferConfirmView,
    EstimateProductionTimeView,
    ProductionGanttView,
)

app_name = "production"

urlpatterns = [
    path("", ProductionDashboardView.as_view(), name="index"),

    path("boms/", BillOfMaterialListView.as_view(), name="bom_list"),
    path("boms/new/", BillOfMaterialCreateView.as_view(), name="bom_create"),
    path("boms/<int:pk>/edit/", BillOfMaterialUpdateView.as_view(), name="bom_update"),

    # Planes de producción
    path("plans/",ProductionPlanListView.as_view(),name="plans_list",),
    path("plans/new/",ProductionPlanCreateView.as_view(),name="plans_create",),
    path("plans/<int:pk>/edit/",ProductionPlanUpdateView.as_view(),name="plans_update",),
    path("plans/<int:pk>/cancel/",ProductionPlanCancelView.as_view(),name="plans_cancel",),
    # AJAX: cálculo FEFO de materias primas
    path("plans/calculate-materials/", PlanCalculateMaterialsView.as_view(), name="plans_calculate_materials"),
       # 🔹 Nueva: crear OP desde un plan
    path("plans/<int:plan_id>/create-order/",ProductionOrderCreateFromPlanView.as_view(),name="plans_create_order",),

    path("orders/<int:pk>/release/", ProductionOrderReleaseView.as_view(), name="orders_release"),
    path("orders/", ProductionOrderListView.as_view(), name="orders_list"),
    path("orders/new/planning/", ProductionOrderCreatePlanningView.as_view(),name="orders_create_planning"),
    path("orders/<int:pk>/",ProductionOrderDetailView.as_view(), name="order_detail"),
     path("orders/<int:pk>/execute/",ProductionOrderExecutionView.as_view(),name="orders_execute",),

        # 🔹 Operaciones
    path("operations/",ProductionOperationListView.as_view(),name="operations_list",),
    path( "operations/<int:pk>/edit/", ProductionOperationUpdateView.as_view(), name="operation_edit", ),

    # Estaciones de trabajo
    path("workcenters/", WorkCenterListView.as_view(), name="workcenters_list"),
    path("workcenters/new/", WorkCenterCreateView.as_view(), name="workcenters_create"),
    path("workcenters/<int:pk>/edit/", WorkCenterUpdateView.as_view(), name="workcenters_update"),

    # Rutas de producción
    path("routes/", ProductRouteListView.as_view(), name="routes_list"),
    path("routes/new/", ProductRouteCreateView.as_view(), name="routes_create"),
    path("routes/<int:pk>/edit/", ProductRouteUpdateView.as_view(), name="routes_update"),

    # Transferencias de material
    path("orders/<int:pk>/transfers/", MaterialTransferListView.as_view(), name="order_transfers"),
    path("transfers/<int:pk>/confirm/", MaterialTransferConfirmView.as_view(), name="transfer_confirm"),

    # Estimación de tiempo (AJAX)
    path("estimate-time/", EstimateProductionTimeView.as_view(), name="estimate_time"),

    # Diagrama de Gantt
    path("gantt/", ProductionGanttView.as_view(), name="gantt"),
]
