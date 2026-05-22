from django.contrib import admin

from .models import Conversation, ConversationMembership, Message, Notification


@admin.register(Conversation)
class ConversationAdmin(admin.ModelAdmin):
    list_display = ("title", "kind", "entity", "deal", "last_message_at", "is_active")
    list_filter = ("kind", "is_active")
    search_fields = ("title", "entity__full_name", "deal__title")


@admin.register(ConversationMembership)
class ConversationMembershipAdmin(admin.ModelAdmin):
    list_display = ("conversation", "user", "role", "is_active", "is_muted", "last_read_at")
    list_filter = ("role", "is_active", "is_muted")
    search_fields = ("conversation__title", "user__username")


@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = ("conversation", "author", "created_at", "is_system")
    list_filter = ("is_system",)
    search_fields = ("conversation__title", "author__username", "body")


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ("user", "conversation", "title", "is_read", "created_at")
    list_filter = ("is_read", "level")
    search_fields = ("user__username", "conversation__title", "title", "body")
