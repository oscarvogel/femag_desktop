"""Configuración persistente del sobre por puesto (#740).

El sobre es un elemento físico: el papel que usa la impresora de Secretaría no
es el mismo en todos los equipos, y la Epson L3250 no siempre admite el mismo
tamaño de papel personalizado en todos sus drivers. Por eso las medidas, la
rotación y los desplazamientos viven en un archivo del puesto y no en el
código.

La persistencia usa el mismo patrón que ``app.ui.theme`` y
``app.config.secure_credentials``: un JSON atómico (``.tmp`` + ``os.replace``)
en el directorio de configuración del puesto
(``%LOCALAPPDATA%\\FEMAG Desktop``). No se usa ``QSettings`` a propósito: el
proyecto ya tiene una capa de configuración local consistente y esta
preferencia es del mismo tipo que la de apariencia o la de conexión.

Un archivo de configuración no puede impedir que la aplicación abra: cualquier
valor inusable vuelve al predeterminado y queda registrado en el archivo
guardado, no en una excepción.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, replace
from pathlib import Path

from app.config.secure_credentials import default_config_dir

ENVELOPE_FILE_NAME = "envelope.json"
ENVELOPE_VERSION = 1

#: Rotaciones admitidas. Son las que dejan el texto del sobre legible sobre el
#: sobre terminado, en el sentido de lectura del papel.
ALLOWED_ROTATIONS = (0, 90, 180, 270)

#: Tamaño real del sobre que usa FEMAG, confirmado el 20/10/2026: 23,5 x 12 cm.
#: No es un sobre N.º 10.
DEFAULT_ENVELOPE_WIDTH_MM = 235.0
DEFAULT_ENVELOPE_HEIGHT_MM = 120.0


@dataclass(frozen=True)
class EnvelopeSettings:
    """Geometría y preferences de impresión del sobre.

    ``envelope_width_mm`` y ``envelope_height_mm`` son las medidas físicas del
    sobre tal como se ve terminado (ancho x alto, en horizontal). La página del
    PDF se deriva de ellas según la rotación: con 0°/180° la página es
    horizontal (235 x 120 mm) y con 90°/270° es vertical (120 x 235 mm), que es
    el mismo papel descrito en el otro sentido.
    """

    envelope_width_mm: float = DEFAULT_ENVELOPE_WIDTH_MM
    envelope_height_mm: float = DEFAULT_ENVELOPE_HEIGHT_MM
    rotation_deg: int = 0
    offset_x_mm: float = 0.0
    offset_y_mm: float = 0.0
    margin_mm: float = 12.0
    printer_name: str = ""
    copies: int = 1
    show_logo: bool = True
    show_budget_reference: bool = True
    show_pallet_count: bool = True

    @property
    def page_size_mm(self) -> tuple[float, float]:
        """Tamaño de la página del PDF, en mm, ya según la rotación."""
        if self.rotation_deg in (90, 270):
            return (self.envelope_height_mm, self.envelope_width_mm)
        return (self.envelope_width_mm, self.envelope_height_mm)

    def normalized(self) -> "EnvelopeSettings":
        """Deja los valores en un rango utilizable.

        Se aplica al leer del disco: un archivo editado a mano o con una
        versión vieja no puede dejar la impresión sin BoundsError ni con
        rotación en un ángulo que no existe.
        """
        width = _positive(self.envelope_width_mm, DEFAULT_ENVELOPE_WIDTH_MM)
        height = _positive(self.envelope_height_mm, DEFAULT_ENVELOPE_HEIGHT_MM)
        margin = max(0.0, min(float(self.margin_mm), min(width, height) / 3))
        rotation = int(self.rotation_deg) % 360
        if rotation not in ALLOWED_ROTATIONS:
            rotation = 0
        return replace(
            self,
            envelope_width_mm=width,
            envelope_height_mm=height,
            rotation_deg=rotation,
            offset_x_mm=float(self.offset_x_mm),
            offset_y_mm=float(self.offset_y_mm),
            margin_mm=margin,
            copies=max(1, int(self.copies)),
            printer_name=(self.printer_name or "").strip(),
        )


def _positive(value: object, fallback: float) -> float:
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return fallback
    if number <= 0:
        return fallback
    return number


def _settings_path(config_dir: Path | None = None) -> Path:
    return (config_dir or default_config_dir()) / ENVELOPE_FILE_NAME


def default_settings() -> EnvelopeSettings:
    """Configuración de fábrica: el sobre real de FEMAG, sin ajustes."""
    return EnvelopeSettings()


def load_envelope_settings(config_dir: Path | None = None) -> EnvelopeSettings:
    """Lee la configuración del puesto; vuelve a la de fábrica si no hay.

    Igual que la preferencia de apariencia, un archivo a medias o corrupto no
    puede impedir que la aplicación abra: se descarta y se sigue con los
    valores de fábrica.
    """
    try:
        raw = json.loads(_settings_path(config_dir).read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return default_settings()
    if not isinstance(raw, dict):
        return default_settings()
    defaults = default_settings()
    try:
        settings = EnvelopeSettings(
            envelope_width_mm=_positive(
                raw.get("envelope_width_mm"), defaults.envelope_width_mm
            ),
            envelope_height_mm=_positive(
                raw.get("envelope_height_mm"), defaults.envelope_height_mm
            ),
            rotation_deg=int(raw.get("rotation_deg", defaults.rotation_deg)),
            offset_x_mm=float(raw.get("offset_x_mm", defaults.offset_x_mm)),
            offset_y_mm=float(raw.get("offset_y_mm", defaults.offset_y_mm)),
            margin_mm=float(raw.get("margin_mm", defaults.margin_mm)),
            printer_name=str(raw.get("printer_name", defaults.printer_name)),
            copies=int(raw.get("copies", defaults.copies)),
            show_logo=bool(raw.get("show_logo", defaults.show_logo)),
            show_budget_reference=bool(
                raw.get("show_budget_reference", defaults.show_budget_reference)
            ),
            show_pallet_count=bool(
                raw.get("show_pallet_count", defaults.show_pallet_count)
            ),
        )
    except (TypeError, ValueError):
        return default_settings()
    return settings.normalized()


def save_envelope_settings(
    settings: EnvelopeSettings, config_dir: Path | None = None
) -> EnvelopeSettings:
    """Guarda la configuración de forma atómica y devuelve la versión normalizada."""
    normalized = settings.normalized()
    target_dir = config_dir or default_config_dir()
    target_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": ENVELOPE_VERSION,
        "envelope_width_mm": normalized.envelope_width_mm,
        "envelope_height_mm": normalized.envelope_height_mm,
        "rotation_deg": normalized.rotation_deg,
        "offset_x_mm": normalized.offset_x_mm,
        "offset_y_mm": normalized.offset_y_mm,
        "margin_mm": normalized.margin_mm,
        "printer_name": normalized.printer_name,
        "copies": normalized.copies,
        "show_logo": normalized.show_logo,
        "show_budget_reference": normalized.show_budget_reference,
        "show_pallet_count": normalized.show_pallet_count,
    }
    tmp = target_dir / f"{ENVELOPE_FILE_NAME}.tmp"
    tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    os.replace(tmp, _settings_path(config_dir))
    return normalized
