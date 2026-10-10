"""Tema de apariencia: claro / oscuro y su persistencia.

FEMAG Desktop nació con un solo tema claro. Este módulo centraliza las dos
mitades del tema:

* la **persistencia** de la preferencia del operador, y
* la **inversión de paleta** que produce el QSS oscuro a partir del claro.

La persistencia usa el mismo patrón que ``app.config.secure_credentials``:
un archivo JSON atómico (``.tmp`` + ``os.replace``) en el directorio de
configuración del puesto (``%LOCALAPPDATA%\\FEMAG Desktop``). No se introduce
``QSettings`` por primera vez: el proyecto ya tiene una capa de config local
consistente y la preferencia de apariencia es del mismo tipo que la conexión.

Por qué una tabla de inversión y no reescribir los estilos con tokens: el QSS
de ``glass_v2`` son ~1000 líneas con ~145 colores literales ya validados a ojo
en producción. Reescribirlos a tokens genera un diff gigante donde un typo se
ve como un color roto. Acá el tema claro se devuelve **sin tocar** y el oscuro
se deriva con sustituciones literales, de modo que el claro es idéntico byte a
byte por construcción y la paleta oscura queda en una tabla revisable.

``DARK_OVERRIDES`` es el lugar donde se ajusta el tema oscuro. El orden no es
significativo (las sustituciones no se pisan entre sí: cada literal aparece una
sola vez en el destino), pero conviene agrupar por familia: superficies,
bordes, texto, acentos, estados.
"""

from __future__ import annotations

import json
import os
import re
from enum import Enum
from pathlib import Path

from app.config.secure_credentials import default_config_dir


APPEARANCE_FILE_NAME = "appearance.json"
APPEARANCE_VERSION = 1


class Theme(Enum):
    """Temas de apariencia soportados."""

    LIGHT = "light"
    DARK = "dark"


def _appearance_path(config_dir: Path | None = None) -> Path:
    return (config_dir or default_config_dir()) / APPEARANCE_FILE_NAME


