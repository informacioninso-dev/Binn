from django import forms
from django.contrib.auth import get_user_model

from access.runtime import get_tenant_user_queryset

from .models import Message


INPUT = {"class": "binn-input"}
TEXTAREA = {"class": "binn-input", "rows": 3}


class MessageForm(forms.Form):
    message_kind = forms.ChoiceField(
        label="Tipo",
        choices=Message.KIND_CHOICES,
        initial=Message.KIND_UPDATE,
        widget=forms.Select(attrs=INPUT),
    )
    body = forms.CharField(
        label="Mensaje",
        widget=forms.Textarea(
            attrs={
                **TEXTAREA,
                "placeholder": "Escribe una actualizacion clara para el equipo",
            }
        ),
    )
    assignee = forms.ModelChoiceField(
        label="Responsable",
        required=False,
        queryset=get_user_model()._default_manager.none(),
        empty_label="Sin responsable",
        widget=forms.Select(attrs=INPUT),
    )
    due_at = forms.DateTimeField(
        label="Vence",
        required=False,
        widget=forms.DateTimeInput(attrs={**INPUT, "type": "datetime-local"}, format="%Y-%m-%dT%H:%M"),
    )
    create_task = forms.BooleanField(
        label="Crear tarea",
        required=False,
        widget=forms.CheckboxInput(attrs={"class": "h-4 w-4 rounded border-gray-300"}),
    )

    def __init__(
        self,
        *args,
        tenant=None,
        current_user=None,
        task_context_enabled: bool = False,
        allow_task_linking: bool = False,
        **kwargs,
    ):
        self.tenant = tenant
        self.current_user = current_user
        self.task_context_enabled = bool(task_context_enabled)
        self.allow_task_linking = bool(allow_task_linking)
        super().__init__(*args, **kwargs)
        if tenant is not None:
            self.fields["assignee"].queryset = get_tenant_user_queryset(tenant)
        self.fields["due_at"].input_formats = ["%Y-%m-%dT%H:%M"]
        if not self.task_context_enabled or not self.allow_task_linking:
            self.fields["create_task"].disabled = True

    def clean(self):
        cleaned = super().clean()
        create_task = bool(cleaned.get("create_task"))

        if create_task and not self.task_context_enabled:
            self.add_error(None, "Solo puedes crear tareas desde un canal de ficha o deal.")

        if create_task and not self.allow_task_linking:
            self.add_error(None, "Tu rol actual no puede crear tareas desde colaboracion.")

        if create_task and not cleaned.get("due_at"):
            self.add_error("due_at", "La tarea necesita fecha y hora de vencimiento.")

        return cleaned
