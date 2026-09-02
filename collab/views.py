from __future__ import annotations

import json
from urllib.parse import urlencode

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from access.permissions import (
    PERMISSION_ACTIVITIES_EDIT,
    PERMISSION_COLLAB_EDIT,
    PERMISSION_COLLAB_VIEW,
    request_has_tenant_permission,
    tenant_permission_required,
)
from binncrm.models import Deal, Entity

from .forms import MessageForm, TeamChannelForm
from .models import Conversation
from .services import (
    build_conversation_summary,
    can_access_conversation,
    create_team_conversation,
    ensure_deal_conversation,
    ensure_entity_conversation,
    follow_conversation,
    get_deal_conversation,
    get_entity_conversation,
    get_unread_notification_count,
    list_inbox_summaries,
    list_user_notifications,
    mark_conversation_as_read,
    mark_notifications_read,
    post_message,
    set_conversation_archived,
    set_conversation_muted,
    set_conversation_pinned,
    unfollow_conversation,
)


def _can_post_messages(request) -> bool:
    return request_has_tenant_permission(request, PERMISSION_COLLAB_EDIT)


def _can_link_tasks(request) -> bool:
    tenant = getattr(request, "tenant", None)
    return bool(
        tenant is not None
        and tenant.has_capability("activities")
        and request_has_tenant_permission(request, PERMISSION_ACTIVITIES_EDIT)
    )


def _resolve_inbox_filters(request) -> tuple[str, str]:
    search_query = (request.GET.get("q") or "").strip()
    filter_key = (request.GET.get("filter") or "").strip().lower()
    if filter_key not in {"", "unread", "mine", "team", "entity", "deal", "muted", "archived"}:
        filter_key = ""
    return search_query, filter_key


def _build_inbox_url(*, search_query: str = "", filter_key: str = "", selected_conversation_id=None, list_view: bool = False) -> str:
    route_name = "collab:inbox_list" if list_view else "collab:inbox"
    params = {}
    if search_query:
        params["q"] = search_query
    if filter_key:
        params["filter"] = filter_key
    if selected_conversation_id:
        params["conversation"] = selected_conversation_id
    base_url = reverse(route_name)
    return f"{base_url}?{urlencode(params)}" if params else base_url


def _build_filter_options(*, search_query: str = "", selected_conversation_id=None, active_filter: str = "") -> list[dict]:
    return [
        {
            "key": "",
            "label": "Todo",
            "url": _build_inbox_url(
                search_query=search_query,
                filter_key="",
                selected_conversation_id=selected_conversation_id,
            ),
            "is_active": active_filter == "",
        },
        {
            "key": "unread",
            "label": "No leidos",
            "url": _build_inbox_url(
                search_query=search_query,
                filter_key="unread",
                selected_conversation_id=selected_conversation_id,
            ),
            "is_active": active_filter == "unread",
        },
        {
            "key": "mine",
            "label": "Mios",
            "url": _build_inbox_url(
                search_query=search_query,
                filter_key="mine",
                selected_conversation_id=selected_conversation_id,
            ),
            "is_active": active_filter == "mine",
        },
        {
            "key": "team",
            "label": "Equipo",
            "url": _build_inbox_url(
                search_query=search_query,
                filter_key="team",
                selected_conversation_id=selected_conversation_id,
            ),
            "is_active": active_filter == "team",
        },
        {
            "key": "entity",
            "label": "Fichas",
            "url": _build_inbox_url(
                search_query=search_query,
                filter_key="entity",
                selected_conversation_id=selected_conversation_id,
            ),
            "is_active": active_filter == "entity",
        },
        {
            "key": "deal",
            "label": "Deals",
            "url": _build_inbox_url(
                search_query=search_query,
                filter_key="deal",
                selected_conversation_id=selected_conversation_id,
            ),
            "is_active": active_filter == "deal",
        },
        {
            "key": "muted",
            "label": "Silenciados",
            "url": _build_inbox_url(
                search_query=search_query,
                filter_key="muted",
                selected_conversation_id=selected_conversation_id,
            ),
            "is_active": active_filter == "muted",
        },
        {
            "key": "archived",
            "label": "Archivados",
            "url": _build_inbox_url(
                search_query=search_query,
                filter_key="archived",
                selected_conversation_id=selected_conversation_id,
            ),
            "is_active": active_filter == "archived",
        },
    ]


