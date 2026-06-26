from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from django.utils import timezone
from django_tenants.utils import schema_context

from tenants.defaults import (
    PROFILE_BROKER,
    PROFILE_CONDOMINIO,
    PROFILE_GENERAL,
    PROFILE_MARKETING,
    PROFILE_RETAIL_MODA,
    PROFILE_SERVICIOS,
)
from tenants.services import sync_tenant_object_schemas, sync_tenant_pipelines

from .models import Activity, CollectionRecord, Deal, Document, Entity, ObjectRecord, ObjectSchema, Pipeline, Proposal, TimelineEvent
from .object_engine import resolve_object_record_title
from .timeline import (
    log_activity_created,
    log_collection_created,
    log_deal_created,
    log_document_created,
    log_entity_created,
    log_object_record_created,
    log_proposal_created,
)


def seed_tenant_demo(tenant, *, actor=None) -> dict:
    notices = sync_tenant_pipelines(tenant)
    notices.extend(sync_tenant_object_schemas(tenant))
    scenario = build_demo_scenario(tenant)
    summary = {
        "tenant": tenant.schema_name,
        "profile": tenant.tenant_config.profile,
        "pipeline": "",
        "notices": notices,
        "counts": {
            "entities": {"created": 0, "updated": 0, "total": 0},
            "deals": {"created": 0, "updated": 0, "total": 0},
            "activities": {"created": 0, "updated": 0, "total": 0},
            "proposals": {"created": 0, "updated": 0, "total": 0},
            "collections": {"created": 0, "updated": 0, "total": 0},
            "documents": {"created": 0, "updated": 0, "total": 0},
            "object_records": {"created": 0, "updated": 0, "total": 0},
        },
    }

    with schema_context(tenant.schema_name):
        TimelineEvent.objects.filter(payload__origin="demo_seed").delete()
        pipeline = Pipeline.objects.filter(is_default=True, is_active=True).order_by("position", "name").first()
        if pipeline is None:
            pipeline = Pipeline.objects.filter(is_active=True).order_by("position", "name").first()
        if pipeline is None:
            raise ValueError(f"El tenant '{tenant.schema_name}' no tiene pipelines configurados.")

        summary["pipeline"] = pipeline.name
        stages = list(pipeline.stage_choices or [])
        entity_map: dict[str, Entity] = {}
        deal_map: dict[str, Deal] = {}

        for payload in scenario["entities"]:
            entity_defaults = {
                "full_name": payload["full_name"],
                "legal_id": payload["legal_id"],
                "phone": payload["phone"],
                "email": payload["email"],
                "data_extra": payload["extra"],
                "notes": payload["notes"],
                "is_active": True,
                "updated_by": actor,
            }
            if actor:
                entity_defaults["created_by"] = actor
            entity, created = Entity.objects.update_or_create(
                email=payload["email"],
                defaults=entity_defaults,
            )
            entity_map[payload["key"]] = entity
            _tally(summary["counts"]["entities"], created)

        if tenant.has_capability("deals"):
            stage_counts: dict[str, int] = {}
            for payload in scenario["deals"]:
                stage = _resolve_stage(stages, payload["stage_index"])
                sort_order = stage_counts.get(stage, 0)
                stage_counts[stage] = sort_order + 1
                deal_defaults = {
                    "entity": entity_map[payload["entity_key"]],
                    "pipeline": pipeline,
                    "amount": payload["amount"],
                    "currency": "USD",
                    "stage": stage,
                    "status": payload["status"],
                    "expected_close_on": timezone.localdate() + timedelta(days=payload["expected_close_in_days"]),
                    "notes": payload["notes"],
                    "sort_order": sort_order,
                    "is_active": True,
                    "updated_by": actor,
                }
                if actor:
                    deal_defaults["created_by"] = actor
                deal, created = Deal.objects.update_or_create(
                    entity=entity_map[payload["entity_key"]],
                    title=payload["title"],
                    pipeline=pipeline,
                    defaults=deal_defaults,
                )
                deal_map[payload["key"]] = deal
                _tally(summary["counts"]["deals"], created)

        now = timezone.now()

        if tenant.has_capability("activities"):
            for payload in scenario["activities"]:
                deal = deal_map.get(payload.get("deal_key")) if payload.get("deal_key") else None
                completed_at = now - timedelta(hours=payload["completed_hours_ago"]) if payload.get("completed_hours_ago") else None
                due_at = now + timedelta(hours=payload["due_in_hours"]) if payload.get("due_in_hours") is not None else None
                activity_defaults = {
                    "deal": deal,
                    "description": payload["description"],
                    "assigned_to": actor if payload.get("assign_actor") else None,
                    "due_at": due_at,
                    "completed_at": completed_at,
                    "updated_by": actor,
                }
                if actor:
                    activity_defaults["created_by"] = actor
                activity, created = Activity.objects.update_or_create(
                    entity=entity_map[payload["entity_key"]],
                    activity_type=payload["activity_type"],
                    title=payload["title"],
                    defaults=activity_defaults,
                )
                _tally(summary["counts"]["activities"], created)
                if payload.get("age_days") is not None:
                    Activity.objects.filter(pk=activity.pk).update(
                        created_at=now - timedelta(days=payload["age_days"]),
                        updated_at=now - timedelta(days=payload["age_days"]),
                    )

        if tenant.has_capability("proposals"):
            for payload in scenario["proposals"]:
                sent_at = now - timedelta(days=payload["sent_days_ago"]) if payload.get("sent_days_ago") is not None else None
                responded_at = (
                    now - timedelta(days=payload["responded_days_ago"])
                    if payload.get("responded_days_ago") is not None
                    else None
                )
                proposal_defaults = {
                    "entity": entity_map[payload["entity_key"]],
                    "deal": deal_map.get(payload.get("deal_key")),
                    "title": payload["title"],
                    "amount": payload["amount"],
                    "currency": "USD",
                    "status": payload["status"],
                    "valid_until": timezone.localdate() + timedelta(days=payload["valid_in_days"]),
                    "summary": payload["summary"],
                    "terms": payload["terms"],
                    "sent_at": sent_at,
                    "responded_at": responded_at,
                    "is_active": True,
                    "updated_by": actor,
                }
                if actor:
                    proposal_defaults["created_by"] = actor
                proposal, created = Proposal.objects.update_or_create(
                    proposal_number=payload["proposal_number"],
                    defaults=proposal_defaults,
                )
                _tally(summary["counts"]["proposals"], created)

        if tenant.has_capability("collections"):
            for payload in scenario["collections"]:
                collection_defaults = {
                    "entity": entity_map[payload["entity_key"]],
                    "deal": deal_map.get(payload.get("deal_key")),
                    "title": payload["title"],
                    "amount_due": payload["amount_due"],
                    "amount_paid": payload["amount_paid"],
                    "currency": "USD",
                    "status": payload["status"],
                    "due_on": timezone.localdate() + timedelta(days=payload["due_in_days"]),
                    "promised_for": (
                        timezone.localdate() + timedelta(days=payload["promised_in_days"])
                        if payload.get("promised_in_days") is not None
                        else None
                    ),
                    "notes": payload["notes"],
                    "last_contacted_at": (
                        now - timedelta(days=payload["last_contact_days_ago"])
                        if payload.get("last_contact_days_ago") is not None
                        else None
                    ),
                    "is_active": True,
                    "updated_by": actor,
                }
                if actor:
                    collection_defaults["created_by"] = actor
                collection, created = CollectionRecord.objects.update_or_create(
                    reference=payload["reference"],
                    defaults=collection_defaults,
                )
                _tally(summary["counts"]["collections"], created)

        if tenant.has_capability("documents"):
            for payload in scenario["documents"]:
                document_defaults = {
                    "title": payload["title"],
                    "document_type": payload["document_type"],
                    "entity": entity_map[payload["entity_key"]],
                    "deal": deal_map.get(payload.get("deal_key")),
                    "storage_provider": Document.STORAGE_EXTERNAL,
                    "external_url": payload["external_url"],
                    "content_type": payload.get("content_type", "application/pdf"),
                    "file_size": payload.get("file_size", 0),
                    "metadata": payload.get("metadata", {}),
                    "expires_on": (
                        timezone.localdate() + timedelta(days=payload["expires_in_days"])
                        if payload.get("expires_in_days") is not None
                        else None
                    ),
                    "is_verified": payload.get("is_verified", False),
                    "is_active": True,
                    "updated_by": actor,
                }
                if actor:
                    document_defaults["created_by"] = actor
                document, created = Document.objects.update_or_create(
                    external_url=payload["external_url"],
                    defaults=document_defaults,
                )
                _tally(summary["counts"]["documents"], created)

        for payload in scenario.get("object_records", []):
            object_schema = ObjectSchema.objects.filter(key=payload["object_key"], is_active=True).first()
            if object_schema is None:
                notices.append(
                    f"No se pudo sembrar el objeto custom '{payload['object_key']}' porque no existe su schema activo."
                )
                continue
            title = resolve_object_record_title(object_schema=object_schema, data=payload["data"])
            record_defaults = {
                "data": payload["data"],
                "title": title,
                "is_active": True,
                "updated_by": actor,
            }
            if actor:
                record_defaults["created_by"] = actor
            record, created = ObjectRecord.objects.update_or_create(
                object_schema=object_schema,
                title=title,
                defaults=record_defaults,
            )
            _tally(summary["counts"]["object_records"], created)
            if payload.get("age_days") is not None:
                ObjectRecord.objects.filter(pk=record.pk).update(
                    created_at=now - timedelta(days=payload["age_days"]),
                    updated_at=now - timedelta(days=payload["age_days"]),
                )

        if scenario.get("stale_deal_key") and scenario["stale_deal_key"] in deal_map:
            Deal.objects.filter(pk=deal_map[scenario["stale_deal_key"]].pk).update(
                updated_at=now - timedelta(days=18)
            )

        if scenario.get("cold_entity_key") and scenario["cold_entity_key"] in entity_map:
            Entity.objects.filter(pk=entity_map[scenario["cold_entity_key"]].pk).update(
                updated_at=now - timedelta(days=30)
            )

        summary["counts"]["entities"]["total"] = Entity.objects.filter(is_active=True).count()
        summary["counts"]["deals"]["total"] = Deal.objects.filter(is_active=True).count()
        summary["counts"]["activities"]["total"] = Activity.objects.count()
        summary["counts"]["proposals"]["total"] = Proposal.objects.filter(is_active=True).count()
        summary["counts"]["collections"]["total"] = CollectionRecord.objects.filter(is_active=True).count()
        summary["counts"]["documents"]["total"] = Document.objects.filter(is_active=True).count()
        summary["counts"]["object_records"]["total"] = ObjectRecord.objects.filter(is_active=True).count()

        profile = tenant.tenant_config.profile
        custom_blueprints = tenant.document_blueprints
        for entity in entity_map.values():
            log_entity_created(
                entity=entity,
                actor=actor,
                kind_label=tenant.get_label("entity_singular", "Contacto"),
                origin="demo_seed",
                occurred_at=entity.updated_at,
            )
        for deal in deal_map.values():
            log_deal_created(
                deal=deal,
                actor=actor,
                kind_label=tenant.get_label("deal_singular", "Deal"),
                origin="demo_seed",
                occurred_at=deal.updated_at,
            )
        if tenant.has_capability("activities"):
            for activity in Activity.objects.filter(entity__in=entity_map.values()).select_related("deal", "assigned_to"):
                log_activity_created(
                    activity=activity,
                    actor=actor,
                    origin="demo_seed",
                    occurred_at=activity.completed_at or activity.created_at,
                )
        if tenant.has_capability("proposals"):
            for proposal in Proposal.objects.filter(entity__in=entity_map.values()).select_related("deal"):
                log_proposal_created(
                    proposal=proposal,
                    actor=actor,
                    kind_label=tenant.get_label("proposal_singular", "Propuesta"),
                    origin="demo_seed",
                    occurred_at=proposal.responded_at or proposal.sent_at or proposal.created_at,
                )
        if tenant.has_capability("collections"):
            for collection in CollectionRecord.objects.filter(entity__in=entity_map.values()).select_related("deal"):
                log_collection_created(
                    collection=collection,
                    actor=actor,
                    kind_label=tenant.get_label("collection_singular", "Cobranza"),
                    origin="demo_seed",
                    occurred_at=collection.last_contacted_at or collection.updated_at,
                )
        if tenant.has_capability("documents"):
            for document in Document.objects.filter(entity__in=entity_map.values()).select_related("deal"):
                log_document_created(
                    document=document,
                    profile=profile,
                    custom_blueprints=custom_blueprints,
                    actor=actor,
                    kind_label=tenant.get_label("document_singular", "Documento"),
                    origin="demo_seed",
                    occurred_at=document.created_at,
                )
        for record in ObjectRecord.objects.filter(is_active=True).select_related("object_schema"):
            log_object_record_created(
                record=record,
                actor=actor,
                origin="demo_seed",
                occurred_at=record.updated_at,
            )

    return summary


