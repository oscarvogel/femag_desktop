"""Texto de seguimiento comercial para el informe de recompra.

El mensaje se arma con lo que el informe ya sabe del cliente: nombre/contacto,
producto, cantidades de los dos períodos, variación y situación. No es un
mensaje genérico: cambia si el cliente dejó de comprar, compró menos, compró
más, se mantuvo o es nuevo. Queda como borrador editable en el diálogo de
WhatsApp; nunca se envía automáticamente.
"""

from __future__ import annotations

from datetime import date

SPANISH_MONTHS = (
    "enero",
    "febrero",
    "marzo",
    "abril",
    "mayo",
    "junio",
    "julio",
    "agosto",
    "septiembre",
    "octubre",
    "noviembre",
    "diciembre",
)

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


def period_phrase(start: date, end: date) -> str:
    """Período en lenguaje natural: 'octubre de 2026' o 'del 1 al 12 de octubre'."""
    if start.year == end.year and start.month == end.month:
        month = SPANISH_MONTHS[start.month - 1]
        if start.day == 1:
            return f"{month} de {start.year}"
        return f"del {start.day} al {end.day} de {month}"
    return f"del {start:%d/%m/%Y} al {end:%d/%m/%Y}"


def _variation_text(value: object) -> str:
    if value is None:
        return ""
    number = f"{abs(float(value)):,.1f}"
    return f"{number.replace(',', 'X').replace('.', ',').replace('X', '.')}%"


def build_followup_message_for_row(
    row: dict,
    unit: object,
    *,
    client_name: str = "",
    current_period: str = "",
    previous_period: str = "",
) -> str:
    """Mensaje personalizado según la situación comercial del cliente."""
    status = str(row.get("status") or "").strip()
    product = str(row.get("product_name") or "").strip()
    product_ref = f" de {product}" if product else ""
    current_quantity = float(row.get("current_quantity") or 0)
    previous_quantity = float(row.get("previous_quantity") or 0)
    current_text = (
        f"{format_quantity(current_quantity)} {unit_label(unit, current_quantity)}"
    )
    previous_text = (
        f"{format_quantity(previous_quantity)} {unit_label(unit, previous_quantity)}"
    )
    variation = _variation_text(row.get("variation_kilos_percent"))

    greeting = f", {client_name.strip()}" if client_name and client_name.strip() else ""
    when = f" en {current_period}" if current_period else ""
    previous_when = (
        f" en el mismo período de {previous_period}"
        if previous_period
        else " en el período anterior"
    )

    if status == "sin_recompra":
        last_date = format_date(row.get("previous_last_date"))
        previous_phrase = (
            f"el mismo período de {previous_period}"
            if previous_period
            else "el período anterior"
        )
        if last_date:
            previous_clause = (
                f" Su última compra fue el {last_date}; en {previous_phrase} "
                f"había comprado {previous_text}."
            )
        else:
            previous_clause = (
                f" En {previous_phrase} había comprado {previous_text}."
            )
        return (
            f"Buen día{greeting}. No registramos compras{product_ref}{when}."
            f"{previous_clause} "
            "¿Quiere que le acerquemos una propuesta para reponer stock?"
        )

    if status == "compro_menos":
        if variation:
            comparison = (
                f", un {variation} menos que{previous_when} ({previous_text})"
            )
        else:
            comparison = f", menos que{previous_when} ({previous_text})"
        return (
            f"Buen día{greeting}. Notamos que{when} compró {current_text}"
            f"{product_ref}{comparison}. "
            "¿Quiere que le acerquemos una propuesta para reponer stock?"
        )

    if status == "compro_mas":
        if variation:
            comparison = f", un {variation} más que{previous_when} ({previous_text})"
        else:
            comparison = f", más que{previous_when} ({previous_text})"
        return (
            f"Buen día{greeting}. Gracias por su confianza:{when} compró "
            f"{current_text}{product_ref}{comparison}. "
            "¿Quiere que le reservemos stock para el próximo período?"
        )

    if status == "nuevo":
        return (
            f"Buen día{greeting}. Gracias por su primera compra{product_ref}{when} "
            f"({current_text}). ¿Quiere que le armemos un plan de reposición?"
        )

    if status == "igual":
        return (
            f"Buen día{greeting}. Vemos que{when} mantuvo su compra{product_ref} "
            f"en {current_text}. ¿Necesita reponer stock?"
        )

    if current_quantity > 0:
        return (
            f"Buen día{greeting}. Registramos su compra{product_ref}{when} "
            f"({current_text}). ¿Quisiera saber si necesita reponer su stock?"
        )
    return f"Buen día{greeting}. Quisiera saber si necesita reponer su stock."
