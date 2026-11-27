"""Cotizaciones historicas inmutables por fecha, moneda, tipo y fuente.

Convencion monetaria
--------------------
``base_currency`` es la moneda cotizada (1 unidad) y ``quote_currency`` es la
moneda en la que se expresa el precio. Para USD/ARS, ``buy_rate`` y
``sell_rate`` son **pesos argentinos por un dolar estadounidense**.

Cada correccion de una fuente crea una nueva ``version``; la version anterior
nunca se modifica ni se elimina. La combinacion
``(base, quote, tipo, fuente, fecha, version)`` es unica.
"""

from __future__ import annotations

from peewee import CharField, DateField, DateTimeField, DecimalField, IntegerField

from app.models.base import BaseModel, utc_now


class ExchangeRate(BaseModel):
    #: Origen del registro. No se aceptan origenes libres.
    ORIGIN_API = "api"
    ORIGIN_HISTORICAL_IMPORT = "historical_import"
    ORIGIN_MANUAL = "manual"
    ORIGIN_OTHER = "other"
    ORIGINS = (
        ORIGIN_API,
        ORIGIN_HISTORICAL_IMPORT,
        ORIGIN_MANUAL,
        ORIGIN_OTHER,
    )

    #: Puntas disponibles para consultas y conversiones.
    SIDE_BUY = "buy"
    SIDE_SELL = "sell"
    SIDE_AVERAGE = "average"
    SIDES = (SIDE_BUY, SIDE_SELL, SIDE_AVERAGE)

    base_currency = CharField(max_length=3)
    quote_currency = CharField(max_length=3)
    effective_date = DateField()
    rate_type = CharField(max_length=32)
    buy_rate = DecimalField(max_digits=18, decimal_places=6)
    sell_rate = DecimalField(max_digits=18, decimal_places=6)
    source = CharField(max_length=64)
    fetched_at = DateTimeField(default=utc_now)
    origin = CharField(max_length=32, default=ORIGIN_OTHER)
    version = IntegerField(default=1)
    #: SHA256 de los datos normalizados. Permite detectar una importacion
    #: repetida sin comparar Decimales ni confiar en el orden de los campos.
    fingerprint = CharField(max_length=64)
    created_by = CharField(null=True)

    def save(self, *args, **kwargs):
        if self.id is not None:
            raise ValueError(
                "Las cotizaciones historicas son inmutables: "
                "registre una nueva version en lugar de modificar la existente."
            )
        return super().save(*args, **kwargs)

    def delete_instance(self, *args, **kwargs):
        raise ValueError(
            "Las cotizaciones historicas no se eliminan: "
            "registre una nueva version si la fuente corrige el dato."
        )

    class Meta:
        indexes = (
            # Indice unico de version y, a la vez, el que resuelve la consulta
            # habitual por moneda, tipo, fuente y fecha.
            (
                (
                    "base_currency",
                    "quote_currency",
                    "rate_type",
                    "source",
                    "effective_date",
                    "version",
                ),
                True,
            ),
            # Consultas por par/fecha/tipo sin fijar fuente (para detectar
            # fuentes multiples) y rangos historicos.
            (
                ("base_currency", "quote_currency", "effective_date", "rate_type"),
                False,
            ),
            # Consultas por proveedor y fecha.
            (("source", "effective_date"), False),
        )
