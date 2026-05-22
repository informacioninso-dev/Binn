from django.contrib.auth.signals import user_logged_in, user_logged_out
from django.dispatch import receiver

from .services import close_authenticated_session, register_authenticated_session


@receiver(user_logged_in)
def handle_user_logged_in(sender, request, user, **kwargs):
    register_authenticated_session(request, user)


@receiver(user_logged_out)
def handle_user_logged_out(sender, request, user, **kwargs):
    close_authenticated_session(request, user, reason="logout")
