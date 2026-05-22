from datetime import date, timedelta
from types import SimpleNamespace
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase
from django.utils import timezone

from .document_blueprints import (
    build_document_metadata_summary,
    build_document_metadata_template,
    get_document_blueprints,
    get_document_type_label,
)
from .demo_seed import build_demo_scenario
from .forms import CollectionRecordForm, EntityForm, ObjectRecordForm, PipelineTemplateEditorForm, ProposalForm
from .importers import import_entities_from_csv
from .models import CollectionRecord, Document, ObjectSchema, Proposal
from .object_engine import get_entity_field_definitions, resolve_object_record_title
from .view_engine import apply_deal_saved_view, apply_entity_saved_view, get_saved_views, resolve_saved_view
from .views import (
    _build_broker_document_checklist,
    _build_document_access_url,
    _build_entity_timeline,
    _collection_status,
    _build_extra_values,
    _build_entity_search_query,
    _document_expiry_status,
    _format_extra_value,
    _proposal_status,
    _task_status,
)
from tenants.defaults import PROFILE_BROKER, PROFILE_MARKETING, PROFILE_RETAIL_MODA, PROFILE_SERVICIOS


class EntityFormTests(SimpleTestCase):
    def test_builds_dynamic_fields_from_tenant_config(self):
        tenant = SimpleNamespace(
            entity_fields=[
                {"key": "placa", "label": "Placa", "type": "text"},
                {"key": "aseguradora", "label": "Aseguradora", "type": "text"},
            ]
        )

        form = EntityForm(tenant=tenant)

        self.assertIn("extra__placa", form.fields)
        self.assertIn("extra__aseguradora", form.fields)
        self.assertEqual(form.fields["extra__placa"].label, "Placa")

    def test_save_maps_dynamic_fields_into_data_extra(self):
        tenant = SimpleNamespace(
            entity_fields=[
                {"key": "placa", "label": "Placa", "type": "text"},
                {"key": "aseguradora", "label": "Aseguradora", "type": "text"},
            ]
        )
        form = EntityForm(
            data={
                "full_name": "Ana Perez",
                "legal_id": "0912345678",
                "phone": "0999999999",
                "email": "ana@example.com",
                "notes": "Cliente prioritaria",
                "is_active": "on",
                "extra__placa": "ABC-123",
                "extra__aseguradora": "Binn Seguros",
            },
            tenant=tenant,
        )

        self.assertTrue(form.is_valid(), form.errors)

        entity = form.save(commit=False)

        self.assertEqual(
            entity.data_extra,
            {
                "placa": "ABC-123",
                "aseguradora": "Binn Seguros",
            },
        )


class PipelineTemplateEditorFormTests(SimpleTestCase):
    def test_builds_stage_list_without_json(self):
        form = PipelineTemplateEditorForm(
            data={
                "label": "Ventas B2B",
                "stages_text": "Lead\nDiscovery\nPropuesta\nGanado",
                "make_default": "on",
            },
            existing_keys=[],
        )

        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["pipeline_key"], "ventas_b2b")
        self.assertEqual(form.cleaned_data["stages"], ["Lead", "Discovery", "Propuesta", "Ganado"])

    def test_rejects_duplicated_stages(self):
        form = PipelineTemplateEditorForm(
            data={
                "label": "Renovaciones",
                "stages_text": "Cotizado\nEmitido\nCotizado",
            },
            existing_keys=[],
        )

        self.assertFalse(form.is_valid())
        self.assertIn("stages_text", form.errors)

    def test_rejects_duplicate_generated_key_when_creating_new_pipeline(self):
        form = PipelineTemplateEditorForm(
            data={
                "label": "Ventas B2B",
                "stages_text": "Lead\nPropuesta",
            },
            existing_keys=["ventas_b2b"],
            current_key="",
        )

        self.assertFalse(form.is_valid())
        self.assertIn("label", form.errors)


