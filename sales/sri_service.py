"""
Servicio de integración con el SRI Ecuador.
Firma digital de XML y envío/autorización de comprobantes electrónicos.
Soporta facturas y guías de remisión.
"""
import base64
import logging
from django.utils import timezone
from django.core.exceptions import ValidationError

logger = logging.getLogger(__name__)

# URLs del SRI
SRI_URLS = {
    "1": {  # Pruebas
        "recepcion": "https://celcer.sri.gob.ec/comprobantes-electronicos-ws/RecepcionComprobantesOffline?wsdl",
        "autorizacion": "https://celcer.sri.gob.ec/comprobantes-electronicos-ws/AutorizacionComprobantesOffline?wsdl",
    },
    "2": {  # Producción
        "recepcion": "https://cel.sri.gob.ec/comprobantes-electronicos-ws/RecepcionComprobantesOffline?wsdl",
        "autorizacion": "https://cel.sri.gob.ec/comprobantes-electronicos-ws/AutorizacionComprobantesOffline?wsdl",
    },
}


def _get_status_enum(document):
    """Retorna el enum de estados correcto según el tipo de documento."""
    model_name = document._meta.model_name
    if model_name == "guiaremision":
        from .models import GuiaRemisionStatus
        return GuiaRemisionStatus
    else:
        from .models import InvoiceStatus
        return InvoiceStatus


def sign_xml(document):
    """
    Firma el XML del documento con el certificado .p12.
    Acepta SaleInvoice o GuiaRemision.
    """
    from core.models import CompanyConfig

    config = CompanyConfig.get()
    if not config or not config.certificate_file:
        raise ValidationError("No hay certificado .p12 configurado.")

    if not document.xml_unsigned:
        raise ValidationError("El documento no tiene XML generado.")

    StatusEnum = _get_status_enum(document)

    try:
        from cryptography.hazmat.primitives.serialization import pkcs12
        from cryptography.hazmat.backends import default_backend
        from signxml import XMLSigner, methods
        from lxml import etree

        p12_data = config.certificate_file.read()
        private_key, certificate, chain = pkcs12.load_key_and_certificates(
            p12_data,
            config.certificate_password.encode("utf-8"),
            default_backend(),
        )

        xml_doc = etree.fromstring(document.xml_unsigned.encode("utf-8"))

        signer = XMLSigner(
            method=methods.enveloped,
            c14n_algorithm="http://www.w3.org/TR/2001/REC-xml-c14n-20010315",
        )
        signed_xml = signer.sign(
            xml_doc,
            key=private_key,
            cert=[certificate] + (list(chain) if chain else []),
        )

        signed_xml_str = etree.tostring(signed_xml, encoding="unicode", xml_declaration=True)

        document.xml_signed = signed_xml_str
        document.status = StatusEnum.SIGNED
        document.save(update_fields=["xml_signed", "status"])

        return document

    except Exception as e:
        doc_label = getattr(document, "full_number", str(document))
        logger.error(f"Error firmando XML documento {doc_label}: {e}")
        raise ValidationError(f"Error al firmar el XML: {e}")


def send_to_sri(document):
    """
    Envía el XML firmado al SRI y consulta la autorización.
    Acepta SaleInvoice o GuiaRemision.
    """
    from core.models import CompanyConfig
    import zeep

    config = CompanyConfig.get()
    if not config:
        raise ValidationError("Configure los datos de la empresa.")

    if not document.xml_signed:
        raise ValidationError("El documento debe estar firmado antes de enviar al SRI.")

    env = config.environment
    urls = SRI_URLS.get(env)
    if not urls:
        raise ValidationError(f"Ambiente SRI no válido: {env}")

    StatusEnum = _get_status_enum(document)
    doc_label = getattr(document, "full_number", str(document))

    try:
        # 1. Enviar comprobante
        xml_bytes = document.xml_signed.encode("utf-8")
        xml_b64 = base64.b64encode(xml_bytes)

        client_recepcion = zeep.Client(wsdl=urls["recepcion"])
        response = client_recepcion.service.validarComprobante(xml_b64)

        estado = response.estado if hasattr(response, "estado") else str(response)
        logger.info(f"SRI Recepción {doc_label} - Estado: {estado}")

        if estado == "DEVUELTA":
            mensajes = []
            if hasattr(response, "comprobantes") and response.comprobantes:
                for comp in response.comprobantes.comprobante:
                    if hasattr(comp, "mensajes") and comp.mensajes:
                        for msg in comp.mensajes.mensaje:
                            mensajes.append(
                                f"[{getattr(msg, 'identificador', '')}] "
                                f"{getattr(msg, 'mensaje', '')} - "
                                f"{getattr(msg, 'informacionAdicional', '')}"
                            )
            sri_msg = " | ".join(mensajes) if mensajes else str(response)
            document.sri_response = sri_msg
            document.status = StatusEnum.REJECTED
            document.save(update_fields=["sri_response", "status"])
            raise ValidationError(f"SRI rechazó el comprobante: {sri_msg}")

        # 2. Consultar autorización
        document.status = StatusEnum.SENT
        document.save(update_fields=["status"])

        client_auth = zeep.Client(wsdl=urls["autorizacion"])
        auth_response = client_auth.service.autorizacionComprobante(document.access_key)

        autorizaciones = getattr(auth_response, "autorizaciones", None)
        if autorizaciones and autorizaciones.autorizacion:
            auth = autorizaciones.autorizacion[0]
            auth_estado = getattr(auth, "estado", "")

            if auth_estado == "AUTORIZADO":
                document.authorization_number = getattr(
                    auth, "numeroAutorizacion", document.access_key
                )
                document.authorization_date = getattr(
                    auth, "fechaAutorizacion", timezone.now()
                )
                document.sri_response = f"AUTORIZADO - {document.authorization_number}"
                document.status = StatusEnum.AUTHORIZED
            else:
                mensajes = []
                if hasattr(auth, "mensajes") and auth.mensajes:
                    for msg in auth.mensajes.mensaje:
                        mensajes.append(
                            f"[{getattr(msg, 'identificador', '')}] "
                            f"{getattr(msg, 'mensaje', '')} - "
                            f"{getattr(msg, 'informacionAdicional', '')}"
                        )
                sri_msg = " | ".join(mensajes) if mensajes else auth_estado
                document.sri_response = sri_msg
                document.status = StatusEnum.REJECTED
        else:
            document.sri_response = "Sin respuesta de autorización"
            document.status = StatusEnum.SENT

        document.save(update_fields=[
            "authorization_number", "authorization_date",
            "sri_response", "status",
        ])

        return document

    except ValidationError:
        raise
    except Exception as e:
        logger.error(f"Error enviando al SRI documento {doc_label}: {e}")
        document.sri_response = str(e)
        document.save(update_fields=["sri_response"])
        raise ValidationError(f"Error de comunicación con el SRI: {e}")
