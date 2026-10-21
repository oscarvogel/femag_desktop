import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _admin_window(username: str):
    from PyQt5.QtWidgets import QApplication

    from app.models.security import User, UserProfile
    from app.services.permission_service import PermissionService
    from app.ui.desktop_app import FemagDesktopWindow

    app = QApplication.instance() or QApplication([])
    PermissionService().seed_defaults()
    profile = UserProfile.get(UserProfile.name == "Administrador")
    user = User.create(username=username, password_hash="x", profile=profile)
    window = FemagDesktopWindow(user=user, demo_mode=True)
    # show() para que Qt active los layouts: en offscreen, sin mostrar, los
    # widgets quedan con la geometria por defecto y no se puede medir nada.
    window.show()
    app.processEvents()
    return app, window


RUTAS = ("raw_material_intake", "production_parts")


def _abrir(app, window, ruta: str):
    window.stack.setCurrentIndex(window._route_indexes[ruta])
    app.processEvents()
    app.processEvents()
    return window.stack.currentWidget()


def test_issue_749_las_dos_pantallas_estan_en_un_area_desplazable(db):
    """Ingreso de materia prima y Partes de produccion necesitan scroll.

    Antes (issue #749) las dos paginas se agregaban directo al stack: con una
    ventana de 1366x768 quedaban comprimidas y sus filas superpuestas.
    """
    from PyQt5.QtWidgets import QScrollArea

    app, window = _admin_window("admin_issue_749_scroll")
    window.setFixedSize(1366, 768)
    app.processEvents()
    app.processEvents()

    for ruta in RUTAS:
        page = _abrir(app, window, ruta)
        assert isinstance(page, QScrollArea), f"{ruta} deberia ir en un area desplazable"
        assert page.widget() is not None
        assert page.verticalScrollBar().maximum() > 0, (
            f"{ruta} con 1366x768 deberia poder desplazarse, no entrar apretada"
        )

    window.close()


def test_issue_749_el_contenido_no_se_corta_de_ancho(db):
    """El contenido tiene que entrar en el ancho de la ventana.

    Los textos largos de estas dos paginas no hacian word wrap, asi que el
    QLabel imponia un ancho minimo de 1571 px: dentro del area desplazable la
    pagina quedaba mas ancha que la ventana y lo de la derecha se perdia
    (con la barra horizontal desactivada, no habia forma de llegar).
    """
    from PyQt5.QtWidgets import QScrollArea

    app, window = _admin_window("admin_issue_749_ancho")
    window.setFixedSize(1366, 768)
    app.processEvents()
    app.processEvents()

    for ruta in RUTAS:
        page = _abrir(app, window, ruta)
        assert isinstance(page, QScrollArea)
        inner = page.widget()
        assert inner.width() <= page.viewport().width() + 1, (
            f"{ruta} quedo de {inner.width()}px en un viewport de "
            f"{page.viewport().width()}px: el contenido se corta"
        )

    window.close()


def test_issue_749_los_textos_largos_hacen_word_wrap(db):
    """Los textos largos tienen que poder tomar varias lineas."""
    from PyQt5.QtWidgets import QLabel

    app, window = _admin_window("admin_issue_749_wrap")
    window.setFixedSize(1366, 768)
    app.processEvents()
    app.processEvents()

    for ruta in RUTAS:
        page = _abrir(app, window, ruta)
        inner = page.widget()
        largos = [
            label
            for label in inner.findChildren(QLabel)
            if label.objectName() == "subheading" and label.wordWrap()
        ]
        assert largos, f"{ruta}: ningun texto largo hace word wrap"
        for label in largos:
            assert label.minimumSizeHint().width() < 400, (
                f"{ruta}: un texto sin wrap impone {label.minimumSizeHint().width()}px "
                "de ancho minimo y la pagina no entra en una pantalla chica"
            )

    window.close()


def test_issue_749_las_filas_del_formulario_no_se_superponen(db):
    """Con la ventana chica las filas del formulario siguen separadas."""
    from PyQt5.QtWidgets import QFormLayout, QLineEdit

    app, window = _admin_window("admin_issue_749_filas")
    window.setFixedSize(1366, 768)
    app.processEvents()
    app.processEvents()

    for ruta in RUTAS:
        page = _abrir(app, window, ruta)
        inner = page.widget()
        form = inner.findChild(QFormLayout)
        assert form is not None, f"{ruta} deberia tener un formulario"

        campos = [
            form.itemAt(row, 1).widget()
            for row in range(form.rowCount())
            if form.itemAt(row, 1) is not None and form.itemAt(row, 1).widget() is not None
        ]
        assert campos, f"{ruta}: el formulario no tiene campos"

        geometrias = []
        for campo in campos:
            geo = campo.geometry()
            geometrias.append((campo.objectName() or type(campo).__name__, geo))
            assert geo.height() >= 30, (
                f"{ruta}: {campo.objectName()} quedo con {geo.height()}px: "
                "el layout lo aplasto"
            )

        for (nombre_a, geo_a), (nombre_b, geo_b) in zip(geometrias, geometrias[1:]):
            assert geo_a.bottom() < geo_b.top(), (
                f"{ruta}: {nombre_a} y {nombre_b} se superponen"
            )

    window.close()