def _build_message_form(request, *, form=None, conversation=None, entity=None):
    message_form = form or MessageForm(
        tenant=request.tenant,
        current_user=request.user,
        task_context_enabled=bool(entity) or (
            conversation is not None and conversation.kind in {Conversation.KIND_ENTITY, Conversation.KIND_DEAL, Conversation.KIND_PROJECT}
        ),
        allow_task_linking=_can_link_tasks(request)
        and (bool(entity) or (conversation is not None and conversation.kind in {Conversation.KIND_ENTITY, Conversation.KIND_DEAL, Conversation.KIND_PROJECT})),
    )
    message_form.fields["body"].widget.attrs["placeholder"] = (
        "Escribe una nota operativa que deje claro que paso y que sigue."
    )
    return message_form


def _is_htmx_request(request) -> bool:
    return request.headers.get("HX-Request") == "true"


def _apply_collab_list_refresh(response):
    if response is not None:
        response.headers["HX-Trigger"] = json.dumps({"binn:collab-refresh-list": True})
    return response


def _build_inbox_context(request, *, active_summary=None):
    search_query, active_filter = _resolve_inbox_filters(request)
    selected_id = (request.GET.get("conversation") or "").strip()
    summaries = list_inbox_summaries(
        tenant=request.tenant,
        user=request.user,
        search=search_query,
        filter_key=active_filter,
    )
    # Track explicit selection separately so auto-select doesn't trigger mark-as-read.
    explicitly_selected = active_summary is not None
    if not explicitly_selected and selected_id.isdigit():
        active_summary = next((summary for summary in summaries if summary.conversation.pk == int(selected_id)), None)
        explicitly_selected = active_summary is not None
    if active_summary is None and summaries:
        active_summary = summaries[0]
    if active_summary is not None and explicitly_selected:
        selected_conversation = active_summary.conversation
        mark_conversation_as_read(conversation=selected_conversation, user=request.user)
        selected_id = str(selected_conversation.pk)
        summaries = list_inbox_summaries(
            tenant=request.tenant,
            user=request.user,
            search=search_query,
            filter_key=active_filter,
        )
        refreshed_summary = next(
            (summary for summary in summaries if str(summary.conversation.pk) == selected_id),
            None,
        )
        active_summary = build_conversation_summary(
            conversation=(refreshed_summary.conversation if refreshed_summary is not None else selected_conversation),
            user=request.user,
        )
    selected_conversation_id = getattr(getattr(active_summary, "conversation", None), "pk", None)
    return {
        "conversation_summaries": summaries,
        "active_conversation": getattr(active_summary, "conversation", None),
        "active_summary": active_summary,
        "message_form": _build_message_form(request),
        "search_query": search_query,
        "active_filter": active_filter,
        "selected_conversation_id": selected_conversation_id,
        "filter_options": _build_filter_options(
            search_query=search_query,
            selected_conversation_id=selected_conversation_id,
            active_filter=active_filter,
        ),
        "inbox_url": _build_inbox_url(
            search_query=search_query,
            filter_key=active_filter,
            selected_conversation_id=selected_conversation_id,
        ),
        "inbox_list_url": _build_inbox_url(
            search_query=search_query,
            filter_key=active_filter,
            selected_conversation_id=None,
            list_view=True,
        ),
        "unread_total": sum(summary.unread_count for summary in summaries),
        "pinned_total": sum(1 for summary in summaries if getattr(summary.membership, "is_pinned", False)),
        "archived_total": sum(1 for summary in summaries if getattr(summary.membership, "is_archived", False)),
        "has_pinned_summaries": any(getattr(summary.membership, "is_pinned", False) for summary in summaries),
        "can_create_team_channel": _can_post_messages(request),
    }


def _render_context_bootstrap_panel(request, *, layout: str = "compact", form=None, conversation=None, entity=None, deal=None):
    response = render(
        request,
        "collab/_conversation_panel.html",
        {
            "conversation": None,
            "existing_conversation": conversation,
            "existing_members_count": (
                conversation.memberships.filter(is_active=True).count()
                if conversation is not None
                else 0
            ),
            "conversation_summary": None,
            "conversation_memberships": [],
            "current_membership": None,
            "entity": entity,
            "deal": deal,
            "messages_feed": [],
            "message_form": _build_message_form(
                request,
                form=form,
                conversation=conversation,
                entity=entity or getattr(deal, "entity", None),
            ),
            "layout": layout,
            "can_post_messages": _can_post_messages(request),
        },
    )
    return _apply_collab_list_refresh(response) if _is_htmx_request(request) else response


