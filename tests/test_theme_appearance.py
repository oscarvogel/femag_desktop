"""Apariencia de la app: persistencia del tema y paleta oscura (#120).

El tema claro no se puede tocar sin querer: estos tests son el freno. El hash
ancla el QSS claro contra el que hay en produccion (main en el momento de
escribir esto), y los demas comprueban que el oscuro se inverso de verdad y no
solo "no revienta".
"""

import hashlib
import json
import re

import pytest

#: SHA256 del QSS claro con la ruta del asset neutralizada. Si cambia, alguien
#: toco un color de `glass_v2.py` a proposito y hay que actualizarlo a mano.
LIGHT_STYLESHEET_SHA256 = (
    "b9129a8c72b875177087067dc0b828ad93e9308f394bb51175c373333d28c65c"
)

_URL_RE = re.compile(r'url\("[^"]*"\)')

#: Fondos claros que no pueden quedar asomando en el tema oscuro.
LIGHT_SURFACES = ("#edf3f9", "#ffffff", "rgba(255,255,255,")

#: Fondos oscuros que el tema oscuro tiene que traer.
DARK_SURFACES = ("#0f141a", "#1b222c", "rgba(27,34,44,")


def _portable(qss: str) -> str:
    """Reemplaza la ruta absoluta del asset para que el hash sea portable."""
    return _URL_RE.sub('url("<asset>")', qss)


def test_tema_claro_sigue_siendo_el_de_produccion():
    """Ancla: el claro tiene que quedar byte a byte como estaba en main."""
    from app.ui.glass_v2 import glass_v2_stylesheet
    from app.ui.theme import Theme

    qss = glass_v2_stylesheet(Theme.LIGHT)
    assert hashlib.sha256(_portable(qss).encode("utf-8")).hexdigest() == LIGHT_STYLESHEET_SHA256


def test_llamar_sin_argumentos_sigue_dando_el_tema_claro():
    """Los llamadores actuales no pasan tema y no tienen que cambiar."""
    from app.ui.glass_v2 import glass_v2_stylesheet
    from app.ui.theme import Theme

    assert glass_v2_stylesheet() == glass_v2_stylesheet(Theme.LIGHT)


def test_tema_oscuro_no_deja_fondos_claros():
    from app.ui.glass_v2 import glass_v2_stylesheet
    from app.ui.theme import Theme

    dark = glass_v2_stylesheet(Theme.DARK)
    for surface in LIGHT_SURFACES:
        assert surface not in dark, f"el tema oscuro todavia trae {surface}"


def test_tema_oscuro_trae_los_fondos_oscuros():
    """Si esto falla, la paleta quedaria invertida pero invisible."""
    from app.ui.glass_v2 import glass_v2_stylesheet
    from app.ui.theme import Theme

    dark = glass_v2_stylesheet(Theme.DARK)
    for surface in DARK_SURFACES:
        assert surface in dark, f"el tema oscuro no trae {surface}"


def test_el_tema_oscuro_invierte_los_rgba_con_espacios():
    """`glass_v2.py` mezcla `rgba(255, 255, 255, 220)` y `rgba(232,242,241,225)`.

    Sin normalizar antes de invertir, la mitad del stylesheet se queda clara y
    no hay ningun sintoma visible: solo queda un theme oscuro a medio hacer.
    """
    from app.ui.theme import apply_dark_overrides

    spaced = "QFrame { background-color: rgba(255, 255, 255, 220); }"
    assert apply_dark_overrides(spaced) == "QFrame { background-color: rgba(27,34,44,220); }"

    tight = "QFrame { background-color: rgba(255,255,255,220); }"
    assert apply_dark_overrides(tight) == "QFrame { background-color: rgba(27,34,44,220); }"


def test_la_marca_de_agua_clara_solo_aparece_en_el_tema_claro():
    """El SVG de marca es de tonos claros: sobre fondo oscuro deja un rectangulo
    brillante del tamano de la ventana."""
    from app.ui.glass_v2 import glass_v2_stylesheet
    from app.ui.theme import Theme

    assert "femag-starch" in glass_v2_stylesheet(Theme.LIGHT)
    assert "femag-starch" not in glass_v2_stylesheet(Theme.DARK)


def test_la_persistencia_va_y_vuelve(tmp_path):
    from app.ui.theme import Theme, load_theme, save_theme

    assert load_theme(tmp_path) is Theme.LIGHT
    save_theme(Theme.DARK, tmp_path)
    assert load_theme(tmp_path) is Theme.DARK
    save_theme(Theme.LIGHT, tmp_path)
    assert load_theme(tmp_path) is Theme.LIGHT


def test_guardar_el_tema_escribe_el_archivo_esperado(tmp_path):
    from app.ui.theme import Theme, save_theme

    save_theme(Theme.DARK, tmp_path)
    guardado = json.loads((tmp_path / "appearance.json").read_text(encoding="utf-8"))

    assert guardado == {"version": 1, "theme": "dark"}


def test_guardar_no_deja_el_temporal_colgado(tmp_path):
    """La escritura es atomica: si el puesto se apaga, no queda un .tmp a medias."""
    from app.ui.theme import Theme, save_theme

    save_theme(Theme.DARK, tmp_path)

    assert list(tmp_path.glob("*.tmp")) == []


@pytest.mark.parametrize(
    "contenido",
    ["", "{", "null", '{"theme": "fucsia"}', "[]"],
    ids=["vacio", "truncado", "null", "tema-desconocido", "lista"],
)
def test_un_archivo_roto_deja_el_tema_claro(tmp_path, contenido):
    """Un `appearance.json` danado no puede impedir que abra la aplicacion."""
    from app.ui.theme import Theme, load_theme

    (tmp_path / "appearance.json").write_text(contenido, encoding="utf-8")

    assert load_theme(tmp_path) is Theme.LIGHT


def test_el_toggle_alterna_los_dos_temas():
    from app.ui.theme import Theme, toggle_theme

    assert toggle_theme(Theme.LIGHT) is Theme.DARK
    assert toggle_theme(Theme.DARK) is Theme.LIGHT