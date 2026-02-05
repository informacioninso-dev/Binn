from django.urls import path
from . import views
from . import exports

urlpatterns = [
    path('', views.SalesIndexView.as_view(), name='index'),
    path('orders', views.SaleOrderListView.as_view(), name='order_list'),
    path('order/<int:pk>/', views.SaleOrderDetailView.as_view(), name='order_detail'),
    path('order/create/', views.SaleOrderCreateView.as_view(), name='order_create'),
    path('order/confirm/<int:pk>/', views.confirm_order, name='confirm_order'),

    # Exportaciones — listado
    path('orders/export/pdf/', exports.SaleOrderListPDFView.as_view(), name='order_list_pdf'),
    path('orders/export/excel/', exports.SaleOrderListExcelView.as_view(), name='order_list_excel'),

    # Exportaciones — detalle individual
    path('order/<int:pk>/export/pdf/', exports.SaleOrderDetailPDFView.as_view(), name='order_detail_pdf'),
    path('order/<int:pk>/export/excel/', exports.SaleOrderDetailExcelView.as_view(), name='order_detail_excel'),

    # Picking
    path('order/<int:pk>/dispatch/check/', views.DispatchCheckView.as_view(), name='dispatch_check'),
    path('order/<int:pk>/picking/create/', views.PickingCreateView.as_view(), name='picking_create'),
    path('picking/<int:pk>/', views.PickingDetailView.as_view(), name='picking_detail'),
    path('pickings/', views.PickingListView.as_view(), name='picking_list'),

    # Packing
    path('packing/<int:pk>/', views.PackingDetailView.as_view(), name='packing_detail'),

    # Despacho
    path('order/<int:pk>/dispatch/confirm/', views.DispatchConfirmView.as_view(), name='dispatch_confirm'),
    path('dispatches/', views.DispatchListView.as_view(), name='dispatch_list'),

    # Facturación
    path('invoices/', views.InvoiceListView.as_view(), name='invoice_list'),
    path('order/<int:pk>/invoice/create/', views.InvoiceCreateView.as_view(), name='invoice_create'),
    path('invoice/<int:pk>/', views.InvoiceDetailView.as_view(), name='invoice_detail'),
    path('invoice/<int:pk>/send-sri/', views.InvoiceSendSRIView.as_view(), name='invoice_send_sri'),
    path('invoice/<int:pk>/ride/', views.InvoiceRIDEView.as_view(), name='invoice_ride_pdf'),

    # Guías de Remisión
    path('guias/', views.GuiaRemisionListView.as_view(), name='guia_list'),
    path('dispatch/<int:dispatch_pk>/guia/create/', views.GuiaRemisionCreateView.as_view(), name='guia_create'),
    path('guia/<int:pk>/', views.GuiaRemisionDetailView.as_view(), name='guia_detail'),
    path('guia/<int:pk>/send-sri/', views.GuiaRemisionSendSRIView.as_view(), name='guia_send_sri'),
    path('guia/<int:pk>/ride/', views.GuiaRemisionRIDEView.as_view(), name='guia_ride_pdf'),

    # Devoluciones
    path('returns/', views.SaleReturnListView.as_view(), name='return_list'),
    path('returns/create/', views.SaleReturnCreateView.as_view(), name='return_create'),
    path('return/<int:pk>/', views.SaleReturnDetailView.as_view(), name='return_detail'),
    path('return/<int:pk>/receive/', views.receive_return_view, name='return_receive'),
    path('return/<int:pk>/approve/', views.approve_return_view, name='return_approve'),
    path('return/<int:pk>/reject/', views.reject_return_view, name='return_reject'),
    path('return/<int:pk>/credit-note/', views.issue_credit_note_view, name='return_credit_note'),

    # Notas de crédito
    path('credit-notes/', views.CreditNoteListView.as_view(), name='credit_note_list'),
]
