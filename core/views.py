from django.contrib.auth.decorators import login_required
from django.shortcuts import render


@login_required
def dashboard(request):
    tenant = getattr(request, "tenant", None)
    return render(
        request,
        "pages/dashboard.html",
        {
            "tenant_name": getattr(tenant, "name", ""),
            "tenant_schema": getattr(tenant, "schema_name", ""),
        },
    )
