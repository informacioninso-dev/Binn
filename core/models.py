from django.db import models
from django.conf import settings
from django.core.exceptions import ValidationError

#-------------------Modelo abstracto para auditoría de creación y modificación
class AuditModel(models.Model):
    """
    Incluye fecha y hora de actualización al igual que el usuario.
    Tambien incluye la creación
    """
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
    related_name="%(class)s_created", on_delete=models.SET_NULL)
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
    related_name="%(class)s_updated", on_delete=models.SET_NULL)

    class Meta:
        abstract = True

#-------------------Modelo para esquemas tributarios para inventarios y transacciones
class TaxScheme(AuditModel):
    """
    Aqui se establece el modelo para gestionar los posible impuesto de manera dinamica
    Es decir genera un tabla de registro de estos valores 
    Incluye el nombre de impuesto, codigo y valor del impuesto tipo decimal
    """
    code = models.CharField(max_length=20,unique=True,
    help_text="Código interno del esquema tributario (ej: IVA12, IVA0, EXENTO)"
    )
    name = models.CharField(
    max_length=100,
    help_text="Nombre descriptivo (IVA 12%, IVA 0%, Exento, etc.)"
    )
    rate = models.DecimalField(max_digits=5,decimal_places=2,
    help_text="Porcentaje (ej. 12.00 para IVA 12%)"
    )
    is_active = models.BooleanField(default=True)

    applies_sales = models.BooleanField(default=True)
    applies_purchases = models.BooleanField(default=True)

    class Meta:
        verbose_name = "Esquema Tributario"
        verbose_name_plural = "Esquemas Tributarios"

    def __str__(self):
        return f"{self.code} ({self.rate}%)"
    
#-------------------Categorias de unidades donde se consdiera las mas usadas en producto
class UnitCategory(models.TextChoices):
    """
    Aqui se establecen las categorias de unidades para la aprte de compra, venta y producción 
    Incluye Masa, longuitud, unidad (conteo), volumne, area y otros 
    """
    MASS = "MASS", "Masa"
    LENGTH = "LENGTH", "Longitud"
    COUNT = "COUNT", "Unidad (pieza, rollo, etc.)"
    VOLUME = "VOLUME", "Volumen"
    AREA = "AREA", "Área"
    OTHER = "OTHER", "Otro"
    
