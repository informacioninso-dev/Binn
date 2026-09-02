"""Services-only handoff from an accepted proposal into delivery."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from collab.services import ensure_project_conversation

from .models import Activity, CollectionRecord, Document, ObjectRecord, ObjectSchema, Proposal
from .object_engine import get_object_schema_definition
from .timeline import (
    log_activity_created,
    log_collection_created,
    log_document_created,
    log_object_record_created,
)


class ProjectActivationError(ValueError):
    pass


@dataclass(frozen=True)
class ProjectActivationResult:
    project: ObjectRecord
    conversation_id: int | None
    created: bool


def _services_profile(tenant) -> bool:
    return getattr(getattr(tenant, "tenant_config", None), "profile", "") == "servicios"


def _project_schema() -> ObjectSchema:
    schema = get_object_schema_definition(object_key="proyecto")
    if schema is None or schema.source != ObjectSchema.SOURCE_CUSTOM or not schema.is_active:
        raise ProjectActivationError("El objeto Proyectos no esta configurado para este espacio de Servicios.")
    return schema


def _ensure_delivery_tasks(*, proposal: Proposal, project: ObjectRecord, actor) -> None:
    due_at = timezone.now() + timedelta(days=2)
    task_specs = [
        ("Kickoff del proyecto", "Confirma alcance, responsables, fechas y siguiente paso con el cliente."),
        ("Definir entregables iniciales", "Crea los entregables iniciales y acuerda su calendario de validacion."),
    ]
    for index, (title, description) in enumerate(task_specs):
        activity, created = Activity.objects.get_or_create(
            entity=proposal.entity,
            deal=proposal.deal,
            activity_type=Activity.TYPE_TASK,
            title=f"{title} | {project.title}",
            defaults={
                "description": description,
                "assigned_to": actor,
                "due_at": due_at + timedelta(days=index * 3),
                "created_by": actor,
                "updated_by": actor,
            },
        )
        if created:
            log_activity_created(activity=activity, actor=actor, origin="proposal_activation")


def _ensure_initial_collection(*, proposal: Proposal, project: ObjectRecord, actor) -> None:
    reference = f"PROP-{proposal.pk}-INICIAL"
    collection, created = CollectionRecord.objects.get_or_create(
        entity=proposal.entity,
        deal=proposal.deal,
        reference=reference,
        defaults={
            "title": f"Cobro inicial | {project.title}",
            "amount_due": proposal.amount,
            "currency": proposal.currency,
            "status": CollectionRecord.STATUS_PENDING,
            "due_on": proposal.deal.expected_close_on if proposal.deal_id else None,
            "notes": "Generado desde la propuesta aceptada. Ajusta monto, fecha y plan de cobro segun el acuerdo firmado.",
            "created_by": actor,
            "updated_by": actor,
        },
    )
    if created:
        log_collection_created(collection=collection, actor=actor, origin="proposal_activation")


def _ensure_project_file_anchor(*, tenant, proposal: Proposal, project: ObjectRecord, actor) -> None:
    title = f"Expediente | {project.title}"
    document, created = Document.objects.get_or_create(
        entity=proposal.entity,
        deal=proposal.deal,
        title=title,
        defaults={
            "document_type": "kickoff",
            "storage_provider": Document.STORAGE_MANUAL,
            "metadata": {
                "project_id": project.pk,
                "project_title": project.title,
                "proposal_id": proposal.pk,
                "purpose": "expediente_proyecto",
            },
            "created_by": actor,
            "updated_by": actor,
        },
    )
    if created:
        log_document_created(
            document=document,
            profile="servicios",
            custom_blueprints=getattr(tenant, "document_blueprints", []),
            actor=actor,
            origin="proposal_activation",
        )


def _mark_deal_won(*, proposal: Proposal, actor) -> None:
    deal = proposal.deal
    if deal is None:
        return
    updates = []
    if deal.status != deal.STATUS_WON:
        deal.status = deal.STATUS_WON
        updates.append("status")
    won_stage = next((stage for stage in deal.pipeline.stage_choices if stage.casefold() in {"ganado", "ganada", "won"}), "")
    if won_stage and deal.stage != won_stage:
        deal.stage = won_stage
        updates.append("stage")
    if updates:
        deal.updated_by = actor
        deal.save(update_fields=[*updates, "updated_by", "updated_at"])


@transaction.atomic
def activate_services_project(*, tenant, proposal: Proposal, actor) -> ProjectActivationResult:
    """Create the delivery workspace once for an accepted Services proposal."""
    if not _services_profile(tenant):
        raise ProjectActivationError("La conversion a proyecto solo esta disponible para Servicios.")
    if proposal.status != Proposal.STATUS_ACCEPTED:
        raise ProjectActivationError("Acepta la propuesta antes de convertirla en proyecto.")

    project_schema = _project_schema()
    project = (
        ObjectRecord.objects.select_for_update()
        .filter(object_schema=project_schema, proposal=proposal, is_active=True)
        .first()
    )
    created = project is None
    if project is None:
        entity_data = proposal.entity.data_extra or {}
        project = ObjectRecord.objects.create(
            object_schema=project_schema,
            entity=proposal.entity,
            deal=proposal.deal,
            proposal=proposal,
            assessment_submission=proposal.source_assessment,
            title=proposal.title,
            data={
                "nombre": proposal.title,
                "cliente": entity_data.get("empresa") or proposal.entity.full_name,
                "linea_servicio": entity_data.get("service_line") or entity_data.get("servicio_principal") or "",
                "estado": "kickoff",
                "responsable": entity_data.get("delivery_owner") or getattr(actor, "username", ""),
                "fecha_inicio": str(timezone.localdate()),
                "fecha_cierre_objetivo": "",
                "prioridad": "media",
            },
            created_by=actor,
            updated_by=actor,
        )
        log_object_record_created(record=project, actor=actor, origin="proposal_activation")

    _mark_deal_won(proposal=proposal, actor=actor)
    _ensure_delivery_tasks(proposal=proposal, project=project, actor=actor)
    _ensure_initial_collection(proposal=proposal, project=project, actor=actor)
    _ensure_project_file_anchor(tenant=tenant, proposal=proposal, project=project, actor=actor)

    conversation_id = None
    if getattr(tenant, "has_capability", lambda _name: False)("collab"):
        conversation = ensure_project_conversation(tenant=tenant, project=project, actor=actor)
        conversation_id = conversation.pk
    return ProjectActivationResult(project=project, conversation_id=conversation_id, created=created)
