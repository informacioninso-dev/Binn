from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime
from decimal import Decimal

from tenants.defaults import (
    PROFILE_BROKER,
    PROFILE_CONDOMINIO,
    PROFILE_GENERAL,
    PROFILE_MARKETING,
    PROFILE_RETAIL_MODA,
    PROFILE_SERVICIOS,
)


_GENERAL_DOCUMENT_BLUEPRINTS = [
    {
        "key": "general",
        "label": "Documento general",
        "category": "Soporte",
        "description": "Archivo libre para respaldo operativo o evidencia puntual.",
        "storage_hint": "general/{entity}/{filename}",
        "metadata_fields": [
            {"key": "referencia", "label": "Referencia", "type": "text"},
            {"key": "notas", "label": "Notas", "type": "text"},
        ],
    }
]

_PROFILE_DOCUMENT_BLUEPRINTS = {
    PROFILE_GENERAL: [],
    PROFILE_CONDOMINIO: [
        {
            "key": "contrato_residente",
            "label": "Contrato de residente",
            "category": "Legal",
            "description": "Contrato o convenio principal firmado por el residente.",
            "storage_hint": "condominio/contratos/{departamento}/{filename}",
            "metadata_fields": [
                {"key": "departamento", "label": "Departamento", "type": "text"},
                {"key": "vigencia_desde", "label": "Vigencia desde", "type": "date"},
                {"key": "vigencia_hasta", "label": "Vigencia hasta", "type": "date"},
            ],
        },
        {
            "key": "estado_cuenta",
            "label": "Estado de cuenta",
            "category": "Cartera",
            "description": "Estado de obligaciones para recaudacion y seguimiento.",
            "storage_hint": "condominio/cartera/{departamento}/{periodo}.pdf",
            "metadata_fields": [
                {"key": "periodo", "label": "Periodo", "type": "text"},
                {"key": "saldo", "label": "Saldo", "type": "number"},
                {"key": "vencimiento", "label": "Vencimiento", "type": "date"},
            ],
        },
        {
            "key": "comprobante_pago",
            "label": "Comprobante de pago",
            "category": "Recaudacion",
            "description": "Evidencia del pago realizado por el residente.",
            "storage_hint": "condominio/pagos/{departamento}/{fecha}.pdf",
            "metadata_fields": [
                {"key": "monto", "label": "Monto", "type": "number"},
                {"key": "fecha_pago", "label": "Fecha de pago", "type": "date"},
                {"key": "referencia", "label": "Referencia", "type": "text"},
            ],
        },
    ],
    PROFILE_BROKER: [
        {
            "key": "poliza",
            "label": "Poliza",
            "category": "Emision",
            "description": "Documento principal de cobertura listo para renovacion o entrega.",
            "storage_hint": "broker/polizas/{numero_poliza}/{filename}",
            "metadata_fields": [
                {"key": "aseguradora", "label": "Aseguradora", "type": "text"},
                {"key": "numero_poliza", "label": "Numero de poliza", "type": "text"},
                {"key": "vigencia_desde", "label": "Vigencia desde", "type": "date"},
                {"key": "vigencia_hasta", "label": "Vigencia hasta", "type": "date"},
                {"key": "ramo", "label": "Ramo", "type": "text"},
            ],
        },
        {
            "key": "cedula",
            "label": "Cedula o RUC",
            "category": "Identificacion",
            "description": "Documento de identidad del asegurado o del titular.",
            "storage_hint": "broker/identidad/{legal_id}/{filename}",
            "metadata_fields": [
                {"key": "titular", "label": "Titular", "type": "text"},
                {"key": "identificacion", "label": "Identificacion", "type": "text"},
            ],
        },
        {
            "key": "matricula",
            "label": "Matricula",
            "category": "Vehiculo",
            "description": "Soporte vehicular para emisiones y renovaciones automotrices.",
            "storage_hint": "broker/vehiculos/{placa}/{filename}",
            "metadata_fields": [
                {"key": "placa", "label": "Placa", "type": "text"},
                {"key": "chasis", "label": "Chasis", "type": "text"},
                {"key": "anio", "label": "Anio", "type": "number"},
            ],
        },
        {
            "key": "inspeccion",
            "label": "Inspeccion",
            "category": "Inspeccion",
            "description": "Resultado de inspeccion previa a la emision o renovacion.",
            "storage_hint": "broker/inspecciones/{placa}/{fecha}.pdf",
            "metadata_fields": [
                {"key": "placa", "label": "Placa", "type": "text"},
                {"key": "fecha_inspeccion", "label": "Fecha de inspeccion", "type": "date"},
                {"key": "estado", "label": "Estado", "type": "text"},
            ],
        },
        {
            "key": "comprobante_pago",
            "label": "Comprobante de pago",
            "category": "Cobranza",
            "description": "Soporte de pago de prima, renovacion o abono.",
            "storage_hint": "broker/pagos/{numero_poliza}/{fecha}.pdf",
            "metadata_fields": [
                {"key": "valor", "label": "Valor", "type": "number"},
                {"key": "fecha_pago", "label": "Fecha de pago", "type": "date"},
                {"key": "referencia", "label": "Referencia", "type": "text"},
            ],
        },
    ],
    PROFILE_MARKETING: [
        {
            "key": "brief",
            "label": "Brief",
            "category": "Discovery",
            "description": "Documento de contexto para discovery, tono y alcance inicial.",
            "storage_hint": "marketing/briefs/{empresa}/{filename}",
            "metadata_fields": [
                {"key": "empresa", "label": "Empresa", "type": "text"},
                {"key": "campana", "label": "Campana", "type": "text"},
                {"key": "objetivo", "label": "Objetivo", "type": "text"},
            ],
        },
        {
            "key": "propuesta",
            "label": "Propuesta",
            "category": "Comercial",
            "description": "Propuesta presentada al lead u oportunidad.",
            "storage_hint": "marketing/propuestas/{empresa}/{filename}",
            "metadata_fields": [
                {"key": "empresa", "label": "Empresa", "type": "text"},
                {"key": "monto", "label": "Monto", "type": "number"},
                {"key": "vigencia_hasta", "label": "Vigencia hasta", "type": "date"},
            ],
        },
        {
            "key": "media_plan",
            "label": "Media plan",
            "category": "Planificacion",
            "description": "Plan de pauta, canales y presupuesto aprobado.",
            "storage_hint": "marketing/media-plan/{campana}/{filename}",
            "metadata_fields": [
                {"key": "campana", "label": "Campana", "type": "text"},
                {"key": "presupuesto", "label": "Presupuesto", "type": "number"},
                {"key": "periodo", "label": "Periodo", "type": "text"},
            ],
        },
        {
            "key": "reporte_campana",
            "label": "Reporte de campana",
            "category": "Performance",
            "description": "Resultado de campana para seguimiento y renovacion.",
            "storage_hint": "marketing/reportes/{campana}/{periodo}.pdf",
            "metadata_fields": [
                {"key": "campana", "label": "Campana", "type": "text"},
                {"key": "periodo", "label": "Periodo", "type": "text"},
                {"key": "resultado", "label": "Resultado clave", "type": "text"},
            ],
        },
    ],
    PROFILE_SERVICIOS: [
        {
            "key": "propuesta_servicio",
            "label": "Propuesta de servicio",
            "category": "Comercial",
            "description": "Documento base de alcance, valor y vigencia para clientes B2B.",
            "storage_hint": "servicios/propuestas/{empresa}/{filename}",
            "metadata_fields": [
                {"key": "empresa", "label": "Empresa", "type": "text"},
                {"key": "servicio_principal", "label": "Servicio principal", "type": "text"},
                {"key": "vigencia_hasta", "label": "Vigencia hasta", "type": "date"},
            ],
        },
        {
            "key": "contrato_servicio",
            "label": "Contrato de servicio",
            "category": "Legal",
            "description": "Contrato firmado o listo para formalizar el proyecto.",
            "storage_hint": "servicios/contratos/{empresa}/{filename}",
            "metadata_fields": [
                {"key": "empresa", "label": "Empresa", "type": "text"},
                {"key": "fecha_inicio", "label": "Fecha de inicio", "type": "date"},
                {"key": "fecha_fin", "label": "Fecha de fin", "type": "date"},
            ],
        },
        {
            "key": "kickoff",
            "label": "Kickoff",
            "category": "Entrega",
            "description": "Acta o resumen inicial para alinear alcance y responsables.",
            "storage_hint": "servicios/kickoff/{empresa}/{fecha}.pdf",
            "metadata_fields": [
                {"key": "empresa", "label": "Empresa", "type": "text"},
                {"key": "responsable", "label": "Responsable", "type": "text"},
                {"key": "fecha", "label": "Fecha", "type": "date"},
            ],
        },
        {
            "key": "reporte_entrega",
            "label": "Reporte de entrega",
            "category": "Operacion",
            "description": "Documento de avance o entrega para renovacion y upsell.",
            "storage_hint": "servicios/reportes/{empresa}/{periodo}.pdf",
            "metadata_fields": [
                {"key": "empresa", "label": "Empresa", "type": "text"},
                {"key": "periodo", "label": "Periodo", "type": "text"},
                {"key": "resultado", "label": "Resultado", "type": "text"},
            ],
        },
    ],
    PROFILE_RETAIL_MODA: [
        {
            "key": "ficha_tallas",
            "label": "Ficha de tallas",
            "category": "Cliente",
            "description": "Registro de tallas y preferencias del cliente frecuente.",
            "storage_hint": "retail/clientes/{entity}/tallas/{filename}",
            "metadata_fields": [
                {"key": "talla_superior", "label": "Talla superior", "type": "text"},
                {"key": "talla_inferior", "label": "Talla inferior", "type": "text"},
                {"key": "preferencia", "label": "Preferencia", "type": "text"},
            ],
        },
        {
            "key": "pedido_apartado",
            "label": "Pedido apartado",
            "category": "Venta",
            "description": "Soporte de apartado o pedido especial del cliente.",
            "storage_hint": "retail/apartados/{entity}/{fecha}.pdf",
            "metadata_fields": [
                {"key": "fecha", "label": "Fecha", "type": "date"},
                {"key": "monto", "label": "Monto", "type": "number"},
                {"key": "canal", "label": "Canal", "type": "text"},
            ],
        },
        {
            "key": "comprobante_entrega",
            "label": "Comprobante de entrega",
            "category": "Entrega",
            "description": "Evidencia de entrega o retiro para el pedido del cliente.",
            "storage_hint": "retail/entregas/{entity}/{fecha}.pdf",
            "metadata_fields": [
                {"key": "fecha", "label": "Fecha", "type": "date"},
                {"key": "canal", "label": "Canal", "type": "text"},
                {"key": "vendedor", "label": "Vendedor", "type": "text"},
            ],
        },
    ],
}


