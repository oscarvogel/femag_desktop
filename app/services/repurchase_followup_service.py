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


def message_unit_label(unit: object, quantity: float) -> str:
    """En el mensaje, bolsas/unidades se dicen genéricamente 'unidades'.

    Es el lenguaje que pidió Dante: "3.000 unidades de F. de mandioca". Para
    kg, litros u otras unidades se mantiene la unidad real para no deformar la
    información.
    """
    key = str(unit or "unidad").strip().lower()
    if key in {"bolsa", "bolsón", "bolson", "unidad", "unidades"}:
        return "unidad" if abs(float(quantity) - 1) < 0.0005 else "unidades"
    return unit_label(unit, quantity)


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
    if number.endswith(".0"):
        number = number[:-2]
    number = number.replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{number}%"


def build_followup_message_for_row(
    row: dict,
    unit: object,
    *,
    client_name: str = "",
    current_period: str = "",
    previous_period: str = "",
) -> str:
    """Mensaje personalizado, con el lenguaje comercial que pidió Dante."""
    status = str(row.get("status") or "").strip()
    product = str(row.get("product_name") or "").strip()
    product_ref = f" de {product}" if product else ""
    current_quantity = float(row.get("current_quantity") or 0)
    previous_quantity = float(row.get("previous_quantity") or 0)
    current_text = (
        f"{format_quantity(current_quantity)} "
        f"{message_unit_label(unit, current_quantity)}"
    )
    previous_text = (
        f"{format_quantity(previous_quantity)} "
        f"{message_unit_label(unit, previous_quantity)}"
    )
    variation = _variation_text(row.get("variation_kilos_percent"))
    greeting = f", {client_name.strip()}" if client_name and client_name.strip() else ""
    current_when = f" en {current_period}" if current_period else ""
    comparison_when = (
        f" en el mismo período de {previous_period}"
        if previous_period
        else " en el período anterior"
    )
    current_last_date = format_date(row.get("current_last_date"))
    previous_last_date = format_date(row.get("previous_last_date"))

    if status == "sin_recompra":
        if previous_last_date:
            opening = (
                f"Buen día{greeting}. Vi que su última compra{product_ref} "
                f"fue el {previous_last_date}; "
            )
            return (
                f"{opening}en el mismo período de {previous_period or 'el período anterior'} "
                f"había comprado {previous_text}, y{current_when or ' en el período actual'} "
                "no registramos compras. "
                "¿Quería saber si necesita reponer stock?"
            )
        return (
            f"Buen día{greeting}. En el mismo período de "
            f"{previous_period or 'el período anterior'} había comprado {previous_text}, "
            f"y{current_when or ' en el período actual'} no registramos compras. "
            "¿Quería saber si necesita reponer stock?"
        )

    if current_last_date:
        opening = (
            f"Buen día{greeting}. Vi que su última compra{product_ref} "
            f"fue el {current_last_date}; "
        )
        bought = (
            f"en {current_period} compró {current_text}."
            if current_period
            else f"compró {current_text}."
        )
    else:
        opening = f"Buen día{greeting}. "
        bought = (
            f"En {current_period} compró {current_text}."
            if current_period
            else f"Compró {current_text}."
        )

    if status == "compro_menos":
        if variation:
            comparison = (
                f" Fue un {variation} menos que{comparison_when} "
                f"({previous_text})."
            )
        else:
            comparison = f" Fue menos que{comparison_when} ({previous_text})."
        question = " ¿Quería saber si necesita reponer stock?"
    elif status == "compro_mas":
        if variation:
            comparison = (
                f" Fue un {variation} más que{comparison_when} "
                f"({previous_text})."
            )
        else:
            comparison = f" Fue más que{comparison_when} ({previous_text})."
        question = " ¿Quiere que le reservemos stock para el próximo período?"
    elif status == "nuevo":
        comparison = " Gracias por su primera compra."
        question = " ¿Quería saber si necesita reponer stock?"
    elif status == "igual":
        comparison = " Se mantuvo en el mismo volumen."
        question = " ¿Quería saber si necesita reponer stock?"
    else:
        comparison = ""
        question = " ¿Quería saber si necesita reponer stock?"

    return f"{opening}{bought}{comparison}{question}"
