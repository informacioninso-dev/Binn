from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied

@login_required
def index(request):
    user = request.user
    if not (user.is_superuser or user.groups.filter(name__in=["admin", "contabilidad"]).exists()):
        raise PermissionDenied
    return render(request, 'finance/index.html')
