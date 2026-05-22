from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from core.preflight import run_platform_preflight, summarize_preflight


class Command(BaseCommand):
    help = "Ejecuta un preflight de plataforma para revisar configuracion base antes de despliegue."

    def add_arguments(self, parser):
        parser.add_argument(
            "--strict",
            action="store_true",
            help="Devuelve error si existe al menos un check bloqueante.",
        )

    def handle(self, *args, **options):
        checks = run_platform_preflight()
        summary = summarize_preflight(checks)

        for check in checks:
            style = {
                "ok": self.style.SUCCESS,
                "warn": self.style.WARNING,
                "fail": self.style.ERROR,
            }.get(check.status, self.style.WARNING)
            self.stdout.write(style(f"[{check.status.upper()}] {check.label}: {check.message}"))

        self.stdout.write(
            self.style.NOTICE(
                f"Resumen preflight -> ok: {summary['ok']} | warn: {summary['warn']} | fail: {summary['fail']}"
            )
        )

        if options["strict"] and summary["fail"]:
            raise CommandError("El preflight detecto checks bloqueantes.")
