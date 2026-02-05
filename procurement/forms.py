# procurement/forms.py
from django import forms
from django.forms import inlineformset_factory, formset_factory
from .models import PurchaseOrder, PurchaseOrderLine, PurchaseOrderStatus
from partners.models import Partner
from inventory.models import Product, ProductType
from core.models import Unit
from django.utils import timezone
from .models   import   RawMaterialReception, RawMaterialReceptionLine, ReceptionStatus


class PurchaseOrderForm(forms.ModelForm):
    class Meta:
        model = PurchaseOrder
        # OJO: number y order_date son automáticos/editable=False → no los ponemos aquí
        fields = [
            "supplier",
            "status",
            "currency",
        ]
        widgets = {
            "supplier": forms.Select(
                attrs={"class": "w-full rounded-lg border px-3 py-2 text-sm"}
            ),
            "status": forms.Select(
                attrs={"class": "w-full rounded-lg border px-3 py-2 text-sm"}
            ),
            "currency": forms.TextInput(
                attrs={"class": "w-full rounded-lg border px-3 py-2 text-sm"}
            ),
        }

    def __init__(self, *args, **kwargs):
        user = kwargs.pop("user", None)
        super().__init__(*args, **kwargs)

        # Solo proveedores activos
        self.fields["supplier"].queryset = Partner.objects.filter(
            is_supplier=True,
            is_active=True,
        ).order_by("trade_name", "legal_name")

        # Defaults razonables
        if not self.instance.pk:
            if "status" not in self.initial:
                self.initial["status"] = PurchaseOrderStatus.DRAFT
            if "currency" not in self.initial:
                self.initial["currency"] = "USD"


