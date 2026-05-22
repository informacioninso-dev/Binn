from .runtime import build_access_subject
from .services import load_active_session_context


class ActiveAccessContextMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.access_subject = build_access_subject(getattr(request, "user", None))
        request.active_session_context = load_active_session_context(request)
        return self.get_response(request)