def build_demo_scenario(tenant) -> dict:
    profile = tenant.tenant_config.profile
    if profile == PROFILE_BROKER:
        scenario = _build_broker_demo(tenant)
    elif profile == PROFILE_CONDOMINIO:
        scenario = _build_condominio_demo(tenant)
    elif profile == PROFILE_RETAIL_MODA:
        scenario = _build_retail_demo(tenant)
    else:
        scenario = _build_commercial_demo(tenant, profile=profile)
    scenario.setdefault("object_records", _build_demo_object_records(profile=profile))
    return scenario


def _build_commercial_demo(tenant, *, profile: str) -> dict:
    entities = [
        _entity_payload(
            tenant,
            key="mariana-vega",
            full_name="Mariana Vega",
            legal_id="0912345601",
            phone="0992451180",
            email="mariana.vega@floresco.ec",
            notes="Busca ordenar el seguimiento comercial sin dejar de usar WhatsApp.",
            extra={
                "city": "Guayaquil",
                "reference": "Referida por Andrea Leon",
                "empresa": "Flores & Co",
                "instagram": "@floresco.ec",
                "campana": "Lanzamiento mayo",
                "servicio_principal": "Acompanamiento comercial",
                "cargo": "Fundadora",
                "retainer_mensual": 950,
                "service_stage": "cliente_activo" if profile == PROFILE_SERVICIOS else "",
                "renewal_on": str(timezone.localdate() + timedelta(days=42)) if profile == PROFILE_SERVICIOS else "",
                "delivery_owner": "Andrea Leon" if profile == PROFILE_SERVICIOS else "",
            },
        ),
        _entity_payload(
            tenant,
            key="carlos-montalvo",
            full_name="Carlos Montalvo",
            legal_id="1719982210",
            phone="0981104422",
            email="carlos.montalvo@distandina.ec",
            notes="Pide propuesta formal y tiempos de implementacion claros.",
            extra={
                "city": "Quito",
                "reference": "Demo enviada por LinkedIn",
                "empresa": "Distribuidora Andina",
                "instagram": "@distandina",
                "campana": "Inbound Q2",
                "servicio_principal": "Implementacion CRM",
                "cargo": "Gerente comercial",
                "retainer_mensual": 3200,
                "service_stage": "prospecto" if profile == PROFILE_SERVICIOS else "",
                "delivery_owner": "Mateo Ruiz" if profile == PROFILE_SERVICIOS else "",
            },
        ),
        _entity_payload(
            tenant,
            key="paola-cedeno",
            full_name="Paola Cedeno",
            legal_id="0927785403",
            phone="0990011144",
            email="paola@studiorio.ec",
            notes="Muy interesada, pero quiere ver impacto rapido y entregables simples.",
            extra={
                "city": "Samborondon",
                "reference": "Pauta de Instagram",
                "empresa": "Studio Rio",
                "instagram": "@studiorio.ec",
                "campana": "Brand awareness",
                "servicio_principal": "Activacion comercial",
                "cargo": "Directora",
                "retainer_mensual": 1800,
                "service_stage": "prospecto" if profile == PROFILE_SERVICIOS else "",
            },
        ),
        _entity_payload(
            tenant,
            key="diego-almeida",
            full_name="Diego Almeida",
            legal_id="0104432298",
            phone="0987723110",
            email="diego@proveedorasol.ec",
            notes="Cliente con decision rapida si se le muestra un plan aterrizado.",
            extra={
                "city": "Cuenca",
                "reference": "Networking Camara de Comercio",
                "empresa": "Proveedora Sol",
                "instagram": "@proveedorasol",
                "campana": "Prospeccion directa",
                "servicio_principal": "Capacitacion comercial",
                "cargo": "Gerente general",
                "retainer_mensual": 1200,
                "service_stage": "renovacion_upsell" if profile == PROFILE_SERVICIOS else "",
                "renewal_on": str(timezone.localdate() + timedelta(days=18)) if profile == PROFILE_SERVICIOS else "",
                "delivery_owner": "Valentina Mena" if profile == PROFILE_SERVICIOS else "",
            },
        ),
        _entity_payload(
            tenant,
            key="valeria-ruiz",
            full_name="Valeria Ruiz",
            legal_id="1308821142",
            phone="0998844112",
            email="valeria@casalila.ec",
            notes="Le responde mejor por WhatsApp y prefiere demos cortas.",
            extra={
                "city": "Manta",
                "reference": "Cliente referido por Mariana",
                "empresa": "Casa Lila",
                "instagram": "@casa.lila.ec",
                "campana": "Reactivacion cartera",
                "servicio_principal": "Seguimiento comercial",
                "cargo": "Administradora",
                "retainer_mensual": 780,
                "service_stage": "cliente_activo" if profile == PROFILE_SERVICIOS else "",
                "renewal_on": str(timezone.localdate() + timedelta(days=55)) if profile == PROFILE_SERVICIOS else "",
                "delivery_owner": "Luis Rojas" if profile == PROFILE_SERVICIOS else "",
            },
        ),
        _entity_payload(
            tenant,
            key="andres-ponce",
            full_name="Andres Ponce",
            legal_id="0922204481",
            phone="0962218844",
            email="andres@tallernorte.ec",
            notes="Lead frio guardado para retomar cuando se reactive el presupuesto.",
            extra={
                "city": "Daule",
                "reference": "Contacto de feria local",
                "empresa": "Taller Norte",
                "instagram": "@tallernorte",
                "campana": "Base propia",
                "servicio_principal": "Seguimiento comercial",
                "cargo": "Propietario",
                "retainer_mensual": 650,
            },
        ),
    ]

    return {
        "entities": entities,
        "deals": [
            {
                "key": "deal-mariana",
                "entity_key": "mariana-vega",
                "title": "Diagnostico comercial y tablero semanal",
                "amount": Decimal("950.00"),
                "stage_index": 0,
                "status": Deal.STATUS_OPEN,
                "expected_close_in_days": 10,
                "notes": "Quiere empezar rapido con una primera version operativa.",
            },
            {
                "key": "deal-carlos",
                "entity_key": "carlos-montalvo",
                "title": "Implementacion CRM y seguimiento de equipo",
                "amount": Decimal("3200.00"),
                "stage_index": 1,
                "status": Deal.STATUS_OPEN,
                "expected_close_in_days": 7,
                "notes": "Negocio con mas potencial, pero lleva dias sin moverse.",
            },
            {
                "key": "deal-paola",
                "entity_key": "paola-cedeno",
                "title": "Activacion comercial Q2",
                "amount": Decimal("1800.00"),
                "stage_index": 2,
                "status": Deal.STATUS_OPEN,
                "expected_close_in_days": 5,
                "notes": "Esperando aprobacion de alcance y fee mensual.",
            },
            {
                "key": "deal-diego",
                "entity_key": "diego-almeida",
                "title": "Capacitacion comercial in-company",
                "amount": Decimal("1200.00"),
                "stage_index": 3,
                "status": Deal.STATUS_WON,
                "expected_close_in_days": -4,
                "notes": "Cierre ganado para que la ficha del cliente se vea mas real.",
            },
        ],
        "activities": [
            {
                "entity_key": "carlos-montalvo",
                "deal_key": "deal-carlos",
                "activity_type": Activity.TYPE_MEETING,
                "title": "Discovery comercial",
                "description": "Sesion con el gerente comercial para mapear proceso, objeciones y responsables.",
                "due_in_hours": 30,
                "assign_actor": True,
                "age_days": 0,
            },
            {
                "entity_key": "carlos-montalvo",
                "deal_key": "deal-carlos",
                "activity_type": Activity.TYPE_TASK,
                "title": "Revisar feedback de la propuesta",
                "description": "Volver a llamar y confirmar si el alcance sigue igual o necesita ajuste.",
                "due_in_hours": -48,
                "assign_actor": True,
                "age_days": 2,
            },
            {
                "entity_key": "mariana-vega",
                "deal_key": "deal-mariana",
                "activity_type": Activity.TYPE_TASK,
                "title": "Enviar resumen de discovery",
                "description": "Compartir una version simple del plan semanal y proximos pasos.",
                "due_in_hours": 22,
                "assign_actor": True,
                "age_days": 0,
            },
            {
                "entity_key": "paola-cedeno",
                "deal_key": "deal-paola",
                "activity_type": Activity.TYPE_WHATSAPP,
                "title": "Follow up por WhatsApp",
                "description": "Paola respondio bien al mensaje, pero quedo pendiente la aprobacion final.",
                "completed_hours_ago": 18,
                "age_days": 1,
            },
            {
                "entity_key": "diego-almeida",
                "deal_key": "deal-diego",
                "activity_type": Activity.TYPE_MEETING,
                "title": "Kickoff operativo",
                "description": "Reunion inicial con el cliente y el equipo de delivery para confirmar alcance, calendario y entregables.",
                "due_in_hours": 12,
                "assign_actor": True,
                "age_days": 0,
            },
            {
                "entity_key": "diego-almeida",
                "deal_key": "deal-diego",
                "activity_type": Activity.TYPE_CALL,
                "title": "Llamada de cierre",
                "description": "Se confirmo fecha de arranque y lista de asistentes.",
                "completed_hours_ago": 30,
                "age_days": 3,
            },
            {
                "entity_key": "valeria-ruiz",
                "activity_type": Activity.TYPE_NOTE,
                "title": "Nota de contexto",
                "description": "Prefiere mensajes cortos y quiere revisar ejemplos antes de decidir.",
                "completed_hours_ago": 6,
                "age_days": 0,
            },
        ],
        "proposals": [
            {
                "entity_key": "carlos-montalvo",
                "deal_key": "deal-carlos",
                "title": "Propuesta de implementacion CRM",
                "proposal_number": "ELR-PROP-001",
                "amount": Decimal("3200.00"),
                "status": Proposal.STATUS_SENT,
                "valid_in_days": 3,
                "summary": "Incluye pipeline, seguimiento del equipo y reportes iniciales.",
                "terms": "Implementacion en 3 semanas, onboarding y ajustes basicos incluidos.",
                "sent_days_ago": 4,
            },
            {
                "entity_key": "paola-cedeno",
                "deal_key": "deal-paola",
                "title": "Paquete de activacion comercial",
                "proposal_number": "ELR-PROP-002",
                "amount": Decimal("1800.00"),
                "status": Proposal.STATUS_DRAFT,
                "valid_in_days": 6,
                "summary": "Acompanamiento comercial y tablero de seguimiento semanal.",
                "terms": "Borrador listo para enviar apenas se confirme el alcance final.",
            },
            {
                "entity_key": "diego-almeida",
                "deal_key": "deal-diego",
                "title": "Capacitacion comercial para jefes de equipo",
                "proposal_number": "ELR-PROP-003",
                "amount": Decimal("1200.00"),
                "status": Proposal.STATUS_ACCEPTED,
                "valid_in_days": -5,
                "summary": "Sesion de trabajo y material base para el equipo comercial.",
                "terms": "Aceptada y convertida en proyecto activo.",
                "sent_days_ago": 8,
                "responded_days_ago": 5,
            },
        ],
        "collections": [
            {
                "entity_key": "carlos-montalvo",
                "deal_key": "deal-carlos",
                "title": "Primer anticipo de implementacion",
                "reference": "ELR-CXC-001",
                "amount_due": Decimal("1200.00"),
                "amount_paid": Decimal("0.00"),
                "status": CollectionRecord.STATUS_OVERDUE,
                "due_in_days": -5,
                "notes": "Pendiente de confirmacion con finanzas.",
                "last_contact_days_ago": 1,
            },
            {
                "entity_key": "mariana-vega",
                "deal_key": "deal-mariana",
                "title": "Reserva de arranque",
                "reference": "ELR-CXC-002",
                "amount_due": Decimal("350.00"),
                "amount_paid": Decimal("0.00"),
                "status": CollectionRecord.STATUS_PROMISED,
                "due_in_days": 2,
                "promised_in_days": 4,
                "notes": "La clienta confirmo pago al cierre de semana.",
                "last_contact_days_ago": 0,
            },
            {
                "entity_key": "diego-almeida",
                "deal_key": "deal-diego",
                "title": "Pago total de capacitacion",
                "reference": "ELR-CXC-003",
                "amount_due": Decimal("1200.00"),
                "amount_paid": Decimal("1200.00"),
                "status": CollectionRecord.STATUS_PAID,
                "due_in_days": -8,
                "notes": "Cobro cerrado y conciliado.",
                "last_contact_days_ago": 6,
            },
        ],
        "documents": _commercial_documents(profile),
        "stale_deal_key": "deal-carlos",
        "cold_entity_key": "andres-ponce",
    }