class ObjectEngineFallbackTests(SimpleTestCase):
    def test_entity_field_definitions_fall_back_to_tenant_config_when_schema_runtime_is_unavailable(self):
        tenant = SimpleNamespace(
            entity_fields=[
                {"key": "placa", "label": "Placa", "type": "text"},
                {"key": "vigente", "label": "Vigente", "type": "boolean"},
            ]
        )

        field_definitions = get_entity_field_definitions(tenant=tenant)

        self.assertEqual(field_definitions[0]["key"], "placa")
        self.assertEqual(field_definitions[1]["type"], "boolean")

    def test_saved_views_include_operational_presets_without_schema_runtime(self):
        views = get_saved_views(object_key="entity")

        self.assertTrue(any(view["key"] == "recently_updated" for view in views))
        self.assertTrue(any(view["key"] == "missing_contact" for view in views))

    def test_resolve_saved_view_uses_default_when_view_is_unknown(self):
        view = resolve_saved_view(object_key="deal", view_key="nope")

        self.assertEqual(view["key"], "pipeline_board")

    @patch("binncrm.object_engine.get_object_record_field_definitions")
    def test_resolve_object_record_title_uses_primary_field_setting(self, field_definitions):
        field_definitions.return_value = [
            {"key": "numero_poliza", "label": "Numero de poliza", "type": "text"},
            {"key": "producto", "label": "Producto", "type": "text"},
        ]
        object_schema = ObjectSchema(
            key="poliza_detalle",
            label="Polizas",
            settings={"primary_field": "numero_poliza"},
        )

        title = resolve_object_record_title(
            object_schema=object_schema,
            data={"numero_poliza": "POL-001", "producto": "Auto"},
        )

        self.assertEqual(title, "POL-001")

    @patch("binncrm.forms.get_object_record_field_definitions")
    def test_object_record_form_maps_dynamic_payload(self, field_definitions):
        field_definitions.return_value = [
            {"key": "numero_poliza", "label": "Numero de poliza", "type": "text", "required": True},
            {"key": "vigente", "label": "Vigente", "type": "boolean", "required": False},
        ]
        object_schema = ObjectSchema(key="poliza_detalle", label="Polizas", settings={"primary_field": "numero_poliza"})
        form = ObjectRecordForm(
            data={"is_active": "on", "data__numero_poliza": "POL-001", "data__vigente": "on"},
            object_schema=object_schema,
        )

        self.assertTrue(form.is_valid(), form.errors)
        record = form.save(commit=False)

        self.assertEqual(record.data["numero_poliza"], "POL-001")
        self.assertTrue(record.data["vigente"])
        self.assertEqual(record.title, "POL-001")


class _RecordingQuerySet:
    def __init__(self):
        self.filtered = []
        self.ordered = []

    def filter(self, *args, **kwargs):
        self.filtered.append((args, kwargs))
        return self

    def order_by(self, *args):
        self.ordered.append(args)
        return self


class SavedViewFilteringTests(SimpleTestCase):
    def test_entity_view_applies_missing_contact_and_ordering(self):
        queryset = _RecordingQuerySet()

        apply_entity_saved_view(
            queryset,
            view={
                "config": {
                    "filters": {"missing_contact": True},
                    "ordering": "-updated_at,full_name",
                }
            },
        )

        self.assertEqual(len(queryset.filtered), 1)
        self.assertEqual(queryset.ordered[-1], ("-updated_at", "full_name"))

    def test_deal_view_applies_stale_filter_and_ordering(self):
        queryset = _RecordingQuerySet()

        apply_deal_saved_view(
            queryset,
            view={
                "config": {
                    "filters": {"stale_days": 14},
                    "ordering": "sort_order,-updated_at",
                }
            },
        )

        self.assertEqual(len(queryset.filtered), 1)
        self.assertEqual(queryset.ordered[-1], ("sort_order", "-updated_at"))


