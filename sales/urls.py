from django.urls import path
from . import views

urlpatterns = [
    path('', views.SalesIndexView.as_view(), name='index'),  
    path('orders', views.SaleOrderListView.as_view(), name='order_list'),
    path('order/<int:pk>/', views.SaleOrderDetailView.as_view(), name='order_detail'),
    path('order/create/', views.SaleOrderCreateView.as_view(), name='order_create'),
    path('order/confirm/<int:pk>/', views.confirm_order, name='confirm_order'),
]
