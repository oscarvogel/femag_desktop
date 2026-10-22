"""Clasificación de teléfonos argentinos: a quién se le puede mandar WhatsApp.

Un número local de 10 u 11 dígitos (código de área + 8) **no se puede distinguir** entre una
línea fija y un celular escrito sin el "15": en Argentina los dos tienen la misma forma y la
gente escribe el celular de las dos maneras. Por eso la clasificación tiene tres estados y no
dos:

- ``celular``: tiene el "15" detrás del código de área, o viene en formato internacional
  ``+549...``. Se puede mandar WhatsApp.
- ``posible``: tiene forma de línea fija pero podría ser un celular escrito sin el "15".
  **No se manda solo**: se muestra el número que se enviaría y lo tilda el operador.
- ``invalido`` / ``vacio``: no hay número usable.

El módulo no toca la base ni la interfaz: es una función pura, para poder testearla y para que
la usen la pantalla de envío y el diálogo de edición del teléfono.

Los formatos válidos (los dos primeros son el mismo número):

===========================  ==========================  ====================
Cómo está escrito            Ejemplo                     Normalizado
===========================  ==========================  ====================
Local con "15"               ``011 15 53088679``         ``5491153088679``
Internacional                ``+549 11 53088679``        ``5491153088679``
===========================  ==========================  ====================
"""

from __future__ import annotations

import re
from dataclasses import dataclass

ESTADO_CELULAR = "celular"
ESTADO_POSIBLE = "posible"
ESTADO_INVALIDO = "invalido"
ESTADO_VACIO = "vacio"

#: Prefijos de código de área válidos de Argentina (2 dígitos): 11, 22-29, 33-38.
PREFIJOS_AREA = ("11", "22", "23", "24", "26", "28", "29", "33", "34", "35", "36", "37", "38")

_SOLO_DIGITOS = re.compile(r"\D")
_SEPARADORES = re.compile(r"[-/,;]|\s{2,}")


@dataclass(frozen=True)
class PhoneClassification:
    """Resultado de clasificar un teléfono."""

    estado: str
    normalizado: str
    motivo: str
    original: str = ""
    propuesta: str = ""

    @property
    def es_celular(self) -> bool:
        return self.estado == ESTADO_CELULAR

    @property
    def es_posible(self) -> bool:
        return self.estado == ESTADO_POSIBLE

    @property
    def es_enviable(self) -> bool:
        """Si el número se puede mandar sin que un humano lo revise."""
        return self.estado == ESTADO_CELULAR

    @property
    def tiene_problema(self) -> bool:
        return self.estado in (ESTADO_INVALIDO, ESTADO_VACIO)

    @property
    def etiqueta(self) -> str:
        """Texto corto para la pantalla."""
        if self.estado == ESTADO_CELULAR:
            return "Celular"
        if self.estado == ESTADO_POSIBLE:
            return "Revisar"
        if self.estado == ESTADO_VACIO:
            return "Sin teléfono"
        return "No válido"

    @property
    def detalle(self) -> str:
        """Texto para la pantalla, con el motivo."""
        if self.estado == ESTADO_CELULAR:
            return f"Celular: se envía a +{self.normalizado}"
        if self.estado == ESTADO_POSIBLE:
            return f"Revisar: {self.motivo}"
        if self.estado == ESTADO_VACIO:
            return "Sin teléfono"
        return f"No válido: {self.motivo}"


def solo_digitos(valor) -> str:
    return _SOLO_DIGITOS.sub("", str(valor or ""))


def _area_valida(area: str) -> bool:
    """El único código de área de 2 dígitos es el 11 (CABA); los demás son de 3 o 4."""
    if len(area) == 2:
        return area == "11"
    if len(area) in (3, 4):
        return area[:2] in PREFIJOS_AREA
    return False


def _detectar_movil_local(local: str) -> tuple[str, str] | None:
    """Devuelve (área, suscriptor) si el número local tiene el "15" del móvil."""
    for largo_area in (2, 3, 4):
        if len(local) < largo_area + 2 + 6:
            continue
        if local[largo_area : largo_area + 2] != "15":
            continue
        area = local[:largo_area]
        if not _area_valida(area):
            continue
        suscriptor = local[largo_area + 2 :]
        if len(suscriptor) in (6, 7, 8):
            return area, suscriptor
    return None


def _sin_cero_inicial(digitos: str) -> str:
    return digitos[1:] if digitos.startswith("0") else digitos


