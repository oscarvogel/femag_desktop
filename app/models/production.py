from peewee import CharField, DateTimeField, DecimalField, TextField

from app.models.base import BaseModel, utc_now


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