#-------------------Modelo de unidades de medida considerando como cegorias de UnitCategory
class Unit(AuditModel):
    """
    Aqui se establecen la entidad unidad de medida de producto ( materias primas, producto etc)
    Incluye codigo de unidad, nombre, categoria(UnitCategory), factor base para conversion 
    """
    code = models.CharField(max_length=10,unique=True,
    help_text="Código corto: kg, g, m, cm, un, caja, etc."
    )
    name = models.CharField(max_length=50,
    help_text="Nombre descriptivo: Kilogramo, Metro, Unidad, Caja..."
    )
    category = models.CharField(max_length=10,choices=UnitCategory.choices,default=UnitCategory.COUNT,
    )
    # factor relativo a la unidad base de su categoría
    factor_to_base = models.DecimalField(max_digits=10,decimal_places=4,
    help_text="Factor para convertir a la unidad base de la categoría"
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name = "Unidad de medida"
        verbose_name_plural = "Unidades de medida"

    def __str__(self):
        return f"{self.code} ({self.name})"
    
    def clean(self):
        super().clean()
        if self.factor_to_base <= 0:
            raise ValidationError({
                'factor_to_base': 'El factor de conversión debe ser mayor a 0'
            })


#-------------------Clasificación de tipos como minimo de bodega acorde a BPDT e ISO 13485
class WarehouseType(models.TextChoices):
    """
    Aqui se establecen los tipos de bodegas
    """
    QUARANTINE = "QUARANTINE", "Cuarentena"
    RAW = "RAW", "Materia prima"
    WIP = "WIP", "Semielaborado"
    FINISHED = "FINISHED", "Producto terminado"
    SCRAP = "SCRAP", "Producto de baja"
    RECALL = "RECALL", "Retiro de mercado"
    RETURNS    = "RETURNS",    "Devoluciones de clientes"
    STAGING    = "STAGING",    "Zona de predespacho"
    SAMPLES    = "SAMPLES",    "Muestras / retención"
    LABELS     = "LABELS", "Etiquetas"
    PACK = "PACK", "Material de empaque"
    OTHER = "OTHER", "Otro"


#-------------------Clasificación de tipos diferentes bodegas en el sistema 
class Warehouse(AuditModel):
    code = models.CharField(max_length=20,unique=True,
    help_text="Código interno de bodega (ej: BOD-CUA, BOD-MP, BOD-PT)"
    )
    name = models.CharField(max_length=100,
    help_text="Nombre descriptivo (ej: Bodega de cuarentena)"
    )
    type = models.CharField(max_length=20,choices=WarehouseType.choices,default=WarehouseType.OTHER,
    help_text="Tipo de bodega según clasificación regulatoria/operativa"
    )

    is_active = models.BooleanField(default=True)
    # Flags para flujos por defecto
    is_default_quarantine = models.BooleanField(default=False,
    help_text="Usar como bodega de cuarentena por defecto en recepción"
    )
    is_default_for_raw = models.BooleanField(default=False,
    help_text="Bodega por defecto para materia prima liberada"
    )

    is_default_fg_released = models.BooleanField(
        default=False,
        help_text="Bodega por defecto para producto terminado liberado."
    )

    class Meta:
        verbose_name = "Bodega"
        verbose_name_plural = "Bodegas"

    def __str__(self):
        return f"{self.code} - {self.name}"

# -------------------Modelo de tipo de ubicaciones
class Location(AuditModel):
    warehouse = models.ForeignKey(
    Warehouse, on_delete=models.CASCADE,related_name="locations",verbose_name="Bodega")
    code = models.CharField( max_length=30,
    help_text="Código de ubicación (ej: EST-01-N1-A)")
    name = models.CharField(max_length=100, blank=True,null=True, 
    help_text="Nombre o alias de la ubicació")
    description = models.CharField(max_length=255,blank=True,null=True,
    help_text="Descripción adicional (pasillo, estante, etc.)"
    )

    # Campos a usar  futuro un sistema de gestion en un centro de almacenamiento (WMS)
    row = models.CharField(max_length=10, blank=True, null=True)
    rack = models.CharField(max_length=10, blank=True, null=True)
    level = models.CharField(max_length=10, blank=True, null=True)

    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name = "Ubicación"
        verbose_name_plural = "Ubicaciones"
        unique_together = ("warehouse", "code")

    def __str__(self):
        return f"{self.warehouse.code} / {self.code}"


# ─── Configuración del Emisor (Singleton) ──────────────────
class SRIEnvironment(models.TextChoices):
    PRUEBAS = "1", "Pruebas"
    PRODUCCION = "2", "Producción"


class CompanyConfig(AuditModel):
    ruc = models.CharField("RUC", max_length=13)
    legal_name = models.CharField("Razón social", max_length=300)
    trade_name = models.CharField("Nombre comercial", max_length=300, blank=True)
    address = models.CharField("Dirección matriz", max_length=300)
    establishment_code = models.CharField(
        "Código establecimiento", max_length=3, default="001",
        help_text="Ej: 001",
    )
    emission_point = models.CharField(
        "Punto de emisión", max_length=3, default="001",
        help_text="Ej: 001",
    )
    special_taxpayer = models.CharField(
        "Contribuyente especial Nº", max_length=13, blank=True,
    )
    obligated_accounting = models.BooleanField(
        "Obligado a llevar contabilidad", default=True,
    )
    environment = models.CharField(
        "Ambiente SRI", max_length=1,
        choices=SRIEnvironment.choices, default=SRIEnvironment.PRUEBAS,
    )
    emission_type = models.CharField(
        "Tipo de emisión", max_length=1, default="1",
        help_text="1 = Emisión normal",
    )
    certificate_file = models.FileField(
        "Certificado .p12", upload_to="sri_certs/", blank=True,
    )
    certificate_password = models.CharField(
        "Contraseña del certificado", max_length=200, blank=True,
    )
    logo = models.ImageField("Logo", upload_to="company/", blank=True)

    class Meta:
        verbose_name = "Configuración de empresa"
        verbose_name_plural = "Configuración de empresa"

    def __str__(self):
        return f"{self.ruc} – {self.legal_name}"

    def save(self, *args, **kwargs):
        # Singleton: solo permite 1 registro
        if not self.pk and CompanyConfig.objects.exists():
            raise ValidationError("Solo puede existir un registro de configuración de empresa.")
        super().save(*args, **kwargs)

    @classmethod
    def get(cls):
        return cls.objects.first()