def _build_broker_demo(tenant) -> dict:
    entities = [
        _entity_payload(
            tenant,
            key="lucia-torres",
            full_name="Lucia Torres",
            legal_id="0915578214",
            phone="0994402288",
            email="lucia.torres@clienteauto.ec",
            notes="Renovacion vehicular con todos los documentos casi listos.",
            extra={"placa": "PCA-4821", "aseguradora": "Latina Seguros", "poliza": "AUTO-2026-001"},
        ),
        _entity_payload(
            tenant,
            key="marco-aguirre",
            full_name="Marco Aguirre",
            legal_id="1721135580",
            phone="0982241100",
            email="marco@aguirrelogistica.ec",
            notes="Hace seguimiento al costo final y a la inspeccion.",
            extra={"placa": "GSB-1102", "aseguradora": "Equinoccial", "poliza": "AUTO-2026-014"},
        ),
        _entity_payload(
            tenant,
            key="ana-beltran",
            full_name="Ana Beltran",
            legal_id="0923367719",
            phone="0997710044",
            email="ana@beltranpyme.ec",
            notes="Negociacion de cobertura pyme con cierre cercano.",
            extra={"placa": "PBD-9045", "aseguradora": "Hispana", "poliza": "PYME-2026-009"},
        ),
        _entity_payload(
            tenant,
            key="jose-campoverde",
            full_name="Jose Campoverde",
            legal_id="0105514478",
            phone="0985577331",
            email="jose@transportescampo.ec",
            notes="Asegurado historico, ideal para mostrar un caso sin actividad reciente.",
            extra={"placa": "MBQ-7710", "aseguradora": "Confianza", "poliza": "AUTO-2026-021"},
        ),
    ]

    return {
        "entities": entities,
        "deals": [
            {
                "key": "deal-lucia",
                "entity_key": "lucia-torres",
                "title": "Renovacion Toyota Fortuner",
                "amount": Decimal("680.00"),
                "stage_index": 0,
                "status": Deal.STATUS_OPEN,
                "expected_close_in_days": 4,
                "notes": "Esperando confirmar fecha de emision.",
            },
            {
                "key": "deal-marco",
                "entity_key": "marco-aguirre",
                "title": "Renovacion flota liviana",
                "amount": Decimal("1420.00"),
                "stage_index": 1,
                "status": Deal.STATUS_OPEN,
                "expected_close_in_days": 6,
                "notes": "Caso ideal para que el reporte muestre una renovacion estancada.",
            },
            {
                "key": "deal-ana",
                "entity_key": "ana-beltran",
                "title": "Cobertura pyme multirriesgo",
                "amount": Decimal("2100.00"),
                "stage_index": 2,
                "status": Deal.STATUS_OPEN,
                "expected_close_in_days": 8,
                "notes": "Listo para emision en cuanto llegue la aprobacion final.",
            },
        ],
        "activities": [
            {
                "entity_key": "marco-aguirre",
                "deal_key": "deal-marco",
                "activity_type": Activity.TYPE_TASK,
                "title": "Confirmar inspeccion pendiente",
                "description": "Llamar para reagendar la inspeccion del vehiculo.",
                "due_in_hours": -24,
                "assign_actor": True,
                "age_days": 1,
            },
            {
                "entity_key": "lucia-torres",
                "deal_key": "deal-lucia",
                "activity_type": Activity.TYPE_WHATSAPP,
                "title": "WhatsApp con documentos",
                "description": "La clienta envio cedula y matricula.",
                "completed_hours_ago": 8,
                "age_days": 0,
            },
            {
                "entity_key": "ana-beltran",
                "deal_key": "deal-ana",
                "activity_type": Activity.TYPE_CALL,
                "title": "Llamada de validacion final",
                "description": "Se revisaron coberturas y deducibles.",
                "completed_hours_ago": 16,
                "age_days": 2,
            },
            {
                "entity_key": "lucia-torres",
                "activity_type": Activity.TYPE_CLAIM,
                "title": "Siniestro consultado",
                "description": "Consulta menor sobre proceso de atencion y talleres.",
                "completed_hours_ago": 36,
                "age_days": 4,
            },
        ],
        "proposals": [
            {
                "entity_key": "marco-aguirre",
                "deal_key": "deal-marco",
                "title": "Cotizacion renovacion flota",
                "proposal_number": "ELR-BRK-001",
                "amount": Decimal("1420.00"),
                "status": Proposal.STATUS_SENT,
                "valid_in_days": 4,
                "summary": "Cotizacion con cobertura base y asistencia ampliada.",
                "terms": "Vigencia de 4 dias y emision sujeta a inspeccion.",
                "sent_days_ago": 3,
            },
            {
                "entity_key": "ana-beltran",
                "deal_key": "deal-ana",
                "title": "Cotizacion pyme multirriesgo",
                "proposal_number": "ELR-BRK-002",
                "amount": Decimal("2100.00"),
                "status": Proposal.STATUS_DRAFT,
                "valid_in_days": 6,
                "summary": "Borrador listo para compartir al cierre del dia.",
                "terms": "Incluye cobertura patrimonial y responsabilidad civil.",
            },
        ],
        "collections": [
            {
                "entity_key": "marco-aguirre",
                "deal_key": "deal-marco",
                "title": "Prima pendiente renovacion flota",
                "reference": "ELR-BRK-COB-001",
                "amount_due": Decimal("730.00"),
                "amount_paid": Decimal("0.00"),
                "status": CollectionRecord.STATUS_OVERDUE,
                "due_in_days": -6,
                "notes": "Pendiente de tesoreria del cliente.",
                "last_contact_days_ago": 1,
            },
            {
                "entity_key": "lucia-torres",
                "deal_key": "deal-lucia",
                "title": "Reserva de emision",
                "reference": "ELR-BRK-COB-002",
                "amount_due": Decimal("180.00"),
                "amount_paid": Decimal("0.00"),
                "status": CollectionRecord.STATUS_PROMISED,
                "due_in_days": 1,
                "promised_in_days": 3,
                "notes": "Clienta prometio transferir apenas reciba la cotizacion final.",
                "last_contact_days_ago": 0,
            },
            {
                "entity_key": "ana-beltran",
                "deal_key": "deal-ana",
                "title": "Pago inicial cobertura pyme",
                "reference": "ELR-BRK-COB-003",
                "amount_due": Decimal("500.00"),
                "amount_paid": Decimal("500.00"),
                "status": CollectionRecord.STATUS_PAID,
                "due_in_days": -10,
                "notes": "Primer abono ya conciliado.",
                "last_contact_days_ago": 5,
            },
        ],
        "documents": [
            {
                "entity_key": "lucia-torres",
                "deal_key": "deal-lucia",
                "title": "Poliza Toyota Fortuner",
                "document_type": "poliza",
                "external_url": "https://demo.binn.ec/el_rosal/broker/poliza-lucia.pdf",
                "metadata": {
                    "aseguradora": "Latina Seguros",
                    "numero_poliza": "AUTO-2026-001",
                    "vigencia_desde": "2026-04-01",
                    "vigencia_hasta": "2026-05-20",
                    "ramo": "Autos",
                },
                "expires_in_days": 24,
                "is_verified": True,
            },
            {
                "entity_key": "lucia-torres",
                "title": "Cedula Lucia Torres",
                "document_type": "cedula",
                "external_url": "https://demo.binn.ec/el_rosal/broker/cedula-lucia.pdf",
                "metadata": {
                    "titular": "Lucia Torres",
                    "identificacion": "0915578214",
                },
                "is_verified": True,
            },
            {
                "entity_key": "lucia-torres",
                "title": "Matricula Toyota Fortuner",
                "document_type": "matricula",
                "external_url": "https://demo.binn.ec/el_rosal/broker/matricula-lucia.pdf",
                "metadata": {
                    "placa": "PCA-4821",
                    "chasis": "8FAGZ22P0AA123456",
                    "anio": 2022,
                },
                "is_verified": True,
            },
            {
                "entity_key": "marco-aguirre",
                "deal_key": "deal-marco",
                "title": "Inspeccion pendiente flota",
                "document_type": "inspeccion",
                "external_url": "https://demo.binn.ec/el_rosal/broker/inspeccion-marco.pdf",
                "metadata": {
                    "placa": "GSB-1102",
                    "fecha_inspeccion": "2026-04-28",
                    "estado": "Pendiente",
                },
                "expires_in_days": 5,
                "is_verified": False,
            },
        ],
        "stale_deal_key": "deal-marco",
        "cold_entity_key": "jose-campoverde",
    }