def _render_conversation_panel(request, *, conversation, layout: str = "full", form=None, refresh_list: bool = True):
    if not can_access_conversation(conversation=conversation, user=request.user):
        messages.error(request, "No tienes acceso a esta conversacion.")
        return redirect("collab:inbox")

    mark_conversation_as_read(conversation=conversation, user=request.user)
    summary = build_conversation_summary(conversation=conversation, user=request.user)
    messages_feed = list(conversation.messages.select_related("author").order_by("-created_at", "-id")[:30])
    messages_feed.reverse()
    context = {
        "conversation": conversation,
        "existing_conversation": None,
        "existing_members_count": 0,
        "conversation_summary": summary,
        "current_membership": summary.membership,
        "conversation_memberships": conversation.memberships.select_related("user").filter(is_active=True).order_by("user__username"),
        "entity": conversation.entity if conversation.kind == Conversation.KIND_ENTITY else getattr(conversation.project, "entity", None),
        "deal": conversation.deal if conversation.kind == Conversation.KIND_DEAL else getattr(conversation.project, "deal", None),
        "project": conversation.project if conversation.kind == Conversation.KIND_PROJECT else None,
        "messages_feed": messages_feed,
        "message_form": _build_message_form(
            request,
            form=form,
            conversation=conversation,
            entity=conversation.entity if conversation.kind == Conversation.KIND_ENTITY else getattr(conversation.project, "entity", None),
        ),
        "layout": layout,
        "can_post_messages": _can_post_messages(request),
    }
    response = render(request, "collab/_conversation_panel.html", context)
    if _is_htmx_request(request) and refresh_list:
        return _apply_collab_list_refresh(response)
    return response


@login_required
@tenant_permission_required(PERMISSION_COLLAB_VIEW, capability="collab")
def inbox(request):
    return render(request, "collab/inbox.html", _build_inbox_context(request))


@login_required
@tenant_permission_required(PERMISSION_COLLAB_EDIT, capability="collab")
def team_channel_create(request):
    form = TeamChannelForm(request.POST or None, tenant=request.tenant)
    if request.method == "POST" and form.is_valid():
        conversation = create_team_conversation(
            tenant=request.tenant,
            actor=request.user,
            title=form.cleaned_data["title"],
            description=form.cleaned_data["description"],
            participants=form.cleaned_data["participants"],
        )
        return redirect("collab:conversation_detail", pk=conversation.pk)
    return render(request, "collab/team_channel_form.html", {"form": form})


@login_required
@tenant_permission_required(PERMISSION_COLLAB_VIEW, capability="collab")
def conversation_detail(request, pk):
    conversation = get_object_or_404(Conversation, pk=pk, is_active=True)
    if not can_access_conversation(conversation=conversation, user=request.user):
        messages.error(request, "No puedes abrir esta conversacion.")
        return redirect("collab:inbox")
    active_summary = build_conversation_summary(conversation=conversation, user=request.user)
    return render(request, "collab/inbox.html", _build_inbox_context(request, active_summary=active_summary))


@login_required
@tenant_permission_required(PERMISSION_COLLAB_VIEW, capability="collab")
def inbox_list(request):
    context = _build_inbox_context(request)
    return render(request, "collab/_conversation_list.html", context)


@login_required
@tenant_permission_required(PERMISSION_COLLAB_VIEW, capability="collab")
def conversation_panel(request, pk):
    conversation = get_object_or_404(Conversation, pk=pk, is_active=True)
    # The panel endpoint is only for HTMX swaps. A direct browser visit must load
    # the full inbox shell instead of rendering an unstyled fragment by itself.
    if not _is_htmx_request(request):
        return redirect("collab:conversation_detail", pk=conversation.pk)
    return _render_conversation_panel(
        request,
        conversation=conversation,
        layout=(request.GET.get("layout") or "full").strip() or "full",
        refresh_list=False,
    )


@login_required
@tenant_permission_required(PERMISSION_COLLAB_VIEW, capability="collab")
def entity_panel(request, entity_id):
    entity = get_object_or_404(Entity, pk=entity_id)
    conversation = get_entity_conversation(entity=entity)
    if conversation is None or not can_access_conversation(conversation=conversation, user=request.user):
        return _render_context_bootstrap_panel(
            request,
            entity=entity,
            layout=(request.GET.get("layout") or "compact").strip() or "compact",
            conversation=conversation,
        )
    return _render_conversation_panel(
        request,
        conversation=conversation,
        layout=(request.GET.get("layout") or "compact").strip() or "compact",
    )


@login_required
@tenant_permission_required(PERMISSION_COLLAB_VIEW, capability="collab")
def deal_panel(request, deal_id):
    deal = get_object_or_404(Deal.objects.select_related("entity", "pipeline"), pk=deal_id)
    conversation = get_deal_conversation(deal=deal)
    if conversation is None or not can_access_conversation(conversation=conversation, user=request.user):
        return _render_context_bootstrap_panel(
            request,
            deal=deal,
            layout=(request.GET.get("layout") or "compact").strip() or "compact",
            conversation=conversation,
        )
    return _render_conversation_panel(
        request,
        conversation=conversation,
        layout=(request.GET.get("layout") or "compact").strip() or "compact",
    )


