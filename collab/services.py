from __future__ import annotations

import re
from dataclasses import dataclass

from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Count, F, OuterRef, Q, Subquery
from django.utils import timezone
from django.utils.text import Truncator

from access.models import TenantMembership
from binncrm.models import Activity, ObjectRecord
from tenants.observability import record_tenant_event

from .models import Conversation, ConversationMembership, Message, Notification
from .realtime import broadcast_tenant_collab_event


@dataclass(frozen=True)
class ConversationSummary:
    conversation: Conversation
    membership: ConversationMembership | None
    unread_count: int
    last_message: Message | None


MESSAGE_KIND_LABELS = dict(Message.KIND_CHOICES)


def _get_message_kind_label(message_kind: str) -> str:
    return MESSAGE_KIND_LABELS.get(message_kind, MESSAGE_KIND_LABELS[Message.KIND_UPDATE])


def _format_due_label(due_at) -> str:
    if due_at is None:
        return ""
    due_display = timezone.localtime(due_at) if timezone.is_aware(due_at) else due_at
    return due_display.strftime("%d/%m %H:%M")


def _extract_mention_user_ids(body: str, tenant) -> frozenset[int]:
    """Resolve @username mentions in body to user IDs that are active tenant members."""
    usernames = set(re.findall(r"@(\w+)", body or ""))
    if not usernames:
        return frozenset()
    return frozenset(
        TenantMembership.objects.filter(
            tenant=tenant,
            is_active=True,
            user__username__in=usernames,
        ).values_list("user_id", flat=True)
    )


def _build_message_metadata(
    *,
    message_kind: str,
    assignee=None,
    due_at=None,
    linked_task=None,
    mention_ids: frozenset[int] | None = None,
) -> dict:
    return {
        "message_kind": message_kind,
        "kind_label": _get_message_kind_label(message_kind),
        "kind_tone": Message.KIND_TONE_MAP.get(message_kind, Message.KIND_TONE_MAP[Message.KIND_UPDATE]),
        "assignee_id": getattr(assignee, "pk", None),
        "assignee_name": getattr(assignee, "username", ""),
        "due_at": due_at.isoformat() if due_at is not None else "",
        "due_label": _format_due_label(due_at),
        "mention_ids": sorted(mention_ids) if mention_ids else [],
        "linked_task_id": getattr(linked_task, "pk", None),
        "linked_task_title": getattr(linked_task, "title", ""),
    }


def _create_linked_task(*, conversation: Conversation, user, message_kind: str, body: str, assignee=None, due_at=None):
    if conversation.kind == Conversation.KIND_ENTITY and conversation.entity is not None:
        entity = conversation.entity
        deal = None
    elif conversation.kind == Conversation.KIND_DEAL and conversation.deal is not None:
        entity = conversation.deal.entity
        deal = conversation.deal
    elif conversation.kind == Conversation.KIND_PROJECT and conversation.project is not None:
        entity = conversation.project.entity
        deal = conversation.project.deal
    else:
        raise ValueError("Solo puedes crear tareas desde un canal de ficha, oportunidad o proyecto.")

    kind_label = _get_message_kind_label(message_kind)
    task_title = Truncator(f"{kind_label}: {body}").chars(160)
    description_lines = [
        body,
        "",
        f"Origen: colaboracion interna en '{conversation.title}'.",
    ]
    if assignee is not None:
        description_lines.append(f"Responsable sugerido: {assignee.username}.")
    if due_at is not None:
        description_lines.append(f"Vence: {_format_due_label(due_at)}.")

    return Activity.objects.create(
        entity=entity,
        deal=deal,
        activity_type=Activity.TYPE_TASK,
        title=task_title,
        description="\n".join(description_lines).strip(),
        assigned_to=assignee,
        due_at=due_at,
        created_by=user,
        updated_by=user,
    )


