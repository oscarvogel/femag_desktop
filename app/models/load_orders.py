from datetime import date
from decimal import Decimal

from peewee import (
    BooleanField,
    CharField,
    DateField,
    DateTimeField,
    DecimalField,
    FloatField,
    ForeignKeyField,
    IntegerField,
    TextField,
)

from app.models.base import BaseModel, utc_now
from app.models.masters import Carrier, Client, ClientAddress, Driver, PalletType, Product, TipoIVA, Truck


class LoadOrder(BaseModel):
    STATUS_PENDING = "Pendiente"
    STATUS_LEGACY_DRAFT = "Borrador"
    STATUS_ISSUED = "Emitida"
    STATUS_CLOSED = "Cerrada"
    STATUS_ANNULLED = "Anulada"
    PENDING_STATUSES = (STATUS_PENDING, STATUS_LEGACY_DRAFT)
    ACTIVE_STATUSES = (*PENDING_STATUSES, STATUS_ISSUED)
    FINAL_STATUSES = (STATUS_CLOSED, STATUS_ANNULLED)

    order_number = IntegerField(unique=True)
    date = DateField(default=date.today)
    client = ForeignKeyField(Client, backref="load_orders", null=True)
    delivery_address = ForeignKeyField(ClientAddress, backref="load_orders", null=True)
    carrier = ForeignKeyField(Carrier, backref="load_orders")
    driver = ForeignKeyField(Driver, backref="load_orders")
    truck = ForeignKeyField(Truck, backref="load_orders")
    trailer_domain = CharField(null=True)
    status = CharField(default=STATUS_PENDING)
    observations = TextField(null=True)
    created_by = CharField(null=True)
    updated_by = CharField(null=True)

    @property
    def is_active(self) -> bool:
        return self.status in self.ACTIVE_STATUSES

    @property
    def is_pending(self) -> bool:
        return self.status in self.PENDING_STATUSES

    @property
    def is_unissued(self) -> bool:
        return self.status not in (self.STATUS_ISSUED, *self.FINAL_STATUSES)


class LoadOrderDestination(BaseModel):
    order = ForeignKeyField(LoadOrder, backref="destinations", on_delete="CASCADE")
    client = ForeignKeyField(Client, backref="load_order_destinations")
    delivery_address = ForeignKeyField(ClientAddress, backref="load_order_destinations")
    sequence = IntegerField(default=1)
    observations = TextField(null=True)


class LoadOrderProduct(BaseModel):
    order = ForeignKeyField(LoadOrder, backref="products", on_delete="CASCADE")
    destination = ForeignKeyField(LoadOrderDestination, backref="products", on_delete="CASCADE", null=True)
    product = ForeignKeyField(Product, backref="load_order_details")
    quantity = FloatField()
    unit = CharField()
    observations = TextField(null=True)
    precio_neto_unitario = FloatField(default=0.0)
    descuento_porcentaje = FloatField(default=0.0)
    neto_subtotal = FloatField(default=0.0)
    descuento_importe = FloatField(default=0.0)
    neto_gravado = FloatField(default=0.0)
    iva_porcentaje = FloatField(default=21.0)
    iva_importe = FloatField(default=0.0)
    total = FloatField(default=0.0)
    lote = CharField(null=True)
    fecha_elaboracion = DateField(null=True)


class LoadOrderPallet(BaseModel):
    order = ForeignKeyField(LoadOrder, backref="pallets", on_delete="CASCADE")
    pallet_type = ForeignKeyField(PalletType, backref="load_order_details", null=True)
    sequence = IntegerField(default=1)
    measure = CharField(default="")
    weight = FloatField(default=0.0)
    quantity = IntegerField(default=1)
    observations = TextField(null=True)

    @property
    def kilos(self) -> Decimal:
        return sum((allocation.kilos for allocation in self.allocations), Decimal("0.000"))

    class Meta:
        indexes = ((('order', 'sequence'), True),)


