# core/middleware.py
from django.shortcuts import redirect
from django.urls import reverse

PUBLIC_PATHS = {'/accounts/login/', '/admin/login/'}

class LoginRequiredMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response
    def __call__(self, request):
        if request.user.is_authenticated:
            return self.get_response(request)
        path = request.path
        if path.startswith('/static/') or path in PUBLIC_PATHS:
            return self.get_response(request)
        return redirect(reverse('login'))