def _ensure_conversation_membership(
    *,
    conversation: Conversation,
    user,
    actor=None,
    role: str = ConversationMembership.ROLE_MEMBER,
    clear_muted: bool = False,
    clear_archived: bool = False,
) -> ConversationMembership:
    membership, _ = ConversationMembership.objects.get_or_create(
        conversation=conversation,
        user=user,
        defaults={
            "role": role,
            "created_by": actor or user,
            "updated_by": actor or user,
        },
    )
    updates = []
    desired_roles = {
        ConversationMembership.ROLE_OBSERVER: 0,
        ConversationMembership.ROLE_MEMBER: 1,
        ConversationMembership.ROLE_MANAGER: 2,
    }
    if desired_roles.get(role, 0) > desired_roles.get(membership.role, 0):
        membership.role = role
        updates.append("role")
    if not membership.is_active:
        membership.is_active = True
        updates.append("is_active")
    if clear_muted and membership.is_muted:
        membership.is_muted = False
        updates.append("is_muted")
    if clear_archived and membership.is_archived:
        membership.is_archived = False
        updates.append("is_archived")
    if updates:
        membership.updated_by = actor or user
        updates.append("updated_by")
        membership.save(update_fields=[*updates, "updated_at"])
    return membership


def ensure_team_conversation(*, tenant, actor=None) -> Conversation:
    conversation, created = Conversation.objects.get_or_create(
        kind=Conversation.KIND_TEAM,
        title="Sala operativa",
        defaults={
            "description": "Canal interno para coordinar al equipo del tenant.",
            "created_by": actor,
            "updated_by": actor,
        },
    )
    if created:
        sync_conversation_memberships(conversation=conversation, tenant=tenant, actor=actor)
        record_tenant_event(
            tenant=tenant,
            actor=actor,
            code="collab.team.bootstrap",
            title="Canal operativo base inicializado.",
            message="Se creo la sala operativa base del tenant.",
            metadata={"conversation_id": str(conversation.pk)},
        )
    elif actor is not None:
        _ensure_conversation_membership(conversation=conversation, user=actor, actor=actor)
    return conversation


@transaction.atomic
def create_team_conversation(*, tenant, actor, title: str, description: str = "", participants=()) -> Conversation:
    """Create a tenant-local team channel and explicitly grant its initial members."""
    conversation = Conversation.objects.create(
        kind=Conversation.KIND_TEAM,
        title=(title or "").strip(),
        description=(description or "").strip(),
        created_by=actor,
        updated_by=actor,
    )
    _ensure_conversation_membership(
        conversation=conversation,
        user=actor,
        actor=actor,
        role=ConversationMembership.ROLE_MANAGER,
    )
    for participant in {user for user in participants if user is not None and user.pk != actor.pk}:
        _ensure_conversation_membership(
            conversation=conversation,
            user=participant,
            actor=actor,
            role=ConversationMembership.ROLE_MEMBER,
        )
    record_tenant_event(
        tenant=tenant,
        actor=actor,
        code="collab.team.created",
        title="Canal de equipo creado.",
        message=f"Se creo el canal '{conversation.title}'.",
        metadata={"conversation_id": str(conversation.pk)},
    )
    transaction.on_commit(
        lambda: broadcast_tenant_collab_event(
            tenant=tenant,
            conversation_id=conversation.pk,
            event_name="collab.conversation.created",
            metadata={"conversation_id": conversation.pk},
        )
    )
    return conversation


def get_entity_conversation(*, entity) -> Conversation | None:
    return (
        Conversation.objects.select_related("entity", "deal")
        .filter(kind=Conversation.KIND_ENTITY, entity=entity, is_active=True)
        .first()
    )


def ensure_entity_conversation(*, tenant, entity, actor=None) -> Conversation:
    conversation, created = Conversation.objects.get_or_create(
        kind=Conversation.KIND_ENTITY,
        entity=entity,
        defaults={
            "title": f"Ficha - {entity.full_name}",
            "description": "Conversacion contextual de la ficha.",
            "created_by": actor,
            "updated_by": actor,
        },
    )
    if created:
        record_tenant_event(
            tenant=tenant,
            actor=actor,
            code="collab.entity.bootstrap",
            title="Conversacion contextual creada para ficha.",
            message=f"Se habilito la conversacion interna de la ficha '{entity.full_name}'.",
            metadata={"conversation_id": str(conversation.pk), "entity_id": str(entity.pk)},
        )
    if actor is not None:
        _ensure_conversation_membership(
            conversation=conversation,
            user=actor,
            actor=actor,
            role=ConversationMembership.ROLE_MEMBER,
            clear_muted=True,
            clear_archived=True,
        )
    return conversation


