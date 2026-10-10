"""El toggle de tema: arranca con la preferencia y la cambia de verdad (#120).

Un boton visible que no hace nada es exactamente lo que el loop no permite, asi
que estos tests no se quedan en "la preferencia existe": comprueban que la
ventana arranca oscura si el operador la dejo oscura y que el boton cambia la
hoja de estilos de verdad.

Sobre el costo: dos de estos tests instancian ``FemagDesktopWindow``. No es
gratis. ``_aplicar_tema`` escribe la hoja en el ``QApplication``, que es
singleton, y eso le pide a Qt reestilizar todos los widgets vivos del proceso.
En la suite completa hay miles ya construidos por otros tests, y una version
anterior de este archivo con 7 tests de ventana adding ~8 minutos a una corrida
de 7. Lo que se prueba aca no necesita ventana se prueba calling the method
directly con un ``self`` de mentira: no se pierde cobertura y no se paga el
restyle global.
"""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture()
def appearance_dir(tmp_path, monkeypatch):
    """Apunta la config del puesto a un directorio temporal.

    Se usa la variable de entorno y no un monkeypatch interno: asi los tests
    recorren el mismo camino que un puesto real, incluido `default_config_dir`.
    """
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    return tmp_path / "FEMAG Desktop"


class BotonDeMentira:
    """Lo unico que hace el boton es texto y tooltip: alcanza con anotarlos."""

    def __init__(self) -> None:
        self.text = ""
        self.tool_tip = ""

    def setText(self, text: str) -> None:
        self.text = text

    def setToolTip(self, tip: str) -> None:
        self.tool_tip = tip


class VentanaDeMentira:
    """``self`` minimo para los metodos que no necesitan un ``QMainWindow``."""

    def __init__(self, theme=None) -> None:
        self.theme = theme
        self.theme_button = BotonDeMentira()
        self.aplicados: list = []

    def _aplicar_tema(self, theme) -> None:
        """Sustituto de la version real.

        La real escribe la hoja en el ``QApplication`` y eso reestiliza todos los
        widgets vivos del proceso: en la suite completa son miles y cuesta
        decenas de segundos por llamada. Lo que se prueba aca es que
        ``_toggle_theme`` delegue y avise, no que el reestilo pase: eso lo
        cubre el test que si crea la ventana.
        """
        from app.ui.desktop_app import FemagDesktopWindow

        self.theme = theme
        self.aplicados.append(theme)
        FemagDesktopWindow._update_theme_button(self, theme)


# --- Tests que necesitan la ventana real ----------------------------------


def test_la_app_arranca_oscura_si_el_operador_la_dejo_oscura(db, appearance_dir):
    """La preferencia tiene que llegar al arranque, no solo guardarse."""
    from PyQt5.QtWidgets import QApplication

    from app.models.security import User, UserProfile
    from app.services.permission_service import PermissionService
    from app.ui.desktop_app import FemagDesktopWindow
    from app.ui.theme import Theme, save_theme, stylesheet_for

    app = QApplication.instance() or QApplication([])
    previo = app.styleSheet()
    try:
        save_theme(Theme.DARK)
        PermissionService().seed_defaults()
        profile = UserProfile.get(UserProfile.name == "Administrador")
        user = User.create(username="admin_oscuro", password_hash="x", profile=profile)

        window = FemagDesktopWindow(user=user, demo_mode=True)
        app.processEvents()

        assert window.theme is Theme.DARK
        assert window.styleSheet() == stylesheet_for(Theme.DARK)
        assert "#0f141a" in window.styleSheet()
        window.close()
    finally:
        app.setStyleSheet(previo)


