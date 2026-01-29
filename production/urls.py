# production/urls 
from django.urls import path
from .views import (
    ProductionDashboardView,
    BillOfMaterialListView,
    BillOfMaterialCreateView,
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
  
)

app_name = "production"

urlpatterns = [
    path("", ProductionDashboardView.as_view(), name="index"),

    path("boms/", BillOfMaterialListView.as_view(), name="bom_list"),
    path("boms/new/", BillOfMaterialCreateView.as_view(), name="bom_create"),
        # Planes de producción
    path("plans/",ProductionPlanListView.as_view(),name="plans_list",),
    path("plans/new/",ProductionPlanCreateView.as_view(),name="plans_create",),
    path("plans/<int:pk>/edit/",ProductionPlanUpdateView.as_view(),name="plans_update",),
       # 🔹 Nueva: crear OP desde un plan
    path("plans/<int:plan_id>/create-order/",ProductionOrderCreateFromPlanView.as_view(),name="plans_create_order",),

    path("orders/", ProductionOrderListView.as_view(), name="orders_list"),
    path("orders/new/planning/", ProductionOrderCreatePlanningView.as_view(),name="orders_create_planning"),
    path("orders/<int:pk>/",ProductionOrderDetailView.as_view(), name="order_detail"),
     path("orders/<int:pk>/execute/",ProductionOrderExecutionView.as_view(),name="orders_execute",),

        # 🔹 Operaciones
    path("operations/",ProductionOperationListView.as_view(),name="operations_list",),
    path( "operations/<int:pk>/edit/", ProductionOperationUpdateView.as_view(), name="operation_edit", ),
   

]