def get_deal_conversation(*, deal) -> Conversation | None:
    return (
        Conversation.objects.select_related("deal", "deal__entity")
        .filter(kind=Conversation.KIND_DEAL, deal=deal, is_active=True)
        .first()
    )


def get_project_conversation(*, project: ObjectRecord) -> Conversation | None:
    return (
        Conversation.objects.select_related("project", "project__entity", "project__deal")
        .filter(kind=Conversation.KIND_PROJECT, project=project, is_active=True)
        .first()
    )


def ensure_project_conversation(*, tenant, project: ObjectRecord, actor=None) -> Conversation:
    conversation, created = Conversation.objects.get_or_create(
        kind=Conversation.KIND_PROJECT,
        project=project,
        defaults={
            "title": f"Proyecto - {project.title}",
            "description": "Canal operativo para coordinar la ejecucion del proyecto.",
            "created_by": actor,
            "updated_by": actor,
        },
    )
    if created:
        sync_conversation_memberships(conversation=conversation, tenant=tenant, actor=actor)
        record_tenant_event(
            tenant=tenant,
            actor=actor,
            code="collab.project.bootstrap",
            title="Canal de proyecto creado.",
            message=f"Se habilito el canal operativo de '{project.title}'.",
            metadata={"conversation_id": str(conversation.pk), "project_id": str(project.pk)},
        )
    if actor is not None:
        _ensure_conversation_membership(
            conversation=conversation,
            user=actor,
            actor=actor,
            role=ConversationMembership.ROLE_MANAGER,
            clear_muted=True,
            clear_archived=True,
        )
    return conversation


def ensure_deal_conversation(*, tenant, deal, actor=None) -> Conversation:
    conversation, created = Conversation.objects.get_or_create(
        kind=Conversation.KIND_DEAL,
        deal=deal,
        defaults={
            "title": f"Deal - {deal.title}",
            "description": "Conversacion contextual del deal.",
            "created_by": actor,
            "updated_by": actor,
        },
    )
    if created:
        record_tenant_event(
            tenant=tenant,
            actor=actor,
            code="collab.deal.bootstrap",
            title="Conversacion contextual creada para deal.",
            message=f"Se habilito la conversacion interna del deal '{deal.title}'.",
            metadata={"conversation_id": str(conversation.pk), "deal_id": str(deal.pk)},
        )
    if actor is not None:
        _ensure_conversation_membership(
            conversation=conversation,
            user=actor,
            actor=actor,
            role=ConversationMembership.ROLE_MEMBER,
            clear_muted=True,
            clear_archived=True,
        )
    return conversation


def sync_conversation_memberships(*, conversation: Conversation, tenant, actor=None) -> None:
    active_member_ids = list(
        TenantMembership.objects.filter(tenant=tenant, is_active=True).values_list("user_id", flat=True)
    )
    existing_memberships = {
        membership.user_id: membership
        for membership in ConversationMembership.objects.filter(conversation=conversation)
    }
    memberships_to_create = []
    memberships_to_update = []
    now = timezone.now()

    for user_id in active_member_ids:
        membership = existing_memberships.get(user_id)
        if membership is None:
            memberships_to_create.append(
                ConversationMembership(
                    conversation=conversation,
                    user_id=user_id,
                    role=ConversationMembership.ROLE_MEMBER,
                    is_active=True,
                    created_by=actor,
                    updated_by=actor,
                )
            )
            continue
        if not membership.is_active:
            membership.is_active = True
            membership.updated_by = actor
            membership.updated_at = now
            memberships_to_update.append(membership)

    if memberships_to_create:
        ConversationMembership.objects.bulk_create(memberships_to_create)
    if memberships_to_update:
        ConversationMembership.objects.bulk_update(
            memberships_to_update,
            ["is_active", "updated_by", "updated_at"],
        )

    stale_memberships = conversation.memberships.filter(is_active=True)
    if active_member_ids:
        stale_memberships = stale_memberships.exclude(user_id__in=active_member_ids)
    stale_memberships.update(is_active=False, updated_by=actor, updated_at=now)