def _build_condominio_demo(tenant) -> dict:
    entities = [
        _entity_payload(
            tenant,
            key="adriana-perez",
            full_name="Adriana Perez",
            legal_id="0911142233",
            phone="0992201100",
            email="adriana@residente-elrosal.ec",
            notes="Residente puntual que solo necesita recordatorios claros.",
            extra={"departamento": "A-204", "torre": "Torre A", "alicuota": 135},
        ),
        _entity_payload(
            tenant,
            key="jorge-mera",
            full_name="Jorge Mera",
            legal_id="1718820031",
            phone="0981133002",
            email="jorge@residente-elrosal.ec",
            notes="Cuenta con cartera vencida y seguimiento frecuente.",
            extra={"departamento": "B-703", "torre": "Torre B", "alicuota": 165},
        ),
        _entity_payload(
            tenant,
            key="susana-mora",
            full_name="Susana Mora",
            legal_id="0924413370",
            phone="0998811440",
            email="susana@residente-elrosal.ec",
            notes="Pago prometido para esta semana.",
            extra={"departamento": "C-110", "torre": "Torre C", "alicuota": 148},
        ),
        _entity_payload(
            tenant,
            key="hector-robles",
            full_name="Hector Robles",
            legal_id="0106685521",
            phone="0966611442",
            email="hector@residente-elrosal.ec",
            notes="Residente sin novedad reciente para mostrar una ficha mas tranquila.",
            extra={"departamento": "A-105", "torre": "Torre A", "alicuota": 122},
        ),
    ]

    return {
        "entities": entities,
        "deals": [
            {
                "key": "deal-adriana",
                "entity_key": "adriana-perez",
                "title": "Alicuota abril Torre A",
                "amount": Decimal("135.00"),
                "stage_index": 0,
                "status": Deal.STATUS_OPEN,
                "expected_close_in_days": 3,
                "notes": "Cobro en seguimiento normal.",
            },
            {
                "key": "deal-jorge",
                "entity_key": "jorge-mera",
                "title": "Cartera vencida Torre B",
                "amount": Decimal("330.00"),
                "stage_index": 1,
                "status": Deal.STATUS_OPEN,
                "expected_close_in_days": 2,
                "notes": "Caso ideal para ver atraso en reportes y actividad.",
            },
            {
                "key": "deal-susana",
                "entity_key": "susana-mora",
                "title": "Promesa de pago abril",
                "amount": Decimal("148.00"),
                "stage_index": 2,
                "status": Deal.STATUS_WON,
                "expected_close_in_days": -1,
                "notes": "Pago ya encaminado para que el tablero no quede todo en rojo.",
            },
        ],
        "activities": [
            {
                "entity_key": "jorge-mera",
                "deal_key": "deal-jorge",
                "activity_type": Activity.TYPE_TASK,
                "title": "Llamar por cartera vencida",
                "description": "Confirmar fecha real de pago y documentar compromiso.",
                "due_in_hours": -30,
                "assign_actor": True,
                "age_days": 2,
            },
            {
                "entity_key": "susana-mora",
                "deal_key": "deal-susana",
                "activity_type": Activity.TYPE_WHATSAPP,
                "title": "Recordatorio de pago",
                "description": "Se envio el valor exacto y datos de transferencia.",
                "completed_hours_ago": 5,
                "age_days": 0,
            },
            {
                "entity_key": "adriana-perez",
                "deal_key": "deal-adriana",
                "activity_type": Activity.TYPE_NOTE,
                "title": "Residente al dia",
                "description": "Solo requiere seguimiento preventivo.",
                "completed_hours_ago": 28,
                "age_days": 1,
            },
        ],
        "proposals": [],
        "collections": [
            {
                "entity_key": "jorge-mera",
                "deal_key": "deal-jorge",
                "title": "Saldo abril y marzo",
                "reference": "ELR-CON-001",
                "amount_due": Decimal("330.00"),
                "amount_paid": Decimal("0.00"),
                "status": CollectionRecord.STATUS_OVERDUE,
                "due_in_days": -12,
                "notes": "Vencido, con seguimiento activo.",
                "last_contact_days_ago": 1,
            },
            {
                "entity_key": "susana-mora",
                "deal_key": "deal-susana",
                "title": "Alicuota abril",
                "reference": "ELR-CON-002",
                "amount_due": Decimal("148.00"),
                "amount_paid": Decimal("0.00"),
                "status": CollectionRecord.STATUS_PROMISED,
                "due_in_days": 1,
                "promised_in_days": 3,
                "notes": "La residente prometio pago antes del viernes.",
                "last_contact_days_ago": 0,
            },
            {
                "entity_key": "adriana-perez",
                "deal_key": "deal-adriana",
                "title": "Alicuota marzo",
                "reference": "ELR-CON-003",
                "amount_due": Decimal("135.00"),
                "amount_paid": Decimal("135.00"),
                "status": CollectionRecord.STATUS_PAID,
                "due_in_days": -20,
                "notes": "Pago recibido y registrado.",
                "last_contact_days_ago": 7,
            },
        ],
        "documents": [],
        "stale_deal_key": "deal-jorge",
        "cold_entity_key": "hector-robles",
    }