class EntityHelperTests(SimpleTestCase):
    def test_format_extra_value_respects_type(self):
        self.assertEqual(_format_extra_value(True, {"type": "boolean"}), "Si")
        self.assertEqual(_format_extra_value(False, {"type": "boolean"}), "No")
        self.assertEqual(_format_extra_value(date(2026, 4, 24), {"type": "date"}), "24/04/2026")

    def test_build_extra_values_formats_dynamic_fields(self):
        entity = SimpleNamespace(
            data_extra={
                "placa": "ABC-123",
                "vigente": True,
                "renovacion": "2026-04-24",
            }
        )

        values = _build_extra_values(
            entity,
            [
                {"key": "placa", "label": "Placa", "type": "text"},
                {"key": "vigente", "label": "Vigente", "type": "boolean"},
                {"key": "renovacion", "label": "Renovacion", "type": "date"},
            ],
        )

        self.assertEqual(values[0]["value"], "ABC-123")
        self.assertEqual(values[1]["value"], "Si")
        self.assertEqual(values[2]["value"], "24/04/2026")

    def test_build_entity_search_query_includes_dynamic_field_paths(self):
        query = _build_entity_search_query("ABC", [{"key": "placa", "label": "Placa", "type": "text"}])

        flattened = repr(query)

        self.assertIn("full_name__icontains", flattened)
        self.assertIn("data_extra__placa__icontains", flattened)

    def test_task_status_marks_overdue_task(self):
        now = timezone.now()
        activity = SimpleNamespace(completed_at=None, due_at=now - timedelta(hours=2))

        status = _task_status(activity, now=now)

        self.assertTrue(status["is_overdue"])
        self.assertIn("Vencida", status["label"])

    def test_proposal_status_marks_sent_until_validity(self):
        proposal = Proposal(status=Proposal.STATUS_SENT, valid_until=date(2026, 4, 30))

        status = _proposal_status(proposal, now=date(2026, 4, 25))

        self.assertIn("hasta 30/04/2026", status["label"])

    def test_collection_status_marks_overdue_item(self):
        collection = CollectionRecord(status=CollectionRecord.STATUS_PENDING, due_on=date(2026, 4, 24))

        status = _collection_status(collection, now=date(2026, 4, 25))

        self.assertTrue(status["is_overdue"])
        self.assertIn("Vencida", status["label"])

    def test_entity_timeline_merges_deals_activities_and_documents(self):
        entity = SimpleNamespace(
            timeline_events=[
                SimpleNamespace(
                    category="deal",
                    kind_label="Renovacion",
                    title="Renovacion auto",
                    meta="Renovaciones | Emitido",
                    description="USD 350",
                    occurred_at=timezone.now() - timedelta(hours=1),
                    accent="bg-blue-50 text-blue-700",
                ),
                SimpleNamespace(
                    category="activity",
                    kind_label="Tarea",
                    title="Llamar al cliente",
                    meta="ana",
                    description="Confirmar documentos",
                    occurred_at=timezone.now() - timedelta(minutes=30),
                    accent="bg-gray-100 text-gray-700",
                ),
                SimpleNamespace(
                    category="document",
                    kind_label="Documento",
                    title="Poliza firmada",
                    meta="Poliza",
                    description="broker/polizas/poliza.pdf",
                    occurred_at=timezone.now() - timedelta(minutes=10),
                    accent="bg-green-50 text-green-700",
                ),
            ],
        )

        timeline = _build_entity_timeline(entity, profile=PROFILE_BROKER, blueprint_map={"poliza": {"label": "Poliza"}}, custom_blueprints=[])

        self.assertEqual(timeline[0]["kind"], "document")
        self.assertTrue(any(item["kind"] == "deal" for item in timeline))
        self.assertTrue(any(item["kind"] == "activity" for item in timeline))


class _FakeQuerySet(list):
    def all(self):
        return self

    def order_by(self, *args, **kwargs):
        return self

    def first(self):
        return self[0] if self else None


class ProposalAndCollectionFormTests(SimpleTestCase):
    @patch("binncrm.forms.Deal.objects.filter")
    @patch("binncrm.forms.Entity.objects.filter")
    def test_proposal_form_infers_entity_from_deal(self, entity_filter, deal_filter):
        entity_filter.return_value = _FakeQuerySet()
        deal_filter.return_value = _FakeQuerySet()
        form = ProposalForm()
        inferred_entity = SimpleNamespace(id=7)
        deal = SimpleNamespace(entity=inferred_entity, entity_id=7)
        errors = {}
        form.cleaned_data = {"entity": None, "deal": deal}
        form.add_error = lambda field, message: errors.setdefault(field, []).append(message)

        cleaned = form.clean()

        self.assertEqual(cleaned["entity"], inferred_entity)
        self.assertEqual(errors, {})

    @patch("binncrm.forms.Deal.objects.filter")
    @patch("binncrm.forms.Entity.objects.filter")
    def test_collection_form_requires_promise_date(self, entity_filter, deal_filter):
        entity_filter.return_value = _FakeQuerySet()
        deal_filter.return_value = _FakeQuerySet()
        form = CollectionRecordForm()
        entity = SimpleNamespace(id=3)
        deal = SimpleNamespace(entity=entity, entity_id=3)
        errors = {}
        form.cleaned_data = {
            "entity": entity,
            "deal": deal,
            "amount_due": 120,
            "amount_paid": 0,
            "status": CollectionRecord.STATUS_PROMISED,
            "promised_for": None,
        }
        form.add_error = lambda field, message: errors.setdefault(field, []).append(message)

        form.clean()

        self.assertIn("promised_for", errors)