def can_access_conversation(*, conversation: Conversation, user) -> bool:
    if getattr(user, "is_superuser", False):
        return True
    return conversation.memberships.filter(user=user, is_active=True).exists()


def follow_conversation(
    *,
    conversation: Conversation,
    user,
    actor=None,
    role: str = ConversationMembership.ROLE_MEMBER,
) -> ConversationMembership:
    return _ensure_conversation_membership(
        conversation=conversation,
        user=user,
        actor=actor,
        role=role,
        clear_muted=True,
        clear_archived=True,
    )


def unfollow_conversation(*, conversation: Conversation, user, actor=None) -> ConversationMembership | None:
    membership = conversation.memberships.filter(user=user).first()
    if membership is None:
        return None
    if membership.is_active:
        membership.is_active = False
        membership.updated_by = actor or user
        membership.save(update_fields=["is_active", "updated_by", "updated_at"])
    return membership


def set_conversation_muted(*, conversation: Conversation, user, muted: bool, actor=None) -> ConversationMembership:
    membership = _ensure_conversation_membership(conversation=conversation, user=user, actor=actor)
    if membership.is_muted != bool(muted):
        membership.is_muted = bool(muted)
        membership.updated_by = actor or user
        membership.save(update_fields=["is_muted", "updated_by", "updated_at"])
    return membership


def set_conversation_pinned(*, conversation: Conversation, user, pinned: bool, actor=None) -> ConversationMembership:
    membership = _ensure_conversation_membership(conversation=conversation, user=user, actor=actor)
    if membership.is_pinned != bool(pinned):
        membership.is_pinned = bool(pinned)
        membership.updated_by = actor or user
        membership.save(update_fields=["is_pinned", "updated_by", "updated_at"])
    return membership


def set_conversation_archived(*, conversation: Conversation, user, archived: bool, actor=None) -> ConversationMembership:
    membership = _ensure_conversation_membership(conversation=conversation, user=user, actor=actor)
    if membership.is_archived != bool(archived):
        membership.is_archived = bool(archived)
        membership.updated_by = actor or user
        membership.save(update_fields=["is_archived", "updated_by", "updated_at"])
    return membership