def load_theme(config_dir: Path | None = None) -> Theme:
    """Lee la preferencia guardada; vuelve a LIGHT si no hay configuración.

    El archivo es del puesto y puede quedar a medias si se apaga la máquina.
    Cualquier cosa que no sea un objeto con un tema conocido deja la app en
    claro: una preferencia de apariencia no puede impedir que abra.
    """
    try:
        data = json.loads(_appearance_path(config_dir).read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return Theme.LIGHT
        return Theme(str(data.get("theme", Theme.LIGHT.value)))
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return Theme.LIGHT


def save_theme(theme: Theme, config_dir: Path | None = None) -> None:
    """Guarda la preferencia de tema de forma atómica."""
    target_dir = config_dir or default_config_dir()
    target_dir.mkdir(parents=True, exist_ok=True)
    config = {"version": APPEARANCE_VERSION, "theme": theme.value}
    tmp = target_dir / f"{APPEARANCE_FILE_NAME}.tmp"
    tmp.write_text(json.dumps(config, indent=2), encoding="utf-8")
    os.replace(tmp, _appearance_path(config_dir))


def toggle_theme(current: Theme) -> Theme:
    """Alterna entre LIGHT y DARK."""
    return Theme.DARK if current is Theme.LIGHT else Theme.LIGHT


#: Paleta oscura, como sustituciones literales sobre el QSS claro.
#:
#: Los ``rgba(...)`` se mapean por su prefijo ``rgba(r,g,b,`` y no por el
#: literal completo: así un solo par cubre las cinco o seis variantes de alfa
#: que usa el mismo color de superficie.
DARK_OVERRIDES: tuple[tuple[str, str], ...] = (
    # --- Superficies: de casi blanco a casi negro -------------------------
    ("#f6f8fb", "#0f141a"),  # fondo general de la app (STYLES)
    ("#edf3f9", "#0f141a"),  # raíz glass v2
    ("#f5f8fc", "#161c24"),  # diálogo genérico
    ("#edf4f7", "#161c24"),  # diálogo de órdenes de carga
    ("#ffffff", "#1b222c"),  # tarjetas, topbar, statusbar, sidebar, inputs
    ("#fbfdff", "#181f28"),  # panel inline de detalle
    ("#f8fafc", "#232b36"),  # hover de botón en STYLES
    ("#f1f5f9", "#1b222c"),
    ("#eef2f7", "#1b222c"),
    ("#edf2f7", "#1b222c"),
    ("#e2e8f0", "#232b36"),
    ("#e5e7eb", "#232b36"),
    ("#e8f1ff", "#24344a"),  # sidebar ::item:selected (STYLES)
    ("#e8f2fd", "#1d2b3d"),  # botón :pressed
    ("#e9eef4", "#232b36"),  # botón deshabilitado de diálogo
    ("#fff7d6", "#2f2a17"),
    ("#dcfce7", "#18301f"),
    ("#dbeafe", "#16283f"),
    ("#fee2e2", "#331d1d"),
    ("#f6c453", "#3d3418"),
    ("rgba(255,255,255,", "rgba(27,34,44,"),  # overlays de cristal (28 usos)
    ("rgba(248,251,255,", "rgba(21,27,35,"),  # shell
    ("rgba(237,244,252,", "rgba(21,27,35,"),  # sidebarContainer
    ("rgba(242,248,250,", "rgba(15,20,26,"),  # página de órdenes de carga
    ("rgba(250,253,253,", "rgba(28,36,40,"),  # botón de acción rápida
    ("rgba(251,253,253,", "rgba(23,30,36,"),  # fondo de tabla
    ("rgba(246,249,253,", "rgba(28,34,42,"),  # fila alternada
    ("rgba(241,247,247,", "rgba(24,31,36,"),
    ("rgba(239,246,245,", "rgba(22,29,34,"),
    ("rgba(242,244,241,", "rgba(28,32,36,"),  # botón planificado
    ("rgba(230,236,243,", "rgba(30,36,44,"),  # botón deshabilitado
    ("rgba(236,243,251,", "rgba(28,35,44,"),  # header de tabla genérico
    ("rgba(232,242,241,", "rgba(28,38,40,"),  # header de tabla teal
    # Tarjetas de estado: el tinte se mantiene, la luminosidad baja.
    ("rgba(255,244,245,", "rgba(48,26,30,"),  # vencidos
    ("rgba(255,245,246,", "rgba(48,26,30,"),  # botón de peligro
    ("#fff5f6", "#2a1a1d"),
    ("rgba(255,248,238,", "rgba(46,34,20,"),  # vence hoy
    ("rgba(255,252,235,", "rgba(45,40,20,"),  # próximos 7 días
    ("rgba(244,249,255,", "rgba(22,32,48,"),  # próximos 30 días
    ("rgba(247,251,250,", "rgba(23,32,33,"),  # saldo de deudores
    ("rgba(116,143,171,", "rgba(96,120,148,"),  # handle de scrollbar
    # --- Bordes: de gris claro a gris oscuro ------------------------------
    ("#d9e1ec", "#2a3340"),
    ("#d9e3ef", "#2a3340"),
    ("#d6e0ec", "#2a3340"),
    ("#d4e3e2", "#2a3a3b"),
    ("#cbd9e8", "#2f3a48"),
    ("#cedbea", "#2f3a48"),
    ("#cbd5e1", "#2f3a48"),
    ("rgba(204,216,230,", "rgba(44,54,66,"),
    ("rgba(207,220,233,", "rgba(44,54,66,"),
    ("rgba(205,218,232,", "rgba(44,54,66,"),
    ("rgba(207,218,230,", "rgba(44,54,66,"),
    ("rgba(194,210,229,", "rgba(44,54,66,"),
    ("rgba(199,213,230,", "rgba(44,54,66,"),
    ("rgba(195,211,226,", "rgba(44,54,66,"),
    ("rgba(200,216,218,", "rgba(46,58,60,"),
    ("rgba(201,218,220,", "rgba(46,58,60,"),
    ("rgba(199,216,218,", "rgba(46,58,60,"),
    ("rgba(191,210,215,", "rgba(46,62,64,"),
    ("rgba(179,205,207,", "rgba(46,62,64,"),
    ("rgba(159,193,192,", "rgba(46,62,64,"),
    ("rgba(150,164,153,", "rgba(46,62,64,"),
    ("rgba(112,168,166,", "rgba(46,62,64,"),
    ("rgba(220,239,237,", "rgba(26,48,47,"),  # paso activo
    ("#9ab9de", "#4a6d96"),  # borde de hover
    ("#86acd8", "#4a7cae"),
    ("#78a5da", "#5b8ac4"),  # borde de foco
    ("#6b9fe0", "#5b8ac4"),
    ("#83aaad", "#6f9ea1"),
    ("#8ab1b5", "#7ba5a9"),
    ("#ebecf0", "#2a3340"),
    # --- Texto: de tinta sobre blanco a tinta clara sobre oscuro -----------
    ("#172033", "#e6edf5"),
    ("#111827", "#e9eff7"),
    ("#1e293b", "#cbd5e1"),
    ("#17345a", "#dce8f6"),
    ("#173d4b", "#d5e7ec"),
    ("#254d5b", "#c3dbe2"),
    ("#294b70", "#a9c2dc"),
    ("#31557e", "#9fb9d6"),
    ("#315969", "#9cc3ca"),
    ("#365965", "#a5c6cc"),
    ("#334155", "#b6c2d4"),
    ("#385778", "#a8c0da"),
    ("#2d4e72", "#adc4de"),
    ("#49686f", "#9fbfc4"),
    ("#4c6687", "#a3bad4"),
    ("#496582", "#a3b8cf"),
    ("#476a70", "#a1c2c7"),
    ("#526174", "#a7b3c5"),
    ("#516174", "#a7b3c5"),
    ("#617980", "#93aab1"),
    ("#6c7f98", "#8d9cb2"),
    ("#64748b", "#8d9bb0"),
    ("#475569", "#a2adbd"),
    ("#6a836d", "#93aa95"),
    ("#6b8186", "#8ea4a9"),
    ("#698087", "#8ba0a6"),
    ("#70839b", "#8798ae"),
    ("#71868b", "#87a1a6"),
    ("#7a9093", "#84a0a3"),
    ("#94a3b8", "#6f7d90"),
    ("#849189", "#7b8880"),
    ("#8a9aac", "#75838f"),
    ("#b7d3f6", "#7fa8d8"),
    # --- Acentos: mismo tono, saturación y brillo de acento ---------------
    ("#0b63c7", "#5fa8f5"),  # enlace / tab seleccionado
    ("#0b6fdc", "#5aa5f0"),  # sidebar ::item:selected (STYLES)
    ("#1473e6", "#2f86e6"),  # acción primaria
    ("#0f68cf", "#3a7fdc"),
    ("#167a76", "#2f9f9a"),  # acción primaria del dashboard
    ("#176f70", "#2f9f9a"),
    ("#0e6966", "#2f8f8a"),
    ("#17636c", "#4fb8b3"),
    # --- Estados: el color sigue identificando el estado ------------------
    ("#9f3043", "#f0909f"),  # vencidos
    ("#b4233c", "#f07a8c"),  # peligro
    ("#b91c1c", "#f07a8c"),
    ("#a55c16", "#e5a05a"),  # vence hoy
    ("#b45309", "#e5a05a"),
    ("#8a690a", "#d6c169"),  # próximos 7 días
    ("#2c629d", "#7fb0e6"),  # próximos 30 días
    ("#15803d", "#5fbf7a"),
    ("#86efac", "#3f7d55"),
    ("#93c5fd", "#4d7fb0"),
    ("#fecaca", "#8a3a3a"),
    ("#e1eefc", "#26405e"),  # selección de tabla
    ("#dcefed", "#20403f"),
    ("#14365e", "#cfe2f7"),  # texto sobre selección
)


#: ``rgba(...)`` escrito con y sin espacios conviven en ``glass_v2.py``: el
#: archivo mezcla ``rgba(255, 255, 255, 224)`` y ``rgba(232,242,241,225)``. Como
#: la tabla de arriba está escrita sin espacios (que es como se lee y se revisa
#: una paleta), primero se normaliza el QSS. Sin esto, medio stylesheet oscuro
#: saldría sin invertir sin que nada lo delate.
_RGBA_CALL = re.compile(r"rgba\(\s*([^)]*?)\s*\)")


def _normalize_rgba(qss: str) -> str:
    return _RGBA_CALL.sub(lambda m: "rgba(" + m.group(1).replace(" ", "") + ")", qss)


def apply_dark_overrides(qss: str) -> str:
    """Devuelve el QSS claro con la paleta ya invertida a oscuro.

    No muta la entrada. Los literales de ``DARK_OVERRIDES`` no se pisan entre sí,
    así que el orden de la tupla no cambia el resultado.
    """
    result = _normalize_rgba(qss)
    for light, dark in DARK_OVERRIDES:
        result = result.replace(light, dark)
    return result


def stylesheet_for(theme: Theme) -> str:
    """Devuelve el stylesheet completo de la aplicación para el tema pedido."""
    from app.ui.desktop_app import styles_for as base_styles_for
    from app.ui.glass_v2 import glass_v2_stylesheet

    return base_styles_for(theme) + glass_v2_stylesheet(theme)