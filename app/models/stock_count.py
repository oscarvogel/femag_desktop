from __future__ import annotations

from decimal import Decimal

from peewee import (
    CharField,
    DateField,
    DateTimeField,
    DecimalField,
    ForeignKeyField,
    TextField,
)

from app.models.base import BaseModel, utc_now
from app.models.masters import Product

ZERO = Decimal("0.000")


class StockCount(BaseModel):
    """Sesion de conteo fisico de deposito (#574).

    Es una sesion y no un formulario suelto a propósito: se cuentan los
    productos, se revisan las diferencias y recien ahi se cierran. Cerrar es lo
    que genera los movimientos de ajuste.

    Lo que se guarda en cada linea es **el stock que el libro mostraba al
    contar**, no el de ahora. Si entre el conteo y el cierre se emite una orden,
    el ajuste tiene que compararse contra lo que el operador vio, no contra un
    numero que ya cambio sola: si no, el conteo estariaria ajustando una
    diferencia que en realidad cambio por otra operacion.
    """

    STATUS_OPEN = "open"
    STATUS_CLOSED = "closed"

    count_date = DateField()
    counted_by = CharField(max_length=80, null=True)
    notes = TextField(null=True)
    status = CharField(default=STATUS_OPEN)
    closed_at = DateTimeField(null=True)
    closed_by = CharField(max_length=80, null=True)

    class Meta:
        table_name = "stock_count"
        indexes = ((("status", "count_date"), False),)

    @property
    def is_open(self) -> bool:
        return self.status == self.STATUS_OPEN


class StockCountLine(BaseModel):
    """Una linea del conteo: lo que decia el libro y lo que se conto."""

    count = ForeignKeyField(StockCount, backref="lines", on_delete="CASCADE")
    product = ForeignKeyField(Product, backref="stock_count_lines")
    # Copia del saldo del libro en el momento del conteo.
    calculated_kg = DecimalField(max_digits=14, decimal_places=3)
    counted_kg = DecimalField(max_digits=14, decimal_places=3, default=ZERO)
    reason = TextField(null=True)

    class Meta:
        table_name = "stock_count_line"
        # Un producto se cuenta una sola vez por sesion: dos renglones del mismo
        # producto harian ajustes que se cancelan entre si.
        indexes = ((("count", "product"), True),)

    @property
    def difference_kg(self) -> Decimal:
        """Contado menos calculado. Positivo hay mas de lo que dice el libro."""
        return Decimal(str(self.counted_kg or 0)) - Decimal(str(self.calculated_kg or 0))

    @property
    def has_difference(self) -> bool:
        return self.difference_kg != ZERO
