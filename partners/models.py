# partners/models.py
from django.db import models
from core.models import AuditModel  # mismo patrón que QAPlan, etc.


class IdentificationType(models.TextChoices):
    RUC = "RUC", "RUC"
    DNI = "DNI", "Cédula"
    PASSPORT = "PASSPORT", "Pasaporte"
    OTHER = "OTHER", "Otro"


class CompanyType(models.TextChoices):
    COMPANY = "COMPANY", "Empresa"
    PERSON = "PERSON", "Persona natural"


class PartnerCategory(models.TextChoices):
    A = "A", "Categoría A"
    B = "B", "Categoría B"
    C = "C", "Categoría C"
    OTHER = "OTHER", "Otra"


class RetentionProfile(models.TextChoices):
    NONE = "NONE", "No emite retención"
    AGENT = "AGENT", "Agente de retención general"
    RENT = "RENT", "Retención en renta"
    VAT = "VAT", "Retención en IVA"
    RENT_VAT = "RENT_VAT", "Retención en renta e IVA"


class Partner(AuditModel):
    """
    Entidad genérica para:
      - Proveedores
      - Clientes
      - Entidades públicas
    Usada por compras (procurement), ventas y, a futuro, CRM.
    """

    code = models.CharField(
        "Código interno",
        max_length=20,
        unique=True,
        help_text="Código interno del socio (ej. PRV-001, CLI-100).",
    )

    alt_code = models.CharField(
        "Código alterno",
        max_length=20,
        blank=True,
        null=True,
        help_text="Código alterno o de sistema externo (opcional).",
    )

    identification_type = models.CharField(
        "Tipo de identificación",
        max_length=20,
        choices=IdentificationType.choices,
        default=IdentificationType.RUC,
    )

    identification = models.CharField(
        "Identificación",
        max_length=20,
        help_text="RUC / cédula / pasaporte, según corresponda.",
    )

    trade_name = models.CharField(
        "Nombre comercial",
        max_length=150,
        blank=True,
        help_text="Nombre comercial (si aplica).",
    )

    legal_name = models.CharField(
        "Nombre fiscal / razón social",
        max_length=200,
        help_text="Nombre fiscal que aparece en facturas.",
    )

    category = models.CharField(
        "Categoría",
        max_length=10,
        choices=PartnerCategory.choices,
        default=PartnerCategory.OTHER,
        blank=True,
    )

    company_type = models.CharField(
        "Tipo de empresa",
        max_length=20,
        choices=CompanyType.choices,
        default=CompanyType.COMPANY,
    )

    # Flags de uso
    is_customer = models.BooleanField("Cliente", default=False)
    is_supplier = models.BooleanField("Proveedor", default=True)
    is_public_entity = models.BooleanField("Entidad pública", default=False)

    # Información de crédito
    credit_limit = models.DecimalField(
        "Crédito máximo",
        max_digits=12,
        decimal_places=2,
        default=0,
    )
    credit_available = models.DecimalField(
        "Crédito disponible",
        max_digits=12,
        decimal_places=2,
        default=0,
    )
    credit_used = models.DecimalField(
        "Crédito utilizado",
        max_digits=12,
        decimal_places=2,
        default=0,
    )
    credit_terms_days = models.PositiveIntegerField(
        "Días de crédito",
        default=0,
        help_text="Plazo de pago en días (0 = contado).",
    )

    retention_profile = models.CharField(
        "Perfil de retención",
        max_length=20,
        choices=RetentionProfile.choices,
        default=RetentionProfile.NONE,
    )

    # Ubicación básica (para MVP; luego se puede normalizar en tabla Address)
    branch_name = models.CharField(
        "Sucursal",
        max_length=100,
        blank=True,
        help_text="Sucursal asociada (si aplica).",
    )
    address = models.CharField(
        "Dirección",
        max_length=255,
        blank=True,
    )
    city = models.CharField(
        "Ciudad",
        max_length=100,
        blank=True,
    )
    province = models.CharField(
        "Provincia",
        max_length=100,
        blank=True,
    )
    country = models.CharField(
        "País",
        max_length=100,
        blank=True,
        default="Ecuador",
    )

    # Contacto principal (para compras / cartera / CRM)
    contact_name = models.CharField(
        "Contacto principal",
        max_length=150,
        blank=True,
    )
    contact_email = models.EmailField(
        "Correo de contacto",
        blank=True,
    )
    contact_phone = models.CharField(
        "Teléfono de contacto",
        max_length=50,
        blank=True,
    )
    website = models.URLField(
        "Sitio web",
        blank=True,
    )

    # Calificación de proveedor (ISO 13485)
    is_qualified_supplier = models.BooleanField(
        "Proveedor calificado ISO 13485",
        default=False,
    )
    qualification_level = models.CharField(
        "Nivel de calificación",
        max_length=50,
        blank=True,
        help_text="Ejemplo: Crítico / No crítico, A / B / C, etc.",
    )
    qualification_date = models.DateField(
        "Fecha de última calificación",
        blank=True,
        null=True,
    )
    qualification_notes = models.TextField(
        "Notas de calificación",
        blank=True,
    )

    notes = models.TextField(
        "Notas internas",
        blank=True,
    )

    is_active = models.BooleanField(
        "Activo",
        default=True,
    )

    # ─── Transportista (para Guías de Remisión) ───
    is_carrier = models.BooleanField(
        "Transportista", default=False,
        help_text="Marcar si es proveedor de transporte.",
    )
    vehicle_plate = models.CharField(
        "Placa del vehículo", max_length=20, blank=True,
    )
    driver_name = models.CharField(
        "Nombre del conductor", max_length=200, blank=True,
    )
    driver_identification = models.CharField(
        "Cédula del conductor", max_length=20, blank=True,
    )

    class Meta:
        verbose_name = "Socio (cliente/proveedor)"
        verbose_name_plural = "Socios (clientes y proveedores)"
        ordering = ["trade_name", "legal_name"]

    def __str__(self) -> str:
        return f"{self.trade_name or self.legal_name} ({self.code})"
