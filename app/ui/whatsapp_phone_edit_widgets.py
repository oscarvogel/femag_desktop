"""Piezas compartidas por los dialogos de telefono y de WhatsApp (#923).

Los dos dialogos de edicion rapida (el del telefono general y el del numero
de WhatsApp dedicado) muestran lo mismo: la clasificacion del numero que se
esta escribiendo y, cuando el campo trae dos numeros, un boton que propone
usar el primero. Esas piezas viven aca para que no esten duplicadas.
"""

from __future__ import annotations

from PyQt5.QtWidgets import QLabel, QPushButton

from app.services.whatsapp_phone_classifier import (
    ESTADO_CELULAR,
    ESTADO_INVALIDO,
    ESTADO_POSIBLE,
    ESTADO_VACIO,
    PhoneClassification,
)

#: Colores por estado: (texto, fondo, borde).
ESTILOS_CLASIFICACION = {
    ESTADO_CELULAR: ("#166534", "#ecfdf3", "#4ade80"),
    ESTADO_POSIBLE: ("#92400e", "#fffbeb", "#f6c453"),
    ESTADO_INVALIDO: ("#991b1b", "#fef2f2", "#f87171"),
    ESTADO_VACIO: ("#374151", "#f3f4f6", "#d1d5db"),
}


def prefill_whatsapp(valor: str | None) -> str:
    """Como se precarga el numero de WhatsApp que ya estaba guardado.

    Lo que se guarda es el normalizado **sin** "+" ("5491153088679"), pero el
    clasificador solo reconoce el formato internacional si el texto empieza con
    "+". Precargando la forma internacional, el numero guardado se vuelve a
    clasificar como celular (asi se ve al reabrir el dialogo) y guardar no
    cambia nada: el servicio sigue guardando el valor sin "+".
    """
    valor = (valor or "").strip()
    if not valor:
        return ""
    return valor if valor.startswith("+") else f"+{valor}"


class ClasificacionLabel(QLabel):
    """Muestra en vivo si el numero es un celular, dudoso o invalido."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWordWrap(True)

    def mostrar(self, clasificacion: PhoneClassification) -> None:
        color, fondo, borde = ESTILOS_CLASIFICACION.get(
            clasificacion.estado, ESTILOS_CLASIFICACION[ESTADO_VACIO]
        )
        self.setText(clasificacion.detalle)
        self.setStyleSheet(
            f"QLabel {{"
            f"background-color: {fondo};"
            f"border: 1px solid {borde};"
            f"border-left: 4px solid {borde};"
            f"border-radius: 7px;"
            f"color: {color};"
            "font-size: 13px;"
            "font-weight: 600;"
            "padding: 9px 11px;"
            "}"
        )


class BotonPropuesta(QPushButton):
    """El boton que propone el numero a usar cuando el campo trae dos.

    El texto es un parametro para que cada dialogo muestre el suyo: el del
    telefono conserva el que ya tenia.
    """

    def __init__(self, texto: str = "Usar el primer numero", parent=None):
        super().__init__(texto, parent)
        self.setVisible(False)

    def mostrar(self, clasificacion: PhoneClassification) -> None:
        self.setVisible(bool(clasificacion.propuesta))

    def aplicar(self, clasificacion: PhoneClassification) -> str:
        """Devuelve el numero que hay que poner en el campo."""
        return clasificacion.propuesta