def list_inbox_summaries(*, tenant, user, search: str = "", filter_key: str = "") -> list[ConversationSummary]:
    ensure_team_conversation(tenant=tenant, actor=user)
    normalized_filter = str(filter_key or "").strip().lower()
    normalized_search = str(search or "").strip()
    conversation_queryset = Conversation.objects.select_related("entity", "deal", "project", "project__entity", "project__deal").filter(
        is_active=True,
        memberships__user=user,
        memberships__is_active=True,
    )
    if normalized_filter == "archived":
        conversation_queryset = conversation_queryset.filter(memberships__is_archived=True)
    else:
        conversation_queryset = conversation_queryset.filter(memberships__is_archived=False)

    if normalized_filter == "muted":
        conversation_queryset = conversation_queryset.filter(memberships__is_muted=True)
    elif normalized_filter == "team":
        conversation_queryset = conversation_queryset.filter(kind=Conversation.KIND_TEAM)
    elif normalized_filter == "entity":
        conversation_queryset = conversation_queryset.filter(kind=Conversation.KIND_ENTITY)
    elif normalized_filter == "deal":
        conversation_queryset = conversation_queryset.filter(kind=Conversation.KIND_DEAL)
    elif normalized_filter == "mine":
        conversation_queryset = conversation_queryset.filter(Q(messages__author=user) | Q(created_by=user))

    if normalized_search:
        conversation_queryset = conversation_queryset.filter(
            Q(title__icontains=normalized_search)
            | Q(entity__full_name__icontains=normalized_search)
            | Q(deal__title__icontains=normalized_search)
            | Q(deal__entity__full_name__icontains=normalized_search)
            | Q(project__title__icontains=normalized_search)
            | Q(project__entity__full_name__icontains=normalized_search)
            | Q(messages__body__icontains=normalized_search)
            | Q(messages__author__username__icontains=normalized_search)
        )

    conversations = list(
        conversation_queryset
        .distinct()
        .order_by("-memberships__is_pinned", "-last_message_at", "-updated_at", "-id")
    )
    if not conversations:
        return []

    conversation_ids = [conversation.pk for conversation in conversations]
    membership_map = {
        membership.conversation_id: membership
        for membership in ConversationMembership.objects.filter(
            conversation_id__in=conversation_ids,
            user=user,
            is_active=True,
        )
    }
    latest_message_ids = list(
        Message.objects.filter(conversation_id__in=conversation_ids)
        .order_by("conversation_id", "-created_at", "-id")
        .distinct("conversation_id")
        .values_list("id", flat=True)
    )
    last_message_map = {
        message.conversation_id: message
        for message in Message.objects.select_related("author").filter(id__in=latest_message_ids)
    }
    last_read_subquery = ConversationMembership.objects.filter(
        conversation_id=OuterRef("conversation_id"),
        user=user,
        is_active=True,
    ).values("last_read_at")[:1]
    unread_counts = {
        row["conversation_id"]: row["total"]
        for row in (
            Message.objects.filter(conversation_id__in=conversation_ids)
            .exclude(author=user)
            .annotate(member_last_read_at=Subquery(last_read_subquery))
            .filter(Q(member_last_read_at__isnull=True) | Q(created_at__gt=F("member_last_read_at")))
            .values("conversation_id")
            .annotate(total=Count("id"))
        )
    }
    summaries = [
        ConversationSummary(
            conversation=conversation,
            membership=membership_map.get(conversation.pk),
            unread_count=unread_counts.get(conversation.pk, 0),
            last_message=last_message_map.get(conversation.pk),
        )
        for conversation in conversations
    ]
    if normalized_filter == "unread":
        summaries = [summary for summary in summaries if summary.unread_count > 0]
    return summaries


def build_conversation_summary(*, conversation: Conversation, user) -> ConversationSummary:
    membership = conversation.memberships.filter(user=user, is_active=True).first()
    last_message = conversation.messages.select_related("author").order_by("-created_at", "-id").first()
    unread_messages = conversation.messages.exclude(author=user)
    if membership and membership.last_read_at:
        unread_messages = unread_messages.filter(created_at__gt=membership.last_read_at)
    unread_count = unread_messages.count()
    return ConversationSummary(
        conversation=conversation,
        membership=membership,
        unread_count=unread_count,
        last_message=last_message,
    )


