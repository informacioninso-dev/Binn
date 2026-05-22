from __future__ import annotations

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.core.management import call_command
from django.core import mail

from core.runtime_services import get_runtime_services_status, is_runtime_healthy
from identity.forms import StrictPasswordResetForm
from tenants.models import Client


class Command(BaseCommand):
    help = "Ejecuta smoke tests operativos de salida: deploy checks, runtime, password reset y tenant/domain."

    def add_arguments(self, parser):
        parser.add_argument("--username", help="Usuario al que se le probara el password reset.")
        parser.add_argument("--email", help="Email al que se le probara el password reset.")
        parser.add_argument("--tenant-schema", help="Schema tenant que debe existir y tener dominio.")
        parser.add_argument(
            "--allow-unhealthy-runtime",
            action="store_true",
            help="No falla aunque la sonda runtime encuentre servicios degradados.",
        )

    def handle(self, *args, **options):
        call_command("check", "--deploy", stdout=self.stdout)

        checks: list[tuple[str, str]] = []
        self._check_superuser_exists(checks)
        self._check_runtime_health(checks, allow_unhealthy=options["allow_unhealthy_runtime"])
        self._check_password_reset(checks, username=options.get("username"), email=options.get("email"))
        if options.get("tenant_schema"):
            self._check_tenant_domain(checks, schema_name=options["tenant_schema"])

        for status, message in checks:
            writer = self.style.SUCCESS if status == "ok" else self.style.WARNING
            self.stdout.write(writer(f"[{status.upper()}] {message}"))

    def _check_superuser_exists(self, checks: list[tuple[str, str]]) -> None:
        if not get_user_model().objects.filter(is_superuser=True, is_active=True).exists():
            raise CommandError("No existe ningun superuser activo para operacion.")
        checks.append(("ok", "Existe al menos un superuser activo."))

    def _check_runtime_health(self, checks: list[tuple[str, str]], *, allow_unhealthy: bool) -> None:
        runtime_status = get_runtime_services_status()
        if not is_runtime_healthy(runtime_status):
            unhealthy = [key for key, value in runtime_status.items() if not value.healthy]
            if not allow_unhealthy:
                raise CommandError(f"Runtime degradado en: {', '.join(unhealthy)}.")
            checks.append(("warn", f"Runtime degradado en: {', '.join(unhealthy)}."))
            return
        checks.append(("ok", "Runtime services responden sanos."))

    def _check_password_reset(self, checks: list[tuple[str, str]], *, username: str | None, email: str | None) -> None:
        user_model = get_user_model()
        target_user = None
        if username:
            target_user = user_model.objects.filter(username=username, is_active=True).first()
        elif email:
            target_user = user_model.objects.filter(email__iexact=email, is_active=True).first()
        else:
            target_user = user_model.objects.filter(is_active=True).exclude(email="").order_by("is_superuser", "id").last()

        if target_user is None or not target_user.email:
            raise CommandError("No existe un usuario activo con email para probar password reset.")

        form = StrictPasswordResetForm({"email": target_user.email})
        if not form.is_valid():
            raise CommandError("El formulario de password reset no valido el email objetivo.")

        initial_outbox_size = len(getattr(mail, "outbox", [])) if hasattr(mail, "outbox") else None
        form.save(
            domain_override=settings.ALLOWED_HOSTS[0] if settings.ALLOWED_HOSTS else "localhost",
            from_email=settings.DEFAULT_FROM_EMAIL,
            use_https=bool(getattr(settings, "ENABLE_SSL", False)),
            subject_template_name="auth/password_reset_subject.txt",
            email_template_name="auth/password_reset_email.txt",
        )

        if initial_outbox_size is not None and len(mail.outbox) <= initial_outbox_size:
            raise CommandError("La prueba de password reset no genero ningun correo en el backend actual.")
        checks.append(("ok", f"Password reset generado para {target_user.email}."))

    def _check_tenant_domain(self, checks: list[tuple[str, str]], *, schema_name: str) -> None:
        tenant = Client.objects.filter(schema_name=schema_name).prefetch_related("domains").first()
        if tenant is None:
            raise CommandError(f"No existe tenant con schema {schema_name}.")
        if not tenant.primary_domain:
            raise CommandError(f"El tenant {schema_name} no tiene dominio configurado.")
        checks.append(("ok", f"Tenant {schema_name} tiene dominio primario {tenant.primary_domain}."))