def _build_retail_demo(tenant) -> dict:
    entities = [
        _entity_payload(
            tenant,
            key="camila-arias",
            full_name="Camila Arias",
            legal_id="0911123499",
            phone="0994401199",
            email="camila@clientevip.ec",
            notes="Cliente recurrente que responde bien a lanzamientos por WhatsApp.",
            extra={"talla": "M", "estilo": "Minimalista", "instagram": "@camilaarias", "ultima_compra": "2026-04-12"},
        ),
        _entity_payload(
            tenant,
            key="sofia-viteri",
            full_name="Sofia Viteri",
            legal_id="0922334488",
            phone="0989911770",
            email="sofia@clientevip.ec",
            notes="Pidio apartado de la nueva coleccion denim.",
            extra={"talla": "S", "estilo": "Denim", "instagram": "@sofiaviteri", "ultima_compra": "2026-04-05"},
        ),
        _entity_payload(
            tenant,
            key="martin-loor",
            full_name="Martin Loor",
            legal_id="1300022114",
            phone="0990033445",
            email="martin@clienteespecial.ec",
            notes="Interesado en un pedido especial para regalo.",
            extra={"talla": "L", "estilo": "Casual", "instagram": "@martinloor", "ultima_compra": "2026-03-18"},
        ),
        _entity_payload(
            tenant,
            key="elena-zambrano",
            full_name="Elena Zambrano",
            legal_id="1712211440",
            phone="0967721188",
            email="elena@reactivacion.ec",
            notes="Cliente fria para probar el radar de reactivacion.",
            extra={"talla": "M", "estilo": "Basicos", "instagram": "@elena.z", "ultima_compra": "2026-01-15"},
        ),
    ]

    return {
        "entities": entities,
        "deals": [
            {
                "key": "deal-camila",
                "entity_key": "camila-arias",
                "title": "Recompra capsule office",
                "amount": Decimal("145.00"),
                "stage_index": 0,
                "status": Deal.STATUS_OPEN,
                "expected_close_in_days": 2,
                "notes": "Caso pensado para mostrar seguimiento rapido y recompra.",
            },
            {
                "key": "deal-sofia",
                "entity_key": "sofia-viteri",
                "title": "Apartado denim weekend",
                "amount": Decimal("98.00"),
                "stage_index": 1,
                "status": Deal.STATUS_OPEN,
                "expected_close_in_days": 1,
                "notes": "Cliente esperando confirmacion de talla.",
            },
            {
                "key": "deal-martin",
                "entity_key": "martin-loor",
                "title": "Pedido especial regalo",
                "amount": Decimal("210.00"),
                "stage_index": 2,
                "status": Deal.STATUS_WON,
                "expected_close_in_days": -3,
                "notes": "Pedido ya confirmado.",
            },
        ],
        "activities": [
            {
                "entity_key": "sofia-viteri",
                "deal_key": "deal-sofia",
                "activity_type": Activity.TYPE_TASK,
                "title": "Confirmar talla reservada",
                "description": "Ver si se mantiene la talla S o hay que separar una M.",
                "due_in_hours": -10,
                "assign_actor": True,
                "age_days": 1,
            },
            {
                "entity_key": "camila-arias",
                "deal_key": "deal-camila",
                "activity_type": Activity.TYPE_WHATSAPP,
                "title": "Mensaje de recompra",
                "description": "Se compartio lookbook y cupo de preventa.",
                "completed_hours_ago": 7,
                "age_days": 0,
            },
            {
                "entity_key": "martin-loor",
                "deal_key": "deal-martin",
                "activity_type": Activity.TYPE_NOTE,
                "title": "Cliente satisfecho",
                "description": "Pide guardar historial para futuras compras especiales.",
                "completed_hours_ago": 20,
                "age_days": 2,
            },
        ],
        "proposals": [],
        "collections": [],
        "documents": [],
        "stale_deal_key": "deal-sofia",
        "cold_entity_key": "elena-zambrano",
    }


