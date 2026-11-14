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

La forma canonica
-----------------

Lo que se guarda en el campo ``whatsapp_phone`` es el numero **normalizado
sin el "+"** ("5491153088679"). El clasificador, en cambio, solo reconoce el
formato internacional cuando el texto empieza con "+". Por eso el resolver
clasifica el numero dedicado como si estuviera escrito con el "+": asi el
mismo valor sirve para decidir (es un celular) y para mostrar (se precarga
"+5491153088679", que el dialogo de envio acepta sin cambios).
"""

from __future__ import annotations

import re
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

#: Solo digitos ASCII: la forma canonica ("5491153088679").
_SOLO_DIGITOS = re.compile(r"^[0-9]+$")


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


def es_canonico_sin_mas(valor) -> bool:
    """True si el valor ya esta en la forma internacional sin el "+".

    Es la forma en que se guarda el numero dedicado: "5491153088679".
    """
    texto = str(valor or "").strip()
    return bool(_SOLO_DIGITOS.match(texto)) and texto.startswith("54")


def clasificar_canonico(valor) -> PhoneClassification:
    """Clasifica un numero escrito en la forma canonica sin el "+".

    Si el valor es solo digitos y arranca con "54", se clasifica como si
    estuviera escrito con el "+": es el mismo numero, y asi el clasificador
    lo reconoce como celular. Cualquier otro valor se clasifica tal cual.
    """
    texto = str(valor or "").strip()
    if es_canonico_sin_mas(texto):
        return clasificar_telefono(f"+{texto}")
    return clasificar_telefono(texto)


def forma_internacional(valor) -> str:
    """El numero como lo espera el dialogo de envio: "+5491153088679".

    Un valor que no es la forma canonica se devuelve tal cual: el prefill
    muestra lo que el operador cargo, y la validacion sigue estando en el
    dialogo, como hoy.
    """
    texto = str(valor or "").strip()
    if not texto or texto.startswith("+"):
        return texto
    if es_canonico_sin_mas(texto):
        return f"+{texto}"
    return texto


def prefill_contacto(
    *,
    whatsapp_phone=None,
    phone=None,
    preferir_dedicado: bool = True,
) -> str:
    """El numero que se precarga en el dialogo de envio.

    El prefill decide **que se muestra**, no si el envio se puede hacer: la
    validacion sigue en el dialogo, al confirmar, como hoy.

    - Con el flag apagado: el telefono de siempre, tal cual esta escrito.
    - Con el flag encendido: el numero dedicado si hay uno (en forma
      internacional); si no hay, el telefono de siempre.
    """
    if preferir_dedicado:
        dedicado = str(whatsapp_phone or "").strip()
        if dedicado:
            return forma_internacional(dedicado)
    return str(phone or "").strip()


def resolver_contacto(
    *,
    whatsapp_phone=None,
    phone=None,
    preferir_dedicado: bool = True,
) -> WhatsAppContact:
    """Resuelve el destino de WhatsApp de un contacto.

    ``preferir_dedicado`` decide de donde sale el destino:

    - Con ``True`` (el default): si el contacto tiene ``whatsapp_phone``
      cargado, ese manda; si no, se cae a ``phone``.
    - Con ``False``: el campo nuevo se ignora y el destino sale siempre del
      telefono, como antes de este issue.
    """
    dedicado = str(whatsapp_phone or "").strip()
    if preferir_dedicado and dedicado:
        return _contacto(clasificar_canonico(dedicado), ORIGEN_DEDICADO)
    telefono = str(phone or "").strip()
    if not telefono:
        return _contacto(clasificar_telefono(""), ORIGEN_NINGUNO)
    return _contacto(clasificar_telefono(telefono), ORIGEN_TELEFONO)
