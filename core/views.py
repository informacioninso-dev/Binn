from django.contrib.auth.decorators import login_required
from django.shortcuts import render

@login_required
def dashboard(request):
    # Supongamos que obtienes KPIs desde servicios en inglés:
    data = {
        'stock_total': 1250,
        'sales_this_month': '$ 13.250',
        'pending_invoices': 7,
        'open_work_orders': 3,
        'last_movements': [],  # lista de dicts
    }

    # Mapeas a variables de contexto con nombres en español (solo UI):
    ctx = {
        'kpi_stock_total': data['stock_total'],
        'kpi_ventas_mes': data['sales_this_month'],
        'kpi_facturas_pendientes': data['pending_invoices'],
        'kpi_op_abiertas': data['open_work_orders'],
        'movimientos': data['last_movements'],
    }
    return render(request, 'pages/dashboard.html', ctx)

