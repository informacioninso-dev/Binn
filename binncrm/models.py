import re
import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from core.models import AuditModel


class Pipeline(AuditModel):
    name = models.CharField(max_length=120)
    key = models.SlugField(max_length=60, unique=True)
    stages = models.JSONField(default=list, blank=True)
    position = models.PositiveIntegerField(default=0)
    is_default = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["position", "name"]

    def __str__(self):
        return self.name

    @property
    def stage_choices(self) -> list[str]:
        return list(self.stages or [])


class ObjectSchema(AuditModel):
    SOURCE_SYSTEM = "system"
    SOURCE_CUSTOM = "custom"
    SOURCE_CHOICES = [
        (SOURCE_SYSTEM, "Sistema"),
        (SOURCE_CUSTOM, "Custom"),
    ]

    key = models.SlugField(max_length=60, unique=True)
    label = models.CharField(max_length=120)
    description = models.TextField(blank=True)
    source = models.CharField(max_length=20, choices=SOURCE_CHOICES, default=SOURCE_SYSTEM)
    settings = models.JSONField(default=dict, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["label", "id"]

    def __str__(self):
        return self.label


class ObjectField(AuditModel):
    TYPE_TEXT = "text"
    TYPE_TEXTAREA = "textarea"
    TYPE_NUMBER = "number"
    TYPE_EMAIL = "email"
    TYPE_DATE = "date"
    TYPE_BOOLEAN = "boolean"
    TYPE_CHOICES = [
        (TYPE_TEXT, "Texto"),
        (TYPE_TEXTAREA, "Texto largo"),
        (TYPE_NUMBER, "Numero"),
        (TYPE_EMAIL, "Correo"),
        (TYPE_DATE, "Fecha"),
        (TYPE_BOOLEAN, "Booleano"),
    ]

    object_schema = models.ForeignKey(ObjectSchema, on_delete=models.CASCADE, related_name="fields")
    key = models.SlugField(max_length=60)
    label = models.CharField(max_length=120)
    field_type = models.CharField(max_length=20, choices=TYPE_CHOICES, default=TYPE_TEXT)
    position = models.PositiveIntegerField(default=0)
    required = models.BooleanField(default=False)
    config = models.JSONField(default=dict, blank=True)
    is_system = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["object_schema__label", "position", "label", "id"]
        unique_together = ("object_schema", "key")

    def __str__(self):
        return f"{self.object_schema.label}::{self.label}"


class ObjectView(AuditModel):
    VIEW_TABLE = "table"
    VIEW_KANBAN = "kanban"
    VIEW_LIST = "list"
    VIEW_CHOICES = [
        (VIEW_TABLE, "Tabla"),
        (VIEW_KANBAN, "Kanban"),
        (VIEW_LIST, "Lista"),
    ]

    object_schema = models.ForeignKey(ObjectSchema, on_delete=models.CASCADE, related_name="views")
    key = models.SlugField(max_length=60)
    label = models.CharField(max_length=120)
    description = models.TextField(blank=True)
    view_type = models.CharField(max_length=20, choices=VIEW_CHOICES, default=VIEW_TABLE)
    position = models.PositiveIntegerField(default=0)
    config = models.JSONField(default=dict, blank=True)
    is_default = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["object_schema__label", "position", "label", "id"]
        unique_together = ("object_schema", "key")

    def __str__(self):
        return f"{self.object_schema.label}::{self.label}"


class ObjectRecord(AuditModel):
    object_schema = models.ForeignKey(ObjectSchema, on_delete=models.CASCADE, related_name="records")
    title = models.CharField(max_length=180, blank=True)
    data = models.JSONField(default=dict, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["object_schema__label", "-updated_at", "-id"]

    def __str__(self):
        return self.title or f"{self.object_schema.label} #{self.pk}"


class TimelineEvent(models.Model):
    CATEGORY_ENTITY = "entity"
    CATEGORY_DEAL = "deal"
    CATEGORY_PROPOSAL = "proposal"
    CATEGORY_COLLECTION = "collection"
    CATEGORY_ACTIVITY = "activity"
    CATEGORY_DOCUMENT = "document"
    CATEGORY_OBJECT_RECORD = "object_record"
    CATEGORY_CHOICES = [
        (CATEGORY_ENTITY, "Ficha"),
        (CATEGORY_DEAL, "Deal"),
        (CATEGORY_PROPOSAL, "Propuesta"),
        (CATEGORY_COLLECTION, "Cobranza"),
        (CATEGORY_ACTIVITY, "Actividad"),
        (CATEGORY_DOCUMENT, "Documento"),
        (CATEGORY_OBJECT_RECORD, "Objeto custom"),
    ]

    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        related_name="timeline_events",
        on_delete=models.SET_NULL,
    )
    entity = models.ForeignKey("Entity", null=True, blank=True, related_name="timeline_events", on_delete=models.CASCADE)
    deal = models.ForeignKey("Deal", null=True, blank=True, related_name="timeline_events", on_delete=models.CASCADE)
    proposal = models.ForeignKey("Proposal", null=True, blank=True, related_name="timeline_events", on_delete=models.CASCADE)
    collection = models.ForeignKey(
        "CollectionRecord",
        null=True,
        blank=True,
        related_name="timeline_events",
        on_delete=models.CASCADE,
    )
    activity = models.ForeignKey("Activity", null=True, blank=True, related_name="timeline_events", on_delete=models.CASCADE)
    document = models.ForeignKey("Document", null=True, blank=True, related_name="timeline_events", on_delete=models.CASCADE)
    object_record = models.ForeignKey(
        "ObjectRecord",
        null=True,
        blank=True,
        related_name="timeline_events",
        on_delete=models.CASCADE,
    )
    category = models.CharField(max_length=30, choices=CATEGORY_CHOICES, db_index=True)
    event_key = models.SlugField(max_length=80)
    kind_label = models.CharField(max_length=80)
    title = models.CharField(max_length=180)
    meta = models.CharField(max_length=180, blank=True)
    description = models.TextField(blank=True)
    accent = models.CharField(max_length=60, blank=True)
    payload = models.JSONField(default=dict, blank=True)
    occurred_at = models.DateTimeField(default=timezone.now, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-occurred_at", "-id"]

    def __str__(self):
        return f"{self.kind_label}: {self.title}"


class SavedWorkspaceFilter(AuditModel):
    OBJECT_ENTITY = "entity"
    OBJECT_DEAL = "deal"
    OBJECT_CHOICES = [
        (OBJECT_ENTITY, "Contactos"),
        (OBJECT_DEAL, "Deals"),
    ]

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="binn_saved_workspace_filters",
        on_delete=models.CASCADE,
    )
    object_type = models.CharField(max_length=20, choices=OBJECT_CHOICES)
    label = models.CharField(max_length=80)
    params = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["object_type", "label", "id"]
        unique_together = ("owner", "object_type", "label")

    def __str__(self):
        return f"{self.get_object_type_display()}: {self.label}"


class Entity(AuditModel):
    full_name = models.CharField("Nombre", max_length=180)
    legal_id = models.CharField("RUC/Cedula", max_length=20, blank=True)
    phone = models.CharField("Telefono", max_length=30, blank=True)
    email = models.EmailField("Correo", blank=True)
    data_extra = models.JSONField(default=dict, blank=True)
    notes = models.TextField("Notas", blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["full_name"]

    def __str__(self):
        return self.full_name

    @property
    def whatsapp_url(self) -> str:
        phone = re.sub(r"\D", "", self.phone or "")
        return f"https://wa.me/{phone}" if phone else ""


class Deal(AuditModel):
    STATUS_OPEN = "open"
    STATUS_WON = "won"
    STATUS_LOST = "lost"
    STATUS_CHOICES = [
        (STATUS_OPEN, "Abierto"),
        (STATUS_WON, "Ganado"),
        (STATUS_LOST, "Perdido"),
    ]

    entity = models.ForeignKey(Entity, on_delete=models.CASCADE, related_name="deals")
    pipeline = models.ForeignKey(Pipeline, on_delete=models.PROTECT, related_name="deals")
    title = models.CharField(max_length=160)
    amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    currency = models.CharField(max_length=8, default="USD")
    stage = models.CharField(max_length=120)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_OPEN)
    expected_close_on = models.DateField(null=True, blank=True)
    notes = models.TextField(blank=True)
    sort_order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["pipeline__position", "sort_order", "-updated_at"]
        indexes = [
            models.Index(fields=["is_active", "status", "pipeline", "stage"], name="binn_deal_flow_idx"),
            models.Index(fields=["pipeline", "stage", "sort_order"], name="binn_deal_stage_sort_idx"),
            models.Index(fields=["expected_close_on"], name="binn_deal_close_idx"),
        ]

    def __str__(self):
        return self.title

    def clean(self):
        if self.pipeline_id and self.stage and self.stage not in self.pipeline.stage_choices:
            raise ValidationError({"stage": "La etapa no existe dentro del pipeline seleccionado."})


class AssessmentTemplate(AuditModel):
    """Tenant-local blueprint for an operational diagnostic or questionnaire."""

    name = models.CharField(max_length=140)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    is_default = models.BooleanField(default=False)

    class Meta:
        ordering = ["name", "id"]

    def __str__(self):
        return self.name


class AssessmentSection(AuditModel):
    template = models.ForeignKey(AssessmentTemplate, on_delete=models.CASCADE, related_name="sections")
    title = models.CharField(max_length=160)
    description = models.TextField(blank=True)
    position = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["template__name", "position", "id"]

    def __str__(self):
        return f"{self.template.name}: {self.title}"


class AssessmentQuestion(AuditModel):
    TYPE_TEXT = "text"
    TYPE_TEXTAREA = "textarea"
    TYPE_SINGLE_CHOICE = "single_choice"
    TYPE_MULTIPLE_CHOICE = "multiple_choice"
    TYPE_BOOLEAN = "boolean"
    TYPE_NUMBER = "number"
    TYPE_RATING = "rating"
    TYPE_CHOICES = [
        (TYPE_TEXT, "Texto corto"),
        (TYPE_TEXTAREA, "Texto largo"),
        (TYPE_SINGLE_CHOICE, "Una opcion"),
        (TYPE_MULTIPLE_CHOICE, "Varias opciones"),
        (TYPE_BOOLEAN, "Si / No"),
        (TYPE_NUMBER, "Numero"),
        (TYPE_RATING, "Escala"),
    ]

    section = models.ForeignKey(AssessmentSection, on_delete=models.CASCADE, related_name="questions")
    key = models.SlugField(max_length=60)
    label = models.CharField(max_length=240)
    help_text = models.TextField(blank=True)
    question_type = models.CharField(max_length=24, choices=TYPE_CHOICES, default=TYPE_TEXT)
    required = models.BooleanField(default=False)
    choices = models.JSONField(default=list, blank=True)
    config = models.JSONField(default=dict, blank=True)
    position = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["section__template__name", "section__position", "position", "id"]
        unique_together = ("section", "key")

    def __str__(self):
        return self.label


class AssessmentSubmission(AuditModel):
    MODE_FIELD = "field"
    MODE_CLIENT = "client"
    MODE_CHOICES = [(MODE_FIELD, "Levantamiento interno"), (MODE_CLIENT, "Enlace para cliente")]
    STATUS_DRAFT = "draft"
    STATUS_SENT = "sent"
    STATUS_IN_PROGRESS = "in_progress"
    STATUS_COMPLETED = "completed"
    STATUS_CHOICES = [
        (STATUS_DRAFT, "Borrador"),
        (STATUS_SENT, "Enviado"),
        (STATUS_IN_PROGRESS, "En progreso"),
        (STATUS_COMPLETED, "Completado"),
    ]

    template = models.ForeignKey(AssessmentTemplate, on_delete=models.PROTECT, related_name="submissions")
    entity = models.ForeignKey(Entity, on_delete=models.CASCADE, related_name="assessment_submissions")
    deal = models.ForeignKey(Deal, null=True, blank=True, on_delete=models.SET_NULL, related_name="assessment_submissions")
    capture_mode = models.CharField(max_length=20, choices=MODE_CHOICES, default=MODE_FIELD)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_DRAFT, db_index=True)
    public_token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False, db_index=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    submitted_by_name = models.CharField(max_length=160, blank=True)
    score = models.DecimalField(max_digits=7, decimal_places=2, null=True, blank=True)
    snapshot = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-updated_at", "-id"]
        indexes = [
            models.Index(fields=["entity", "status"], name="binn_assessment_entity_idx"),
            models.Index(fields=["deal", "status"], name="binn_assessment_deal_idx"),
        ]

    def __str__(self):
        return f"{self.template.name} · {self.entity.full_name}"

    @property
    def is_expired(self):
        return bool(self.expires_at and self.expires_at <= timezone.now())


