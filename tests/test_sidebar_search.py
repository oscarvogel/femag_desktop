"""El buscador del menu lateral (#694).

Por que hay dos grupos de tests
-------------------------------
La logica de filtro esta en ``app.ui.menu.filtrar_sidebar``, que no importa Qt:
se prueba sola, rapido y sin ventanas.

Lo que si necesita Qt es la parte que se puede romper sin que nadie se entere:
que escribir no naveque (``currentRowChanged`` dispara la navegacion), que el
filtro respete el ``QSignalBlocker`` de ``_populate_sidebar`` y que el aviso de
sin resultados se muestre y se baje. Eso se prueba con una ``QListWidget`` real
y un ``self`` minimo, no con la ventana entera: ver la nota de costo en
``tests/test_theme_toggle_ui.py`` (instanciar ``FemagDesktopWindow`` en la suite
completa costo ~8 minutos). Hay un solo test que abre la ventana de verdad, para
comprobar que el widget existe y esta cableado.
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from app.ui.desktop_app import FemagDesktopWindow
from app.ui.menu import (
    MenuItemView,
    MenuSectionView,
    SidebarTreeSpec,
    filtrar_sidebar,
    normalizar_texto_menu,
)


# -- Armado del menu de prueba -------------------------------------------


def _hoja(title, route_key, **kwargs):
    return MenuItemView(title=title, route_key=route_key, **kwargs)


def _grupo(title, hijos):
    return MenuItemView(title=title, children=list(hijos))


def _spec():
    """Un menu con la misma forma que el de femag: sueltas y grupos."""
    return SidebarTreeSpec(
        sections=[
            MenuSectionView(
                title="Principal",
                items=[
                    _hoja("Dashboard", "dashboard"),
                    _hoja("Cuenta corriente", "customer_ledger"),
                    _grupo(
                        "Maestros",
                        [
                            _hoja("Clientes", "clientes"),
                            _hoja("Productos", "productos"),
                            _hoja("Tipos de IVA", "vat_types"),
                        ],
                    ),
                    _grupo(
                        "Operaciones",
                        [
                            _hoja("Órdenes de carga", "load_orders"),
                            _hoja("Remitos", "remitos"),
                            _hoja("F150", "f150"),
                        ],
                    ),
                    _grupo(
                        "Sistema",
                        [_hoja("Configuración", "remittance_series")],
                    ),
                ],
            )
        ]
    )


def _títulos(resultado):
    """Los titulos que quedaron, con los grupos tal como aparecen en la lista."""
    filas = []
    for seccion in resultado.sections:
        for item in seccion.items:
            filas.append(item.title)
            for hijo in item.children or []:
                filas.append(f"    {hijo.title}")
    return filas


# -- La logica pura -------------------------------------------------------


def test_sin_consulta_devuelve_el_menu_entero():
    """Sin escribir nada, el menu tiene que quedar como estaba."""
    spec = _spec()

    resultado = filtrar_sidebar(spec.sections, "")

    assert resultado.sections == spec.sections
    assert resultado.empty is False


def test_la_coincidencia_ignora_tildes_y_mayusculas():
    """'configuracion' tiene que encontrar 'Configuración'.

    Sin esto el operador escribe la palabra como la recuerda, no como esta
    escrita, y concluye que la pantalla no existe.
    """
    assert normalizar_texto_menu("Configuración") == "configuracion"

    resultado = filtrar_sidebar(_spec().sections, "configuracion")

    assert _títulos(resultado) == ["Sistema", "    Configuración"]


def test_el_titulo_de_un_grupo_muestra_el_grupo_entero():
    """Buscar 'operaciones' muestra sus tres pantallas, no solo las que matchean.

    El operador que busca un grupo quiere ver el grupo: si solo apareciera
    'Órdenes de carga', el filtro estaria respondiendo otra pregunta.
    """
    resultado = filtrar_sidebar(_spec().sections, "operaciones")

    assert _títulos(resultado) == [
        "Operaciones",
        "    Órdenes de carga",
        "    Remitos",
        "    F150",
    ]


def test_el_titulo_de_un_hijo_muestra_solo_ese_hijo():
    """Buscar 'f150' no puede volcar las ocho pantallas de Operaciones."""
    resultado = filtrar_sidebar(_spec().sections, "f150")

    assert _títulos(resultado) == ["Operaciones", "    F150"]
    assert resultado.matches == 1


def test_una_accion_suelta_se_filtra():
    resultado = filtrar_sidebar(_spec().sections, "corriente")

    assert _títulos(resultado) == ["Cuenta corriente"]


def test_sin_resultados_no_deja_grupos_colgados():
    """Un grupo sin ninguna coincidencia desaparece entero.

    Si se dejara el titulo visible, el operador veria 'Operaciones' en el menu
    y no tendria ninguna accion debajo: pareceria que el filtro anda mal.
    """
    resultado = filtrar_sidebar(_spec().sections, "xyzxyzxyz")

    assert resultado.sections == []
    assert resultado.matches == 0
    assert resultado.empty is True


def test_la_consulta_se_normaliza_para_el_aviso():
    """El aviso muestra lo que se escribio, sin espacios ni mayusculas sueltas."""
    resultado = filtrar_sidebar(_spec().sections, "  ÓRDENES  ")

    assert resultado.query == "ordenes"
    assert _títulos(resultado) == ["Operaciones", "    Órdenes de carga"]


def test_el_filtro_no_revisa_permisos():
    """El filtro opera sobre el spec ya construido: no puede inventar ni revelar.

    Si el usuario no tiene 'Usuarios', esa accion no llega al spec y el buscador
    no tiene nada que filtrar. Por eso no hace falta ninguna consulta extra.
    """
    spec = SidebarTreeSpec(
        sections=[
            MenuSectionView(
                title="Principal",
                items=[_hoja("Dashboard", "dashboard")],
            )
        ]
    )

    resultado = filtrar_sidebar(spec.sections, "usuarios")

    assert resultado.matches == 0


# -- La parte que necesita Qt --------------------------------------------


@pytest.fixture()
def qapp():
    from PyQt5.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


class _ShellDeMentira:
    def __init__(self, sidebar):
        self.sidebar = sidebar


class _VentanaMinima:
    """``self`` con lo unico que tocan los metodos del sidebar.

    Se usan los metodos reales de ``FemagDesktopWindow`` (no copias): lo que se
    prueba es el codigo que corre en la app, con una lista real y sin pagar la
    construccion de la ventana entera.
    """

    _populate_sidebar = FemagDesktopWindow._populate_sidebar
    _toggle_sidebar_group = FemagDesktopWindow._toggle_sidebar_group
    _on_sidebar_search_changed = FemagDesktopWindow._on_sidebar_search_changed
    _limpiar_buscador_menu = FemagDesktopWindow._limpiar_buscador_menu
    _ir_al_primer_resultado_menu = FemagDesktopWindow._ir_al_primer_resultado_menu
    _navigate = FemagDesktopWindow._navigate

    def __init__(self, spec):
        from PyQt5.QtWidgets import QLabel, QLineEdit, QListWidget, QStackedWidget

        self.nav = QListWidget()
        self.stack = QStackedWidget()
        self.sidebar_search = QLineEdit()
        self.sidebar_search_empty = QLabel("")
        self.shell = _ShellDeMentira(spec)
        self._sidebar_query = ""
        self._expanded_sidebar_groups = set()
        self._current_route = "dashboard"
        self._route_indexes = {}
        self.visitas = []

        # La ventana real conecta esto en `_sidebar_search_widget`.
        self.sidebar_search.textChanged.connect(self._on_sidebar_search_changed)
        self.nav.currentRowChanged.connect(self._navigate)

        # La ventana real tiene una pagina por cada ruta del menu. Aqui se
        # registran todas las del spec para que `_navigate` tenga donde ir.
        for seccion in spec.sections:
            for item in seccion.items:
                for hoja in item.children or [item]:
                    self._route_indexes[hoja.route_key] = self.stack.addWidget(QLabel(hoja.title))
        self._populate_sidebar()

    def _refresh_route(self, route):
        self.visitas.append(route)

    def filas(self):
        return [self.nav.item(i).text() for i in range(self.nav.count())]


def test_el_menu_arranca_completo_y_con_el_acordeon_cerrado(qapp):
    ventana = _VentanaMinima(_spec())

    assert ventana.filas()[0] == "Dashboard"
    assert "Operaciones" in ventana.filas()
    # Sin desplegar, los hijos no estan: es el comportamiento de siempre.
    assert not any(fila.strip() == "F150" for fila in ventana.filas())


def test_escribir_filtra_la_lista_real(qapp):
    ventana = _VentanaMinima(_spec())

    ventana.sidebar_search.setText("f150")

    assert ventana.filas() == ["Operaciones", "    F150"]


def test_escribir_no_navega_sola(qapp):
    """La navegacion sale de ``currentRowChanged``.

    Si el filtro repoblara la lista sin bloquear senales, escribir "clientes"
    dejaria marcado otro indice y la pantalla cambiaria sola.
    """
    ventana = _VentanaMinima(_spec())
    ventana._populate_sidebar()
    ventana.visitas.clear()
    ventana.stack.setCurrentIndex(ventana._route_indexes["dashboard"])

    ventana.sidebar_search.setText("f150")

    assert ventana.visitas == []
    assert ventana._current_route == "dashboard"


def test_el_aviso_aparece_y_se_baja_al_borrar(qapp):
    ventana = _VentanaMinima(_spec())

    ventana.sidebar_search.setText("xyzxyzxyz")
    assert ventana.sidebar_search_empty.isVisible()
    assert "xyzxyzxyz" in ventana.sidebar_search_empty.text()

    ventana.sidebar_search.clear()
    assert not ventana.sidebar_search_empty.isVisible()


def test_borrar_devuelve_el_menu_y_el_acordeon_como_estaba(qapp):
    """Limpiar no puede dejar el menu desplegado por el filtro."""
    ventana = _VentanaMinima(_spec())
    ventana.sidebar_search.setText("f150")

    ventana.sidebar_search.clear()

    assert ventana.filas()[0] == "Dashboard"
    assert not any(fila.strip() == "F150" for fila in ventana.filas())


def test_enter_lleva_al_primer_resultado_una_sola_vez(qapp):
    ventana = _VentanaMinima(_spec())
    ventana.sidebar_search.setText("f150")
    ventana.visitas.clear()

    ventana._ir_al_primer_resultado_menu()

    # Una sola pasada: si `setCurrentRow` no estuviera bloqueado, la señal
    # `currentRowChanged` entraria por `_navigate` y despues se llamaria otra
    # vez a mano, y la pagina se refrescaria dos veces por un solo Enter.
    assert ventana.visitas == ["f150"]
    assert ventana._current_route == "f150"


def test_enter_salta_el_titulo_de_grupo(qapp):
    """La fila 0 buscando suele ser el titulo de un grupo: no se entra ahi."""
    ventana = _VentanaMinima(_spec())

    ventana.sidebar_search.setText("maestros")
    ventana.visitas.clear()

    ventana._ir_al_primer_resultado_menu()

    assert ventana.visitas == ["clientes"]


def test_entrar_en_una_pantalla_filtrada_parte_de_la_lista(qapp):
    """Si la ruta actual no esta en el filtro, no queda marcado el titulo del grupo."""
    ventana = _VentanaMinima(_spec())

    ventana.sidebar_search.setText("maestros")

    assert ventana.nav.currentRow() == -1


def test_mientras_se_busca_el_titulo_no_colapsa_el_grupo(qapp):
    """Con el filtro puesto, el titulo es una carpeta de resultados."""
    ventana = _VentanaMinima(_spec())
    ventana.sidebar_search.setText("f150")

    ventana._toggle_sidebar_group("Operaciones")

    assert ventana.filas() == ["Operaciones", "    F150"]


def test_sin_buscar_el_titulo_sigue_colapsando(qapp):
    """El acordeon no cambia: el buscador no puede romperlo."""
    ventana = _VentanaMinima(_spec())
    ventana.sidebar_search.setText("f150")
    ventana.sidebar_search.clear()

    ventana._toggle_sidebar_group("Operaciones")
    assert any(fila.strip() == "F150" for fila in ventana.filas())

    ventana._toggle_sidebar_group("Operaciones")
    assert not any(fila.strip() == "F150" for fila in ventana.filas())


# -- El widget, en la ventana de verdad -----------------------------------


def test_el_buscador_existe_y_esta_cableado_en_la_ventana(db):
    """El criterio de aceptacion es que el operador lo vea y le funcione.

    Los tests de arriba usan una ``QListWidget`` real pero montada a mano. Este
    abre la ventana una sola vez para comprobar que el widget existe con el
    objectName que espera el QSS, que el atajo de Escape esta_colgado y que
    escribir de verdad repuebla la lista del sidebar.
    """
    from PyQt5.QtWidgets import QApplication, QLineEdit, QShortcut
    from app.models.security import User, UserProfile
    from app.services.permission_service import PermissionService

    app = QApplication.instance() or QApplication([])
    PermissionService().seed_defaults()
    profile = UserProfile.get(UserProfile.name == "Administrador")
    user = User.create(username="admin_sidebar_search", password_hash="x", profile=profile)

    window = FemagDesktopWindow(user=user, demo_mode=True)
    app.processEvents()

    search = window.findChild(QLineEdit, "sidebarSearch")
    assert search is not None, "el sidebar no tiene el buscador del menu"
    assert search.findChild(QShortcut) is not None, "Escape no esta atado al buscador"
    assert search.placeholderText(), "el buscador no dice que busca"

    antes = window.nav.count()
    search.setText("f150")
    app.processEvents()

    visibles = [window.nav.item(i).text() for i in range(window.nav.count())]
    assert any("F150" in texto for texto in visibles), visibles
    assert len(visibles) < antes, "escribir en el buscador no filtro nada"

    search.clear()
    app.processEvents()
    assert window.nav.count() == antes