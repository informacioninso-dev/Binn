# core/context_processors.py
"""
Inyecta flags de acceso por módulo para controlar la visibilidad del sidebar
y otros elementos de la UI según los permisos del usuario.
"""

# Mapeo: clave del módulo → app_label(s) que se revisan
MODULE_APP_MAP = {
    "partners":    ["partners"],
    "procurement": ["procurement"],
    "production":  ["production"],
    "quality":     ["quality"],
    "sales":       ["sales"],
    "inventory":   ["inventory"],
    "finance":     ["finance"],
    "billing":     ["billing"],
    "core":        ["core"],
}


def module_access(request):
    """
    Devuelve un dict ``modules`` donde cada clave es un nombre de módulo
    y el valor es True/False indicando si el usuario tiene al menos un
    permiso en alguna de las apps asociadas.

    Superusuarios y miembros del grupo 'admin' ven todo.
    """
    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated:
        return {"modules": {k: False for k in MODULE_APP_MAP}}

    # Superusuarios o miembros del grupo admin ven todo
    if user.is_superuser or user.groups.filter(name="admin").exists():
        return {"modules": {k: True for k in MODULE_APP_MAP}}

    # Obtener todos los permisos del usuario (directos + de grupo)
    user_perms = user.get_all_permissions()  # set de "app_label.codename"
    app_labels_with_access = {p.split(".")[0] for p in user_perms}

    modules = {}
    for module, apps in MODULE_APP_MAP.items():
        modules[module] = any(app in app_labels_with_access for app in apps)

    return {"modules": modules}
