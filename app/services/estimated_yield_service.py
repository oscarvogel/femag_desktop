from __future__ import annotations

from decimal import Decimal, InvalidOperation

from app.models.system import AppParameter


ESTIMATED_YIELD_KEY = "raw_material_estimated_yield_pct"

# El 22,33 % es el valor que propuso la planta para las cargas que llegan sin
# rinde medido. Es solo el valor por defecto: el numero que se aplica sale
# siempre del parametro, nunca de una constante escrita en el calculo.
DEFAULT_ESTIMATED_YIELD_PCT = Decimal("22.33")

MAX_ESTIMATED_YIELD_PCT = Decimal("100")


def _decimal(value) -> Decimal:
    try:
        result = Decimal(str(value)).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError("El rinde estimado debe ser un numero valido.") from exc
    if result <= 0:
        raise ValueError("El rinde estimado debe ser mayor a cero.")
    if result > MAX_ESTIMATED_YIELD_PCT:
        raise ValueError("El rinde estimado no puede superar el 100 %.")
    return result


class EstimatedYieldService:
    """Rinde estimado para las cargas que llegan sin rinde medido (#722).

    El valor es un parametro operativo: lo define la planta. El ticket
    importado guarda tanto el valor aplicado como su origen ("estimated"), de
    modo que el rendimiento de un mes se puede mostrar partido en lugar de
    mezclado con lo que la planta midio de verdad.
    """

    @classmethod
    def estimated_yield_pct(cls) -> Decimal:
        row = AppParameter.get_or_none(AppParameter.key == ESTIMATED_YIELD_KEY)
        if row is None or not (row.value or "").strip():
            return DEFAULT_ESTIMATED_YIELD_PCT
        try:
            return _decimal(row.value)
        except ValueError:
            # Un parametro corrupto no puede voltear la importacion: se cae al
            # valor por defecto y el ticket queda marcado como estimado.
            return DEFAULT_ESTIMATED_YIELD_PCT

    @classmethod
    def set_estimated_yield_pct(cls, value) -> Decimal:
        normalized = _decimal(value)
        row, _created = AppParameter.get_or_create(
            key=ESTIMATED_YIELD_KEY,
            defaults={"value": format(normalized, "f")},
        )
        row.value = format(normalized, "f")
        row.save()
        return normalized
