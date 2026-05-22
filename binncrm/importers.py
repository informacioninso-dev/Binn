import csv
import io
import re
import unicodedata
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from .models import Entity
from .object_engine import get_entity_field_definitions


ENTITY_HEADER_ALIASES = {
    "full_name": "full_name",
    "nombre": "full_name",
    "nombres": "full_name",
    "cliente": "full_name",
    "contacto": "full_name",
    "name": "full_name",
    "legal_id": "legal_id",
    "identificacion": "legal_id",
    "identificacion_o_ruc": "legal_id",
    "cedula": "legal_id",
    "ruc": "legal_id",
    "documento": "legal_id",
    "phone": "phone",
    "telefono": "phone",
    "celular": "phone",
    "movil": "phone",
    "whatsapp": "phone",
    "email": "email",
    "correo": "email",
    "correo_electronico": "email",
    "mail": "email",
    "notes": "notes",
    "notas": "notes",
    "observaciones": "notes",
    "comentarios": "notes",
    "is_active": "is_active",
    "activo": "is_active",
    "active": "is_active",
}


def _normalize_header(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", str(value or ""))
    normalized = normalized.encode("ascii", "ignore").decode("ascii")
    normalized = normalized.strip().lower()
    normalized = re.sub(r"[^a-z0-9]+", "_", normalized)
    return normalized.strip("_")


def _normalize_phone(value: str) -> str:
    return re.sub(r"\D", "", value or "")


def _parse_bool(value: str) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "si", "sí", "yes", "y", "activo"}


def _decode_uploaded_csv(uploaded_file) -> str:
    raw = uploaded_file.read()
    if isinstance(raw, str):
        return raw
    for encoding in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ValueError("No se pudo leer el archivo CSV con una codificacion soportada.")


def _build_dynamic_aliases(entity_fields: list[dict]) -> dict[str, str]:
    aliases: dict[str, str] = {}
    for field in entity_fields:
        key = field["key"]
        aliases[_normalize_header(key)] = key
        aliases[_normalize_header(field.get("label", key))] = key
    return aliases


def _convert_dynamic_value(raw_value, field_definition: dict):
    value = (raw_value or "").strip()
    if value == "":
        return ""
    field_type = field_definition.get("type", "text")
    if field_type == "boolean":
        return _parse_bool(value)
    if field_type == "number":
        try:
            return Decimal(value.replace(",", ""))
        except InvalidOperation:
            return value
    if field_type == "date":
        for parser in (date.fromisoformat, datetime.fromisoformat):
            try:
                parsed = parser(value)
                return parsed.isoformat() if isinstance(parsed, datetime) else parsed.isoformat()
            except ValueError:
                continue
    return value


def _find_existing_entity(mapped_data: dict) -> Entity | None:
    legal_id = (mapped_data.get("legal_id") or "").strip()
    email = (mapped_data.get("email") or "").strip()
    phone = _normalize_phone(mapped_data.get("phone") or "")

    if legal_id:
        match = Entity.objects.filter(legal_id__iexact=legal_id).first()
        if match is not None:
            return match
    if email:
        match = Entity.objects.filter(email__iexact=email).first()
        if match is not None:
            return match
    if phone:
        for candidate in Entity.objects.exclude(phone="").only("id", "phone"):
            if _normalize_phone(candidate.phone) == phone:
                return candidate
    return None


def import_entities_from_csv(uploaded_file, *, tenant, actor=None, update_existing: bool = True) -> dict:
    csv_text = _decode_uploaded_csv(uploaded_file)
    if not csv_text.strip():
        raise ValueError("El archivo CSV esta vacio.")

    sample = csv_text[:2048]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;|\t")
    except csv.Error:
        dialect = csv.excel

    reader = csv.DictReader(io.StringIO(csv_text), dialect=dialect)
    if not reader.fieldnames:
        raise ValueError("No se encontraron encabezados en el archivo CSV.")

    entity_fields = get_entity_field_definitions(tenant=tenant)
    dynamic_map = {field["key"]: field for field in entity_fields}
    dynamic_aliases = _build_dynamic_aliases(entity_fields)

    created = 0
    updated = 0
    skipped = 0
    processed = 0
    error_rows: list[dict] = []

    for row_number, raw_row in enumerate(reader, start=2):
        if raw_row is None:
            continue
        if not any(str(value or "").strip() for value in raw_row.values()):
            continue

        processed += 1
        mapped_data = {}
        extra_data = {}

        for header, raw_value in raw_row.items():
            normalized_header = _normalize_header(header)
            if not normalized_header:
                continue

            target = ENTITY_HEADER_ALIASES.get(normalized_header)
            if target:
                value = (raw_value or "").strip()
                if target == "is_active":
                    mapped_data[target] = _parse_bool(value)
                else:
                    mapped_data[target] = value
                continue

            if normalized_header.startswith("extra__"):
                normalized_header = normalized_header.split("extra__", 1)[1]
            elif normalized_header.startswith("data_extra__"):
                normalized_header = normalized_header.split("data_extra__", 1)[1]

            dynamic_key = dynamic_aliases.get(normalized_header)
            if dynamic_key and dynamic_key in dynamic_map:
                extra_data[dynamic_key] = _convert_dynamic_value(raw_value, dynamic_map[dynamic_key])

        full_name = (mapped_data.get("full_name") or "").strip()
        if not full_name:
            error_rows.append({"row_number": row_number, "message": "Falta la columna nombre/full_name."})
            skipped += 1
            continue

        entity = _find_existing_entity(mapped_data)
        if entity is not None and not update_existing:
            skipped += 1
            continue

        entity = entity or Entity()
        is_update = entity.pk is not None
        entity.full_name = full_name
        entity.legal_id = mapped_data.get("legal_id", entity.legal_id)
        entity.phone = mapped_data.get("phone", entity.phone)
        entity.email = mapped_data.get("email", entity.email)
        entity.notes = mapped_data.get("notes", entity.notes)
        entity.is_active = mapped_data.get("is_active", entity.is_active if is_update else True)
        entity.data_extra = {**(entity.data_extra or {}), **extra_data}
        if is_update:
            entity.updated_by = actor
        else:
            entity.created_by = actor
            entity.updated_by = actor
        entity.save()

        if is_update:
            updated += 1
        else:
            created += 1

    return {
        "headers": list(reader.fieldnames),
        "processed": processed,
        "created": created,
        "updated": updated,
        "skipped": skipped,
        "error_rows": error_rows[:20],
        "error_count": len(error_rows),
    }
