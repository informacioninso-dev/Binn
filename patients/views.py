from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.shortcuts import render

from .models import Patient


@login_required
def index(request):
    q = (request.GET.get("q") or "").strip()
    patients = Patient.objects.all()
    if q:
        patients = patients.filter(
            Q(last_name__icontains=q) | Q(first_name__icontains=q) | Q(mrn__icontains=q)
        )
    patients = patients.order_by("last_name", "first_name")[:100]
    return render(request, "patients/index.html", {"patients": patients, "q": q})
