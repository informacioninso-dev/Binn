from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch

from django.http import HttpResponse
from django.test import RequestFactory, SimpleTestCase
from django.utils import timezone

from .models import ConsolidationRun
from .views import (
    CorporateGroupReportsView,
    _build_run_status_summary,
    _snapshot_freshness_badge,
)


class ConsolidationReportTelemetryTests(SimpleTestCase):
    def test_run_status_summary_counts_recent_statuses(self):
        cards = _build_run_status_summary(
            [
                SimpleNamespace(status=ConsolidationRun.STATUS_SUCCEEDED),
                SimpleNamespace(status=ConsolidationRun.STATUS_FAILED),
                SimpleNamespace(status=ConsolidationRun.STATUS_FAILED),
                SimpleNamespace(status=ConsolidationRun.STATUS_RUNNING),
            ]
        )

        values = {item["label"]: item["value"] for item in cards}

        self.assertEqual(values["Corridas OK"], 1)
        self.assertEqual(values["En progreso"], 1)
        self.assertEqual(values["Fallidas"], 2)

    def test_snapshot_freshness_badge_marks_stale_snapshots(self):
        now = timezone.now()

        badge = _snapshot_freshness_badge(
            SimpleNamespace(last_synced_at=now - timedelta(minutes=31)),
            now=now,
        )

        self.assertEqual(badge["tone"], "bg-amber-50 text-amber-700")
        self.assertIn("Desactualizado", badge["label"])


class ConsolidationReportViewTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()

    @patch("consolidation.views.render", return_value=HttpResponse("ok"))
    @patch("consolidation.views.record_governance_event")
    @patch("consolidation.views.set_consolidated_context")
    @patch("consolidation.views.build_group_pack_mix", return_value=[])
    @patch(
        "consolidation.views.build_group_report_sections",
        return_value={"leaderboards": [], "risk_rows": [], "mode_summary": []},
    )
    @patch("consolidation.views.build_group_dashboard_rows", return_value=[])
    @patch("consolidation.views.ensure_group_snapshot_fresh")
    @patch(
        "consolidation.views.get_group_dashboard_access",
        return_value=SimpleNamespace(allowed=True, membership=None),
    )
    @patch("consolidation.views.CorporateGroup")
    def test_group_reports_can_force_refresh_snapshot(
        self,
        corporate_group_mock,
        access_mock,
        ensure_snapshot_mock,
        dashboard_rows_mock,
        report_sections_mock,
        profile_mix_mock,
        set_context_mock,
        record_event_mock,
        render_mock,
    ):
        group = SimpleNamespace(
            pk=7,
            name="Holding Uno",
            consolidation_runs=SimpleNamespace(
                order_by=lambda *args: [SimpleNamespace(status=ConsolidationRun.STATUS_FAILED)]
            ),
        )
        corporate_group_mock.objects.filter.return_value.first.return_value = group
        ensure_snapshot_mock.return_value = SimpleNamespace(
            included_tenants_count=3,
            last_synced_at=timezone.now(),
        )
        request = self.factory.get("/consolidation/groups/7/reports/?refresh=1")
        request.user = SimpleNamespace(is_authenticated=True)
        request.session = {}

        response = CorporateGroupReportsView.as_view()(request, pk=group.pk)

        self.assertEqual(response.status_code, 200)
        ensure_snapshot_mock.assert_called_once_with(
            group=group,
            actor=request.user,
            trigger="group_reports",
            force=True,
        )
        context = render_mock.call_args.args[2]
        self.assertEqual(context["run_status_summary"][2]["value"], 1)
        self.assertEqual(
            context["snapshot_freshness"]["tone"],
            "bg-emerald-50 text-emerald-700",
        )
        metadata = record_event_mock.call_args.kwargs["metadata"]
        self.assertEqual(metadata["force_refresh"], "True")
