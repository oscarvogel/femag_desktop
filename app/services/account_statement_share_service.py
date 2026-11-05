from __future__ import annotations

from urllib.parse import urlencode

from app.services.whatsapp_phone_classifier import (
    ESTADO_CELULAR,
    ESTADO_POSIBLE,
    ESTADO_VACIO,
    clasificar_telefono,
)


def normalize_whatsapp_phone(phone: str) -> str:
    """Devuelve un numero enviable o rechaza el envio.

    Solo se aceptan celulares sin ambiguedad. Un local de 10 u 11 digitos puede
    ser un fijo o un celular escrito sin el "15": antes se mandaba como movil y
    eso generaba envios a lineas fijas. Ahora se rechaza para que el operador lo
    revise y corrija el telefono (#759).
    """

    classification = clasificar_telefono(phone)
    if classification.estado == ESTADO_CELULAR:
        return classification.normalizado
    if classification.estado == ESTADO_VACIO:
        raise ValueError("El cliente no tiene un telefono valido para WhatsApp.")
    if classification.estado == ESTADO_POSIBLE:
        raise ValueError(
            "El telefono es dudoso para WhatsApp: "
            f"{classification.motivo}. Reviselo y confirme el numero antes de enviar."
        )
    raise ValueError(
        f"El telefono no es valido para WhatsApp: {classification.motivo}."
    )


def build_whatsapp_url(client_name: str, phone: str) -> str:
    normalized_phone = normalize_whatsapp_phone(phone)
    message = f"Hola {client_name}, le compartimos su extracto de cuenta corriente."
    return f"https://wa.me/{normalized_phone}?{urlencode({'text': message})}"