def _commercial_documents(profile: str) -> list[dict]:
    if profile == PROFILE_SERVICIOS:
        return [
            {
                "entity_key": "carlos-montalvo",
                "deal_key": "deal-carlos",
                "title": "Propuesta de servicio CRM",
                "document_type": "propuesta_servicio",
                "external_url": "https://demo.binn.ec/el_rosal/servicios/propuesta-carlos.pdf",
                "metadata": {
                    "empresa": "Distribuidora Andina",
                    "servicio_principal": "Implementacion CRM",
                    "vigencia_hasta": "2026-04-29",
                },
                "expires_in_days": 3,
                "is_verified": True,
            },
            {
                "entity_key": "diego-almeida",
                "deal_key": "deal-diego",
                "title": "Contrato de capacitacion",
                "document_type": "contrato_servicio",
                "external_url": "https://demo.binn.ec/el_rosal/servicios/contrato-diego.pdf",
                "metadata": {
                    "empresa": "Proveedora Sol",
                    "fecha_inicio": "2026-04-20",
                    "fecha_fin": "2026-05-20",
                },
                "is_verified": True,
            },
        ]
    if profile == PROFILE_MARKETING:
        return [
            {
                "entity_key": "paola-cedeno",
                "deal_key": "deal-paola",
                "title": "Brief de activacion Q2",
                "document_type": "brief",
                "external_url": "https://demo.binn.ec/el_rosal/marketing/brief-paola.pdf",
                "metadata": {
                    "empresa": "Studio Rio",
                    "campana": "Brand awareness",
                    "objetivo": "Captar leads calificados",
                },
                "is_verified": True,
            },
            {
                "entity_key": "paola-cedeno",
                "deal_key": "deal-paola",
                "title": "Propuesta comercial Studio Rio",
                "document_type": "propuesta",
                "external_url": "https://demo.binn.ec/el_rosal/marketing/propuesta-paola.pdf",
                "metadata": {
                    "empresa": "Studio Rio",
                    "monto": Decimal("1800.00"),
                    "vigencia_hasta": "2026-05-02",
                },
                "expires_in_days": 6,
                "is_verified": True,
            },
        ]
    return [
        {
            "entity_key": "carlos-montalvo",
            "deal_key": "deal-carlos",
            "title": "Resumen comercial Distribuidora Andina",
            "document_type": "general",
            "external_url": "https://demo.binn.ec/el_rosal/general/resumen-carlos.pdf",
            "metadata": {
                "referencia": "Implementacion CRM",
                "notas": "Documento de soporte para demo.",
            },
            "is_verified": True,
        }
    ]


