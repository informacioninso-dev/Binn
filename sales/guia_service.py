"""
Servicio de guías de remisión electrónicas para Ecuador (SRI).
Genera guías, XML, clave de acceso y RIDE PDF.
"""
import random
from django.db import transaction
from django.utils import timezone
from django.core.exceptions import ValidationError

from .invoice_service import generate_access_key, ID_TYPE_MAP


def _generate_sequential(establishment, emission_point):
    """Genera el siguiente secuencial para guías de remisión."""
    from .models import GuiaRemision
    last = (
        GuiaRemision.objects
        .filter(establishment=establishment, emission_point=emission_point)
        .order_by("-sequential")
        .values_list("sequential", flat=True)
        .first()
    )
    seq = int(last) + 1 if last else 1
    return f"{seq:09d}"


@transaction.atomic
def create_guia(*, dispatch, carrier, transport_start_date, transport_end_date,
                transfer_reason="Venta", route="", supporting_invoice=None, user):
    """
    Crea guía de remisión desde un despacho.
    """
    from .models import GuiaRemision, GuiaRemisionLine, GuiaRemisionStatus
    from core.models import CompanyConfig

    if not carrier.is_carrier:
        raise ValidationError("El partner seleccionado debe ser transportista.")

    config = CompanyConfig.get()
    if not config:
        raise ValidationError("Configure los datos de la empresa antes de generar guías.")

    sequential = _generate_sequential(config.establishment_code, config.emission_point)

    order = dispatch.order
    client = order.client
    recipient_id_type = ID_TYPE_MAP.get(client.identification_type, "07")
    carrier_id_type = ID_TYPE_MAP.get(carrier.identification_type, "04")

    now = timezone.localtime()
    numeric_code = f"{random.randint(10000000, 99999999)}"

    access_key = generate_access_key(
        date=now,
        doc_type="06",  # 06 = Guía de Remisión
        ruc=config.ruc,
        environment=config.environment,
        establishment=config.establishment_code,
        emission_point=config.emission_point,
        sequential=sequential,
        numeric_code=numeric_code,
    )

    # Documento de sustento (factura si existe)
    supporting_doc_number = ""
    supporting_doc_authorization = ""
    supporting_doc_date = None
    if supporting_invoice:
        supporting_doc_number = supporting_invoice.full_number
        supporting_doc_authorization = (
            supporting_invoice.authorization_number or supporting_invoice.access_key
        )
        supporting_doc_date = supporting_invoice.issue_date.date()

    guia = GuiaRemision.objects.create(
        dispatch=dispatch,
        order=order,
        establishment=config.establishment_code,
        emission_point=config.emission_point,
        sequential=sequential,
        access_key=access_key,
        carrier=carrier,
        carrier_legal_name=carrier.legal_name or carrier.trade_name,
        carrier_identification_type=carrier_id_type,
        carrier_identification=carrier.identification,
        vehicle_plate=carrier.vehicle_plate or "",
        driver_name=carrier.driver_name or "",
        driver_identification=carrier.driver_identification or "",
        transport_start_date=transport_start_date,
        transport_end_date=transport_end_date,
        recipient_identification_type=recipient_id_type,
        recipient_identification=client.identification,
        recipient_legal_name=client.legal_name or client.trade_name,
        recipient_address=client.address or "",
        origin_address=config.address,
        transfer_reason=transfer_reason,
        route=route,
        supporting_doc_type="01",
        supporting_doc_number=supporting_doc_number,
        supporting_doc_authorization=supporting_doc_authorization,
        supporting_doc_date=supporting_doc_date,
        status=GuiaRemisionStatus.DRAFT,
        created_by=user,
        updated_by=user,
    )

    # Líneas desde dispatch
    for dline in dispatch.lines.select_related("product"):
        GuiaRemisionLine.objects.create(
            guia=guia,
            product=dline.product,
            description=dline.product.name,
            quantity=dline.quantity,
            created_by=user,
            updated_by=user,
        )

    # Generar XML
    xml = generate_guia_xml(guia)
    guia.xml_unsigned = xml
    guia.save(update_fields=["xml_unsigned"])

    return guia


