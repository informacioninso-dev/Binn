from django.apps import AppConfig


class IdentityConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "identity"
    verbose_name = "Identity"

    def ready(self):
        from . import signals  # noqa: F401