@login_required
@tenant_permission_required(PERMISSION_COLLAB_VIEW, capability="collab")
@require_POST
def entity_follow(request, entity_id):
    entity = get_object_or_404(Entity, pk=entity_id)
    conversation = ensure_entity_conversation(tenant=request.tenant, entity=entity, actor=request.user)
    follow_conversation(conversation=conversation, user=request.user, actor=request.user)
    return _render_conversation_panel(
        request,
        conversation=conversation,
        layout=(request.POST.get("layout") or "compact").strip() or "compact",
    )


@login_required
@tenant_permission_required(PERMISSION_COLLAB_VIEW, capability="collab")
@require_POST
def deal_follow(request, deal_id):
    deal = get_object_or_404(Deal.objects.select_related("entity", "pipeline"), pk=deal_id)
    conversation = ensure_deal_conversation(tenant=request.tenant, deal=deal, actor=request.user)
    follow_conversation(conversation=conversation, user=request.user, actor=request.user)
    return _render_conversation_panel(
        request,
        conversation=conversation,
        layout=(request.POST.get("layout") or "compact").strip() or "compact",
    )


@login_required
@tenant_permission_required(PERMISSION_COLLAB_EDIT, capability="collab")
@require_POST
def entity_post(request, entity_id):
    entity = get_object_or_404(Entity, pk=entity_id)
    conversation = get_entity_conversation(entity=entity)
    form = MessageForm(
        request.POST,
        tenant=request.tenant,
        current_user=request.user,
        task_context_enabled=True,
        allow_task_linking=_can_link_tasks(request),
    )
    if form.is_valid():
        conversation = conversation or ensure_entity_conversation(tenant=request.tenant, entity=entity, actor=request.user)
        try:
            post_message(
                conversation=conversation,
                tenant=request.tenant,
                user=request.user,
                body=form.cleaned_data["body"],
                message_kind=form.cleaned_data["message_kind"],
                assignee=form.cleaned_data["assignee"],
                due_at=form.cleaned_data["due_at"],
                create_task=form.cleaned_data["create_task"],
            )
        except ValueError as exc:
            form.add_error(None, str(exc))
        else:
            form = _build_message_form(request, conversation=conversation, entity=entity)

    if conversation is None or not can_access_conversation(conversation=conversation, user=request.user):
        return _render_context_bootstrap_panel(
            request,
            entity=entity,
            layout=(request.POST.get("layout") or "compact").strip() or "compact",
            form=form,
            conversation=conversation,
        )
    return _render_conversation_panel(
        request,
        conversation=conversation,
        layout=(request.POST.get("layout") or "compact").strip() or "compact",
        form=form,
    )


@login_required
@tenant_permission_required(PERMISSION_COLLAB_EDIT, capability="collab")
@require_POST
def deal_post(request, deal_id):
    deal = get_object_or_404(Deal.objects.select_related("entity", "pipeline"), pk=deal_id)
    conversation = get_deal_conversation(deal=deal)
    form = MessageForm(
        request.POST,
        tenant=request.tenant,
        current_user=request.user,
        task_context_enabled=True,
        allow_task_linking=_can_link_tasks(request),
    )
    if form.is_valid():
        conversation = conversation or ensure_deal_conversation(tenant=request.tenant, deal=deal, actor=request.user)
        try:
            post_message(
                conversation=conversation,
                tenant=request.tenant,
                user=request.user,
                body=form.cleaned_data["body"],
                message_kind=form.cleaned_data["message_kind"],
                assignee=form.cleaned_data["assignee"],
                due_at=form.cleaned_data["due_at"],
                create_task=form.cleaned_data["create_task"],
            )
        except ValueError as exc:
            form.add_error(None, str(exc))
        else:
            form = _build_message_form(request, conversation=conversation, entity=deal.entity)

    if conversation is None or not can_access_conversation(conversation=conversation, user=request.user):
        return _render_context_bootstrap_panel(
            request,
            deal=deal,
            layout=(request.POST.get("layout") or "compact").strip() or "compact",
            form=form,
            conversation=conversation,
        )
    return _render_conversation_panel(
        request,
        conversation=conversation,
        layout=(request.POST.get("layout") or "compact").strip() or "compact",
        form=form,
    )