def _partir_area_suscriptor(digitos: str) -> tuple[str, str] | None:
    """Parte un número local en (código de área, suscriptor), si el área existe.

    El área tiene 2 dígitos (solo el 11), 3 o 4; el suscriptor, 6, 7 u 8. No todos los
    países tienen el mismo largo: en Rosario (03416) el suscriptor tiene 6 dígitos y en
    CABA (011) tiene 8.
    """
    for largo_area in (2, 3, 4):
        area = digitos[:largo_area]
        if not _area_valida(area):
            continue
        suscriptor = digitos[largo_area:]
        if len(suscriptor) in (6, 7, 8):
            return area, suscriptor
    return None


def clasificar_telefono(texto) -> PhoneClassification:
    """Clasifica un teléfono. No lanza excepciones: siempre devuelve un veredicto."""
    original = str(texto or "").strip()

    if not original:
        return PhoneClassification(ESTADO_VACIO, "", "el cliente no tiene teléfono", original)

    if re.search(r"[A-Za-z]", original):
        return PhoneClassification(
            ESTADO_INVALIDO,
            "",
            "el teléfono tiene letras",
            original,
        )

    # Dos números en el mismo campo. Un fijo con guiones ("011-4441-2835") tiene
    # grupos cortos, así que el corte es "dos grupos con 8 dígitos o más".
    grupos = [
        grupo.strip()
        for grupo in _SEPARADORES.split(original)
        if len(solo_digitos(grupo)) >= 8
    ]
    if len(grupos) >= 2:
        return PhoneClassification(
            ESTADO_INVALIDO,
            "",
            "hay más de un teléfono en el mismo campo",
            original,
            solo_digitos(grupos[0]),
        )

    digitos = solo_digitos(original)
    if len(digitos) < 8:
        return PhoneClassification(
            ESTADO_INVALIDO,
            "",
            "el teléfono es demasiado corto",
            original,
        )

    # Formato internacional: +54 9 <área> <suscriptor> es un celular sin ambigüedad.
    # +54 <área> <suscriptor> (sin el "9") puede ser un fijo: no se manda solo.
    if original.startswith("+"):
        if not digitos.startswith("54"):
            return PhoneClassification(
                ESTADO_INVALIDO,
                "",
                "el código de país no es de Argentina",
                original,
            )
        resto = digitos[2:]
        if resto.startswith("9"):
            if _partir_area_suscriptor(resto[1:]) is not None:
                return PhoneClassification(ESTADO_CELULAR, digitos, "", original)
            return PhoneClassification(
                ESTADO_INVALIDO,
                "",
                "el código de área no existe",
                original,
            )
        if _partir_area_suscriptor(resto) is not None:
            return PhoneClassification(
                ESTADO_POSIBLE,
                f"549{resto}",
                "está escrito sin el 9 del móvil: puede ser una línea fija o un celular",
                original,
            )
        return PhoneClassification(
            ESTADO_INVALIDO,
            "",
            "el formato internacional no se reconoce",
            original,
        )

    local = _sin_cero_inicial(digitos)

    # Móvil con el "15" detrás del área.
    movil = _detectar_movil_local(local)
    if movil is not None:
        area, suscriptor = movil
        return PhoneClassification(ESTADO_CELULAR, f"549{area}{suscriptor}", "", original)

    # Móvil sin código de área: "15" + 8 dígitos.
    if local.startswith("15") and len(local) in (10, 11):
        return PhoneClassification(
            ESTADO_POSIBLE,
            "",
            "es un celular sin código de área: agregale el prefijo 0XX",
            original,
        )

    # Número local de 10 u 11 dígitos: puede ser fijo o un celular escrito sin el "15".
    if len(local) in (10, 11):
        return PhoneClassification(
            ESTADO_POSIBLE,
            f"549{local}",
            "puede ser una línea fija o un celular escrito sin el 15",
            original,
        )

    return PhoneClassification(
        ESTADO_INVALIDO,
        "",
        "el formato del teléfono no se reconoce",
        original,
    )


def es_celular(texto) -> bool:
    """True solo si el número es un celular sin ambigüedad."""
    return clasificar_telefono(texto).es_celular


def numero_enviable(texto) -> str:
    """Número listo para mandar, o vacío si no se puede mandar sin revisarlo."""
    clasificacion = clasificar_telefono(texto)
    return clasificacion.normalizado if clasificacion.es_enviable else ""