@transaction.atomic
def post_message(
    *,
    conversation: Conversation,
    tenant,
    user,
    body: str,
    message_kind: str = Message.KIND_UPDATE,
    assignee=None,
    due_at=None,
    create_task: bool = False,
) -> Message:
    normalized_body = str(body or "").strip()
    if not normalized_body:
        raise ValueError("El mensaje no puede ir vacio.")
    normalized_kind = str(message_kind or Message.KIND_UPDATE).strip().lower()
    if normalized_kind not in MESSAGE_KIND_LABELS:
        raise ValueError("Selecciona un tipo de mensaje valido.")
    if create_task and due_at is None:
        raise ValueError("La tarea necesita fecha y hora de vencimiento.")

    membership = _ensure_conversation_membership(conversation=conversation, user=user, actor=user)
    linked_task = (
        _create_linked_task(
            conversation=conversation,
            user=user,
            message_kind=normalized_kind,
            body=normalized_body,
            assignee=assignee,
            due_at=due_at,
        )
        if create_task
        else None
    )
    mention_ids = _extract_mention_user_ids(body=normalized_body, tenant=tenant)
    message_metadata = _build_message_metadata(
        message_kind=normalized_kind,
        assignee=assignee,
        due_at=due_at,
        linked_task=linked_task,
        mention_ids=mention_ids,
    )

    message = Message.objects.create(
        conversation=conversation,
        author=user,
        body=normalized_body,
        metadata=message_metadata,
        created_by=user,
        updated_by=user,
    )
    conversation.last_message_at = message.created_at
    conversation.updated_by = user
    conversation.save(update_fields=["last_message_at", "updated_by", "updated_at"])

    membership.last_read_at = message.created_at
    membership.updated_by = user
    membership.save(update_fields=["last_read_at", "updated_by", "updated_at", "is_active"])

    notification_title = f"Nuevo mensaje en {conversation.title}"
    notification_body = normalized_body[:160]
    recipient_memberships = conversation.memberships.filter(is_active=True).exclude(user=user)
    notifications = []
    for recipient_membership in recipient_memberships:
        is_mentioned = recipient_membership.user_id in mention_ids
        # Muted members only receive notification if explicitly @mentioned.
        if recipient_membership.is_muted and not is_mentioned:
            continue
        notifications.append(
            Notification(
                user=recipient_membership.user,
                conversation=conversation,
                message=message,
                title=notification_title,
                body=notification_body,
                level=Notification.LEVEL_ATTENTION if is_mentioned else Notification.LEVEL_INFO,
                created_by=user,
                updated_by=user,
            )
        )
    if notifications:
        Notification.objects.bulk_create(notifications)
    record_tenant_event(
        tenant=tenant,
        actor=user,
        code="collab.message.posted",
        title="Mensaje interno registrado.",
        message=f"Se publico un mensaje en '{conversation.title}'.",
        metadata={
            "conversation_id": str(conversation.pk),
            "message_id": str(message.pk),
            "message_kind": normalized_kind,
            "notification_count": str(len(notifications)),
            "task_id": str(linked_task.pk) if linked_task is not None else "",
        },
    )
    transaction.on_commit(
        lambda: broadcast_tenant_collab_event(
            tenant=tenant,
            conversation_id=conversation.pk,
            event_name="collab.message.posted",
            author_id=getattr(user, "pk", None),
            message_id=message.pk,
            metadata={
                "kind": conversation.kind,
                "preview": normalized_body[:160],
                "message_kind": normalized_kind,
                "message_kind_label": message_metadata["kind_label"],
                "message_kind_tone": message_metadata["kind_tone"],
                "assignee_id": message_metadata["assignee_id"],
                "assignee_name": message_metadata["assignee_name"],
                "due_at": message_metadata["due_at"],
                "due_label": message_metadata["due_label"],
                "linked_task_id": message_metadata["linked_task_id"],
                "linked_task_title": message_metadata["linked_task_title"],
                "task_created": bool(linked_task is not None),
            },
        )
    )
    return message


def mark_conversation_as_read(*, conversation: Conversation, user) -> None:
    membership = conversation.memberships.filter(user=user, is_active=True).first()
    if membership is None:
        return
    now = timezone.now()
    membership.last_read_at = now
    membership.updated_by = user
    membership.save(update_fields=["last_read_at", "updated_by", "updated_at"])
    conversation.notifications.filter(user=user, is_read=False).update(is_read=True, read_at=now)


def get_unread_notification_count(*, user) -> int:
    return user.collab_notifications.filter(is_read=False).count()


def list_user_notifications(*, user, limit: int = 30) -> list[Notification]:
    return list(
        user.collab_notifications
        .select_related("conversation", "message", "message__author")
        .order_by("is_read", "-created_at", "-id")[:limit]
    )


def mark_notifications_read(*, user, notification_ids: list[int] | None = None) -> int:
    now = timezone.now()
    qs = user.collab_notifications.filter(is_read=False)
    if notification_ids is not None:
        qs = qs.filter(pk__in=notification_ids)
    return qs.update(is_read=True, read_at=now)
