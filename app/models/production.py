from peewee import (
    CharField,
    DateField,
    DateTimeField,
    DecimalField,
    ForeignKeyField,
    IntegerField,
    TextField,
)

from app.models.base import BaseModel, utc_now
from app.models.masters import Product


class RawMaterialReceipt(BaseModel):
    """Snapshot inmutable/auditable de un ticket finalizado en femagfab.movi."""

    source_key = CharField(max_length=180, unique=True)
    source_instance = CharField(max_length=80, default="femagfab")
    source_comp = CharField(max_length=12)
    source_hash = CharField(max_length=64)

    received_at = DateTimeField()
    supplier_code = CharField(max_length=4)
    supplier_name = CharField(max_length=80, null=True)
    product_code = CharField(max_length=2)
    product_name = CharField(max_length=80, null=True)

    gross_kg = DecimalField(max_digits=12, decimal_places=2)
    tare_kg = DecimalField(max_digits=12, decimal_places=2)
    net_kg = DecimalField(max_digits=12, decimal_places=2)
    payable_kg = DecimalField(max_digits=12, decimal_places=2)
    earth_discount_pct = DecimalField(max_digits=7, decimal_places=2, default=0)
    cepa_discount_pct = DecimalField(max_digits=7, decimal_places=2, default=0)
    yield_1 = DecimalField(max_digits=7, decimal_places=2, default=0)
    yield_2 = DecimalField(max_digits=7, decimal_places=2, default=0)
    yield_3 = DecimalField(max_digits=7, decimal_places=2, default=0)
    yield_average = DecimalField(max_digits=7, decimal_places=2)
    legacy_starch_kg = DecimalField(max_digits=12, decimal_places=2, default=0)
    theoretical_starch_kg = DecimalField(max_digits=12, decimal_places=2)
    source_payload = TextField()
    imported_at = DateTimeField(default=utc_now)

    class Meta:
        table_name = "raw_material_receipt"
        indexes = ((("received_at",), False), (("source_comp",), False))


class ProductionPart(BaseModel):
    """Parte de embolsado por fecha y turno.

    A partir de #580 el parte ya no pide kg de mandioca procesada ni de fécula
    producida: en planta esos datos no se pueden medir. Lo que se registra es
    cuántas bolsas de cada producto se embolsaron, en :class:`ProductionBag`.
    """

    production_date = DateField()
    shift = CharField(max_length=40)
    observations = TextField(null=True)

    class Meta:
        table_name = "production_part"
        indexes = ((("production_date", "shift"), False),)


class ProductionBag(BaseModel):
    """Bolsas embolsadas de un producto terminado dentro de un turno.

    ``unit_weight_kg`` es una copia del peso del producto al momento del
    registro: si despues se corrige el maestro, la produccion ya registrada
    no debe cambiar. ``kg`` queda congelado por el mismo motivo.
    """

    part = ForeignKeyField(ProductionPart, backref="bags", on_delete="CASCADE")
    product = ForeignKeyField(Product, backref="production_bags", on_delete="RESTRICT")
    bags = IntegerField()
    unit_weight_kg = DecimalField(max_digits=12, decimal_places=3)
    kg = DecimalField(max_digits=14, decimal_places=2)

    class Meta:
        table_name = "production_bag"
        indexes = ((("part",), False), (("product",), False))
