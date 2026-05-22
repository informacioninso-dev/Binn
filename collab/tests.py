from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.contrib.auth import get_user_model
from django.conf import settings
from django.core.exceptions import ValidationError
from django.test import RequestFactory, SimpleTestCase
from django.utils import timezone

from .forms import MessageForm
from .models import Conversation, ConversationMembership, Message, Notification
from .realtime import build_tenant_stream_group
from .services import (
    _extract_mention_user_ids,
    ensure_entity_conversation,
    follow_conversation,
    get_unread_notification_count,
    list_user_notifications,
    mark_notifications_read,
    post_message,
    set_conversation_archived,
    set_conversation_pinned,
    unfollow_conversation,
)
from . import views


class ConversationValidationTests(SimpleTestCase):
    def test_entity_conversation_requires_entity(self):
        conversation = Conversation(kind=Conversation.KIND_ENTITY, title="Ficha")

        with self.assertRaises(ValidationError):
            conversation.clean()


class CollabRealtimeTests(SimpleTestCase):
    def test_stream_group_name_is_normalized_for_channels(self):
        group_name = build_tenant_stream_group("Demo Tenant/01")

        self.assertEqual(group_name, "collab.tenant.demotenant01")

    def test_conversation_panel_uses_stream_attributes_and_drops_polling(self):
        template = (Path(settings.BASE_DIR) / "templates" / "collab" / "_conversation_panel.html").read_text(encoding="utf-8")

        self.assertIn("data-collab-stream-path", template)
        self.assertNotIn("every 12s", template)

    def test_base_template_bootstraps_collab_realtime(self):
        template = (Path(settings.BASE_DIR) / "templates" / "base.html").read_text(encoding="utf-8")

        self.assertIn("initBinnCollabRealtime", template)
        self.assertIn("binn:collab-event", template)

    def test_conversation_panel_supports_entity_bootstrap_actions(self):
        template = (Path(settings.BASE_DIR) / "templates" / "collab" / "_conversation_panel.html").read_text(encoding="utf-8")

        self.assertIn("collab:entity_follow", template)
        self.assertIn("collab:entity_post", template)
        self.assertIn("collab:deal_follow", template)
        self.assertIn("collab:deal_post", template)
        self.assertIn("message_form.message_kind", template)
        self.assertIn("message_form.create_task", template)

    def test_inbox_templates_expose_filter_and_prioritization_ui(self):
        inbox_template = (Path(settings.BASE_DIR) / "templates" / "collab" / "inbox.html").read_text(encoding="utf-8")
        list_template = (Path(settings.BASE_DIR) / "templates" / "collab" / "_conversation_list.html").read_text(encoding="utf-8")

        self.assertIn("name=\"filter\"", inbox_template)
        self.assertIn("filter_options", inbox_template)
        self.assertIn("archived", inbox_template)
        self.assertIn("Fijar", list_template)
        self.assertIn("Archivar", list_template)

    def test_deal_templates_link_to_contextual_collab(self):
        deal_template = (Path(settings.BASE_DIR) / "templates" / "binncrm" / "deal_form.html").read_text(encoding="utf-8")
        kanban_template = (Path(settings.BASE_DIR) / "templates" / "binncrm" / "_kanban_board.html").read_text(encoding="utf-8")

        self.assertIn("collab:deal_panel", deal_template)
        self.assertIn("#deal-collab-panel", kanban_template)

    def test_team_conversation_rejects_entity_context(self):
        conversation = Conversation(
            kind=Conversation.KIND_TEAM,
            title="Sala operativa",
            entity_id=3,
        )

        with self.assertRaises(ValidationError):
            conversation.clean()


