from datetime import date
from types import SimpleNamespace

from django.test import SimpleTestCase

from .models import Activity, CollectionRecord, ObjectRecord
from .views import (
    _broker_policy_status,
    _build_broker_entity_summary,
    _build_broker_policy_report_item,
    _collect_broker_due_policy_records,
    _matching_broker_policy_records,
)


class BrokerVerticalHelperTests(SimpleTestCase):
    def test_matching_broker_policy_records_uses_entity_and_document_tokens(self):
        entity = SimpleNamespace(
            full_name="Laura Perez",
            legal_id="0912345678",
            data_extra={"placa": "ABC-123", "poliza": "AUTO-77", "aseguradora": "Latina Seguros"},
        )
        policy_from_entity = ObjectRecord(title="Auto principal", data={"numero_poliza": "AUTO-77"})
        policy_from_document = ObjectRecord(title="RC flota", data={"numero_poliza": "RC-889"})
        other_policy = ObjectRecord(title="Hogar", data={"numero_poliza": "HOME-001"})

        matches = _matching_broker_policy_records(
            entity,
            [policy_from_entity, policy_from_document, other_policy],
            documents=[SimpleNamespace(metadata={"numero_poliza": "RC-889"})],
        )

        self.assertEqual(matches, [policy_from_entity, policy_from_document])

    def test_broker_policy_status_flags_expired_and_expiring_records(self):
        expired = ObjectRecord(data={"vigencia_hasta": "2026-07-01"})
        expiring = ObjectRecord(data={"vigencia_hasta": "2026-08-05"})
        active = ObjectRecord(data={"vigencia_hasta": "2026-10-01"})

        expired_status = _broker_policy_status(expired, today=date(2026, 7, 30))
        expiring_status = _broker_policy_status(expiring, today=date(2026, 7, 30))
        active_status = _broker_policy_status(active, today=date(2026, 7, 30))

        self.assertTrue(expired_status["is_expired"])
        self.assertFalse(expired_status["is_expiring_soon"])
        self.assertEqual(expiring_status["label"], "Vence 05/08/2026")
        self.assertTrue(expiring_status["is_expiring_soon"])
        self.assertEqual(active_status["label"], "Vigente hasta 01/10/2026")
        self.assertEqual(active_status["tone"], "bg-green-50 text-green-700")

    def test_collect_broker_due_policy_records_orders_by_expiry(self):
        expired = ObjectRecord(title="Expirada", data={"vigencia_hasta": "2026-07-15"})
        expiring = ObjectRecord(title="Por vencer", data={"vigencia_hasta": "2026-08-10"})
        far_future = ObjectRecord(title="Lejana", data={"vigencia_hasta": "2026-10-30"})
        no_date = ObjectRecord(title="Sin fecha", data={})

        records = _collect_broker_due_policy_records(
            [expiring, no_date, far_future, expired],
            today=date(2026, 7, 30),
            window_days=45,
        )

        self.assertEqual(records, [expired, expiring])

    def test_build_broker_policy_report_item_includes_status_and_prima(self):
        policy_record = ObjectRecord(
            pk=7,
            title="Poliza auto",
            data={
                "numero_poliza": "AUTO-77",
                "producto": "Auto",
                "aseguradora": "Latina Seguros",
                "vigencia_hasta": "2026-08-12",
                "prima": "1,260.50",
            },
        )

        item = _build_broker_policy_report_item(
            policy_record,
            today=date(2026, 7, 30),
            href="/objects/poliza_detalle/7/",
            cta="Abrir poliza",
        )

        self.assertEqual(item["status"], "Poliza")
        self.assertEqual(item["meta"], "Auto | Latina Seguros")
        self.assertIn("Vence 12/08/2026", item["caption"])
        self.assertIn("USD 1,260.50", item["caption"])
        self.assertEqual(item["href"], "/objects/poliza_detalle/7/")
        self.assertEqual(item["cta"], "Abrir poliza")

    def test_build_broker_entity_summary_surfaces_claims_collections_and_checklist(self):
        entity = SimpleNamespace(
            full_name="Laura Perez",
            legal_id="0912345678",
            data_extra={"placa": "ABC-123", "poliza": "AUTO-77"},
        )
        policy_record = ObjectRecord(
            data={
                "numero_poliza": "AUTO-77",
                "vigencia_hasta": "2026-08-10",
                "prima": "485.00",
            }
        )
        collection = SimpleNamespace(
            status=CollectionRecord.STATUS_PENDING,
            due_on=date(2026, 7, 20),
            balance=150,
            currency="USD",
        )

        summary = _build_broker_entity_summary(
            entity,
            policy_records=[policy_record],
            documents=[
                SimpleNamespace(document_type="poliza"),
                SimpleNamespace(document_type="cedula"),
            ],
            activities=[SimpleNamespace(activity_type=Activity.TYPE_CLAIM, completed_at=None)],
            collections=[collection],
            blueprint_map={
                "poliza": {"label": "Poliza"},
                "cedula": {"label": "Cedula"},
                "matricula": {"label": "Matricula"},
                "inspeccion": {"label": "Inspeccion"},
            },
            today=date(2026, 7, 30),
        )

        items = {item["label"]: item for item in summary}

        self.assertEqual(items["Polizas visibles"]["value"], "1")
        self.assertEqual(items["Proxima vigencia"]["value"], "Vence 10/08/2026")
        self.assertEqual(items["Prima visible"]["value"], "USD 485")
        self.assertEqual(items["Siniestros abiertos"]["value"], "1")
        self.assertEqual(items["Cobranza vencida"]["value"], "USD 150")
        self.assertEqual(items["Checklist"]["value"], "2/4 completos")
