"""
Servicio de facturación electrónica para Ecuador (SRI).
Genera facturas, XML, clave de acceso y RIDE PDF.
"""
from decimal import Decimal, ROUND_HALF_UP
from datetime import datetime
from django.db import transaction
from django.utils import timezone
from django.core.exceptions import ValidationError


# Mapeo de IdentificationType del ERP a códigos SRI
ID_TYPE_MAP = {
    "RUC": "04",
    "DNI": "05",
    "PASSPORT": "06",
    "OTHER": "07",  # Consumidor final
}

# Mapeo de tasa IVA a código tarifa SRI
TAX_RATE_CODE_MAP = {
    Decimal("0.00"): "0",    # 0%
    Decimal("12.00"): "2",   # 12%
    Decimal("14.00"): "3",   # 14%
    Decimal("15.00"): "4",   # 15%
}


def _round2(value):
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _generate_sequential(establishment, emission_point):
    """Genera el siguiente secuencial para establecimiento+punto de emisión."""
    from .models import SaleInvoice
    last = (
        SaleInvoice.objects
        .filter(establishment=establishment, emission_point=emission_point)
        .order_by("-sequential")
        .values_list("sequential", flat=True)
        .first()
    )
    seq = int(last) + 1 if last else 1
    return f"{seq:09d}"


def _modulo11(access_key_48):
    """Calcula dígito verificador módulo 11 para la clave de acceso SRI."""
    weights = [2, 3, 4, 5, 6, 7]
    total = 0
    for i, digit in enumerate(reversed(access_key_48)):
        total += int(digit) * weights[i % len(weights)]
    remainder = total % 11
    if remainder == 0:
        return "0"
    elif remainder == 1:
        return "1"
    else:
        return str(11 - remainder)


def generate_access_key(*, date, doc_type, ruc, environment,
                        establishment, emission_point, sequential, numeric_code):
    """
    Genera clave de acceso de 49 dígitos para factura electrónica SRI.
    Formato: DDMMAAAA + tipoDoc(2) + RUC(13) + ambiente(1) + serie(6) + secuencial(9) + codigoNum(8) + tipoEmision(1) + digitoVerif(1)
    """
    date_str = date.strftime("%d%m%Y")  # 8 dígitos
    key_48 = (
        f"{date_str}"
        f"{doc_type:0>2}"
        f"{ruc}"
        f"{environment}"
        f"{establishment}{emission_point}"
        f"{sequential}"
        f"{numeric_code:0>8}"
        f"1"  # tipo emisión normal
    )
    digit = _modulo11(key_48)
    return key_48 + digit


