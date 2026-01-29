# inventory/forms.py

from django import forms
from django.utils import timezone
from .models import (
    Product,
    ProductType,
    InventoryMove,
    Lot,
    LotStatus,
    MovementTypes,
)
from core.models import (
    TaxScheme,
    Unit,
    Warehouse,
    WarehouseType,
    Location,
)

# -------------------------------------------------------------------
# Formulario de Producto
# -------------------------------------------------------------------
class ProductForm(forms.ModelForm):
    class Meta:
        model = Product
        fields = [
            "product_type",
            "code",
            "code_2",
            "name",
            "tax_scheme",
            "base_unit",
            "unit_price",
            "unit_cost",
            "provider",
            "category",
            "brand",
            "attribute1",
            "attribute2",
            "is_active",
            "lot_prefix",
            "use_date_in_lot",
        ]
        widgets = {
            "product_type": forms.Select(attrs={"class": "w-full rounded-lg border px-3 py-2"}),
            "code": forms.TextInput(attrs={"class": "w-full rounded-lg border px-3 py-2"}),
            "code_2": forms.TextInput(attrs={"class": "w-full rounded-lg border px-3 py-2"}),
            "name": forms.TextInput(attrs={"class": "w-full rounded-lg border px-3 py-2"}),
            "tax_scheme": forms.Select(attrs={"class": "w-full rounded-lg border px-3 py-2"}),
            "base_unit": forms.Select(attrs={"class": "w-full rounded-lg border px-3 py-2"}),
            "unit_price": forms.NumberInput(attrs={"class": "w-full rounded-lg border px-3 py-2"}),
            "unit_cost": forms.NumberInput(attrs={"class": "w-full rounded-lg border px-3 py-2"}),
            "provider": forms.TextInput(attrs={"class": "w-full rounded-lg border px-3 py-2"}),
            "category": forms.TextInput(attrs={"class": "w-full rounded-lg border px-3 py-2"}),
            "brand": forms.TextInput(attrs={"class": "w-full rounded-lg border px-3 py-2"}),
            "attribute1": forms.TextInput(attrs={"class": "w-full rounded-lg border px-3 py-2"}),
            "attribute2": forms.TextInput(attrs={"class": "w-full rounded-lg border px-3 py-2"}),
            "is_active": forms.CheckboxInput(attrs={"class": "rounded"}),
            "lot_prefix": forms.TextInput(attrs={"class": "w-full rounded-lg border px-3 py-2", "placeholder": "CAP, CAM, 00101"}),
            "use_date_in_lot": forms.CheckboxInput(attrs={"class": "rounded"}),}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Solo esquemas tributarios activos
        self.fields["tax_scheme"].queryset = TaxScheme.objects.filter(
            is_active=True
        ).order_by("name")
        # Solo unidades activas
        self.fields["base_unit"].queryset = Unit.objects.filter(
            is_active=True
        ).order_by("category", "name")


# -------------------------------------------------------------------
# Formulario para movimientos de inventario
# -------------------------------------------------------------------
from django import forms
from .models import Product, InventoryMove, MovementTypes, Lot

class InventoryMoveForm(forms.Form):
    product = forms.ModelChoiceField(
        queryset=Product.objects.filter(is_active=True).order_by("name"),
        widget=forms.Select(attrs={"class": "w-full rounded-lg border px-3 py-2"}),
        label="Producto",
    )
    lot = forms.ModelChoiceField(
        queryset=Lot.objects.all(),
        widget=forms.Select(attrs={"class": "w-full rounded-lg border px-3 py-2"}),
        required=False,
        label="Lote",
    )
    movement_type = forms.ChoiceField(
        choices=MovementTypes.choices,
        widget=forms.Select(attrs={"class": "w-full rounded-lg border px-3 py-2"}),
        label="Tipo de movimiento",
    )
    quantity = forms.DecimalField(
        max_digits=12,
        decimal_places=4,
        widget=forms.NumberInput(attrs={"class": "w-full rounded-lg border px-3 py-2"}),
        label="Cantidad",
    )
    unit_cost = forms.DecimalField(
        max_digits=10,
        decimal_places=4,
        required=False,
        widget=forms.NumberInput(attrs={"class": "w-full rounded-lg border px-3 py-2"}),
        label="Costo unitario",
    )
    reference = forms.CharField(
        max_length=100,
        required=False,
        widget=forms.TextInput(attrs={"class": "w-full rounded-lg border px-3 py-2"}),
        label="Referencia",
    )
    area = forms.CharField(
        max_length=100,
        required=False,
        widget=forms.TextInput(attrs={"class": "w-full rounded-lg border px-3 py-2"}),
        label="Área",
    )
    notes = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"class": "w-full rounded-lg border px-3 py-2", "rows": 3}),
        label="Notas",
    )

    def clean(self):
        cleaned_data = super().clean()
        product = cleaned_data.get("product")
        quantity = cleaned_data.get("quantity")
        movement_type = cleaned_data.get("movement_type")

        # Validación para movimiento de salida (OUT) y verificar stock
        if movement_type == MovementTypes.OUT:
            # Convertimos la cantidad a la unidad base
            base_unit_factor = product.base_unit.factor_to_base
            converted_quantity = quantity * base_unit_factor

            # Verificamos si hay suficiente stock
            if converted_quantity > product.stock.quantity:
                self.add_error('quantity', 'La cantidad a retirar supera el stock disponible.')

        return cleaned_data