class EntityImporterTests(SimpleTestCase):
    def setUp(self):
        self.user = SimpleNamespace(username="importador")
        self.tenant = SimpleNamespace(
            entity_fields=[
                {"key": "placa", "label": "Placa", "type": "text"},
                {"key": "vigente", "label": "Vigente", "type": "boolean"},
            ]
        )

    @patch("binncrm.importers._find_existing_entity")
    @patch("binncrm.importers.Entity")
    def test_import_entities_from_csv_creates_records_with_dynamic_fields(self, entity_class, find_existing):
        saved_instances = []

        class FakeEntity:
            def __init__(self):
                self.legal_id = ""
                self.phone = ""
                self.email = ""
                self.notes = ""
                self.is_active = True
                self.data_extra = {}
                self.pk = None

            def save(self):
                self.pk = 1
                saved_instances.append(self)

        entity_class.side_effect = FakeEntity
        find_existing.return_value = None
        csv_file = SimpleUploadedFile(
            "entidades.csv",
            b"nombre,cedula,telefono,placa,vigente\nAna Perez,0912345678,0999999999,ABC-123,si\n",
            content_type="text/csv",
        )

        summary = import_entities_from_csv(csv_file, tenant=self.tenant, actor=self.user, update_existing=True)

        self.assertEqual(summary["created"], 1)
        self.assertEqual(saved_instances[0].data_extra["placa"], "ABC-123")
        self.assertTrue(saved_instances[0].data_extra["vigente"])

    @patch("binncrm.importers._find_existing_entity")
    def test_import_entities_from_csv_updates_existing_match(self, find_existing):
        existing = SimpleNamespace(
            pk=99,
            legal_id="0912345678",
            phone="0900",
            email="",
            notes="",
            is_active=True,
            data_extra={},
            save=lambda: None,
        )
        find_existing.return_value = existing
        csv_file = SimpleUploadedFile(
            "entidades.csv",
            b"nombre,cedula,telefono\nAna Perez,0912345678,0999999999\n",
            content_type="text/csv",
        )

        summary = import_entities_from_csv(csv_file, tenant=self.tenant, actor=self.user, update_existing=True)

        self.assertEqual(summary["updated"], 1)
        self.assertEqual(existing.phone, "0999999999")


class DocumentBlueprintTests(SimpleTestCase):
    def test_broker_blueprints_include_policy_documents(self):
        blueprints = get_document_blueprints(PROFILE_BROKER)

        self.assertTrue(any(blueprint["key"] == "poliza" for blueprint in blueprints))
        self.assertTrue(any(blueprint["key"] == "matricula" for blueprint in blueprints))
        self.assertFalse(any(blueprint["key"] == "reporte_campana" for blueprint in blueprints))

    def test_metadata_template_uses_known_fields(self):
        template = build_document_metadata_template(PROFILE_BROKER, "poliza")

        self.assertEqual(
            template,
            {
                "aseguradora": "",
                "numero_poliza": "",
                "vigencia_desde": "",
                "vigencia_hasta": "",
                "ramo": "",
            },
        )

    def test_metadata_summary_prioritizes_blueprint_fields(self):
        summary = build_document_metadata_summary(
            {
                "aseguradora": "Binn Seguros",
                "numero_poliza": "POL-001",
                "vigencia_hasta": "2026-04-24",
                "notas": "Cliente premium",
            },
            profile=PROFILE_BROKER,
            document_type="poliza",
            limit=3,
        )

        self.assertEqual(summary[0]["label"], "Aseguradora")
        self.assertEqual(summary[1]["label"], "Numero de poliza")
        self.assertEqual(summary[2]["value"], "24/04/2026")

    def test_unknown_document_type_falls_back_to_humanized_label(self):
        self.assertEqual(get_document_type_label(PROFILE_MARKETING, "respaldo_custom"), "Respaldo Custom")

    def test_custom_blueprints_override_profile_defaults(self):
        blueprints = get_document_blueprints(
            PROFILE_BROKER,
            custom_blueprints=[
                {
                    "key": "poliza",
                    "label": "Poliza premium",
                    "category": "Emision",
                    "description": "Blueprint ajustado por tenant.",
                    "storage_hint": "custom/{numero_poliza}/{filename}",
                    "metadata_fields": [{"key": "numero_poliza", "label": "Numero de poliza", "type": "text"}],
                },
                {
                    "key": "certificado",
                    "label": "Certificado",
                    "category": "Entrega",
                    "description": "Documento listo para compartir.",
                    "storage_hint": "custom/certificados/{numero_poliza}/{filename}",
                    "metadata_fields": [{"key": "numero_poliza", "label": "Numero de poliza", "type": "text"}],
                },
            ],
        )

        self.assertTrue(any(blueprint["key"] == "certificado" for blueprint in blueprints))
        self.assertEqual(next(blueprint["label"] for blueprint in blueprints if blueprint["key"] == "poliza"), "Poliza premium")

    def test_services_blueprints_include_contract_and_delivery_documents(self):
        blueprints = get_document_blueprints(PROFILE_SERVICIOS)

        self.assertTrue(any(blueprint["key"] == "contrato_servicio" for blueprint in blueprints))
        self.assertTrue(any(blueprint["key"] == "reporte_entrega" for blueprint in blueprints))

    def test_retail_blueprints_include_size_sheet_and_special_order(self):
        blueprints = get_document_blueprints(PROFILE_RETAIL_MODA)

        self.assertTrue(any(blueprint["key"] == "ficha_tallas" for blueprint in blueprints))
        self.assertTrue(any(blueprint["key"] == "pedido_apartado" for blueprint in blueprints))