@transaction.atomic
def create_invoice(*, order, user):
    """
    Crea factura desde un pedido despachado.
    Genera secuencial, clave de acceso, snapshot del comprador, calcula impuestos.
    """
    from .models import (
        SaleInvoice, SaleInvoiceLine, InvoiceStatus,
        SaleOrderStatus,
    )
    from core.models import CompanyConfig

    if order.status != SaleOrderStatus.DISPATCHED:
        raise ValidationError("Solo se puede facturar pedidos despachados.")

    config = CompanyConfig.get()
    if not config:
        raise ValidationError("Configure los datos de la empresa antes de facturar.")

    # Generar secuencial
    sequential = _generate_sequential(config.establishment_code, config.emission_point)

    # Datos del comprador (snapshot)
    client = order.client
    buyer_id_type = ID_TYPE_MAP.get(client.identification_type, "07")

    now = timezone.localtime()

    # Código numérico para clave de acceso (últimos 8 dígitos del secuencial + random)
    import random
    numeric_code = f"{random.randint(10000000, 99999999)}"

    access_key = generate_access_key(
        date=now,
        doc_type="01",  # 01 = Factura
        ruc=config.ruc,
        environment=config.environment,
        establishment=config.establishment_code,
        emission_point=config.emission_point,
        sequential=sequential,
        numeric_code=numeric_code,
    )

    # Buscar último despacho
    dispatch = order.dispatches.order_by("-dispatched_date").first()

    invoice = SaleInvoice.objects.create(
        order=order,
        dispatch=dispatch,
        establishment=config.establishment_code,
        emission_point=config.emission_point,
        sequential=sequential,
        access_key=access_key,
        buyer_identification_type=buyer_id_type,
        buyer_identification=client.identification,
        buyer_legal_name=client.legal_name or client.trade_name,
        buyer_address=client.address or "",
        buyer_email=client.contact_email or "",
        issue_date=now,
        status=InvoiceStatus.DRAFT,
        created_by=user,
        updated_by=user,
    )

    # Crear líneas con cálculo de impuestos
    subtotal_no_tax = Decimal("0")
    subtotal_iva = Decimal("0")
    total_iva = Decimal("0")
    total_discount = Decimal("0")

    for line in order.lines.select_related("product__tax_scheme"):
        product = line.product
        tax_rate = product.tax_scheme.rate if product.tax_scheme else Decimal("0")
        tax_rate_code = TAX_RATE_CODE_MAP.get(tax_rate, "0")

        subtotal = _round2(line.quantity * line.unit_price)
        tax_amount = _round2(subtotal * tax_rate / Decimal("100"))

        SaleInvoiceLine.objects.create(
            invoice=invoice,
            product=product,
            description=product.name,
            quantity=line.quantity,
            unit_price=line.unit_price,
            discount=Decimal("0"),
            subtotal=subtotal,
            tax_code="2",  # 2 = IVA
            tax_rate_code=tax_rate_code,
            tax_rate=tax_rate,
            tax_amount=tax_amount,
            created_by=user,
            updated_by=user,
        )

        if tax_rate > 0:
            subtotal_iva += subtotal
            total_iva += tax_amount
        else:
            subtotal_no_tax += subtotal

    invoice.subtotal_no_tax = _round2(subtotal_no_tax)
    invoice.subtotal_iva = _round2(subtotal_iva)
    invoice.iva_amount = _round2(total_iva)
    invoice.total_discount = _round2(total_discount)
    invoice.total_amount = _round2(subtotal_no_tax + subtotal_iva + total_iva)
    invoice.save()

    # Generar XML
    xml = generate_invoice_xml(invoice)
    invoice.xml_unsigned = xml
    invoice.save(update_fields=["xml_unsigned"])

    # Cambiar estado del pedido
    order.status = SaleOrderStatus.INVOICED
    order.save(update_fields=["status"])

    return invoice