class AssessmentAnswer(AuditModel):
    submission = models.ForeignKey(AssessmentSubmission, on_delete=models.CASCADE, related_name="answers")
    question_key = models.SlugField(max_length=60)
    question_label = models.CharField(max_length=240)
    value = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["id"]
        unique_together = ("submission", "question_key")

    def __str__(self):
        return f"{self.submission} · {self.question_label}"


class Activity(AuditModel):
    TYPE_CALL = "call"
    TYPE_MEETING = "meeting"
    TYPE_WHATSAPP = "whatsapp"
    TYPE_NOTE = "note"
    TYPE_EMAIL = "email"
    TYPE_TASK = "task"
    TYPE_CLAIM = "claim"
    TYPE_CHOICES = [
        (TYPE_CALL, "Llamada"),
        (TYPE_MEETING, "Reunion"),
        (TYPE_WHATSAPP, "WhatsApp"),
        (TYPE_NOTE, "Nota"),
        (TYPE_EMAIL, "Correo"),
        (TYPE_TASK, "Tarea"),
        (TYPE_CLAIM, "Siniestro"),
    ]

    entity = models.ForeignKey(Entity, on_delete=models.CASCADE, related_name="activities")
    deal = models.ForeignKey(Deal, on_delete=models.CASCADE, related_name="activities", null=True, blank=True)
    activity_type = models.CharField(max_length=20, choices=TYPE_CHOICES, default=TYPE_NOTE)
    title = models.CharField(max_length=160)
    description = models.TextField(blank=True)
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assigned_activities",
    )
    due_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["activity_type", "completed_at", "due_at"], name="binn_activity_due_idx"),
            models.Index(fields=["entity", "created_at"], name="binn_act_entity_idx"),
        ]

    def __str__(self):
        return self.title