def get_document_blueprints(profile: str, *, custom_blueprints: list[dict] | None = None) -> list[dict]:
    blueprints: list[dict] = []
    blueprint_positions: dict[str, int] = {}
    for collection in (
        _GENERAL_DOCUMENT_BLUEPRINTS,
        _PROFILE_DOCUMENT_BLUEPRINTS.get(profile or "", []),
        custom_blueprints or [],
    ):
        for blueprint in collection:
            resolved = deepcopy(blueprint)
            key = resolved["key"]
            if key in blueprint_positions:
                blueprints[blueprint_positions[key]] = resolved
                continue
            blueprint_positions[key] = len(blueprints)
            blueprints.append(resolved)
    return blueprints


def get_document_blueprint_map(profile: str, *, custom_blueprints: list[dict] | None = None) -> dict[str, dict]:
    return {
        blueprint["key"]: blueprint
        for blueprint in get_document_blueprints(profile, custom_blueprints=custom_blueprints)
    }


def build_document_type_choices(profile: str, *, custom_blueprints: list[dict] | None = None) -> list[tuple[str, str]]:
    return [
        (blueprint["key"], blueprint["label"])
        for blueprint in get_document_blueprints(profile, custom_blueprints=custom_blueprints)
    ]


def build_document_metadata_template(
    profile: str,
    document_type: str,
    *,
    custom_blueprints: list[dict] | None = None,
) -> dict:
    blueprint = get_document_blueprint_map(profile, custom_blueprints=custom_blueprints).get(document_type)
    if blueprint is None:
        return {}

    template = {}
    for field in blueprint.get("metadata_fields", []):
        default = field.get("default")
        if default is not None:
            template[field["key"]] = default
            continue
        template[field["key"]] = False if field.get("type") == "boolean" else ""
    return template


