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
    app.processEvents()
    return app, window


def _filas_que_se_superponen(grid) -> list[tuple[str, str]]:
    """Devuelve los pares de filas consecutivas cuyas cajas se pisan."""
    boxes: list[tuple[int, str, object]] = []
    for row in range(grid.rowCount()):
        for col in range(grid.columnCount()):
            item = grid.itemAtPosition(row, col)
            if item is None or item.widget() is None:
                continue
            boxes.append((row, grid.itemAtPosition(row, col).widget().objectName(), item.widget().geometry()))
    overlapped: list[tuple[str, str]] = []
    for index, (row, name, geo) in enumerate(boxes):
        for other_row, other_name, other_geo in boxes[index + 1 :]:
            if other_row != row + 1:
                continue
            if geo.bottom() > other_geo.top() and other_geo.bottom() > geo.top():
                overlapped.append((name, other_name))
    return overlapped


def test_issue_748_importacion_dbf_no_se_superpone_en_pantalla_baja(db):
    """La pantalla de Importacion DBF debe poder usarse en una pantalla baja.

    Antes (issue #748) la pagina no estaba dentro de un area desplazable: con
    una ventana de 1366x768 Qt comprimia los layouts y las filas del formulario
    quedaban superpuestas, sin poder elegir un archivo para importar.
    """
    from PyQt5.QtWidgets import QGridLayout, QLineEdit, QScrollArea

    app, window = _admin_window("admin_issue_748_layout")
    # show() para que Qt active los layouts: en offscreen, sin mostrar, los
    # widgets quedan con la geometria por defecto y no se puede medir nada.
    window.show()
    window._navigate_to_route("legacy_dbf_import")
    window.setFixedSize(1366, 768)
    app.processEvents()
    app.processEvents()

    scroll = window.findChild(QScrollArea, "pageScrollArea")
    assert scroll is not None, "la pagina de Importacion DBF debe ir en un area desplazable"
    assert scroll.widget() is not None
    assert scroll.widget().findChild(QLineEdit, "dbfClientsPathInput") is not None

    # La pagina conserva su alto: el scroll area no la comprime.
    assert scroll.widget().height() >= scroll.widget().minimumSizeHint().height()

    form = scroll.widget().findChild(QGridLayout)
    assert form is not None

    inputs = [
        scroll.widget().findChild(QLineEdit, name)
        for name in (
            "dbfClientsPathInput",
            "dbfCarriersPathInput",
            "dbfDriversPathInput",
            "dbfTrucksPathInput",
            "dbfProductsPathInput",
            "dbfEncodingInput",
            "dbfSourceSystemInput",
        )
    ]
    for field in inputs:
        assert field is not None
        assert field.height() >= 38, (
            f"{field.objectName()} quedo con {field.height()}px: el layout lo aplasto"
        )

    assert _filas_que_se_superponen(form) == [], (
        "las filas del formulario se superponen: "
        f"{_filas_que_se_superponen(form)}"
    )

    window.close()


def test_issue_748_importacion_dbf_tiene_area_desplazable_con_scroll(db):
    """Con la ventana chica debe aparecer la barra vertical de scroll."""
    from PyQt5.QtCore import Qt
    from PyQt5.QtWidgets import QScrollArea

    app, window = _admin_window("admin_issue_748_scroll")
    window.show()
    window._navigate_to_route("legacy_dbf_import")
    window.setFixedSize(1366, 768)
    app.processEvents()
    app.processEvents()

    scroll = window.findChild(QScrollArea, "pageScrollArea")
    assert scroll is not None
    assert scroll.verticalScrollBar().maximum() > 0, (
        "con 1366x768 la pagina no deberia entrar entera: deberia poder desplazarse"
    )
    assert scroll.horizontalScrollBarPolicy() == Qt.ScrollBarAlwaysOff

    window.close()
