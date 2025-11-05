from django.core.management.base import BaseCommand
from django.contrib.auth.models import Group, Permission

ROLES = {
    "admin": {"*": ["*"]},  # todos los permisos
    "operaciones": {"inventory": ["view_", "add_", "change_"], "production": ["view_", "add_", "change_"]},
    "contabilidad": {"finance": ["view_", "add_", "change_"], "billing": ["view_", "add_", "change_"]},
    "comercial": {"inventory": ["view_"], "billing": ["view_", "add_"]},
}

class Command(BaseCommand):
    help = "Crea grupos base y asigna permisos por app/prefijo"

    def handle(self, *args, **kwargs):
        for role, apps in ROLES.items():
            group, _ = Group.objects.get_or_create(name=role)
            perms = Permission.objects.none()
            if apps == {"*": ["*"]}:
                perms = Permission.objects.all()
            else:
                for app_label, prefixes in apps.items():
                    qs = Permission.objects.filter(content_type__app_label=app_label)
                    for pref in prefixes:
                        perms = perms | qs.filter(codename__startswith=pref)
            group.permissions.set(perms.distinct())
            self.stdout.write(self.style.SUCCESS(f"✓ Grupo '{role}' actualizado"))
        self.stdout.write(self.style.SUCCESS("Listo."))
