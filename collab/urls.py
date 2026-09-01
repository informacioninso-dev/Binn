from django.urls import path

from . import views


app_name = "collab"

urlpatterns = [
    path("", views.inbox, name="inbox"),
    path("channels/new/", views.team_channel_create, name="team_channel_create"),
    path("list/", views.inbox_list, name="inbox_list"),
    path("notifications/", views.notification_center, name="notification_center"),
    path("notifications/mark-read/", views.notification_mark_read, name="notification_mark_read"),
    path("conversation/<int:pk>/", views.conversation_detail, name="conversation_detail"),
    path("conversation/<int:pk>/panel/", views.conversation_panel, name="conversation_panel"),
    path("conversation/<int:pk>/membership/", views.conversation_membership_update, name="conversation_membership_update"),
    path("conversation/<int:pk>/post/", views.conversation_post, name="conversation_post"),
    path("deal/<int:deal_id>/follow/", views.deal_follow, name="deal_follow"),
    path("deal/<int:deal_id>/post/", views.deal_post, name="deal_post"),
    path("deal/<int:deal_id>/panel/", views.deal_panel, name="deal_panel"),
    path("entity/<int:entity_id>/follow/", views.entity_follow, name="entity_follow"),
    path("entity/<int:entity_id>/post/", views.entity_post, name="entity_post"),
    path("entity/<int:entity_id>/panel/", views.entity_panel, name="entity_panel"),
]
