from contextlib import nullcontext
from datetime import date, datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.http import HttpResponse
from django.test import RequestFactory, SimpleTestCase

from .audit import record_crm_audit_event
from .models import Activity, CollectionRecord
from .views import activity_toggle_complete, collection_move, deal_move, entity_import


def unwrap_view(view_func):
    while hasattr(view_func, "__wrapped__"):
        view_func = view_func.__wrapped__
    return view_func


class CrmAuditHelperTests(SimpleTestCase):
    @patch("binncrm.audit.record_tenant_event", return_value="ok")
    @patch("binncrm.audit.get_public_schema_name", return_value="public")
    @patch("binncrm.audit.schema_context", side_effect=lambda schema: nullcontext())
    def test_record_crm_audit_event_normalizes_metadata(
        self,
        schema_context_mock,
        public_schema_mock,
        record_tenant_event_mock,
    ):
        tenant = SimpleNamespace(schema_name="demo")
        actor = SimpleNamespace(pk=7)

        result = record_crm_audit_event(
            tenant=tenant,
            actor=actor,
            action="updated",
            object_type="deal",
            title="Deal actualizado",
            metadata={
                "amount": Decimal("10.50"),
                "expires_on": date(2026, 7, 30),
                "tags": {"vip", "renewal"},
                "nested": {"seen_at": datetime(2026, 7, 30, 9, 45, 0)},
            },
        )

        self.assertEqual(result, "ok")
        self.assertEqual(schema_context_mock.call_args.args, ("public",))
        self.assertEqual(
            record_tenant_event_mock.call_args.kwargs,
            {
                "tenant": tenant,
                "actor": actor,
                "title": "Deal actualizado",
                "message": "",
                "code": "crm_deal_updated",
                "metadata": {
                    "scope": "crm",
                    "object_type": "deal",
                    "action": "updated",
                    "amount": "10.50",
                    "expires_on": "2026-07-30",
                    "tags": ["renewal", "vip"],
                    "nested": {"seen_at": "2026-07-30T09:45:00"},
                },
            },
        )


class CrmAuditViewTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.user = SimpleNamespace(is_authenticated=True, pk=7, username="owner")
        self.tenant = MagicMock()
        self.tenant.tenant_config = SimpleNamespace(labels={})
        self.tenant.get_label.side_effect = lambda key, default=None: {
            "entity_plural": "Contactos",
            "entity_singular": "Contacto",
            "deal_singular": "Deal",
            "collection_singular": "Cobranza",
        }.get(key, default or key)

    @patch("binncrm.views._require_crm_permission")
    @patch("binncrm.views.render", return_value=HttpResponse("ok"))
    @patch("binncrm.views.messages.success")
    @patch("binncrm.views.get_entity_field_definitions", return_value=[])
    @patch("binncrm.views._audit_crm_action")
    @patch("binncrm.views.import_entities_from_csv")
    @patch("binncrm.views.EntityImportForm")
    def test_entity_import_records_operational_audit(
        self,
        form_class_mock,
        import_mock,
        audit_mock,
        field_definitions_mock,
        messages_success_mock,
        render_mock,
        require_permission_mock,
    ):
        form = MagicMock()
        form.is_valid.return_value = True
        form.cleaned_data = {
            "csv_file": MagicMock(),
            "update_existing": True,
        }
        form_class_mock.return_value = form
        import_mock.return_value = {
            "processed": 4,
            "created": 2,
            "updated": 1,
            "skipped": 1,
            "error_rows": [],
            "error_count": 0,
            "headers": ["nombre"],
        }

        request = self.factory.post("/crm/entities/import/")
        request.user = self.user
        request.tenant = self.tenant

        response = unwrap_view(entity_import)(request)

        self.assertEqual(response.status_code, 200)
        audit_mock.assert_called_once()
        self.assertEqual(audit_mock.call_args.kwargs["action"], "imported")
        self.assertEqual(audit_mock.call_args.kwargs["object_type"], "entity")
        self.assertEqual(audit_mock.call_args.kwargs["metadata"]["created"], 2)
        self.assertEqual(audit_mock.call_args.kwargs["metadata"]["update_existing"], True)

    @patch("binncrm.views._require_crm_permission")
    @patch("binncrm.views._audit_crm_action")
    @patch("binncrm.views.log_deal_stage_changed")
    @patch("binncrm.views._resequence_stage", return_value=2)
    @patch("binncrm.views.transaction.atomic", side_effect=lambda: nullcontext())
    @patch("binncrm.views.get_object_or_404")
    def test_deal_move_records_move_audit(
        self,
        get_object_mock,
        atomic_mock,
        resequence_mock,
        log_stage_mock,
        audit_mock,
        require_permission_mock,
    ):
        deal = MagicMock()
        deal.pk = 12
        deal.title = "Acme"
        deal.entity_id = 3
        deal.pipeline_id = 5
        deal.stage = "lead"
        deal.pipeline = SimpleNamespace(stage_choices=["lead", "won"], name="Pipeline comercial")
        get_object_mock.return_value = deal

        request = self.factory.post("/crm/deals/12/move/", {"stage": "won", "position": "1"})
        request.user = self.user
        request.tenant = self.tenant

        response = unwrap_view(deal_move)(request, pk=12)

        self.assertEqual(response.status_code, 200)
        log_stage_mock.assert_called_once()
        self.assertEqual(audit_mock.call_args.kwargs["action"], "moved")
        self.assertEqual(audit_mock.call_args.kwargs["object_type"], "deal")
        self.assertEqual(audit_mock.call_args.kwargs["metadata"]["previous_stage"], "lead")
        self.assertEqual(audit_mock.call_args.kwargs["metadata"]["current_stage"], "won")

    @patch("binncrm.views._require_crm_permission")
    @patch("binncrm.views._audit_crm_action")
    @patch("binncrm.views.log_collection_updated")
    @patch("binncrm.views._resequence_collection_status", return_value=4)
    @patch("binncrm.views.transaction.atomic", side_effect=lambda: nullcontext())
    @patch("binncrm.views.get_object_or_404")
    def test_collection_move_records_reorder_audit(
        self,
        get_object_mock,
        atomic_mock,
        resequence_mock,
        log_collection_mock,
        audit_mock,
        require_permission_mock,
    ):
        collection = MagicMock()
        collection.pk = 22
        collection.title = "Cuota julio"
        collection.entity_id = 9
        collection.deal_id = 13
        collection.status = CollectionRecord.STATUS_PENDING
        get_object_mock.return_value = collection

        request = self.factory.post(
            "/crm/collections/22/move/",
            {"status": CollectionRecord.STATUS_PENDING, "position": "3"},
        )
        request.user = self.user
        request.tenant = self.tenant

        response = unwrap_view(collection_move)(request, pk=22)

        self.assertEqual(response.status_code, 200)
        log_collection_mock.assert_not_called()
        self.assertEqual(audit_mock.call_args.kwargs["action"], "reordered")
        self.assertEqual(audit_mock.call_args.kwargs["object_type"], "collection")
        self.assertEqual(audit_mock.call_args.kwargs["metadata"]["position"], 4)

    @patch("binncrm.views._require_crm_permission")
    @patch("binncrm.views.redirect", return_value=HttpResponse(status=302))
    @patch("binncrm.views._audit_crm_action")
    @patch("binncrm.views.log_activity_completion_changed")
    @patch("binncrm.views.timezone.now", return_value=datetime(2026, 7, 30, 11, 0, 0))
    @patch("binncrm.views.get_object_or_404")
    def test_activity_toggle_complete_records_completion_audit(
        self,
        get_object_mock,
        now_mock,
        log_activity_mock,
        audit_mock,
        redirect_mock,
        require_permission_mock,
    ):
        activity = MagicMock()
        activity.pk = 41
        activity.title = "Llamar a cliente"
        activity.entity_id = 5
        activity.deal_id = 6
        activity.activity_type = Activity.TYPE_TASK
        activity.completed_at = None
        get_object_mock.return_value = activity

        request = self.factory.post("/crm/activities/41/toggle/?next=entity")
        request.user = self.user
        request.tenant = self.tenant

        response = unwrap_view(activity_toggle_complete)(request, pk=41)

        self.assertEqual(response.status_code, 302)
        self.assertEqual(activity.completed_at, datetime(2026, 7, 30, 11, 0, 0))
        self.assertEqual(audit_mock.call_args.kwargs["action"], "completed")
        self.assertEqual(audit_mock.call_args.kwargs["object_type"], "task")
        self.assertEqual(audit_mock.call_args.kwargs["metadata"]["activity_id"], 41)
