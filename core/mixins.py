# core/mixins.py
"""
Mixins de control de acceso reutilizables.
"""
from django.contrib.auth.mixins import PermissionRequiredMixin
from django.core.exceptions import PermissionDenied


class ModulePermissionMixin(PermissionRequiredMixin):
    """
    Extiende PermissionRequiredMixin para redirigir con un mensaje
    cuando el usuario no tiene permisos en vez de mostrar 403.
    Los superusuarios y miembros del grupo 'admin' tienen acceso total.
    """
    raise_exception = True

    def has_permission(self):
        user = self.request.user
        if user.is_superuser or user.groups.filter(name="admin").exists():
            return True
        return super().has_permission()
