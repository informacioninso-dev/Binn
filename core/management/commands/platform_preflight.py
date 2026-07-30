from __future__ import annotations

import json

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
        parser.add_argument(
            "--fail-on-warn",
            action="store_true",
            help="Devuelve error si existe al menos un warning o un check bloqueante.",
        )
        parser.add_argument(
            "--json",
            action="store_true",
            help="Imprime el resultado en JSON para pipelines o CI.",
        )

    def handle(self, *args, **options):
        checks = run_platform_preflight()
        summary = summarize_preflight(checks)
        payload = {
            "summary": summary,
            "checks": [
                {
                    "code": check.code,
                    "label": check.label,
                    "status": check.status,
                    "message": check.message,
                }
                for check in checks
            ],
        }

        if options["json"]:
            self.stdout.write(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
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

        if options["fail_on_warn"] and (summary["warn"] or summary["fail"]):
            raise CommandError("El preflight detecto warnings o checks bloqueantes.")
        if options["strict"] and summary["fail"]:
            raise CommandError("El preflight detecto checks bloqueantes.")
