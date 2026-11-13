"""Decide que numero de WhatsApp es el destino valido de un contacto (#923).

Es un modulo **puro**: no toca la base ni la interfaz, para poder testearlo
entero y para que la regla viva en un solo lugar.

La regla:

- Si el contacto tiene ``whatsapp_phone`` cargado, ese manda.
- Si no, se cae a ``phone``, pero **solo si** ``phone`` es un celular sin
  ambiguedad: un local de 10 u 11 digitos puede ser una linea fija o un
  celular escrito sin el "15", y mandarle ahi es adivinar.
- Si el ``whatsapp_phone`` cargado no es un celular, **no** se cae al
  telefono: el operador lo cargo a proposito, y mandar a otro numero seria
  mandar a un destinatario que nadie eligio.

Nunca convierte, nunca le agrega el "15" a un fijo, nunca inventa.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.services.whatsapp_phone_classifier import (
    ESTADO_CELULAR,
    ESTADO_POSIBLE,
    ESTADO_VACIO,
    PhoneClassification,
    clasificar_telefono,
)

ORIGEN_DEDICADO = "whatsapp_phone"
ORIGEN_TELEFONO = "phone"
ORIGEN_NINGUNO = ""


@dataclass(frozen=True)
class WhatsAppContact:
    """El destino de WhatsApp de un contacto, con el motivo si no hay."""

    numero: str
    origen: str
    estado: str
    motivo: str
    mensaje: str

    @property
    def enviable(self) -> bool:
        return bool(self.numero)


def _mensaje_de_error(clasificacion: PhoneClassification) -> str:
    """El mismo texto que hoy usa ``normalize_whatsapp_phone`` (#759)."""
    if clasificacion.estado == ESTADO_VACIO:
        return "El cliente no tiene un telefono valido para WhatsApp."
    if clasificacion.estado == ESTADO_POSIBLE:
        return (
            "El telefono es dudoso para WhatsApp: "
            f"{clasificacion.motivo}. Reviselo y confirme el numero antes de enviar."
        )
    return (
        f"El telefono no es valido para WhatsApp: {clasificacion.motivo}."
    )


def _contacto(clasificacion: PhoneClassification, origen: str) -> WhatsAppContact:
    if clasificacion.estado == ESTADO_CELULAR:
        return WhatsAppContact(
            numero=clasificacion.normalizado,
            origen=origen,
            estado=clasificacion.estado,
            motivo="",
            mensaje="",
        )
    return WhatsAppContact(
        numero="",
        origen=origen,
        estado=clasificacion.estado,
        motivo=clasificacion.motivo,
        mensaje=_mensaje_de_error(clasificacion),
    )


def resolver_contacto(
    *,
    whatsapp_phone=None,
    phone=None,
    preferir_dedicado: bool = True,
) -> WhatsAppContact:
    """Resuelve el destino de WhatsApp de un contacto.

    ``preferir_dedicado`` es el flag ``FEMAG_WHATSAPP_DEDICADO``: con el flag
    apagado (el default) el campo nuevo se ignora y el destino sale del
    telefono, como antes de este issue.
    """
    dedicado = (whatsapp_phone or "").strip()
    if preferir_dedicado and dedicado:
        return _contacto(clasificar_telefono(dedicado), ORIGEN_DEDICADO)
    telefono = (phone or "").strip()
    if not telefono:
        return _contacto(clasificar_telefono(""), ORIGEN_NINGUNO)
    return _contacto(clasificar_telefono(telefono), ORIGEN_TELEFONO)