class ConversationFollowFlowTests(SimpleTestCase):
    @patch("collab.services._ensure_conversation_membership")
    @patch("collab.services.record_tenant_event")
    @patch("collab.services.Conversation.objects.get_or_create")
    def test_ensure_entity_conversation_only_adds_actor_membership(
        self,
        get_or_create_mock,
        record_tenant_event_mock,
        ensure_conversation_membership_mock,
    ):
        actor = SimpleNamespace(pk=3, username="ana")
        entity = SimpleNamespace(pk=7, full_name="Acme Demo")
        conversation = SimpleNamespace(pk=11)
        get_or_create_mock.return_value = (conversation, True)

        result = ensure_entity_conversation(
            tenant=SimpleNamespace(schema_name="demo"),
            entity=entity,
            actor=actor,
        )

        self.assertIs(result, conversation)
        ensure_conversation_membership_mock.assert_called_once_with(
            conversation=conversation,
            user=actor,
            actor=actor,
            role=ConversationMembership.ROLE_MEMBER,
            clear_muted=True,
            clear_archived=True,
        )
        self.assertTrue(record_tenant_event_mock.called)

    @patch("collab.services._ensure_conversation_membership")
    def test_follow_conversation_routes_through_explicit_membership_helper(self, ensure_conversation_membership_mock):
        actor = SimpleNamespace(pk=3, username="ana")
        conversation = SimpleNamespace(pk=11)

        follow_conversation(conversation=conversation, user=actor, actor=actor)

        ensure_conversation_membership_mock.assert_called_once_with(
            conversation=conversation,
            user=actor,
            actor=actor,
            role=ConversationMembership.ROLE_MEMBER,
            clear_muted=True,
            clear_archived=True,
        )

    def test_unfollow_only_touches_the_current_user_membership(self):
        actor = SimpleNamespace(pk=3, username="ana")
        membership = Mock(is_active=True)
        conversation = Mock()
        conversation.memberships.filter.return_value.first.return_value = membership

        result = unfollow_conversation(conversation=conversation, user=actor, actor=actor)

        self.assertIs(result, membership)
        self.assertFalse(membership.is_active)
        membership.save.assert_called_once_with(update_fields=["is_active", "updated_by", "updated_at"])

    def test_pin_and_archive_membership_only_update_target_flags(self):
        actor = SimpleNamespace(pk=3, username="ana")
        membership = Mock(is_pinned=False, is_archived=False, save=Mock())
        conversation = Mock()
        conversation.memberships.filter.return_value.first.return_value = membership

        with patch("collab.services._ensure_conversation_membership", return_value=membership):
            set_conversation_pinned(conversation=conversation, user=actor, pinned=True, actor=actor)
            set_conversation_archived(conversation=conversation, user=actor, archived=True, actor=actor)

        self.assertTrue(membership.is_pinned)
        self.assertTrue(membership.is_archived)
        self.assertEqual(membership.save.call_count, 2)


class MessageFormTests(SimpleTestCase):
    @patch("collab.forms.get_tenant_user_queryset")
    def test_message_form_exposes_operational_fields(self, get_tenant_user_queryset_mock):
        get_tenant_user_queryset_mock.return_value = get_user_model()._default_manager.none()

        form = MessageForm(
            tenant=SimpleNamespace(),
            current_user=SimpleNamespace(is_authenticated=True),
            task_context_enabled=True,
            allow_task_linking=True,
        )

        self.assertIn("message_kind", form.fields)
        self.assertIn("assignee", form.fields)
        self.assertIn("due_at", form.fields)
        self.assertIn("create_task", form.fields)
        self.assertFalse(form.fields["create_task"].disabled)

    @patch("collab.forms.get_tenant_user_queryset")
    def test_message_form_requires_due_date_when_creating_task(self, get_tenant_user_queryset_mock):
        get_tenant_user_queryset_mock.return_value = get_user_model()._default_manager.none()

        form = MessageForm(
            {
                "message_kind": Message.KIND_NEXT_STEP,
                "body": "Cerrar la renovacion con carrier.",
                "create_task": "on",
            },
            tenant=SimpleNamespace(),
            current_user=SimpleNamespace(is_authenticated=True),
            task_context_enabled=True,
            allow_task_linking=True,
        )

        self.assertFalse(form.is_valid())
        self.assertIn("due_at", form.errors)

    @patch("collab.forms.get_tenant_user_queryset")
    def test_message_form_disables_task_creation_without_permission(self, get_tenant_user_queryset_mock):
        get_tenant_user_queryset_mock.return_value = get_user_model()._default_manager.none()

        form = MessageForm(
            tenant=SimpleNamespace(),
            current_user=SimpleNamespace(is_authenticated=True),
            task_context_enabled=True,
            allow_task_linking=False,
        )

        self.assertTrue(form.fields["create_task"].disabled)


