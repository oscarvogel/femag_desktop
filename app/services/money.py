"""Fuente única de cálculo monetario de FEMAG.

Regla del proyecto: LO MOSTRADO = LO CALCULADO = LO PERSISTIDO = LO COBRADO.

Este módulo centraliza el cálculo de un renglón comercial para que el precio
unitario, el subtotal, el descuento, el neto gravado, el IVA y el total se
obtengan siempre de la misma rutina y con la misma política de redondeo.

Política monetaria
------------------

- Precisión: 2 decimales (``MONEY_EXPONENT``) para importes monetarios.
- Redondeo: ``ROUND_HALF_UP`` (redondeo comercial, no bankers).
- Cantidades: 3 decimales (``QUANTITY_EXPONENT``), suficiente para
  fracciones de bulto y no usado como importe.
- Porcentajes: se conservan como ``Decimal`` sin cuantizar hasta el momento
  de aplicar el importe; el importe resultante sí se cuantiza a 2 decimales.
- ``Decimal`` siempre se construye desde ``str``/texto o desde enteros, nunca
  desde ``float``: ``Decimal(0.1)`` arrastra el error binario del float y
  ``Decimal(str(0.1))`` tampoco es necesario para un importe ya redondeado.

Sobre los tipos de columna
--------------------------

Los modelos de FEMAG guardan el dinero en ``FloatField`` (MySQL ``DOUBLE``).
No se cambia el tipo de columna en este hotfix: hacerlo exigiría una
migración destructiva sobre datos ya emitidos. En su lugar, el dinero se
calcula en ``Decimal`` y recién al persistir se convierte a ``float``, de
modo que el valor guardado sea el importe redondeado exacto y no una
aproximación binaria.
"""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP, localcontext
from typing import Iterable, NamedTuple

# Precisión y redondeo del circuito monetario.
MONEY_EXPONENT = Decimal("0.01")
QUANTITY_EXPONENT = Decimal("0.001")
ROUNDING = ROUND_HALF_UP

ZERO_MONEY = Decimal("0.00")
ZERO_QUANTITY = Decimal("0.000")
HUNDRED = Decimal("100")

# Tolerancia de comparación monetaria: dos importes se consideran iguales si
# coinciden al centavo. Es exactamente la precisión con la que se emite.
MONEY_TOLERANCE = Decimal("0.005")


class MonetaryIntegrityError(RuntimeError):
    """El detalle de un documento no suma su total general.

    Se lanza antes de emitir o imprimir cualquier presupuesto para impedir
    que FEMAG genere un documento cuya suma de renglones difiera del total.
    """


def to_decimal(value, default: str = "0") -> Decimal:
    """Convierte a ``Decimal`` sin arrastrar error binario de ``float``.

    Acepta ``None``, ``str``, ``int``, ``float`` y ``Decimal``. Para ``float``
    se usa ``repr``, que en Python 3 devuelve la representación decimal más
    corta que reconstruye el valor (``0.1`` -> ``'0.1'``), evitando el error
    de ``Decimal(0.1)``.
    """
    if value is None:
        return Decimal(default)
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):
        return Decimal(int(value))
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        return Decimal(repr(value))
    if isinstance(value, str):
        cleaned = value.strip().replace(",", ".")
        if not cleaned:
            return Decimal(default)
        return Decimal(cleaned)
    return Decimal(str(value))


def quantize_money(value) -> Decimal:
    """Cuantiza a 2 decimales con redondeo comercial ``ROUND_HALF_UP``."""
    return to_decimal(value).quantize(MONEY_EXPONENT, rounding=ROUNDING)


def quantize_quantity(value) -> Decimal:
    """Cuantiza una cantidad a 3 decimales."""
    return to_decimal(value).quantize(QUANTITY_EXPONENT, rounding=ROUNDING)


def money_equal(left, right) -> bool:
    """Compara dos importes a la precisión monetaria de FEMAG."""
    return quantize_money(left) == quantize_money(right)


def money_sum(values: Iterable) -> Decimal:
    """Suma importes ya cuantizados a 2 decimales.

    Se cuantiza el acumulador y cada sumando para que el resultado no dependa
    del orden ni de acumulaciones binarias de ``float``.
    """
    total = ZERO_MONEY
    for value in values:
        total += quantize_money(value)
    return quantize_money(total)


def money_to_float(value) -> float:
    """Convierte un importe ya redondeado a ``float`` para persistirlo.

    Se llama únicamente en la frontera con la base, nunca para calcular.
    """
    return float(quantize_money(value))


class LineAmounts(NamedTuple):
    """Importes de un renglón, todos cuantizados a la precisión monetaria."""

    quantity: Decimal
    unit_price: Decimal
    discount_percentage: Decimal
    net_subtotal: Decimal
    discount_amount: Decimal
    net_taxable: Decimal
    vat_percentage: Decimal
    vat_amount: Decimal
    total: Decimal


