from __future__ import annotations

from datetime import date, timedelta


#: Los movimientos manuales son cargas administrativas, no proyecciones.
#: 180 días deja margen para una carga adelantada razonable y bloquea el typo
#: de año que originó el #899 (2027-08-31 en un movimiento de 2026-09-28).
MAX_FUTURE_DAYS = 180
MIN_MOVEMENT_DATE = date(2000, 1, 1)


class AccountDateError(ValueError):
    """La fecha de un movimiento cae fuera del rango administrativo."""


def validate_movement_date(
    value: date | None,
    *,
    today: date | None = None,
    max_future_days: int = MAX_FUTURE_DAYS,
) -> date:
    """Normaliza y valida la fecha de un movimiento de cuenta corriente.

    Acepta el pasado y el presente; rechaza fechas absurdamente viejas o
    demasiado adelantadas. El límite es deliberadamente menor a un año: el caso
    real del #899 tenía 337 días de diferencia y una regla de "más de un año"
    no lo habría detectado.
    """
    current = today or date.today()
    normalized = value or current
    if normalized < MIN_MOVEMENT_DATE:
        raise AccountDateError(
            f"La fecha del movimiento no puede ser anterior al "
            f"{MIN_MOVEMENT_DATE:%d/%m/%Y}."
        )
    limit = current + timedelta(days=max_future_days)
    if normalized > limit:
        raise AccountDateError(
            f"La fecha del movimiento no puede ser posterior al "
            f"{limit:%d/%m/%Y}: es más de {max_future_days} días en el futuro."
        )
    return normalized