class LoadOrderPalletAllocation(BaseModel):
    pallet = ForeignKeyField(LoadOrderPallet, backref="allocations", on_delete="CASCADE")
    destination = ForeignKeyField(LoadOrderDestination, backref="pallet_allocations", on_delete="CASCADE")
    product = ForeignKeyField(Product, backref="pallet_allocations")
    quantity = DecimalField(max_digits=14, decimal_places=3)
    peso_unitario_kg = DecimalField(max_digits=12, decimal_places=3)

    @property
    def kilos(self) -> Decimal:
        return (self.quantity * self.peso_unitario_kg).quantize(Decimal("0.001"))

    class Meta:
        indexes = ((('pallet', 'destination', 'product'), True),)


class LoadOrderLooseAllocation(BaseModel):
    """Mercadería despachada suelta / sin pallet, modelada explícitamente.

    Mantiene la trazabilidad de cliente/destino/producto/cantidad sin recurrir
    a pallets ficticios ni a un "pallet 0".
    """

    order = ForeignKeyField(LoadOrder, backref="loose_allocations", on_delete="CASCADE")
    destination = ForeignKeyField(LoadOrderDestination, backref="loose_allocations", on_delete="CASCADE")
    product = ForeignKeyField(Product, backref="loose_allocations")
    quantity = DecimalField(max_digits=14, decimal_places=3)
    peso_unitario_kg = DecimalField(max_digits=12, decimal_places=3)

    @property
    def kilos(self) -> Decimal:
        return (self.quantity * self.peso_unitario_kg).quantize(Decimal("0.001"))

    class Meta:
        indexes = ((("order", "destination", "product"), True),)


class LoadOrderStatusHistory(BaseModel):
    order = ForeignKeyField(LoadOrder, backref="status_history", on_delete="CASCADE")
    old_status = CharField(null=True)
    new_status = CharField()
    user = CharField(null=True)
    observation = TextField(null=True)


class LoadOrderClosure(BaseModel):
    """Auditable delivery-closure cycle for an issued load order."""

    STATUS_ACTIVE = "active"
    STATUS_REOPENED = "reopened"
    STATUSES = (STATUS_ACTIVE, STATUS_REOPENED)

    order = ForeignKeyField(LoadOrder, backref="closures", on_delete="CASCADE")
    status = CharField(default=STATUS_ACTIVE)
    active_marker = BooleanField(default=True, null=True)
    closed_at = DateTimeField(default=utc_now)
    closed_by = CharField()
    observations = TextField(null=True)
    no_payment_reason = TextField(null=True)
    reopened_at = DateTimeField(null=True)
    reopened_by = CharField(null=True)
    reopen_reason = TextField(null=True)

    @property
    def is_active(self) -> bool:
        return self.status == self.STATUS_ACTIVE and self.active_marker is True

    class Meta:
        indexes = ((("order", "active_marker"), True),)


class LoadOrderReturnLine(BaseModel):
    """Returned quantity captured at delivery closure without mutating the issued order."""

    closure = ForeignKeyField(LoadOrderClosure, backref="return_lines", on_delete="CASCADE")
    order_product = ForeignKeyField(LoadOrderProduct, backref="return_lines")
    client = ForeignKeyField(Client, backref="load_order_return_lines")
    quantity = FloatField()
    reason = TextField()
    unit_price = FloatField(default=0.0)
    credit_amount = FloatField(default=0.0)
    created_by = CharField(null=True)

    class Meta:
        indexes = ((("closure", "order_product"), True),)


class LoadOrderBudgetStatus(BaseModel):
    STATUS_PENDING = "Pendiente"
    STATUS_APPROVED = "Aprobado"
    STATUS_REJECTED = "Rechazado"
    STATUS_ANNULLED = "Anulado"
    STATUS_APPLIED = "Aplicado a cuenta corriente"

    order = ForeignKeyField(LoadOrder, backref="budget_statuses", on_delete="CASCADE")
    client = ForeignKeyField(Client, backref="budget_statuses")
    status = CharField(default=STATUS_PENDING)
