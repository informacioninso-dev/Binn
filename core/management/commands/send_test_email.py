from __future__ import annotations

from django.conf import settings
from django.core.mail import EmailMessage
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Envia un correo de prueba usando la configuracion activa."

    def add_arguments(self, parser):
        parser.add_argument("recipient", help="Direccion de email destino.")
        parser.add_argument("--subject", default="Binn test email", help="Asunto del correo.")

    def handle(self, *args, **options):
        recipient = options["recipient"].strip()
        if not recipient:
            raise CommandError("Debes indicar un destinatario valido.")

        message = EmailMessage(
            subject=options["subject"],
            body="Este es un correo de prueba enviado desde la configuracion activa de Binn.",
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[recipient],
        )
        sent = message.send(fail_silently=False)
        if sent != 1:
            raise CommandError("El backend no confirmo el envio del correo de prueba.")
        self.stdout.write(self.style.SUCCESS(f"Correo de prueba enviado a {recipient}."))
