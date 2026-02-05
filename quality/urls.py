# quality/urls.py
from django.urls import path
from . import views
from . import exports

app_name = "quality"

urlpatterns = [
    path("", views.QualityIndexView.as_view(), name="index"),

    # Planes de QA
    path("qa-plans/", views.QAPlanListView.as_view(), name="qa_plan_list"),
    path("qa-plans/export/pdf/", exports.QAPlanListPDFView.as_view(), name="qa_plan_list_pdf"),
    path("qa-plans/export/excel/", exports.QAPlanListExcelView.as_view(), name="qa_plan_list_excel"),
    path("qa-plans/new/", views.QAPlanCreateView.as_view(), name="qa_plan_create"),
    path("qa-plans/<int:pk>/edit/", views.QAPlanUpdateView.as_view(), name="qa_plan_update"),
    path("qa-plans/<int:pk>/parameters/", views.QAPlanParametersView.as_view(), name="qa_plan_parameters"),

    # Inspecciones
    path("inspections/", views.QualityInspectionListView.as_view(), name="inspection_list"),
    path("inspections/new/", views.QualityInspectionCreateView.as_view(), name="inspection_create"),
    path("inspections/<int:pk>/", views.QualityInspectionDetailView.as_view(), name="inspection_detail"),
    path("inspections/export/pdf/", exports.InspectionListPDFView.as_view(), name="inspection_list_pdf"),
    path("inspections/export/excel/", exports.InspectionListExcelView.as_view(), name="inspection_list_excel"),

    # Pendientes (lotes y operaciones)
    path("pending/", views.PendingLotsQAView.as_view(), name="pending_lots"),

    # 🔹 NUEVO: Recepciones de MP pendientes QA
    path("receptions-qa/",views.ReceptionQAListView.as_view(),name="receptions_qa_list",),
    path("receptions-qa/<int:pk>/",views.ReceptionQADetailView.as_view(),name="receptions_qa_detail",),
    path("receptions-qa/<int:pk>/action/",views.ReceptionQAActionView.as_view(),name="receptions_qa_action",),


    path("audit/lot/<int:pk>/", views.LotAuditView.as_view(), name="audit_lot"),
    path("audit/", views.LotAuditSearchView.as_view(), name="audit_home"),

    # Retiro de mercado
    path("recalls/", views.ProductRecallListView.as_view(), name="recall_list"),
    path("recalls/export/pdf/", exports.RecallListPDFView.as_view(), name="recall_list_pdf"),
    path("recalls/export/excel/", exports.RecallListExcelView.as_view(), name="recall_list_excel"),
    path("recall/create/", views.ProductRecallCreateView.as_view(), name="recall_create"),
    path("recall/<int:pk>/", views.ProductRecallDetailView.as_view(), name="recall_detail"),
    path("recall/<int:pk>/activate/", views.activate_recall_view, name="recall_activate"),
    path("recall/<int:pk>/start-notification/", views.start_notification_view, name="recall_start_notification"),
    path("recall/<int:pk>/client/<int:client_pk>/notify/", views.mark_notified_view, name="recall_mark_notified"),
    path("recall/<int:pk>/client/<int:client_pk>/recover/", views.mark_recovered_view, name="recall_mark_recovered"),
    path("recall/<int:pk>/complete/", views.complete_recall_view, name="recall_complete"),
    path("recall/lot/<int:pk>/audit/", views.RecallLotAuditView.as_view(), name="recall_lot_audit"),
]
