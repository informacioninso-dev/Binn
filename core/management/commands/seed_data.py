from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Seed base (placeholder) para el nuevo dominio clinico."

    def handle(self, *args, **kwargs):
        self.stdout.write(self.style.SUCCESS("Seed base ejecutado (sin datos por ahora)."))