def _build_demo_object_records(*, profile: str) -> list[dict]:
    if profile == PROFILE_GENERAL or profile == PROFILE_MARKETING:
        return []
    today = timezone.localdate()
    if profile == PROFILE_SERVICIOS:
        return [
            {
                "object_key": "entregable",
                "data": {
                    "nombre": "Workshop discovery comercial",
                    "cliente": "Flores & Co",
                    "tipo_entregable": "Workshop",
                    "estado": "En curso",
                    "responsable": "Andrea Leon",
                    "fecha_entrega": str(today + timedelta(days=2)),
                },
                "age_days": 1,
            },
            {
                "object_key": "entregable",
                "data": {
                    "nombre": "Playbook de seguimiento Q2",
                    "cliente": "Distribuidora Andina",
                    "tipo_entregable": "Playbook",
                    "estado": "Por validar",
                    "responsable": "Mateo Ruiz",
                    "fecha_entrega": str(today + timedelta(days=5)),
                },
                "age_days": 3,
            },
        ]
    if profile == PROFILE_BROKER:
        return [
            {
                "object_key": "poliza_detalle",
                "data": {
                    "numero_poliza": "POL-ELR-001",
                    "producto": "Vehiculo liviano",
                    "vigencia_hasta": str(today + timedelta(days=30)),
                    "prima": "485.00",
                },
                "age_days": 2,
            },
            {
                "object_key": "poliza_detalle",
                "data": {
                    "numero_poliza": "POL-ELR-002",
                    "producto": "Pyme integral",
                    "vigencia_hasta": str(today + timedelta(days=12)),
                    "prima": "1260.00",
                },
                "age_days": 5,
            },
        ]
    if profile == PROFILE_CONDOMINIO:
        return [
            {
                "object_key": "unidad",
                "data": {
                    "codigo_unidad": "T2-504",
                    "torre": "Torre 2",
                    "propietario": "Lucia Salazar",
                    "metros_cuadrados": "96",
                },
                "age_days": 4,
            },
            {
                "object_key": "unidad",
                "data": {
                    "codigo_unidad": "B1-203",
                    "torre": "Bloque 1",
                    "propietario": "Marco Valverde",
                    "metros_cuadrados": "82",
                },
                "age_days": 7,
            },
        ]
    if profile == PROFILE_RETAIL_MODA:
        return [
            {
                "object_key": "wishlist",
                "data": {
                    "cliente": "Sofia Rendon",
                    "pieza": "Blazer crema oversize",
                    "talla": "M",
                    "vigente": True,
                },
                "age_days": 2,
            },
            {
                "object_key": "wishlist",
                "data": {
                    "cliente": "Elena Zambrano",
                    "pieza": "Vestido lino azul",
                    "talla": "S",
                    "vigente": False,
                },
                "age_days": 8,
            },
        ]
    return []


def _entity_payload(tenant, *, key: str, full_name: str, legal_id: str, phone: str, email: str, notes: str, extra: dict) -> dict:
    return {
        "key": key,
        "full_name": full_name,
        "legal_id": legal_id,
        "phone": phone,
        "email": email,
        "notes": notes,
        "extra": _filter_extra_fields(tenant, extra),
    }


def _filter_extra_fields(tenant, extra: dict) -> dict:
    from .object_engine import get_entity_field_definitions

    allowed_keys = {field["key"] for field in get_entity_field_definitions(tenant=tenant)}
    return {key: value for key, value in extra.items() if key in allowed_keys}


def _resolve_stage(stages: list[str], stage_index: int) -> str:
    if not stages:
        return "Sin etapa"
    if stage_index < 0:
        return stages[0]
    if stage_index >= len(stages):
        return stages[-1]
    return stages[stage_index]


def _tally(counter: dict, created: bool) -> None:
    if created:
        counter["created"] += 1
    else:
        counter["updated"] += 1