def compute_line_amounts(
    *,
    quantity,
    unit_price,
    discount_percentage=None,
    vat_percentage=None,
    quantity_hint: bool = False,
) -> LineAmounts:
    """Calcula todos los importes de un renglón en una sola operación.

    Es la única rutina autorizada para el circuito de presupuestos. Derivada
    de las reglas comerciales ya existentes en el sistema:

        neto_subtotal = cantidad * precio_unitario
        descuento     = neto_subtotal * descuento% / 100
        neto_gravado  = neto_subtotal - descuento
        iva           = neto_gravado * iva% / 100
        total         = neto_gravado + iva

    Cada importe se redondea a 2 decimales con ``ROUND_HALF_UP`` en el momento
    de calcularse, de modo que el total sea siempre la suma exacta de los
    importes redondeados que se muestran al usuario. Esto elimina la
    divergencia entre ``SUM(redondeado)`` y ``redondeo(SUM)``.

    Los porcentajes se aplican con ``localcontext`` de precisión ampliada
    para que la división no introduzca ruido antes del redondeo final.
    """
    qty = (
        quantize_quantity(quantity)
        if quantity_hint
        else to_decimal(quantity)
    )
    price = quantize_money(unit_price)
    discount_pct = (
        ZERO_MONEY if discount_percentage is None else to_decimal(discount_percentage)
    )
    vat_pct = ZERO_MONEY if vat_percentage is None else to_decimal(vat_percentage)

    net_subtotal = quantize_money(qty * price)

    with localcontext() as context:
        context.prec = 34
        discount_amount = quantize_money(
            net_subtotal * discount_pct / HUNDRED
        )
        net_taxable = quantize_money(net_subtotal - discount_amount)
        vat_amount = quantize_money(net_taxable * vat_pct / HUNDRED)

    total = quantize_money(net_taxable + vat_amount)

    return LineAmounts(
        quantity=qty,
        unit_price=price,
        discount_percentage=discount_pct,
        net_subtotal=net_subtotal,
        discount_amount=discount_amount,
        net_taxable=net_taxable,
        vat_percentage=vat_pct,
        vat_amount=vat_amount,
        total=total,
    )


class BudgetTotals(NamedTuple):
    """Totales de cabecera derivados de los mismos renglones que se imprimen."""

    net_amount: Decimal
    discount_amount: Decimal
    vat_amount: Decimal
    total_amount: Decimal


def compute_totals(lines: Iterable[LineAmounts]) -> BudgetTotals:
    """Deriva los totales de cabecera de los mismos renglones mostrados.

    El total general no se recalcula por otra vía: es la suma de los totales
    de renglón ya cuantizados, por lo que ``total_amount`` es por
    construcción igual a la suma de lo que el usuario ve en el PDF.
    """
    materialized = list(lines)
    return BudgetTotals(
        net_amount=money_sum(line.net_subtotal for line in materialized),
        discount_amount=money_sum(line.discount_amount for line in materialized),
        vat_amount=money_sum(line.vat_amount for line in materialized),
        total_amount=money_sum(line.total for line in materialized),
    )


def totals_from_persisted_items(items: Iterable) -> BudgetTotals:
    """Totales de cabecera a partir de renglones ya persistidos.

    Se usa para validar y para reemitir documentos existentes sin volver a
    calcular el commerce desde cero.
    """
    materialized = list(items)
    return BudgetTotals(
        net_amount=money_sum(item.net_subtotal for item in materialized),
        discount_amount=money_sum(item.discount_amount for item in materialized),
        vat_amount=money_sum(item.vat_amount for item in materialized),
        total_amount=money_sum(item.total for item in materialized),
    )


def assert_totals_match_items(
    *,
    items_totals: BudgetTotals,
    header_totals: BudgetTotals,
    document_reference: str,
    order_reference: str | None = None,
    client_name: str | None = None,
) -> None:
    """Verifica que el detalle sume el total general antes de emitir.

    Compara con la precisión monetaria definida. Si no coincide, lanza
    ``MonetaryIntegrityError`` indicando presupuesto, orden, cliente y ambos
    importes, en lugar de emitir un documento incorrecto en silencio.
    """
    problems = []
    checks = (
        ("total", items_totals.total_amount, header_totals.total_amount),
        ("neto", items_totals.net_amount, header_totals.net_amount),
        ("descuento", items_totals.discount_amount, header_totals.discount_amount),
        ("iva", items_totals.vat_amount, header_totals.vat_amount),
    )
    for label, from_items, from_header in checks:
        if abs(from_items - from_header) > MONEY_TOLERANCE:
            problems.append(
                f"{label}: detalle {from_items} vs cabecera {from_header} "
                f"(diferencia {from_items - from_header})"
            )
    if not problems:
        return

    contexto = [f"Presupuesto {document_reference}"]
    if order_reference:
        contexto.append(f"Orden {order_reference}")
    if client_name:
        contexto.append(f"Cliente {client_name}")
    raise MonetaryIntegrityError(
        "Inconsistencia monetaria: la suma del detalle no coincide con el total "
        f"general de {', '.join(contexto)}. "
        + "; ".join(problems)
        + ". No se emite el documento para evitar importes contradictorios."
    )