def generate_guia_xml(guia):
    """Genera XML de guía de remisión según esquema SRI v1.1.0."""
    from core.models import CompanyConfig
    import xml.etree.ElementTree as ET

    config = CompanyConfig.get()

    root = ET.Element("guiaRemision", id="comprobante", version="1.1.0")

    # ─── infoTributaria
    info_trib = ET.SubElement(root, "infoTributaria")
    ET.SubElement(info_trib, "ambiente").text = config.environment
    ET.SubElement(info_trib, "tipoEmision").text = config.emission_type
    ET.SubElement(info_trib, "razonSocial").text = config.legal_name
    if config.trade_name:
        ET.SubElement(info_trib, "nombreComercial").text = config.trade_name
    ET.SubElement(info_trib, "ruc").text = config.ruc
    ET.SubElement(info_trib, "claveAcceso").text = guia.access_key
    ET.SubElement(info_trib, "codDoc").text = "06"
    ET.SubElement(info_trib, "estab").text = guia.establishment
    ET.SubElement(info_trib, "ptoEmi").text = guia.emission_point
    ET.SubElement(info_trib, "secuencial").text = guia.sequential
    ET.SubElement(info_trib, "dirMatriz").text = config.address

    # ─── infoGuiaRemision
    info_guia = ET.SubElement(root, "infoGuiaRemision")
    ET.SubElement(info_guia, "dirEstablecimiento").text = config.address
    ET.SubElement(info_guia, "dirPartida").text = guia.origin_address
    ET.SubElement(info_guia, "razonSocialTransportista").text = guia.carrier_legal_name
    ET.SubElement(info_guia, "tipoIdentificacionTransportista").text = guia.carrier_identification_type
    ET.SubElement(info_guia, "rucTransportista").text = guia.carrier_identification
    ET.SubElement(info_guia, "obligadoContabilidad").text = (
        "SI" if config.obligated_accounting else "NO"
    )
    if config.special_taxpayer:
        ET.SubElement(info_guia, "contribuyenteEspecial").text = config.special_taxpayer
    ET.SubElement(info_guia, "fechaIniTransporte").text = guia.transport_start_date.strftime("%d/%m/%Y")
    ET.SubElement(info_guia, "fechaFinTransporte").text = guia.transport_end_date.strftime("%d/%m/%Y")
    ET.SubElement(info_guia, "placa").text = guia.vehicle_plate

    # ─── destinatarios
    destinatarios = ET.SubElement(root, "destinatarios")
    dest = ET.SubElement(destinatarios, "destinatario")
    ET.SubElement(dest, "identificacionDestinatario").text = guia.recipient_identification
    ET.SubElement(dest, "razonSocialDestinatario").text = guia.recipient_legal_name
    ET.SubElement(dest, "dirDestinatario").text = guia.recipient_address
    ET.SubElement(dest, "motivoTraslado").text = guia.transfer_reason
    if guia.route:
        ET.SubElement(dest, "ruta").text = guia.route

    if guia.supporting_doc_number:
        ET.SubElement(dest, "codDocSustento").text = guia.supporting_doc_type
        ET.SubElement(dest, "numDocSustento").text = guia.supporting_doc_number
        ET.SubElement(dest, "numAutDocSustento").text = guia.supporting_doc_authorization
        if guia.supporting_doc_date:
            ET.SubElement(dest, "fechaEmisionDocSustento").text = (
                guia.supporting_doc_date.strftime("%d/%m/%Y")
            )

    detalles = ET.SubElement(dest, "detalles")
    for line in guia.lines.select_related("product"):
        det = ET.SubElement(detalles, "detalle")
        ET.SubElement(det, "codigoInterno").text = line.product.code
        ET.SubElement(det, "descripcion").text = line.description
        ET.SubElement(det, "cantidad").text = str(line.quantity)

    # ─── infoAdicional
    info_adicional = ET.SubElement(root, "infoAdicional")
    if guia.driver_name:
        campo = ET.SubElement(info_adicional, "campoAdicional", nombre="Conductor")
        campo.text = guia.driver_name
    if guia.driver_identification:
        campo = ET.SubElement(info_adicional, "campoAdicional", nombre="Cédula Conductor")
        campo.text = guia.driver_identification
    campo = ET.SubElement(info_adicional, "campoAdicional", nombre="Pedido")
    campo.text = guia.order.code
    campo = ET.SubElement(info_adicional, "campoAdicional", nombre="Despacho")
    campo.text = guia.dispatch.code

    ET.indent(root)
    return ET.tostring(root, encoding="unicode", xml_declaration=True)


def generate_guia_ride_pdf(guia):
    """Genera el RIDE (PDF) de la guía de remisión usando xhtml2pdf."""
    import io
    from django.template.loader import render_to_string
    from xhtml2pdf import pisa
    from core.models import CompanyConfig

    config = CompanyConfig.get()
    context = {
        "guia": guia,
        "config": config,
        "lines": guia.lines.select_related("product").all(),
    }
    html_string = render_to_string("sales/guia_ride.html", context)
    buffer = io.BytesIO()
    pisa.CreatePDF(io.StringIO(html_string), dest=buffer)
    return buffer.getvalue()
