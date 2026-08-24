from datetime import date

from peewee import BooleanField, CharField, DateField, DecimalField, ForeignKeyField, IntegerField, TextField

from app.models.base import BaseModel
from app.models.load_orders import LoadOrder
from app.models.masters import Carrier, Client, ClientAddress, Driver, Product, Truck


class RemittanceSeries(BaseModel):
    """Talonario físico utilizado para numerar remitos preimpresos."""

    name = CharField(unique=True)
    document_type = CharField(default="Remito R")
    point_of_sale = CharField()
    next_number = IntegerField(default=1)
    end_number = IntegerField(null=True)
    active = BooleanField(default=True)
    is_default = BooleanField(default=False)
    created_by = CharField(null=True)
    updated_by = CharField(null=True)


class Remittance(BaseModel):
    STATUS_DRAFT = "Borrador"
    STATUS_ISSUED = "Emitido"
    STATUS_ANNULLED = "Anulado"
    STATUSES = (STATUS_DRAFT, STATUS_ISSUED, STATUS_ANNULLED)

    # Identificador interno FEMAG, independiente del formulario fisico preimpreso.
    remittance_number = CharField(unique=True)

    # Numeracion del formulario fisico (talonario). Se guarda separada para no
    # confundirla con la numeracion interna ni asumir emision fiscal propia.
    physical_point_of_sale = CharField(null=True)
    physical_number = CharField(null=True)

    date = DateField(default=date.today)
    status = CharField(default=STATUS_DRAFT)

    client = ForeignKeyField(Client, backref="remittances")
    delivery_address = ForeignKeyField(ClientAddress, backref="remittances")
    source_order = ForeignKeyField(LoadOrder, backref="remittances", null=True, on_delete="SET NULL")
    series = ForeignKeyField(RemittanceSeries, backref="remittances", null=True, on_delete="SET NULL")
    carrier = ForeignKeyField(Carrier, backref="remittances", null=True, on_delete="SET NULL")
    truck = ForeignKeyField(Truck, backref="remittances", null=True, on_delete="SET NULL")
    driver = ForeignKeyField(Driver, backref="remittances", null=True, on_delete="SET NULL")

    # Snapshot de los datos impresos: una vez emitido, el remito no depende de
    # cambios posteriores en los maestros ni en la orden de carga.
    client_name = CharField()
    client_cuit = CharField(null=True)
    client_iva_condition = CharField(null=True)
    delivery_address_text = CharField()
    delivery_city = CharField(null=True)
    delivery_province = CharField(null=True)
    document_reference = CharField(null=True)
    carrier_name = CharField(null=True)
    carrier_cuit = CharField(null=True)
    truck_domain = CharField(null=True)
    driver_name = CharField(null=True)
    driver_document = CharField(null=True)

    observations = TextField(null=True)
    created_by = CharField(null=True)
    updated_by = CharField(null=True)
    issued_by = CharField(null=True)
    annulled_by = CharField(null=True)
    annulment_reason = TextField(null=True)

    class Meta:
        indexes = (
            (("physical_point_of_sale", "physical_number"), True),
        )


class RemittanceItem(BaseModel):
    remittance = ForeignKeyField(Remittance, backref="items", on_delete="CASCADE")
    product = ForeignKeyField(Product, backref="remittance_items")
    product_name = CharField()
    printed_description = CharField()
    quantity = DecimalField(max_digits=14, decimal_places=3)
    unit = CharField()
    lot = CharField(null=True)
    production_date = DateField(null=True)
    observations = TextField(null=True)
