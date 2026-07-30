from types import SimpleNamespace

from django.test import SimpleTestCase

from core.views import build_dashboard_experience
from tenants.defaults import PROFILE_GENERAL, PROFILE_SERVICIOS


class DashboardLayoutExperienceTests(SimpleTestCase):
    def _tenant(
        self,
        *,
        profile=PROFILE_SERVICIOS,
        homepage_layout=None,
        module_order=None,
        dashboard_widgets=None,
        feature_flags=None,
    ):
        return SimpleNamespace(
            tenant_config=SimpleNamespace(
                profile=profile,
                labels={
                    "entity_plural": "Clientes",
                    "deal_plural": "Oportunidades",
                    "document_plural": "Documentos",
                    "proposal_plural": "Propuestas",
                    "collection_plural": "Cobros",
                },
                feature_flags=feature_flags
                or {
                    "entities": True,
                    "deals": True,
                    "activities": True,
                    "documents": True,
                    "proposals": True,
                    "collections": True,
                    "reports": True,
                    "kanban": True,
                },
                module_order=module_order or [
                    "entities",
                    "deals",
                    "documents",
                    "proposals",
                    "collections",
                    "activities",
                    "reports",
                ],
                dashboard_widgets=dashboard_widgets
                or [
                    "guided_steps",
                    "quick_actions",
                    "summary_cards",
                    "pipeline_panel",
                    "entity_panel",
                    "activity_panel",
                ],
                homepage_layout=homepage_layout or {},
            )
        )

    def test_hero_metric_prioritizes_summary_cards_for_collections(self):
        tenant = self._tenant(
            homepage_layout={
                "mode": "collections",
                "hero_metric": "open_collections",
                "density": "comfortable",
                "show_guided_steps": True,
            },
            module_order=["entities", "deals", "proposals", "collections", "activities"],
        )

        dashboard = build_dashboard_experience(
            tenant,
            {
                "entities": 6,
                "open_deals": 4,
                "activities_due": 2,
                "documents": 1,
                "open_proposals": 3,
                "open_collections": 9,
                "report_alerts": 0,
            },
        )

        self.assertEqual(dashboard["layout_mode"], "collections")
        self.assertEqual(dashboard["layout_mode_label"], "Centro de cobranza")
        self.assertEqual(dashboard["hero_metric"], "open_collections")
        self.assertEqual(dashboard["summary_cards"][0]["title"], "Cobros")

    def test_compact_density_expands_limits_to_six_cards_and_actions(self):
        tenant = self._tenant(
            homepage_layout={
                "mode": "sales",
                "hero_metric": "open_deals",
                "density": "compact",
                "show_guided_steps": True,
            },
            module_order=["entities", "deals", "documents", "proposals", "collections", "activities", "reports"],
        )

        dashboard = build_dashboard_experience(
            tenant,
            {
                "entities": 18,
                "open_deals": 7,
                "activities_due": 5,
                "documents": 11,
                "open_proposals": 4,
                "open_collections": 3,
                "report_alerts": 2,
            },
        )

        self.assertEqual(dashboard["layout_density"], "compact")
        self.assertEqual(dashboard["summary_card_limit"], 6)
        self.assertEqual(dashboard["quick_action_limit"], 6)
        self.assertEqual(len(dashboard["summary_cards"]), 6)
        self.assertEqual(len(dashboard["quick_actions"]), 6)

    def test_layout_can_disable_guided_steps(self):
        tenant = self._tenant(
            profile=PROFILE_GENERAL,
            homepage_layout={
                "mode": "operations",
                "hero_metric": "activities_due",
                "density": "comfortable",
                "show_guided_steps": False,
            },
        )

        dashboard = build_dashboard_experience(
            tenant,
            {
                "entities": 0,
                "open_deals": 0,
                "activities_due": 0,
                "activities_total": 0,
                "documents": 0,
                "open_proposals": 0,
                "open_collections": 0,
                "report_alerts": 0,
            },
        )

        self.assertEqual(dashboard["guided_steps"], [])
        self.assertEqual(dashboard["layout_mode_label"], "Operacion diaria")
        self.assertEqual(dashboard["hero_metric_label"], "Tareas por vencer")