@login_required
@tenant_permission_required(PERMISSION_COLLAB_VIEW, capability="collab")
@require_POST
def conversation_membership_update(request, pk):
    conversation = get_object_or_404(Conversation, pk=pk, is_active=True)
    if not can_access_conversation(conversation=conversation, user=request.user):
        messages.error(request, "No puedes administrar este canal.")
        return redirect("collab:inbox")

    action = (request.POST.get("action") or "").strip().lower()
    layout = (request.POST.get("layout") or "full").strip() or "full"
    source = (request.POST.get("source") or "panel").strip().lower()
    next_url = (request.POST.get("next") or "").strip()

    if action == "mute":
        set_conversation_muted(conversation=conversation, user=request.user, muted=True, actor=request.user)
    elif action == "unmute":
        set_conversation_muted(conversation=conversation, user=request.user, muted=False, actor=request.user)
    elif action == "pin":
        set_conversation_pinned(conversation=conversation, user=request.user, pinned=True, actor=request.user)
    elif action == "unpin":
        set_conversation_pinned(conversation=conversation, user=request.user, pinned=False, actor=request.user)
    elif action == "archive":
        set_conversation_archived(conversation=conversation, user=request.user, archived=True, actor=request.user)
    elif action == "unarchive":
        set_conversation_archived(conversation=conversation, user=request.user, archived=False, actor=request.user)
    elif action == "unfollow" and conversation.kind != Conversation.KIND_TEAM:
        unfollow_conversation(conversation=conversation, user=request.user, actor=request.user)
        if layout == "compact" and conversation.kind == Conversation.KIND_ENTITY and conversation.entity is not None:
            return _render_context_bootstrap_panel(
                request,
                entity=conversation.entity,
                layout=layout,
                conversation=conversation,
            )
        if layout == "compact" and conversation.kind == Conversation.KIND_DEAL and conversation.deal is not None:
            return _render_context_bootstrap_panel(
                request,
                deal=conversation.deal,
                layout=layout,
                conversation=conversation,
            )

    if source == "list":
        return redirect(next_url or _build_inbox_url())

    return _render_conversation_panel(
        request,
        conversation=conversation,
        layout=layout,
    )


@login_required
@tenant_permission_required(PERMISSION_COLLAB_EDIT, capability="collab")
@require_POST
def conversation_post(request, pk):
    conversation = get_object_or_404(Conversation, pk=pk, is_active=True)
    if not can_access_conversation(conversation=conversation, user=request.user):
        messages.error(request, "No puedes escribir en esta conversacion.")
        return redirect("collab:inbox")

    task_context_enabled = conversation.kind in {Conversation.KIND_ENTITY, Conversation.KIND_DEAL, Conversation.KIND_PROJECT}
    form = MessageForm(
        request.POST,
        tenant=request.tenant,
        current_user=request.user,
        task_context_enabled=task_context_enabled,
        allow_task_linking=_can_link_tasks(request) and task_context_enabled,
    )
    if form.is_valid():
        try:
            post_message(
                conversation=conversation,
                tenant=request.tenant,
                user=request.user,
                body=form.cleaned_data["body"],
                message_kind=form.cleaned_data["message_kind"],
                assignee=form.cleaned_data["assignee"],
                due_at=form.cleaned_data["due_at"],
                create_task=form.cleaned_data["create_task"],
            )
        except ValueError as exc:
            form.add_error(None, str(exc))
        else:
            form = _build_message_form(
                request,
                conversation=conversation,
                entity=conversation.entity if conversation.kind == Conversation.KIND_ENTITY else getattr(conversation.project, "entity", None),
            )

    return _render_conversation_panel(
        request,
        conversation=conversation,
        layout=(request.POST.get("layout") or "full").strip() or "full",
        form=form,
    )


@login_required
@tenant_permission_required(PERMISSION_COLLAB_VIEW, capability="collab")
def notification_center(request):
    notifications = list_user_notifications(user=request.user)
    unread_total = get_unread_notification_count(user=request.user)
    return render(
        request,
        "collab/_notification_center.html",
        {"notifications": notifications, "unread_total": unread_total},
    )


@login_required
@tenant_permission_required(PERMISSION_COLLAB_VIEW, capability="collab")
@require_POST
def notification_mark_read(request):
    raw_ids = request.POST.getlist("notification_id")
    notification_ids = [int(x) for x in raw_ids if x.isdigit()] or None
    mark_notifications_read(user=request.user, notification_ids=notification_ids)
    if _is_htmx_request(request):
        notifications = list_user_notifications(user=request.user)
        return render(
            request,
            "collab/_notification_center.html",
            {"notifications": notifications, "unread_total": 0},
        )
    return redirect((request.POST.get("next") or "").strip() or reverse("collab:inbox"))
