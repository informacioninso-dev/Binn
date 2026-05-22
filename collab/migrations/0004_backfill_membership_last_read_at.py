"""
Backfill ConversationMembership.last_read_at for existing rows where it is NULL.

Strategy: set it to the conversation's last_message_at (if any), or the
membership's created_at.  This prevents members who never explicitly opened a
conversation from seeing every historical message as "unread" after we removed
the auto-mark-as-read on page render.
"""
from django.db import migrations


def backfill_last_read_at(apps, schema_editor):
    ConversationMembership = apps.get_model("collab", "ConversationMembership")
    memberships = (
        ConversationMembership.objects
        .filter(last_read_at__isnull=True, is_active=True)
        .select_related("conversation")
    )
    to_update = []
    for membership in memberships:
        conv = membership.conversation
        membership.last_read_at = conv.last_message_at or membership.created_at or conv.created_at
        to_update.append(membership)
    if to_update:
        ConversationMembership.objects.bulk_update(to_update, ["last_read_at"])


class Migration(migrations.Migration):

    dependencies = [
        ("collab", "0003_conversationmembership_is_archived_and_more"),
    ]

    operations = [
        migrations.RunPython(backfill_last_read_at, migrations.RunPython.noop),
    ]
