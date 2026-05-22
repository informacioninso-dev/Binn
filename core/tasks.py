from __future__ import annotations

from core.preflight import run_platform_preflight, summarize_preflight
from core.tasking import shared_task


@shared_task(name="core.platform_preflight_snapshot")
def platform_preflight_snapshot_task(*, strict: bool = False):
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
    if strict and summary["fail"]:
        payload["status"] = "fail"
    else:
        payload["status"] = "ok"
    return payload
