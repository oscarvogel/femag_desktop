from __future__ import annotations

from decimal import Decimal

from peewee import (
    BooleanField,
    CharField,
    DateField,
    DecimalField,
    ForeignKeyField,
    TextField,
)

from app.models.base import BaseModel
from app.models.masters import Product


class StockMovement(BaseModel):
    """Movimiento inmutable de stock (#572).

    El saldo **nunca** se guarda: se deriva sumando los movimientos. Por eso la
    tabla es de solo agregado: corregir no es reescribir el movimiento original
    sino agregar el contrario, que queda enlazado con ``reverses``.

    La cantidad es siempre positiva. La direccion la define ``movement_type``,
    y no un signo en el numero: asi no puede existir un movimiento que se
    contradiga a si mismo.

    ``source_ref`` identifica el documento de origen (por ejemplo
    ``production_part:41``) y va con indice unico junto con producto, tipo e
    ``is_reversal``. Es el mismo mecanismo que usa ``ClientAccountMovement``:
    garantiza que un mismo documento no genere dos veces el mismo movimiento,
    sin depender de un flag que alguien pueda dejar desactualizado.
    """

    TYPE_INITIAL_INVENTORY = "initial_inventory"
    TYPE_PRODUCTION = "production"
    TYPE_PURCHASE = "purchase"
    TYPE_IMPORT = "import"
    TYPE_DISPATCH = "dispatch"
    TYPE_ADJUSTMENT_POSITIVE = "adjustment_positive"
    TYPE_ADJUSTMENT_NEGATIVE = "adjustment_negative"

    INBOUND_TYPES = frozenset(
        {
            TYPE_INITIAL_INVENTORY,
            TYPE_PRODUCTION,
            TYPE_PURCHASE,
            TYPE_IMPORT,
            TYPE_ADJUSTMENT_POSITIVE,
        }
    )
    OUTBOUND_TYPES = frozenset({TYPE_DISPATCH, TYPE_ADJUSTMENT_NEGATIVE})
    ALL_TYPES = INBOUND_TYPES | OUTBOUND_TYPES

    product = ForeignKeyField(Product, backref="stock_movements")
    movement_type = CharField()
    # 3 decimales igual que ``Product.peso_unitario_kg``: las sumas en SQL son
    # exactas y el stock en kg no necesita mas precision.
    quantity_kg = DecimalField(max_digits=14, decimal_places=3)
    movement_date = DateField(null=True)
    source_ref = CharField()
    description = TextField()
    observations = TextField(null=True)
    is_reversal = BooleanField(default=False)
    reverses = ForeignKeyField("self", backref="reversal_movements", null=True)
    created_by = CharField(null=True)

    class Meta:
        table_name = "stock_movement"
        # Indice unico = idempotencia. El tipo de indice se calcula sobre la
        # columna, y `product` es una FK cuya columna es `product_id`: como el
        # indice cubre cuatro columnas no choca con el indice de la FK.
        indexes = ((("source_ref", "product", "movement_type", "is_reversal"), True),)

    @property
    def is_inbound(self) -> bool:
        return self.movement_type in self.INBOUND_TYPES

    @property
    def signed_quantity_kg(self) -> Decimal:
        """Cantidad con signo, derivada del tipo. Es la base del saldo."""
        quantity = Decimal(str(self.quantity_kg or 0))
        return quantity if self.is_inbound else -quantity
