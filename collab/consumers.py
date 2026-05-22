from __future__ import annotations

from types import SimpleNamespace
from urllib.parse import parse_qs

from django.conf import settings
from django_tenants.utils import schema_context

from access.contracts import ActiveSessionContext, SessionScope
from access.permissions import PERMISSION_COLLAB_VIEW
from access.resolvers import RequestAccessResolver
from access.runtime import build_access_subject
from access.models import ActiveAccessContext
from tenants.models import Domain

from .realtime import build_tenant_stream_group

try:
    from channels.db import database_sync_to_async
    from channels.generic.websocket import AsyncJsonWebsocketConsumer
except ImportError as exc:  # pragma: no cover - imported only when channels is available
    raise RuntimeError("Channels debe estar instalado para usar collab realtime.") from exc


class TenantCollabStreamConsumer(AsyncJsonWebsocketConsumer):
    async def connect(self):
        auth = await self._authorize_scope()
        if not auth["allowed"]:
            await self.close(code=4403)
            return

        self.tenant = auth["tenant"]
        self.group_name = build_tenant_stream_group(self.tenant.schema_name)
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()
        await self.send_json(
            {
                "type": "collab.ready",
                "tenant": self.tenant.schema_name,
            }
        )

    async def disconnect(self, code):
        group_name = getattr(self, "group_name", "")
        if group_name:
            await self.channel_layer.group_discard(group_name, self.channel_name)

    async def receive_json(self, content, **kwargs):
        event_type = (content or {}).get("type")
        if event_type == "collab.ping":
            await self.send_json({"type": "collab.pong"})

    async def collab_event(self, event):
        await self.send_json(
            {
                "type": event.get("event_name", "collab.unknown"),
                "conversation_id": event.get("conversation_id"),
                "author_id": event.get("author_id"),
                "message_id": event.get("message_id"),
                "metadata": event.get("metadata") or {},
            }
        )

    @database_sync_to_async
    def _authorize_scope(self):
        user = self.scope.get("user")
        if user is None or not getattr(user, "is_authenticated", False):
            return {"allowed": False, "tenant": None}

        tenant = _resolve_tenant_from_scope(self.scope)
        if tenant is None or tenant.schema_name == settings.PUBLIC_SCHEMA_NAME or not tenant.is_active:
            return {"allowed": False, "tenant": None}

        if not tenant.has_capability("collab"):
            return {"allowed": False, "tenant": tenant}

        with schema_context(tenant.schema_name):
            if getattr(user, "is_superuser", False):
                return {"allowed": True, "tenant": tenant}

            context = _resolve_active_context(scope=self.scope, user=user, tenant=tenant)
            request_like = SimpleNamespace(
                user=user,
                tenant=tenant,
                access_subject=build_access_subject(user),
                active_session_context=context,
            )
            decision = RequestAccessResolver(request_like).resolve(
                subject=request_like.access_subject,
                context=request_like.active_session_context,
                target_tenant_id=tenant.pk,
                permission_code=PERMISSION_COLLAB_VIEW,
            )
            return {"allowed": decision.allowed, "tenant": tenant}


def _resolve_tenant_from_scope(scope):
    headers = {
        key.decode("latin1").lower(): value.decode("latin1")
        for key, value in (scope.get("headers") or [])
    }
    host = (headers.get("host") or "").split(":", 1)[0].lower()
    query = parse_qs((scope.get("query_string") or b"").decode("utf-8"))
    requested_schema = (query.get("tenant") or [""])[0].strip().lower()

    if host in {"localhost", "127.0.0.1"} and requested_schema:
        preview_domain = (
            Domain.objects.select_related("tenant")
            .filter(tenant__schema_name=requested_schema, tenant__is_active=True)
            .first()
        )
        return preview_domain.tenant if preview_domain else None

    domain = (
        Domain.objects.select_related("tenant")
        .filter(domain=host, tenant__is_active=True)
        .first()
    )
    return domain.tenant if domain else None


def _resolve_active_context(*, scope, user, tenant) -> ActiveSessionContext:
    session = scope.get("session")
    session_key = getattr(session, "session_key", None)
    context_record = None
    if session_key:
        context_record = (
            ActiveAccessContext.objects.select_related("active_tenant", "corporate_group", "global_session")
            .filter(global_session__session_key=session_key, global_session__user=user)
            .first()
        )
    if context_record is None:
        return ActiveSessionContext(
            scope=SessionScope.STRICT_ISOLATION,
            tenant_id=tenant.pk,
            corporate_group_id=None,
            impersonator_user_id=None,
            reason="websocket_bootstrap",
        )
    return ActiveSessionContext(
        scope=SessionScope(context_record.scope),
        tenant_id=context_record.active_tenant_id,
        corporate_group_id=context_record.corporate_group_id,
        impersonator_user_id=context_record.impersonator_id,
        reason=context_record.reason,
    )