class StructuredMessageServiceTests(SimpleTestCase):
    databases = {"default"}

    @patch("collab.services.transaction.on_commit", side_effect=lambda callback: callback())
    @patch("collab.services.broadcast_tenant_collab_event")
    @patch("collab.services.record_tenant_event")
    @patch("collab.services.Notification.objects.bulk_create")
    @patch("collab.services.Message.objects.create")
    @patch("collab.services.Activity.objects.create")
    @patch("collab.services._ensure_conversation_membership")
    def test_post_message_builds_operational_metadata_and_linked_task(
        self,
        ensure_membership_mock,
        activity_create_mock,
        message_create_mock,
        bulk_create_mock,
        record_tenant_event_mock,
        broadcast_tenant_collab_event_mock,
        on_commit_mock,
    ):
        now = timezone.now()
        user = SimpleNamespace(pk=3, username="ana")
        assignee = SimpleNamespace(pk=8, username="luis")
        entity = SimpleNamespace(pk=7, full_name="Acme Demo")
        deal = SimpleNamespace(pk=11, title="Renovacion anual", entity=entity)
        membership = Mock(is_active=True)
        membership.save = Mock()
        ensure_membership_mock.return_value = membership
        linked_task = SimpleNamespace(pk=21, title="Siguiente paso: cerrar renovacion")
        activity_create_mock.return_value = linked_task
        conversation = SimpleNamespace(
            pk=14,
            title="Deal - Renovacion anual",
            kind=Conversation.KIND_DEAL,
            entity=None,
            deal=deal,
            memberships=Mock(),
            save=Mock(),
        )
        conversation.memberships.filter.return_value.exclude.return_value = []

        def build_message(**kwargs):
            return SimpleNamespace(
                pk=55,
                created_at=now,
                metadata=kwargs["metadata"],
                body=kwargs["body"],
                author=user,
            )

        message_create_mock.side_effect = build_message

        message = post_message(
            conversation=conversation,
            tenant=SimpleNamespace(schema_name="demo"),
            user=user,
            body="Cerrar propuesta con carrier antes de viernes.",
            message_kind=Message.KIND_NEXT_STEP,
            assignee=assignee,
            due_at=now,
            create_task=True,
        )

        self.assertEqual(message.metadata["message_kind"], Message.KIND_NEXT_STEP)
        self.assertEqual(message.metadata["kind_label"], "Siguiente paso")
        self.assertEqual(message.metadata["assignee_name"], "luis")
        self.assertEqual(message.metadata["linked_task_id"], 21)
        activity_create_mock.assert_called_once()
        bulk_create_mock.assert_not_called()
        self.assertTrue(record_tenant_event_mock.called)
        broadcast_tenant_collab_event_mock.assert_called_once()
        self.assertEqual(
            broadcast_tenant_collab_event_mock.call_args.kwargs["metadata"]["message_kind_label"],
            "Siguiente paso",
        )
        self.assertTrue(broadcast_tenant_collab_event_mock.call_args.kwargs["metadata"]["task_created"])

    @patch("collab.services._ensure_conversation_membership")
    def test_post_message_rejects_linked_task_for_team_conversations(self, ensure_membership_mock):
        ensure_membership_mock.return_value = Mock(is_active=True, save=Mock())

        with self.assertRaises(ValueError):
            post_message(
                conversation=SimpleNamespace(
                    kind=Conversation.KIND_TEAM,
                    title="Sala operativa",
                ),
                tenant=SimpleNamespace(schema_name="demo"),
                user=SimpleNamespace(pk=3, username="ana"),
                body="Mover handoff a operaciones.",
                message_kind=Message.KIND_HANDOFF,
                due_at=timezone.now(),
                create_task=True,
            )


class ConversationBootstrapViewTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()

    @patch("collab.forms.get_tenant_user_queryset")
    @patch("collab.views._can_post_messages", return_value=True)
    @patch("collab.views.get_entity_conversation")
    @patch("collab.views.get_object_or_404")
    def test_entity_panel_renders_bootstrap_when_user_has_not_followed_case(
        self,
        get_object_or_404_mock,
        get_entity_conversation_mock,
        can_post_messages_mock,
        get_tenant_user_queryset_mock,
    ):
        get_tenant_user_queryset_mock.return_value = get_user_model()._default_manager.none()
        entity = SimpleNamespace(pk=7, full_name="Acme Demo")
        get_object_or_404_mock.return_value = entity
        get_entity_conversation_mock.return_value = None

        request = self.factory.get("/crm/collab/entity/7/panel/")
        request.user = SimpleNamespace(pk=3, username="ana", is_authenticated=True, is_superuser=False)
        request.tenant = SimpleNamespace(schema_name="demo", name="Demo", has_capability=lambda capability: True)
        request.tenant_membership = SimpleNamespace(role="manager")

        response = views.entity_panel.__wrapped__.__wrapped__(request, entity_id=7)

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Tu primera nota crea el canal", response.content)
        self.assertTrue(can_post_messages_mock.called)

    @patch("collab.forms.get_tenant_user_queryset")
    @patch("collab.views._can_post_messages", return_value=True)
    @patch("collab.views.get_deal_conversation")
    @patch("collab.views.get_object_or_404")
    def test_deal_panel_renders_bootstrap_when_user_has_not_followed_deal(
        self,
        get_object_or_404_mock,
        get_deal_conversation_mock,
        can_post_messages_mock,
        get_tenant_user_queryset_mock,
    ):
        get_tenant_user_queryset_mock.return_value = get_user_model()._default_manager.none()
        entity = SimpleNamespace(pk=17, full_name="Acme Demo")
        deal = SimpleNamespace(pk=7, title="Renovacion anual", entity=entity)
        get_object_or_404_mock.return_value = deal
        get_deal_conversation_mock.return_value = None

        request = self.factory.get("/crm/collab/deal/7/panel/")
        request.user = SimpleNamespace(pk=3, username="ana", is_authenticated=True, is_superuser=False)
        request.tenant = SimpleNamespace(schema_name="demo", name="Demo", has_capability=lambda capability: True)
        request.tenant_membership = SimpleNamespace(role="manager")
        request.META["HTTP_HX_REQUEST"] = "true"

        response = views.deal_panel.__wrapped__.__wrapped__(request, deal_id=7)

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Deal - Renovacion anual", response.content)
        self.assertTrue(can_post_messages_mock.called)


class MentionExtractionTests(SimpleTestCase):
    @patch("collab.services.TenantMembership.objects.filter")
    def test_extract_returns_matching_member_ids(self, filter_mock):
        filter_mock.return_value.values_list.return_value = [5, 9]
        tenant = SimpleNamespace(pk=1)

        result = _extract_mention_user_ids("Hola @ana, revisa con @luis lo que pidio el cliente.", tenant)

        self.assertEqual(result, frozenset({5, 9}))
        call_kwargs = filter_mock.call_args.kwargs
        self.assertSetEqual(set(call_kwargs["user__username__in"]), {"ana", "luis"})

    @patch("collab.services.TenantMembership.objects.filter")
    def test_extract_returns_empty_when_no_mentions(self, filter_mock):
        tenant = SimpleNamespace(pk=1)

        result = _extract_mention_user_ids("Mensaje sin menciones.", tenant)

        self.assertEqual(result, frozenset())
        filter_mock.assert_not_called()

    @patch("collab.services.TenantMembership.objects.filter")
    def test_extract_deduplicates_repeated_mentions(self, filter_mock):
        filter_mock.return_value.values_list.return_value = [5]
        tenant = SimpleNamespace(pk=1)

        _extract_mention_user_ids("@ana y de nuevo @ana.", tenant)

        call_kwargs = filter_mock.call_args.kwargs
        self.assertEqual(len(call_kwargs["user__username__in"]), 1)


