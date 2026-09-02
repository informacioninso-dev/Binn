from __future__ import annotations

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from core.models import AuditModel


class Conversation(AuditModel):
    KIND_TEAM = "team"
    KIND_ENTITY = "entity"
    KIND_DEAL = "deal"
    KIND_PROJECT = "project"
    KIND_CHOICES = [
        (KIND_TEAM, "Equipo"),
        (KIND_ENTITY, "Ficha"),
        (KIND_DEAL, "Deal"),
        (KIND_PROJECT, "Proyecto"),
    ]

    title = models.CharField(max_length=160)
    description = models.TextField(blank=True)
    kind = models.CharField(max_length=20, choices=KIND_CHOICES, default=KIND_TEAM)
    entity = models.ForeignKey(
        "binncrm.Entity",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="conversations",
    )
    deal = models.ForeignKey(
        "binncrm.Deal",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="conversations",
    )
    project = models.ForeignKey(
        "binncrm.ObjectRecord",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="conversations",
    )
    last_message_at = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["-last_message_at", "-updated_at", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["kind", "entity"],
                condition=Q(entity__isnull=False),
                name="collab_unique_entity_conversation",
            ),
            models.UniqueConstraint(
                fields=["kind", "deal"],
                condition=Q(deal__isnull=False),
                name="collab_unique_deal_conversation",
            ),
            models.UniqueConstraint(
                fields=["kind", "project"],
                condition=Q(project__isnull=False),
                name="collab_unique_project_conversation",
            ),
        ]
        indexes = [
            models.Index(fields=["is_active", "last_message_at"], name="collab_conversation_recent_idx"),
        ]

    def __str__(self):
        return self.title

    def clean(self):
        if self.kind == self.KIND_ENTITY and not self.entity_id:
            raise ValidationError({"entity": "La conversacion de ficha requiere una entidad."})
        if self.kind == self.KIND_DEAL and not self.deal_id:
            raise ValidationError({"deal": "La conversacion de deal requiere un deal."})
        if self.kind == self.KIND_PROJECT and not self.project_id:
            raise ValidationError({"project": "La conversacion de proyecto requiere un proyecto."})
        if self.kind == self.KIND_TEAM and (self.entity_id or self.deal_id or self.project_id):
            raise ValidationError("La conversacion de equipo no debe quedar pegada a una ficha, deal o proyecto.")


class ConversationMembership(AuditModel):
    ROLE_MANAGER = "manager"
    ROLE_MEMBER = "member"
    ROLE_OBSERVER = "observer"
    ROLE_CHOICES = [
        (ROLE_MANAGER, "Manager"),
        (ROLE_MEMBER, "Miembro"),
        (ROLE_OBSERVER, "Observador"),
    ]

    conversation = models.ForeignKey(Conversation, on_delete=models.CASCADE, related_name="memberships")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="conversation_memberships")
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default=ROLE_MEMBER)
    last_read_at = models.DateTimeField(null=True, blank=True)
    is_muted = models.BooleanField(default=False)
    is_pinned = models.BooleanField(default=False)
    is_archived = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["conversation__title", "user__username"]
        unique_together = ("conversation", "user")
        indexes = [
            models.Index(fields=["user", "is_active", "conversation"], name="collab_member_user_idx"),
            models.Index(
                fields=["user", "is_active", "is_archived", "is_pinned"],
                name="collab_member_inbox_idx",
            ),
        ]

    def __str__(self):
        return f"{self.user} -> {self.conversation}"


class Message(AuditModel):
    KIND_UPDATE = "update"
    KIND_BLOCKER = "blocker"
    KIND_DECISION = "decision"
    KIND_HANDOFF = "handoff"
    KIND_NEXT_STEP = "next_step"
    KIND_CHOICES = [
        (KIND_UPDATE, "Actualizacion"),
        (KIND_BLOCKER, "Bloqueo"),
        (KIND_DECISION, "Decision"),
        (KIND_HANDOFF, "Handoff"),
        (KIND_NEXT_STEP, "Siguiente paso"),
    ]
    KIND_TONE_MAP = {
        KIND_UPDATE: "is-info",
        KIND_BLOCKER: "is-danger",
        KIND_DECISION: "is-success",
        KIND_HANDOFF: "is-warning",
        KIND_NEXT_STEP: "is-primary",
    }

    conversation = models.ForeignKey(Conversation, on_delete=models.CASCADE, related_name="messages")
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="conversation_messages")
    body = models.TextField()
    metadata = models.JSONField(default=dict, blank=True)
    is_system = models.BooleanField(default=False)
    edited_at = models.DateTimeField(null=True, blank=True)
    deleted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["created_at", "id"]
        indexes = [
            models.Index(fields=["conversation", "created_at"], name="collab_message_conv_idx"),
            models.Index(fields=["author", "created_at"], name="collab_message_author_idx"),
        ]

    def __str__(self):
        return f"{self.author} @ {self.conversation}"


class Notification(AuditModel):
    LEVEL_INFO = "info"
    LEVEL_ATTENTION = "attention"
    LEVEL_CHOICES = [
        (LEVEL_INFO, "Info"),
        (LEVEL_ATTENTION, "Atencion"),
    ]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="collab_notifications")
    conversation = models.ForeignKey(Conversation, on_delete=models.CASCADE, related_name="notifications")
    message = models.ForeignKey(Message, on_delete=models.CASCADE, related_name="notifications")
    title = models.CharField(max_length=160)
    body = models.TextField(blank=True)
    level = models.CharField(max_length=20, choices=LEVEL_CHOICES, default=LEVEL_INFO)
    is_read = models.BooleanField(default=False)
    read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["is_read", "-created_at", "-id"]
        unique_together = ("user", "message")
        indexes = [
            models.Index(fields=["user", "is_read", "created_at"], name="collab_notification_user_idx"),
        ]

    def __str__(self):
        return f"{self.user} | {self.title}"