# -------------------------------------------------------------------
# Formulario para actualizar bodega y ubicación de un lote
# -------------------------------------------------------------------
class LotLocationUpdateForm(forms.ModelForm):
    class Meta:
        model = Lot
        fields = ["warehouse", "location"]
        widgets = {
            "warehouse": forms.Select(attrs={"class": "w-full rounded-lg border px-3 py-2"}),
            "location": forms.Select(attrs={"class": "w-full rounded-lg border px-3 py-2"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # 1) Bodegas activas
        self.fields["warehouse"].queryset = Warehouse.objects.filter(
            is_active=True
        ).order_by("name")

        # 2) Ubicaciones según la bodega seleccionada
        if self.is_bound:
            warehouse_id = self.data.get("warehouse") or self.initial.get("warehouse")
        else:
            warehouse = self.instance.warehouse
            warehouse_id = warehouse.id if warehouse else None

        if warehouse_id:
            self.fields["location"].queryset = Location.objects.filter(
                warehouse_id=warehouse_id,
                is_active=True,
            ).order_by("code")
        else:
            self.fields["location"].queryset = Location.objects.none()

    def clean(self):
        cleaned = super().clean()
        warehouse = cleaned.get("warehouse")
        location = cleaned.get("location")
        lot = self.instance

        # 1) Si hay ubicación, debe pertenecer a la bodega seleccionada
        if location and warehouse and location.warehouse_id != warehouse.id:
            self.add_error(
                "location",
                "La ubicación seleccionada no pertenece a la bodega elegida.",
            )

        # 2) Restricción por tipo de producto
        if warehouse and lot and lot.product:
            ptype = lot.product.product_type

            # Materia prima: solo Cuarentena o Materia prima
            if ptype == ProductType.RAW and warehouse.type not in [
                WarehouseType.QUARANTINE,
                WarehouseType.RAW,
            ]:
                self.add_error(
                    "warehouse",
                    "La materia prima solo puede almacenarse en bodegas de Cuarentena o Materia prima.",
                )

            # Producto terminado: solo bodegas válidas
            if ptype == ProductType.FG and warehouse.type not in [
                WarehouseType.FINISHED,
                WarehouseType.RECALL,
                WarehouseType.SCRAP,
            ]:
                self.add_error(
                    "warehouse",
                    "El producto terminado no puede almacenarse en esta bodega.",
                )

        return cleaned





# -------------------------------------------------------------------
# Formulario para la transferencia de un lote
# -------------------------------------------------------------------
class LotTransferForm(forms.Form):
    lot = forms.ModelChoiceField(
        queryset=Lot.objects.filter(status=LotStatus.APPROVED),
        label="Lote",
        widget=forms.Select(attrs={"class": "w-full rounded-lg border px-3 py-2"}),
    )
    warehouse = forms.ModelChoiceField(
        queryset=Warehouse.objects.exclude(type=WarehouseType.QUARANTINE),
        label="Bodega de destino",
        widget=forms.Select(attrs={"class": "w-full rounded-lg border px-3 py-2"}),
    )
    location = forms.ModelChoiceField(
        queryset=Location.objects.none(),
        label="Ubicación",
        widget=forms.Select(attrs={"class": "w-full rounded-lg border px-3 py-2"}),
        required=False,
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # cuando el formulario está enviado, actualizamos las ubicaciones
        if self.is_bound:
            warehouse_id = self.data.get("warehouse")
            if warehouse_id:
                self.fields["location"].queryset = Location.objects.filter(
                    warehouse_id=warehouse_id
                ).order_by("code")
            else:
                self.fields["location"].queryset = Location.objects.none()

    def clean(self):
        cleaned_data = super().clean()
        warehouse = cleaned_data.get("warehouse")
        location = cleaned_data.get("location")
        lot = cleaned_data.get("lot")

        # Validar que la bodega seleccionada sea diferente a la bodega actual del lote
        if warehouse and lot and lot.warehouse == warehouse:
            self.add_error("warehouse", "El lote ya está en esta bodega.")

        # (Opcional) podrías validar que la ubicación pertenezca a la bodega, pero ya lo garantizamos en el queryset

        return cleaned_data