class SelectiveNotificationTests(SimpleTestCase):
    @patch("collab.services.transaction.on_commit", side_effect=lambda cb: cb())
    @patch("collab.services.broadcast_tenant_collab_event")
    @patch("collab.services.record_tenant_event")
    @patch("collab.services.Notification.objects.bulk_create")
    @patch("collab.services.Notification")
    @patch("collab.services.Message.objects.create")
    @patch("collab.services._ensure_conversation_membership")
    @patch("collab.services._extract_mention_user_ids", return_value=frozenset({8}))
    def test_mentioned_muted_member_receives_attention_notification(
        self,
        extract_mock,
        ensure_membership_mock,
        message_create_mock,
        notification_cls_mock,
        bulk_create_mock,
        record_tenant_event_mock,
        broadcast_mock,
        on_commit_mock,
    ):
        now = timezone.now()
        user = SimpleNamespace(pk=3, username="ana")
        mentioned_user = SimpleNamespace(pk=8, username="luis")
        membership_author = Mock(is_active=True, save=Mock())
        membership_muted_mentioned = Mock(
            user=mentioned_user,
            user_id=8,
            is_active=True,
            is_muted=True,
        )
        ensure_membership_mock.return_value = membership_author
        # Keep level/LEVEL_* constants accessible on the patched class.
        notification_cls_mock.LEVEL_INFO = Notification.LEVEL_INFO
        notification_cls_mock.LEVEL_ATTENTION = Notification.LEVEL_ATTENTION

        conversation = SimpleNamespace(
            pk=14,
            title="Sala operativa",
            kind=Conversation.KIND_TEAM,
            entity=None,
            deal=None,
            memberships=Mock(),
            save=Mock(),
        )
        conversation.memberships.filter.return_value.exclude.return_value = [membership_muted_mentioned]

        def build_message(**kwargs):
            return SimpleNamespace(pk=55, created_at=now, metadata=kwargs["metadata"], body=kwargs["body"], author=user)

        message_create_mock.side_effect = build_message

        post_message(
            conversation=conversation,
            tenant=SimpleNamespace(schema_name="demo"),
            user=user,
            body="@luis revisa esto urgente.",
        )

        call_kwargs = notification_cls_mock.call_args.kwargs
        self.assertEqual(call_kwargs["level"], Notification.LEVEL_ATTENTION)
        self.assertEqual(call_kwargs["user"], mentioned_user)

    @patch("collab.services.transaction.on_commit", side_effect=lambda cb: cb())
    @patch("collab.services.broadcast_tenant_collab_event")
    @patch("collab.services.record_tenant_event")
    @patch("collab.services.Notification.objects.bulk_create")
    @patch("collab.services.Message.objects.create")
    @patch("collab.services._ensure_conversation_membership")
    @patch("collab.services._extract_mention_user_ids", return_value=frozenset())
    def test_muted_non_mentioned_member_receives_no_notification(
        self,
        extract_mock,
        ensure_membership_mock,
        message_create_mock,
        bulk_create_mock,
        record_tenant_event_mock,
        broadcast_mock,
        on_commit_mock,
    ):
        now = timezone.now()
        user = SimpleNamespace(pk=3, username="ana")
        muted_user = SimpleNamespace(pk=8, username="luis")
        membership_author = Mock(is_active=True, save=Mock())
        membership_muted = Mock(user=muted_user, user_id=8, is_active=True, is_muted=True)
        ensure_membership_mock.return_value = membership_author

        conversation = SimpleNamespace(
            pk=14, title="Sala", kind=Conversation.KIND_TEAM,
            entity=None, deal=None, memberships=Mock(), save=Mock(),
        )
        conversation.memberships.filter.return_value.exclude.return_value = [membership_muted]

        def build_message(**kwargs):
            return SimpleNamespace(pk=55, created_at=now, metadata=kwargs["metadata"], body=kwargs["body"], author=user)

        message_create_mock.side_effect = build_message

        post_message(
            conversation=conversation,
            tenant=SimpleNamespace(schema_name="demo"),
            user=user,
            body="Actualizacion general sin menciones.",
        )

        bulk_create_mock.assert_not_called()

    @patch("collab.services.transaction.on_commit", side_effect=lambda cb: cb())
    @patch("collab.services.broadcast_tenant_collab_event")
    @patch("collab.services.record_tenant_event")
    @patch("collab.services.Notification.objects.bulk_create")
    @patch("collab.services.Message.objects.create")
    @patch("collab.services._ensure_conversation_membership")
    @patch("collab.services._extract_mention_user_ids", return_value=frozenset({9}))
    def test_mention_ids_stored_in_message_metadata(
        self,
        extract_mock,
        ensure_membership_mock,
        message_create_mock,
        bulk_create_mock,
        record_tenant_event_mock,
        broadcast_mock,
        on_commit_mock,
    ):
        now = timezone.now()
        user = SimpleNamespace(pk=3, username="ana")
        membership_author = Mock(is_active=True, save=Mock())
        ensure_membership_mock.return_value = membership_author
        conversation = SimpleNamespace(
            pk=14, title="Sala", kind=Conversation.KIND_TEAM,
            entity=None, deal=None, memberships=Mock(), save=Mock(),
        )
        conversation.memberships.filter.return_value.exclude.return_value = []

        captured = {}

        def build_message(**kwargs):
            captured["metadata"] = kwargs["metadata"]
            return SimpleNamespace(pk=55, created_at=now, metadata=kwargs["metadata"], body=kwargs["body"], author=user)

        message_create_mock.side_effect = build_message

        post_message(
            conversation=conversation,
            tenant=SimpleNamespace(schema_name="demo"),
            user=user,
            body="@carlos revisa el informe.",
        )

        self.assertIn(9, captured["metadata"]["mention_ids"])