class PurchaseOrderLineForm(forms.ModelForm):
    class Meta:
        model = PurchaseOrderLine
        fields = ["product", "description", "quantity", "unit_price", "unit"]
        widgets = {
            "product": forms.Select(
                attrs={"class": "w-full rounded-lg border px-2 py-1.5 text-xs md:text-sm"}
            ),
            "description": forms.TextInput(
                attrs={"class": "w-full rounded-lg border px-2 py-1.5 text-xs md:text-sm"}
            ),
            "quantity": forms.NumberInput(
                attrs={
                    "class": "w-full rounded-lg border px-2 py-1.5 text-xs md:text-sm",
                    "step": "0.0001",  # Permitimos 4 decimales
                }
            ),
            "unit_price": forms.NumberInput(
                attrs={
                    "class": "w-full rounded-lg border px-2 py-1.5 text-xs md:text-sm",
                    "step": "0.0001",  # Permitimos 4 decimales
                }
            ),
            "unit": forms.Select(
                attrs={"class": "w-full rounded-lg border px-2 py-1.5 text-xs md:text-sm"}
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Establecemos la lista de unidades de medida disponibles para el producto
        self.fields["unit"].queryset = Unit.objects.all()  # Aseguramos que se muestren las unidades disponibles


    def clean(self):
        cleaned = super().clean()
        product = cleaned.get("product")
        quantity = cleaned.get("quantity")
        unit = cleaned.get("unit")

        # Fila totalmente vacía → la dejamos pasar y luego la ignoras en la vista
        if not product and quantity in (None, "") and unit is None:
            return cleaned

        # Validaciones básicas
        if not product:
            self.add_error("product", "Seleccione un producto.")

        if quantity is None or quantity <= 0:
            self.add_error("quantity", "La cantidad debe ser mayor a cero.")

        # Si hay producto y no seleccionaron unidad, usar la base
        if product and not unit:
            cleaned["unit"] = product.base_unit

        return cleaned


PurchaseOrderLineFormSet = inlineformset_factory(
    PurchaseOrder,
    PurchaseOrderLine,
    form=PurchaseOrderLineForm,
    extra=0,
    can_delete=True,
)

# -------------------------------------------------------------------
# Formulario para el encabezado de recepción de materia prima
# -------------------------------------------------------------------
class RawMaterialReceptionHeaderForm(forms.Form):
    supplier_name = forms.CharField(
        label="Proveedor",
        max_length=200,
        widget=forms.TextInput(attrs={"class": "w-full rounded-lg border px-3 py-2"}),
    )
    supplier_ruc = forms.CharField(
        label="RUC proveedor",
        max_length=20,
        required=False,
        widget=forms.TextInput(attrs={"class": "w-full rounded-lg border px-3 py-2"}),
    )
    document_type = forms.CharField(
        label="Tipo de documento",
        max_length=50,
        required=False,
        widget=forms.TextInput(
            attrs={
                "class": "w-full rounded-lg border px-3 py-2",
                "placeholder": "Factura, guía, OC...",
            }
        ),
    )
    document_number = forms.CharField(
        label="N° documento",
        max_length=50,
        required=False,
        widget=forms.TextInput(attrs={"class": "w-full rounded-lg border px-3 py-2"}),
    )
    reception_date = forms.DateField(
        label="Fecha de recepción",
        required=False,  # la vamos a forzar en clean
        widget=forms.DateInput(
            attrs={
                "type": "text",  # ya no 'date' para que no salga el selector
                "class": "w-full rounded-lg border px-3 py-2 bg-gray-100 cursor-not-allowed",
                "readonly": "readonly",
            }
        ),
    )
    arrival_time = forms.TimeField(
        label="Hora de llegada",
        required=False,  # la vamos a forzar en clean
        widget=forms.TimeInput(
            attrs={
                "type": "text",  # lo mostramos como texto plano
                "class": "w-full rounded-lg border px-3 py-2 bg-gray-100 cursor-not-allowed",
                "readonly": "readonly",
            }
        ),
    )

    transport_company = forms.CharField(
        label="Transportista",
        max_length=200,
        required=False,
        widget=forms.TextInput(attrs={"class": "w-full rounded-lg border px-3 py-2"}),
    )
    transport_plate = forms.CharField(
        label="Placa",
        max_length=20,
        required=False,
        widget=forms.TextInput(attrs={"class": "w-full rounded-lg border px-3 py-2"}),
    )

    temperature_recorded = forms.DecimalField(
        label="Temperatura (°C)",
        max_digits=5,
        decimal_places=2,
        required=False,
        widget=forms.NumberInput(attrs={"class": "w-full rounded-lg border px-3 py-2"}),
    )
    num_boxes = forms.IntegerField(
        label="Número de bultos/cajas",
        required=False,
        widget=forms.NumberInput(attrs={"class": "w-full rounded-lg border px-3 py-2"}),
    )
    gross_weight = forms.DecimalField(
        label="Peso bruto (kg)",
        max_digits=12,
        decimal_places=4,
        required=False,
        widget=forms.NumberInput(attrs={"class": "w-full rounded-lg border px-3 py-2"}),
    )
    net_weight = forms.DecimalField(
        label="Peso neto (kg)",
        max_digits=12,
        decimal_places=4,
        required=False,
        widget=forms.NumberInput(attrs={"class": "w-full rounded-lg border px-3 py-2"}),
    )

    observations = forms.CharField(
        label="Observaciones generales",
        required=False,
        widget=forms.Textarea(
            attrs={
                "class": "w-full rounded-lg border px-3 py-2",
                "rows": 3,
            }
        ),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # current date/time por defecto
        if not self.is_bound:
            now = timezone.localtime()
            self.fields["reception_date"].initial = now.date()
            self.fields["arrival_time"].initial = now.strftime("%H:%M")
            
    def clean_reception_date(self):
        """
        Ignoramos cualquier cosa que venga del navegador y 
        siempre usamos la fecha de hoy.
        """
        return timezone.localtime().date()
    
    def clean_arrival_time(self):
        """
        Ignoramos lo que venga del navegador y usamos siempre la hora actual.
        """
        t = timezone.localtime().time().replace(microsecond=0)
        return t



# -------------------------------------------------------------------
# Formulario para las líneas de recepción de materia prima
# -------------------------------------------------------------------
# procurement/forms.py

class RawMaterialReceptionLineForm(forms.Form):
    product_code = forms.CharField(
        label="Código",
        max_length=50,
        required=False,
        widget=forms.TextInput(attrs={
            "class": "w-full rounded-lg border px-2 py-1 text-sm",
            "data-role": "product-code",
        }),
    )
    product = forms.ModelChoiceField(
        label="Producto",
        queryset=Product.objects.none(),
        required=False,
        widget=forms.Select(attrs={
            "class": "w-full rounded-lg border px-2 py-1 text-sm",
            "data-role": "product-select",
        }),
    )
    
    unit = forms.ModelChoiceField(
        label="Unidad",
        queryset=Unit.objects.filter(is_active=True),
        required=False,
        widget=forms.Select(attrs={
            "class": "w-full rounded-lg border px-2 py-1 text-sm",
            "data-role": "unit-select",
        }),
    )
    
    expected_quantity = forms.DecimalField(
        label="Cant. esperada",
        max_digits=12,
        decimal_places=4,
        required=False,
        widget=forms.NumberInput(attrs={"class": "w-full rounded-lg border px-2 py-1 text-sm"}),
    )
    received_quantity = forms.DecimalField(
        label="Cant. recibida",
        max_digits=12,
        decimal_places=4,
        required=False,
        widget=forms.NumberInput(attrs={"class": "w-full rounded-lg border px-2 py-1 text-sm"}),
    )
    unit_cost = forms.DecimalField(
        label="Costo unitario",
        max_digits=10,
        decimal_places=4,
        required=False,
        widget=forms.NumberInput(attrs={"class": "w-full rounded-lg border px-2 py-1 text-sm"}),
    )
    supplier_lot = forms.CharField(
        label="Lote proveedor",
        max_length=50,
        required=False,
        widget=forms.TextInput(attrs={"class": "w-full rounded-lg border px-2 py-1 text-sm"}),
    )
    internal_lot = forms.CharField(
        label="Lote interno",
        max_length=50,
        required=False,
        widget=forms.TextInput(attrs={"class": "w-full rounded-lg border px-2 py-1 text-sm"}),
    )
    manufacturing_date = forms.DateField(
        label="Fecha de elaboración",
        required=False,
        widget=forms.DateInput(
            attrs={
                "type": "date",
                "class": "w-full rounded-lg border px-3 py-2 text-sm"
            },
            format="%Y-%m-%d"
        ),
    )
    expiry_date = forms.DateField(
        label="Fecha de caducidad",
        required=True,
        widget=forms.DateInput(
            attrs={
                "type": "date",
                "class": "w-full rounded-lg border px-3 py-2 text-sm"
            },
            format="%Y-%m-%d"
        ),
    )
    storage_area = forms.CharField(
        label="Área/bodega",
        max_length=100,
        required=False,
        widget=forms.TextInput(attrs={"class": "w-full rounded-lg border px-2 py-1 text-sm"}),
    )
    line_notes = forms.CharField(
        label="Notas",
        required=False,
        widget=forms.Textarea(attrs={
            "class": "w-full rounded-lg border px-2 py-1 text-sm",
            "rows": 1,
        }),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # solo materias primas activas
        self.fields["product"].queryset = Product.objects.filter(
            product_type=ProductType.RAW,
            is_active=True,
        ).order_by("name")
        # Mostrar solo el nombre en el dropdown (el código va en su columna aparte)
        self.fields["product"].label_from_instance = lambda obj: obj.name
    
    def clean(self):
        cleaned = super().clean()
        product = cleaned.get("product")
        product_code = cleaned.get("product_code")
        received_quantity = cleaned.get("received_quantity")
        unit = cleaned.get("unit")

        # Fila totalmente vacía → se permite (el formset la ignora en la vista)
        if not product and not product_code and received_quantity is None:
            return cleaned

        # Si viene código pero no product, intentamos resolverlo
        if not product and product_code:
            try:
                product = Product.objects.get(
                    code=product_code,
                    product_type=ProductType.RAW,
                    is_active=True,
                )
                cleaned["product"] = product
            except Product.DoesNotExist:
                self.add_error("product_code", "No existe un producto RAW activo con este código.")

        # Si hay producto (por código o por select), exigimos cantidad recibida > 0
        if product and (received_quantity is None or received_quantity <= 0):
            self.add_error("received_quantity", "Ingrese una cantidad recibida mayor a cero.")

        # ⭐ VALIDACIÓN DE UNIDAD
        if product and not unit:
            # Si no se selecciona unidad, usar base_unit del producto
            cleaned["unit"] = product.base_unit
        
        if product and unit:
            # Validar que la unidad sea compatible con el producto
            if unit.category != product.base_unit.category:
                self.add_error(
                    "unit",
                    f"La unidad {unit.name} no es compatible con "
                    f"la unidad base del producto ({product.base_unit.name})"
                )

        return cleaned


RawMaterialReceptionLineFormSet = formset_factory(
    RawMaterialReceptionLineForm,
    extra=0,   # las filas las controla el JS
    can_delete=True,
)
