from types import SimpleNamespace
from django.test import SimpleTestCase

from governance.models import CorporateGroup

from .services import (
    build_group_dashboard_row,
    build_group_report_sections,
    calculate_tenant_risk_score,
    empty_metric_bucket,
    merge_metric_buckets,
)


class ConsolidationMetricTests(SimpleTestCase):
    def test_merge_metric_buckets_accumulates_counts_and_amounts(self):
        target = empty_metric_bucket()
        target["entity_count"] = 3
        target["open_deals_count"] = 2
        target["open_deal_amounts"] = {"USD": "10.00"}

        incoming = empty_metric_bucket()
        incoming["entity_count"] = 4
        incoming["open_deals_count"] = 1
        incoming["open_deal_amounts"] = {"USD": "5.50", "EUR": "9.00"}

        merged = merge_metric_buckets(target, incoming)

        self.assertEqual(merged["entity_count"], 7)
        self.assertEqual(merged["open_deals_count"], 3)
        self.assertEqual(merged["open_deal_amounts"], {"EUR": "9.00", "USD": "15.50"})


class ConsolidationDashboardRowTests(SimpleTestCase):
    def _link(self, *, mode, allow_consolidation=True):
        group = SimpleNamespace(
            status=CorporateGroup.STATUS_ACTIVE,
        )
        tenant = SimpleNamespace(name="Acme", schema_name="acme", allow_consolidation=allow_consolidation)
        return SimpleNamespace(
            tenant=tenant,
            group=group,
            effective_mode=mode,
        )

    def _snapshot(self):
        return SimpleNamespace(
            entity_count=12,
            open_deals_count=4,
            pending_activities_count=7,
            overdue_activities_count=2,
            open_proposals_count=3,
            open_collections_count=5,
            open_deal_amounts={"USD": "100.00"},
            outstanding_balance_amounts={"USD": "30.00"},
            last_synced_at=None,
        )

    def test_blocked_row_hides_metrics_and_drilldown(self):
        row = build_group_dashboard_row(link=self._link(mode=CorporateGroup.MODE_BLOCKED), snapshot=self._snapshot())

        self.assertFalse(row["metrics_visible"])
        self.assertFalse(row["detail_allowed"])
        self.assertIsNone(row["entity_count"])
        self.assertEqual(row["mode_label"], "Bloqueado")

    def test_aggregate_only_row_exposes_metrics_without_drilldown(self):
        row = build_group_dashboard_row(link=self._link(mode=CorporateGroup.MODE_AGGREGATE_ONLY), snapshot=self._snapshot())

        self.assertTrue(row["metrics_visible"])
        self.assertFalse(row["detail_allowed"])
        self.assertEqual(row["entity_count"], 12)
        self.assertEqual(row["open_deal_amounts_display"], "USD 100.00")

    def test_full_row_allows_detail(self):
        row = build_group_dashboard_row(link=self._link(mode=CorporateGroup.MODE_FULL), snapshot=self._snapshot())

        self.assertTrue(row["metrics_visible"])
        self.assertTrue(row["detail_allowed"])
        self.assertEqual(row["status_copy"], "El holding puede abrir esta empresa y operar con detalle completo.")

    def test_full_row_surfaces_missing_assignment_message(self):
        user = SimpleNamespace(is_authenticated=True, is_superuser=False)
        original_resolver = build_group_dashboard_row.__globals__["resolve_group_tenant_detail_access"]
        build_group_dashboard_row.__globals__["resolve_group_tenant_detail_access"] = (
            lambda **_: SimpleNamespace(allowed=False, reason="missing_group_tenant_access")
        )
        try:
            row = build_group_dashboard_row(
                link=self._link(mode=CorporateGroup.MODE_FULL),
                snapshot=self._snapshot(),
                user=user,
                membership=SimpleNamespace(can_manage_group=lambda: False),
            )
        finally:
            build_group_dashboard_row.__globals__["resolve_group_tenant_detail_access"] = original_resolver

        self.assertFalse(row["detail_allowed"])
        self.assertIn("todavia no tiene acceso asignado", row["status_copy"])


class ConsolidationReportSectionTests(SimpleTestCase):
    def test_tenant_risk_score_weights_operational_backlog(self):
        score = calculate_tenant_risk_score(
            {
                "overdue_activities_count": 2,
                "overdue_collections_count": 1,
                "expiring_documents_count": 3,
                "open_deals_count": 4,
            }
        )

        self.assertEqual(score, 26)

    def test_group_report_sections_build_rankings_and_risk_rows(self):
        tenant_alpha = SimpleNamespace(name="Alpha")
        tenant_beta = SimpleNamespace(name="Beta")
        sections = build_group_report_sections(
            tenant_rows=[
                {
                    "tenant": tenant_alpha,
                    "profile_label": "Broker",
                    "metrics_visible": True,
                    "detail_allowed": True,
                    "effective_mode": CorporateGroup.MODE_FULL,
                    "entity_count": 10,
                    "open_deals_count": 3,
                    "open_collections_count": 2,
                    "overdue_activities_count": 1,
                    "overdue_collections_count": 1,
                    "expiring_documents_count": 0,
                    "risk_score": 9,
                },
                {
                    "tenant": tenant_beta,
                    "profile_label": "Condominio",
                    "metrics_visible": True,
                    "detail_allowed": False,
                    "effective_mode": CorporateGroup.MODE_AGGREGATE_ONLY,
                    "entity_count": 22,
                    "open_deals_count": 5,
                    "open_collections_count": 8,
                    "overdue_activities_count": 2,
                    "overdue_collections_count": 0,
                    "expiring_documents_count": 3,
                    "risk_score": 17,
                },
            ]
        )

        self.assertEqual(sections["leaderboards"][0]["rows"][0]["tenant_name"], "Beta")
        self.assertEqual(sections["risk_rows"][0]["tenant_name"], "Beta")
        self.assertEqual(sections["mode_summary"][0]["label"], "Detalle total")