class DocumentAccessAndChecklistTests(SimpleTestCase):
    def test_document_access_url_prefers_external_link(self):
        document = Document(storage_provider=Document.STORAGE_EXTERNAL, external_url="https://example.com/poliza.pdf")

        self.assertEqual(_build_document_access_url(document), "https://example.com/poliza.pdf")

    def test_document_expiry_status_marks_expiring_soon(self):
        document = Document(expires_on=date(2026, 5, 5))

        status = _document_expiry_status(document, today=date(2026, 4, 25))

        self.assertTrue(status["is_expiring_soon"])
        self.assertIn("Vence", status["label"])

    def test_broker_document_checklist_requires_vehicle_docs_when_plate_exists(self):
        entity = SimpleNamespace(data_extra={"placa": "ABC-123"})
        documents = [
            SimpleNamespace(document_type="poliza"),
            SimpleNamespace(document_type="cedula"),
        ]

        checklist = _build_broker_document_checklist(
            entity,
            documents,
            blueprint_map={
                "poliza": {"label": "Poliza"},
                "cedula": {"label": "Cedula"},
                "matricula": {"label": "Matricula"},
                "inspeccion": {"label": "Inspeccion"},
            },
        )

        missing = [item["label"] for item in checklist if not item["is_present"]]

        self.assertIn("Matricula", missing)
        self.assertIn("Inspeccion", missing)


class DemoSeedScenarioTests(SimpleTestCase):
    def test_general_demo_scenario_uses_current_entity_fields(self):
        tenant = SimpleNamespace(
            entity_fields=[
                {"key": "city", "label": "Ciudad", "type": "text"},
                {"key": "reference", "label": "Referencia", "type": "text"},
            ],
            tenant_config=SimpleNamespace(profile="general"),
        )

        scenario = build_demo_scenario(tenant)

        self.assertEqual(scenario["entities"][0]["extra"]["city"], "Guayaquil")
        self.assertEqual(scenario["entities"][0]["extra"]["reference"], "Referida por Andrea Leon")
        self.assertEqual(scenario["stale_deal_key"], "deal-carlos")
        self.assertEqual(scenario["cold_entity_key"], "andres-ponce")
        self.assertEqual(scenario["object_records"], [])

    def test_broker_demo_scenario_includes_documents_and_collections(self):
        tenant = SimpleNamespace(
            entity_fields=[
                {"key": "placa", "label": "Placa", "type": "text"},
                {"key": "aseguradora", "label": "Aseguradora", "type": "text"},
                {"key": "poliza", "label": "Numero de poliza", "type": "text"},
            ],
            tenant_config=SimpleNamespace(profile=PROFILE_BROKER),
        )

        scenario = build_demo_scenario(tenant)

        self.assertTrue(any(item["document_type"] == "poliza" for item in scenario["documents"]))
        self.assertTrue(any(item["reference"] == "ELR-BRK-COB-001" for item in scenario["collections"]))
        self.assertTrue(any(item["object_key"] == "poliza_detalle" for item in scenario["object_records"]))

    def test_servicios_demo_scenario_includes_entregables(self):
        tenant = SimpleNamespace(
            entity_fields=[
                {"key": "empresa", "label": "Empresa", "type": "text"},
                {"key": "servicio_principal", "label": "Servicio principal", "type": "text"},
            ],
            tenant_config=SimpleNamespace(profile=PROFILE_SERVICIOS),
        )

        scenario = build_demo_scenario(tenant)

        self.assertTrue(any(item["object_key"] == "entregable" for item in scenario["object_records"]))
