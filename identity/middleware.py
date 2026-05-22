from django.contrib import messages
from django.shortcuts import redirect
from django.urls import reverse

from .services import touch_authenticated_session


class GlobalSessionMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        touch_authenticated_session(request)
        return response


class PasswordRotationMiddleware:
    EXEMPT_PATH_PREFIXES = (
        "/static/",
        "/media/",
        "/health/",
        "/accounts/password/change/",
        "/accounts/logout/",
        "/accounts/password/reset/",
        "/accounts/reset/",
        "/admin/",
    )

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        if (
            user is not None
            and getattr(user, "is_authenticated", False)
            and getattr(user, "must_rotate_password", False)
            and not any(request.path.startswith(prefix) for prefix in self.EXEMPT_PATH_PREFIXES)
        ):
            messages.warning(request, "Debes cambiar tu contrasena antes de seguir operando.")
            return redirect(reverse("password_change"))
        return self.get_response(request)
