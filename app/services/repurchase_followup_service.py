"""Texto de seguimiento comercial para el informe de recompra.

El mensaje se arma con la última compra real del cliente dentro del informe:
si compró en el período actual se usa esa fecha/cantidad; si no, la del
período anterior. El texto queda como borrador editable en el diálogo de
WhatsApp, no se envía automáticamente.
"""

from __future__ import annotations

UNIT_PLURALS = {
    "bolsa": "bolsas",
    "bolsón": "bolsones",
    "bolson": "bolsones",
    "unidad": "unidades",
    "caja": "cajas",
    "litro": "litros",
    "kilo": "kilos",
    "kg": "kg",
    "pallet": "pallets",
    "saco": "sacos",
}


def format_quantity(value: object) -> str:
    """Cantidad con separador de miles local y sin ceros de más."""
    quantity = float(value or 0)
    if abs(quantity - round(quantity)) < 0.0005:
        text = f"{int(round(quantity)):,}"
    else:
        text = f"{quantity:,.3f}"
    return text.replace(",", "X").replace(".", ",").replace("X", ".")


def format_date(value: object) -> str:
    """Fecha ISO (YYYY-MM-DD) a dd/mm/yyyy; deja otros formatos como vienen."""
    if not value:
        return ""
    text = str(value)
    try:
        year, month, day = text[:10].split("-")
        return f"{day}/{month}/{year}"
    except ValueError:
        return text


def unit_label(unit: object, quantity: float) -> str:
    key = str(unit or "unidad").strip().lower()
    if abs(float(quantity) - 1) < 0.0005:
        return key
    return UNIT_PLURALS.get(key, key if key.endswith("s") else f"{key}s")


def last_purchase(row: dict) -> tuple[float, str | None]:
    """(cantidad, fecha ISO) de la compra más reciente del cliente en la fila."""
    candidates: list[tuple[str, float]] = []
    for date_key, quantity_key in (
        ("current_last_date", "current_quantity"),
        ("previous_last_date", "previous_quantity"),
    ):
        purchase_date = row.get(date_key)
        if purchase_date:
            candidates.append((str(purchase_date), float(row.get(quantity_key) or 0)))
    if not candidates:
        return 0.0, None
    purchase_date, quantity = max(candidates, key=lambda item: item[0])
    return quantity, purchase_date


def build_followup_message(
    *,
    quantity: float,
    unit: object,
    purchase_date: object = None,
) -> str:
    if purchase_date and float(quantity or 0) > 0:
        return (
            f"Buen día. Detectamos su última compra de "
            f"{format_quantity(quantity)} {unit_label(unit, quantity)} "
            f"el día {format_date(purchase_date)}. "
            "Quisiera saber si necesita reponer su stock."
        )
    return "Buen día. Quisiera saber si necesita reponer su stock."


def build_followup_message_for_row(row: dict, unit: object) -> str:
    quantity, purchase_date = last_purchase(row)
    return build_followup_message(quantity=quantity, unit=unit, purchase_date=purchase_date)