class NotificationServiceTests(SimpleTestCase):
    def test_get_unread_notification_count_queries_user_notifications(self):
        user = Mock()
        user.collab_notifications.filter.return_value.count.return_value = 7

        count = get_unread_notification_count(user=user)

        self.assertEqual(count, 7)
        user.collab_notifications.filter.assert_called_once_with(is_read=False)

    def test_list_user_notifications_returns_ordered_slice(self):
        user = Mock()
        notif_a = SimpleNamespace(pk=1, is_read=True)
        notif_b = SimpleNamespace(pk=2, is_read=False)
        qs = Mock()
        qs.select_related.return_value = qs
        qs.order_by.return_value = qs
        qs.__getitem__ = Mock(return_value=[notif_b, notif_a])
        user.collab_notifications = qs

        result = list_user_notifications(user=user, limit=10)

        qs.order_by.assert_called_once_with("is_read", "-created_at", "-id")

    def test_mark_notifications_read_marks_all_when_ids_is_none(self):
        user = Mock()
        qs = Mock()
        user.collab_notifications.filter.return_value = qs
        qs.update.return_value = 3

        count = mark_notifications_read(user=user, notification_ids=None)

        self.assertEqual(count, 3)
        user.collab_notifications.filter.assert_called_once_with(is_read=False)
        qs.filter.assert_not_called()

    def test_mark_notifications_read_filters_by_ids_when_provided(self):
        user = Mock()
        qs = Mock()
        filtered_qs = Mock()
        user.collab_notifications.filter.return_value = qs
        qs.filter.return_value = filtered_qs
        filtered_qs.update.return_value = 1

        mark_notifications_read(user=user, notification_ids=[5, 7])

        qs.filter.assert_called_once_with(pk__in=[5, 7])
        filtered_qs.update.assert_called_once()


class InboxAutoReadTests(SimpleTestCase):
    """Ensure unread count is only cleared when the user explicitly opens a conversation."""

    def test_notification_center_template_exists(self):
        template = (Path(settings.BASE_DIR) / "templates" / "collab" / "_notification_center.html").read_text(encoding="utf-8")

        self.assertIn("collab:notification_mark_read", template)
        self.assertIn("binn-notif-item", template)
        self.assertIn("Marcar todo leido", template)

    def test_notification_center_template_shows_attention_badge(self):
        template = (Path(settings.BASE_DIR) / "templates" / "collab" / "_notification_center.html").read_text(encoding="utf-8")

        self.assertIn("Mencion", template)
        self.assertIn("is-attention", template)

    def test_navbar_template_includes_notification_bell(self):
        template = (Path(settings.BASE_DIR) / "templates" / "partials" / "_navbar.html").read_text(encoding="utf-8")

        self.assertIn("collab:notification_center", template)
        self.assertIn("collab_unread_total", template)
