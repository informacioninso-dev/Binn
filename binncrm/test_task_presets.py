from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.http import HttpResponse
from django.test import RequestFactory, SimpleTestCase
from django.utils import timezone

from .models import Activity
from .task_presets import build_task_preset_cards, build_task_preset_form_initial
from .views import activity_create, activity_preset_create


def unwrap_view(view_func):
    while hasattr(view_func, "__wrapped__"):
        view_func = view_func.__wrapped__
    return view_func


class TaskPresetHelperTests(SimpleTestCase):
    def setUp(self):
        self.tenant = SimpleNamespace(
            task_presets=[
                {
                    "key": "followup",
                    "label": "Seguimiento inicial",
                    "description": "Llamar despues del primer contacto.",
                    "category": "followup",
                    "due_in_days": 2,
                    "priority": "medium",
                    "owner_role": "operator",
                },
                {
                    "key": "renew",
                    "label": "Renovar poliza",
                    "description": "Confirmar vigencia y enviar recordatorio.",
                    "category": "renewal",
                    "due_in_days": 1,
                    "priority": "high",
                    "owner_role": "manager",
                },
            ]
        )

    @patch("binncrm.task_presets.build_task_preset_due_at")
    @patch("binncrm.task_presets.resolve_task_preset_assignee")
    def test_build_task_preset_form_initial_uses_due_date_and_assignee(
        self,
        resolve_assignee_mock,
        build_due_at_mock,
    ):
        assignee = SimpleNamespace(pk=31)
        due_at = timezone.make_aware(datetime(2026, 7, 30, 15, 45, 0), timezone.get_current_timezone())
        resolve_assignee_mock.return_value = assignee
        build_due_at_mock.return_value = due_at

        initial = build_task_preset_form_initial(
            self.tenant,
            "renew",
            entity_id=9,
            deal_id=4,
            current_user=SimpleNamespace(pk=7, is_authenticated=True),
        )

        self.assertEqual(initial["activity_type"], Activity.TYPE_TASK)
        self.assertEqual(initial["title"], "Renovar poliza")
        self.assertEqual(initial["description"], "Confirmar vigencia y enviar recordatorio.")
        self.assertEqual(initial["entity"], 9)
        self.assertEqual(initial["deal"], 4)
        self.assertEqual(initial["assigned_to"], 31)
        self.assertEqual(initial["due_at"], timezone.localtime(due_at).strftime("%Y-%m-%dT%H:%M"))

    def test_build_task_preset_cards_marks_selected_and_builds_quick_create_fields(self):
        now = timezone.make_aware(datetime(2026, 7, 30, 10, 0, 0), timezone.get_current_timezone())

        cards = build_task_preset_cards(
            self.tenant,
            entity_id=9,
            next_url="/crm/entities/9/",
            selected_key="renew",
            limit=2,
            now=now,
        )

        self.assertEqual(len(cards), 2)
        self.assertEqual(cards[0]["key"], "followup")
        self.assertEqual(cards[1]["key"], "renew")
        self.assertEqual(cards[0]["category_label"], "Followup")
        self.assertEqual(cards[0]["can_quick_create"], True)
        self.assertIn(("entity", "9"), cards[0]["quick_create_fields"])
        self.assertIn(("next", "/crm/entities/9/"), cards[0]["quick_create_fields"])
        self.assertEqual(cards[1]["is_selected"], True)
        self.assertIn("preset=renew", cards[1]["href"])


class TaskPresetViewTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.user = SimpleNamespace(
            is_authenticated=True,
            is_superuser=False,
            pk=7,
            username="owner",
        )
        self.tenant = SimpleNamespace(
            task_presets=[
                {
                    "key": "renew",
                    "label": "Renovar poliza",
                    "description": "Confirmar vigencia y enviar recordatorio.",
                    "category": "renewal",
                    "due_in_days": 1,
                    "priority": "high",
                    "owner_role": "manager",
                }
            ],
            tenant_config=SimpleNamespace(labels={}),
        )

    @patch("binncrm.views._require_crm_permission")
    @patch("binncrm.views.render", return_value=HttpResponse("ok"))
    @patch("binncrm.views.ActivityForm")
    @patch(
        "binncrm.views.build_task_preset_form_initial",
        return_value={
            "activity_type": Activity.TYPE_TASK,
            "title": "Renovar poliza",
            "description": "Confirmar vigencia y enviar recordatorio.",
            "due_at": "2026-07-31T09:00",
        },
    )
    def test_activity_create_get_exposes_selected_preset_context(
        self,
        build_initial_mock,
        form_class_mock,
        render_mock,
        require_permission_mock,
    ):
        form = SimpleNamespace(data={}, initial={"activity_type": Activity.TYPE_TASK})
        form_class_mock.return_value = form
        request = self.factory.get("/crm/activities/new/", {"preset": "renew", "entity": "9"})
        request.user = self.user
        request.tenant = self.tenant

        response = unwrap_view(activity_create)(request)

        self.assertEqual(response.status_code, 200)
        build_initial_mock.assert_called_once_with(
            self.tenant,
            "renew",
            entity_id=9,
            deal_id=None,
            current_user=self.user,
        )
        self.assertEqual(form_class_mock.call_args.kwargs["initial"]["entity"], "9")
        context = render_mock.call_args.args[2]
        self.assertEqual(context["selected_task_preset"]["key"], "renew")
        self.assertEqual(context["selected_task_preset_card"]["key"], "renew")
        self.assertEqual(context["is_task_mode"], True)

    @patch("binncrm.views._require_crm_permission")
    @patch("binncrm.views.messages.success")
    @patch("binncrm.views._audit_crm_action")
    @patch("binncrm.views.log_activity_created")
    @patch("binncrm.views.Activity.objects.create")
    @patch("binncrm.views.build_task_preset_due_at")
    @patch("binncrm.views.resolve_task_preset_assignee")
    @patch("binncrm.views.Deal.objects.filter")
    @patch("binncrm.views.Entity.objects.filter")
    def test_activity_preset_create_builds_task_and_redirects_to_next(
        self,
        entity_filter_mock,
        deal_filter_mock,
        resolve_assignee_mock,
        build_due_at_mock,
        activity_create_mock,
        log_activity_mock,
        audit_mock,
        messages_success_mock,
        require_permission_mock,
    ):
        entity = SimpleNamespace(pk=9, full_name="Acme Corp")
        assignee = SimpleNamespace(pk=31, username="manager")
        due_at = timezone.make_aware(datetime(2026, 7, 31, 9, 0, 0), timezone.get_current_timezone())
        activity = SimpleNamespace(
            pk=88,
            title="Renovar poliza",
            activity_type=Activity.TYPE_TASK,
            entity_id=9,
            deal_id=None,
            assigned_to_id=31,
            due_at=due_at,
        )
        entity_filter = MagicMock()
        entity_filter.first.return_value = entity
        deal_filter = MagicMock()
        deal_filter.first.return_value = None
        entity_filter_mock.return_value = entity_filter
        deal_filter_mock.return_value = deal_filter
        resolve_assignee_mock.return_value = assignee
        build_due_at_mock.return_value = due_at
        activity_create_mock.return_value = activity

        request = self.factory.post(
            "/crm/activities/presets/create/",
            {"preset": "renew", "entity": "9", "next": "/crm/entities/9/"},
        )
        request.user = self.user
        request.tenant = self.tenant

        response = unwrap_view(activity_preset_create)(request)

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, "/crm/entities/9/")
        activity_create_mock.assert_called_once_with(
            entity=entity,
            deal=None,
            activity_type=Activity.TYPE_TASK,
            title="Renovar poliza",
            description="Confirmar vigencia y enviar recordatorio.",
            assigned_to=assignee,
            due_at=due_at,
            created_by=self.user,
            updated_by=self.user,
        )
        log_activity_mock.assert_called_once_with(activity=activity, actor=self.user)
        self.assertEqual(audit_mock.call_args.kwargs["action"], "created")
        self.assertEqual(audit_mock.call_args.kwargs["object_type"], "task")
        self.assertEqual(audit_mock.call_args.kwargs["metadata"]["preset_key"], "renew")
        self.assertEqual(audit_mock.call_args.kwargs["metadata"]["preset_priority"], "high")
        self.assertEqual(audit_mock.call_args.kwargs["metadata"]["assigned_to_id"], 31)
        messages_success_mock.assert_called_once()
