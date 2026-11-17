"""Configuracion central del envio automatico de presupuestos (#706).

El flag vivia en el ``.env`` de cada puesto, y con doscientos puestos eso no se
administra. La decision de mandar o no los presupuestos al emitir una orden es
del sistema, no de la maquina: se guarda en ``AppParameter`` (la misma tabla
que usan WhatsApp central, la URL del servidor web y la carpeta fiscal) y se
cambia desde ``Parametros``.

El ``.env`` queda como respaldo para demo/tests y para no romper un puesto que
ya lo tenia configurado: si no hay valor central, se lee
``FEMAG_PRESUPUESTOS_AUTOENVIO`` y, si tampoco esta, queda apagado.
"""

from __future__ import annotations

from app.config.settings import load_settings
from app.models.system import AppParameter

_VALORES_ENCENDIDOS = {"1", "true", "yes", "si", "sí", "on"}


def _encendido(valor) -> bool:
    return str(valor or "").strip().lower() in _VALORES_ENCENDIDOS


class BudgetAutoSendConfigurationService:
    PARAMETER_KEY = "presupuestos.autoenvio"

    @classmethod
    def load(cls) -> bool | None:
        """El valor central, o ``None`` si nadie lo configuro todavia."""
        row = AppParameter.get_or_none(AppParameter.key == cls.PARAMETER_KEY)
        if row is None or row.value is None:
            return None
        return _encendido(row.value)

    @classmethod
    def habilitado(cls) -> bool:
        """Si el sistema envia los presupuestos al emitir una orden.

        Prioridad: valor central > ``FEMAG_PRESUPUESTOS_AUTOENVIO`` > apagado.
        """
        central = cls.load()
        if central is not None:
            return central
        try:
            return bool(load_settings().presupuestos_autoenvio)
        except Exception:  # noqa: BLE001 - sin config legible sigue apagado
            return False

    @classmethod
    def save(cls, habilitado: bool) -> bool:
        row, _created = AppParameter.get_or_create(key=cls.PARAMETER_KEY)
        row.value = "1" if habilitado else "0"
        row.save(only=[AppParameter.value])
        return bool(habilitado)

    @classmethod
    def clear(cls) -> None:
        """Borra el valor central para que vuelva a mandar el ``.env``."""
        AppParameter.delete().where(AppParameter.key == cls.PARAMETER_KEY).execute()