def test_el_boton_cambia_el_tema_de_verdad(db, appearance_dir):
    """No alcanza con que el boton exista: tiene que cambiar la hoja de estilos."""
    from PyQt5.QtWidgets import QApplication

    from app.models.security import User, UserProfile
    from app.services.permission_service import PermissionService
    from app.ui.desktop_app import FemagDesktopWindow
    from app.ui.theme import Theme, load_theme

    app = QApplication.instance() or QApplication([])
    previo = app.styleSheet()
    try:
        PermissionService().seed_defaults()
        profile = UserProfile.get(UserProfile.name == "Administrador")
        user = User.create(username="admin_tema", password_hash="x", profile=profile)
        window = FemagDesktopWindow(user=user, demo_mode=True)
        app.processEvents()

        assert window.theme is Theme.LIGHT
        assert window.theme_button.text() == "Tema: Claro"
        claro = window.styleSheet()

        window.theme_button.click()
        app.processEvents()

        # El tema cambio de verdad...
        assert window.theme is Theme.DARK
        assert window.styleSheet() != claro
        assert "#0f141a" in window.styleSheet()
        assert "#edf3f9" not in window.styleSheet()
        assert window.theme_button.text() == "Tema: Oscuro"

        # ...y quedo en la ventana y en la aplicacion. Con una sola de las dos
        # no se veria: la ventana pisa la hoja global para lo que cuelgue de
        # ella, y los dialogos son ventanas aparte que solo toman la global.
        assert app.styleSheet() == window.styleSheet()

        # Y lo que eligio el operador quedo escrito, no solo pintado.
        assert load_theme() is Theme.DARK

        window.close()
    finally:
        app.setStyleSheet(previo)


# --- Tests sin ventana: la logica no necesita un QMainWindow --------------


def test_el_boton_dice_el_tema_actual_y_no_la_accion():
    """Decir la accion ("Oscuro") se lee al reves; el estado actual, no."""
    from app.ui.desktop_app import FemagDesktopWindow
    from app.ui.theme import Theme

    ventana = VentanaDeMentira()
    FemagDesktopWindow._update_theme_button(ventana, Theme.LIGHT)

    assert ventana.theme_button.text == "Tema: Claro"
    assert ventana.theme_button.tool_tip == "Cambiar al tema oscuro"

    FemagDesktopWindow._update_theme_button(ventana, Theme.DARK)

    assert ventana.theme_button.text == "Tema: Oscuro"
    assert ventana.theme_button.tool_tip == "Cambiar al tema claro"


def test_el_toggle_alterna_el_tema_de_la_ventana(appearance_dir):
    # Sin `appearance_dir`, el `save_theme` del toggle escribiria en el
    # `%LOCALAPPDATA%` real y dejaria la app del developer en tema oscuro.
    from app.ui.desktop_app import FemagDesktopWindow
    from app.ui.theme import Theme

    ventana = VentanaDeMentira(theme=Theme.LIGHT)
    FemagDesktopWindow._update_theme_button(ventana, ventana.theme)

    FemagDesktopWindow._toggle_theme(ventana)

    assert ventana.theme is Theme.DARK
    assert ventana.theme_button.text == "Tema: Oscuro"


def test_si_no_se_puede_guardar_avisa_y_aplica_igual(
    appearance_dir, monkeypatch
):
    """El boton tiene que hacer algo igual, pero decir la verdad sobre guardar."""
    from app.ui import desktop_app
    from app.ui.desktop_app import FemagDesktopWindow
    from app.ui.theme import Theme

    ventana = VentanaDeMentira(theme=Theme.LIGHT)
    FemagDesktopWindow._update_theme_button(ventana, ventana.theme)

    avisos = []
    monkeypatch.setattr(
        desktop_app.QMessageBox, "warning", lambda *a, **k: avisos.append(a[2])
    )

    def falla(*args, **kwargs):
        raise OSError("disco lleno")

    monkeypatch.setattr(desktop_app, "save_theme", falla)

    FemagDesktopWindow._toggle_theme(ventana)

    assert avisos, "no aviso que la preferencia no se pudo guardar"
    assert "no se pudo guardar" in avisos[0]
    # Aplica igual: el boton promised hacer algo ahora.
    assert ventana.theme is Theme.DARK
    assert ventana.theme_button.text == "Tema: Oscuro"