def build_document_metadata_summary(
    metadata: dict,
    *,
    profile: str,
    document_type: str,
    limit: int = 3,
    custom_blueprints: list[dict] | None = None,
) -> list[dict]:
    if not isinstance(metadata, dict):
        return []

    summary: list[dict] = []
    consumed_keys = set()
    blueprint = get_document_blueprint_map(profile, custom_blueprints=custom_blueprints).get(document_type, {})
    for field in blueprint.get("metadata_fields", []):
        key = field["key"]
        raw_value = metadata.get(key)
        if raw_value in (None, "", []):
            continue
        summary.append(
            {
                "key": key,
                "label": field["label"],
                "value": _format_metadata_value(raw_value, field.get("type", "text")),
            }
        )
        consumed_keys.add(key)
        if len(summary) >= limit:
            return summary

    for key, raw_value in metadata.items():
        if key in consumed_keys or raw_value in (None, "", []):
            continue
        summary.append(
            {
                "key": key,
                "label": str(key).replace("_", " ").title(),
                "value": _format_metadata_value(raw_value, "text"),
            }
        )
        if len(summary) >= limit:
            break
    return summary


def get_document_type_label(profile: str, document_type: str, *, custom_blueprints: list[dict] | None = None) -> str:
    blueprint = get_document_blueprint_map(profile, custom_blueprints=custom_blueprints).get(document_type)
    if blueprint:
        return blueprint["label"]
    return str(document_type or "general").replace("_", " ").replace("-", " ").title()


def _format_metadata_value(value, field_type: str) -> str:
    if field_type == "boolean":
        return "Si" if bool(value) else "No"
    if field_type == "date":
        if isinstance(value, datetime):
            return value.strftime("%d/%m/%Y")
        if isinstance(value, date):
            return value.strftime("%d/%m/%Y")
        try:
            return datetime.fromisoformat(str(value)).strftime("%d/%m/%Y")
        except ValueError:
            return str(value)
    if field_type == "number" and isinstance(value, (int, float, Decimal)):
        return str(value)
    return str(value)
