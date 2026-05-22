# Generated manually for tenant-local collaboration.

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("binncrm", "0005_object_engine"),
    ]

    operations = [
        migrations.CreateModel(
            name="Conversation",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("title", models.CharField(max_length=160)),
                ("description", models.TextField(blank=True)),
                ("kind", models.CharField(choices=[("team", "Equipo"), ("entity", "Ficha"), ("deal", "Deal")], default="team", max_length=20)),
                ("last_message_at", models.DateTimeField(blank=True, null=True)),
                ("is_active", models.BooleanField(default=True)),
                ("created_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="%(class)s_created", to=settings.AUTH_USER_MODEL)),
                ("deal", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name="conversations", to="binncrm.deal")),
                ("entity", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name="conversations", to="binncrm.entity")),
                ("updated_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="%(class)s_updated", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ["-last_message_at", "-updated_at", "-id"]},
        ),
        migrations.CreateModel(
            name="Message",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("body", models.TextField()),
                ("metadata", models.JSONField(blank=True, default=dict)),
                ("is_system", models.BooleanField(default=False)),
                ("edited_at", models.DateTimeField(blank=True, null=True)),
                ("deleted_at", models.DateTimeField(blank=True, null=True)),
                ("author", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="conversation_messages", to=settings.AUTH_USER_MODEL)),
                ("conversation", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="messages", to="collab.conversation")),
                ("created_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="%(class)s_created", to=settings.AUTH_USER_MODEL)),
                ("updated_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="%(class)s_updated", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ["created_at", "id"]},
        ),
        migrations.CreateModel(
            name="Notification",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("title", models.CharField(max_length=160)),
                ("body", models.TextField(blank=True)),
                ("level", models.CharField(choices=[("info", "Info"), ("attention", "Atencion")], default="info", max_length=20)),
                ("is_read", models.BooleanField(default=False)),
                ("read_at", models.DateTimeField(blank=True, null=True)),
                ("conversation", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="notifications", to="collab.conversation")),
                ("created_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="%(class)s_created", to=settings.AUTH_USER_MODEL)),
                ("message", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="notifications", to="collab.message")),
                ("updated_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="%(class)s_updated", to=settings.AUTH_USER_MODEL)),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="collab_notifications", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ["is_read", "-created_at", "-id"], "unique_together": {("user", "message")}},
        ),
        migrations.CreateModel(
            name="ConversationMembership",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("role", models.CharField(choices=[("manager", "Manager"), ("member", "Miembro"), ("observer", "Observador")], default="member", max_length=20)),
                ("last_read_at", models.DateTimeField(blank=True, null=True)),
                ("is_muted", models.BooleanField(default=False)),
                ("is_active", models.BooleanField(default=True)),
                ("conversation", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="memberships", to="collab.conversation")),
                ("created_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="%(class)s_created", to=settings.AUTH_USER_MODEL)),
                ("updated_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="%(class)s_updated", to=settings.AUTH_USER_MODEL)),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="conversation_memberships", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ["conversation__title", "user__username"], "unique_together": {("conversation", "user")}},
        ),
        migrations.AddConstraint(
            model_name="conversation",
            constraint=models.UniqueConstraint(condition=models.Q(("entity__isnull", False)), fields=("kind", "entity"), name="collab_unique_entity_conversation"),
        ),
        migrations.AddConstraint(
            model_name="conversation",
            constraint=models.UniqueConstraint(condition=models.Q(("deal__isnull", False)), fields=("kind", "deal"), name="collab_unique_deal_conversation"),
        ),
    ]
