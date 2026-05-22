from __future__ import annotations

from uuid import uuid4

from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils import timezone


class User(AbstractUser):
    STATUS_ACTIVE = "active"
    STATUS_SUSPENDED = "suspended"
    STATUS_PENDING = "pending"
    STATUS_CHOICES = [
        (STATUS_ACTIVE, "Activo"),
        (STATUS_SUSPENDED, "Suspendido"),
        (STATUS_PENDING, "Pendiente"),
    ]

    uuid = models.UUIDField(default=uuid4, unique=True, editable=False)
    preferred_name = models.CharField(max_length=80, blank=True)
    display_name = models.CharField(max_length=160, blank=True)
    account_status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_ACTIVE)
    must_rotate_password = models.BooleanField(default=False)
    last_global_login_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "Global user"
        verbose_name_plural = "Global users"

    def __str__(self):
        return self.get_display_name() or self.get_username()

    def clean(self):
        super().clean()
        self.email = self.__class__.objects.normalize_email(self.email)
        if self.account_status in {self.STATUS_SUSPENDED, self.STATUS_PENDING}:
            self.is_active = False

    def save(self, *args, **kwargs):
        if self.email:
            self.email = self.__class__.objects.normalize_email(self.email)
        if self.account_status in {self.STATUS_SUSPENDED, self.STATUS_PENDING}:
            self.is_active = False
        super().save(*args, **kwargs)

    def get_display_name(self) -> str:
        if self.display_name:
            return self.display_name.strip()
        if self.preferred_name:
            return self.preferred_name.strip()
        full_name = self.get_full_name().strip()
        if full_name:
            return full_name
        return self.get_username()


class GlobalSession(models.Model):
    STATE_ACTIVE = "active"
    STATE_ENDED = "ended"
    STATE_REVOKED = "revoked"
    STATE_CHOICES = [
        (STATE_ACTIVE, "Activa"),
        (STATE_ENDED, "Cerrada"),
        (STATE_REVOKED, "Revocada"),
    ]

    SCOPE_STRICT_ISOLATION = "strict_isolation"
    SCOPE_CONSOLIDATED = "consolidated"
    SCOPE_IMPERSONATED = "impersonated"
    SCOPE_CHOICES = [
        (SCOPE_STRICT_ISOLATION, "Strict isolation"),
        (SCOPE_CONSOLIDATED, "Consolidated"),
        (SCOPE_IMPERSONATED, "Impersonated"),
    ]

    user = models.ForeignKey("identity.User", on_delete=models.CASCADE, related_name="global_sessions")
    session_key = models.CharField(max_length=64, unique=True)
    auth_backend = models.CharField(max_length=255, blank=True)
    state = models.CharField(max_length=20, choices=STATE_CHOICES, default=STATE_ACTIVE)
    scope = models.CharField(max_length=32, choices=SCOPE_CHOICES, default=SCOPE_STRICT_ISOLATION)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True)
    request_id = models.CharField(max_length=64, blank=True)
    active_tenant_schema = models.CharField(max_length=63, blank=True)
    impersonator_user_id = models.PositiveBigIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    last_seen_at = models.DateTimeField(default=timezone.now)
    ended_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    ended_reason = models.CharField(max_length=120, blank=True)

    class Meta:
        ordering = ["-last_seen_at", "-id"]
        verbose_name = "Global session"
        verbose_name_plural = "Global sessions"

    def __str__(self):
        return f"{self.user} [{self.state}]"

    @property
    def is_open(self) -> bool:
        return self.state == self.STATE_ACTIVE and self.ended_at is None and self.revoked_at is None