def generate_invoice_xml(invoice):
    """Genera XML de factura según esquema SRI v1.1.0."""
    from core.models import CompanyConfig
    import xml.etree.ElementTree as ET

    config = CompanyConfig.get()

    root = ET.Element("factura", id="comprobante", version="1.1.0")

    # ─── infoTributaria ─────────────────────────────
    info_trib = ET.SubElement(root, "infoTributaria")
    ET.SubElement(info_trib, "ambiente").text = config.environment
    ET.SubElement(info_trib, "tipoEmision").text = config.emission_type
    ET.SubElement(info_trib, "razonSocial").text = config.legal_name
    if config.trade_name:
        ET.SubElement(info_trib, "nombreComercial").text = config.trade_name
    ET.SubElement(info_trib, "ruc").text = config.ruc
    ET.SubElement(info_trib, "claveAcceso").text = invoice.access_key
    ET.SubElement(info_trib, "codDoc").text = "01"  # Factura
    ET.SubElement(info_trib, "estab").text = invoice.establishment
    ET.SubElement(info_trib, "ptoEmi").text = invoice.emission_point
    ET.SubElement(info_trib, "secuencial").text = invoice.sequential
    ET.SubElement(info_trib, "dirMatriz").text = config.address

    # ─── infoFactura ────────────────────────────────
    info_fac = ET.SubElement(root, "infoFactura")
    ET.SubElement(info_fac, "fechaEmision").text = invoice.issue_date.strftime("%d/%m/%Y")
    ET.SubElement(info_fac, "dirEstablecimiento").text = config.address
    if config.special_taxpayer:
        ET.SubElement(info_fac, "contribuyenteEspecial").text = config.special_taxpayer
    ET.SubElement(info_fac, "obligadoContabilidad").text = "SI" if config.obligated_accounting else "NO"
    ET.SubElement(info_fac, "tipoIdentificacionComprador").text = invoice.buyer_identification_type
    ET.SubElement(info_fac, "razonSocialComprador").text = invoice.buyer_legal_name
    ET.SubElement(info_fac, "identificacionComprador").text = invoice.buyer_identification
    if invoice.buyer_address:
        ET.SubElement(info_fac, "direccionComprador").text = invoice.buyer_address
    ET.SubElement(info_fac, "totalSinImpuestos").text = str(invoice.subtotal_no_tax + invoice.subtotal_iva)
    ET.SubElement(info_fac, "totalDescuento").text = str(invoice.total_discount)

    # totalConImpuestos
    total_impuestos = ET.SubElement(info_fac, "totalConImpuestos")

    # Agrupar por tarifa
    tax_groups = {}
    for line in invoice.lines.all():
        key = (line.tax_code, line.tax_rate_code, line.tax_rate)
        if key not in tax_groups:
            tax_groups[key] = {"base": Decimal("0"), "valor": Decimal("0")}
        tax_groups[key]["base"] += line.subtotal
        tax_groups[key]["valor"] += line.tax_amount

    for (code, rate_code, rate), vals in tax_groups.items():
        ti = ET.SubElement(total_impuestos, "totalImpuesto")
        ET.SubElement(ti, "codigo").text = code
        ET.SubElement(ti, "codigoPorcentaje").text = rate_code
        ET.SubElement(ti, "baseImponible").text = str(_round2(vals["base"]))
        ET.SubElement(ti, "valor").text = str(_round2(vals["valor"]))

    ET.SubElement(info_fac, "propina").text = "0.00"
    ET.SubElement(info_fac, "importeTotal").text = str(invoice.total_amount)
    ET.SubElement(info_fac, "moneda").text = "DOLAR"

    # pagos
    pagos = ET.SubElement(info_fac, "pagos")
    pago = ET.SubElement(pagos, "pago")
    ET.SubElement(pago, "formaPago").text = "20"  # Otros con utilización del sistema financiero
    ET.SubElement(pago, "total").text = str(invoice.total_amount)

    # ─── detalles ───────────────────────────────────
    detalles = ET.SubElement(root, "detalles")
    for line in invoice.lines.select_related("product"):
        det = ET.SubElement(detalles, "detalle")
        ET.SubElement(det, "codigoPrincipal").text = line.product.code
        ET.SubElement(det, "descripcion").text = line.description
        ET.SubElement(det, "cantidad").text = str(line.quantity)
        ET.SubElement(det, "precioUnitario").text = str(line.unit_price)
        ET.SubElement(det, "descuento").text = str(line.discount)
        ET.SubElement(det, "precioTotalSinImpuesto").text = str(line.subtotal)

        impuestos = ET.SubElement(det, "impuestos")
        imp = ET.SubElement(impuestos, "impuesto")
        ET.SubElement(imp, "codigo").text = line.tax_code
        ET.SubElement(imp, "codigoPorcentaje").text = line.tax_rate_code
        ET.SubElement(imp, "tarifa").text = str(line.tax_rate)
        ET.SubElement(imp, "baseImponible").text = str(line.subtotal)
        ET.SubElement(imp, "valor").text = str(line.tax_amount)

    # ─── infoAdicional ──────────────────────────────
    info_adicional = ET.SubElement(root, "infoAdicional")
    if invoice.buyer_email:
        campo = ET.SubElement(info_adicional, "campoAdicional", nombre="Email")
        campo.text = invoice.buyer_email
    if invoice.buyer_address:
        campo = ET.SubElement(info_adicional, "campoAdicional", nombre="Dirección")
        campo.text = invoice.buyer_address
    campo_pedido = ET.SubElement(info_adicional, "campoAdicional", nombre="Pedido")
    campo_pedido.text = invoice.order.code

    # Serializar
    ET.indent(root)
    xml_str = ET.tostring(root, encoding="unicode", xml_declaration=True)
    return xml_str


def generate_ride_pdf(invoice):
    """Genera el RIDE (PDF) de la factura usando xhtml2pdf."""
    import io
    from django.template.loader import render_to_string
    from xhtml2pdf import pisa
    from core.models import CompanyConfig

    config = CompanyConfig.get()

    context = {
        "invoice": invoice,
        "config": config,
        "lines": invoice.lines.select_related("product").all(),
    }

    html_string = render_to_string("sales/invoice_ride.html", context)
    buffer = io.BytesIO()
    pisa.CreatePDF(io.StringIO(html_string), dest=buffer)
    return buffer.getvalue()