class Document(AuditModel):
    STORAGE_S3 = "s3"
    STORAGE_EXTERNAL = "external"
    STORAGE_MANUAL = "manual"
    STORAGE_CHOICES = [
        (STORAGE_S3, "S3 / compatible"),
        (STORAGE_EXTERNAL, "URL externa"),
        (STORAGE_MANUAL, "Referencia manual"),
    ]

    title = models.CharField(max_length=180)
    document_type = models.CharField(max_length=80, default="general")
    entity = models.ForeignKey(Entity, on_delete=models.CASCADE, related_name="documents", null=True, blank=True)
    deal = models.ForeignKey(Deal, on_delete=models.CASCADE, related_name="documents", null=True, blank=True)
    storage_provider = models.CharField(max_length=20, choices=STORAGE_CHOICES, default=STORAGE_S3)
    bucket_name = models.CharField(max_length=160, blank=True)
    storage_key = models.CharField(max_length=255, blank=True)
    external_url = models.URLField(blank=True)
    content_type = models.CharField(max_length=120, blank=True)
    file_size = models.PositiveIntegerField(default=0)
    metadata = models.JSONField(default=dict, blank=True)
    expires_on = models.DateField(null=True, blank=True)
    is_verified = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.title


class Proposal(AuditModel):
    STATUS_DRAFT = "draft"
    STATUS_SENT = "sent"
    STATUS_ACCEPTED = "accepted"
    STATUS_REJECTED = "rejected"
    STATUS_EXPIRED = "expired"
    STATUS_CHOICES = [
        (STATUS_DRAFT, "Borrador"),
        (STATUS_SENT, "Enviada"),
        (STATUS_ACCEPTED, "Aceptada"),
        (STATUS_REJECTED, "Rechazada"),
        (STATUS_EXPIRED, "Expirada"),
    ]

    entity = models.ForeignKey(Entity, on_delete=models.CASCADE, related_name="proposals")
    deal = models.ForeignKey(Deal, on_delete=models.CASCADE, related_name="proposals", null=True, blank=True)
    title = models.CharField(max_length=180)
    proposal_number = models.CharField(max_length=50, blank=True)
    amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    currency = models.CharField(max_length=8, default="USD")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_DRAFT)
    valid_until = models.DateField(null=True, blank=True)
    summary = models.TextField(blank=True)
    terms = models.TextField(blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    responded_at = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["-updated_at", "-id"]
        indexes = [
            models.Index(fields=["is_active", "status", "valid_until"], name="binn_proposal_status_idx"),
        ]

    def __str__(self):
        return self.title

    def clean(self):
        if self.deal_id and self.entity_id and self.deal.entity_id != self.entity_id:
            raise ValidationError({"deal": "La propuesta debe pertenecer a la misma entidad del deal seleccionado."})


class CollectionRecord(AuditModel):
    STATUS_PENDING = "pending"
    STATUS_PROMISED = "promised"
    STATUS_PAID = "paid"
    STATUS_OVERDUE = "overdue"
    STATUS_DISPUTED = "disputed"
    STATUS_CHOICES = [
        (STATUS_PENDING, "Pendiente"),
        (STATUS_PROMISED, "Promesa de pago"),
        (STATUS_PAID, "Pagada"),
        (STATUS_OVERDUE, "Vencida"),
        (STATUS_DISPUTED, "En revision"),
    ]

    entity = models.ForeignKey(Entity, on_delete=models.CASCADE, related_name="collections")
    deal = models.ForeignKey(Deal, on_delete=models.CASCADE, related_name="collections", null=True, blank=True)
    title = models.CharField(max_length=180)
    reference = models.CharField(max_length=60, blank=True)
    amount_due = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    amount_paid = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    currency = models.CharField(max_length=8, default="USD")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING)
    due_on = models.DateField(null=True, blank=True)
    promised_for = models.DateField(null=True, blank=True)
    notes = models.TextField(blank=True)
    last_contacted_at = models.DateTimeField(null=True, blank=True)
    sort_order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["due_on", "-updated_at", "-id"]
        indexes = [
            models.Index(fields=["is_active", "status", "due_on"], name="binn_collection_due_idx"),
            models.Index(fields=["status", "sort_order", "due_on"], name="binn_collection_sort_idx"),
        ]

    def __str__(self):
        return self.title

    @property
    def balance(self):
        return max(self.amount_due - self.amount_paid, 0)

    @property
    def is_past_due(self) -> bool:
        return bool(self.due_on and self.status != self.STATUS_PAID and self.due_on < timezone.localdate())

    def clean(self):
        if self.deal_id and self.entity_id and self.deal.entity_id != self.entity_id:
            raise ValidationError({"deal": "La cobranza debe pertenecer a la misma entidad del deal seleccionado."})
