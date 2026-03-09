from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from .models import Appointment


@login_required
def index(request):
    appointments = Appointment.objects.select_related("patient").order_by("-scheduled_at")[:100]
    return render(request, "appointments/index.html", {"appointments": appointments})
