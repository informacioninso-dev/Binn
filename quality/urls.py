# quality/urls.py
from django.urls import path
from . import views

app_name = "quality"

urlpatterns = [
    path("", views.QualityIndexView.as_view(), name="index"),

    # Planes de QA
    path("qa-plans/", views.QAPlanListView.as_view(), name="qa_plan_list"),
    path("qa-plans/new/", views.QAPlanCreateView.as_view(), name="qa_plan_create"),
    path("qa-plans/<int:pk>/edit/", views.QAPlanUpdateView.as_view(), name="qa_plan_update"),
    path("qa-plans/<int:pk>/parameters/", views.QAPlanParametersView.as_view(), name="qa_plan_parameters"),

    # Inspecciones
    path("inspections/", views.QualityInspectionListView.as_view(), name="inspection_list"),
    path("inspections/new/", views.QualityInspectionCreateView.as_view(), name="inspection_create"),
    path("inspections/<int:pk>/", views.QualityInspectionDetailView.as_view(), name="inspection_detail"),

    # Pendientes (lotes y operaciones)
    path("pending/", views.PendingLotsQAView.as_view(), name="pending_lots"),

    # 🔹 NUEVO: Recepciones de MP pendientes QA
    path("receptions-qa/",views.ReceptionQAListView.as_view(),name="receptions_qa_list",),
    path("receptions-qa/<int:pk>/",views.ReceptionQADetailView.as_view(),name="receptions_qa_detail",),
    path("receptions-qa/<int:pk>/action/",views.ReceptionQAActionView.as_view(),name="receptions_qa_action",),


    path("audit/lot/<int:pk>/", views.LotAuditView.as_view(), name="audit_lot"),
    path("audit/", views.LotAuditSearchView.as_view(), name="audit_home"),

]
