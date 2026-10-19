"""#726: la reparación de órdenes emitidas tiene que estar en la aplicación.

El usuario no puede (y no debe) ejecutar un script de consola para dejar la
cuenta corriente de un cliente como corresponde. La reparación es una acción de
administración, en la pantalla de órdenes, y sólo un administrador la puede
hacer.
"""

import os

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from test_issue_726_partial_issue import _maestros, _orden_emitida_sin_cuenta_corriente  # noqa: E402


def _usuarios():
    from app.models.security import User, UserProfile
    from app.services.permission_service import PermissionService

    PermissionService().seed_defaults()
    admin_profile = UserProfile.get(UserProfile.name == "Administrador")
    consulta_profile = UserProfile.get(UserProfile.name == "Solo consulta")
    admin = User.create(username="admin_reparar", password_hash="x", profile=admin_profile)
    consulta = User.create(
        username="consulta_reparar", password_hash="x", profile=consulta_profile
    )
    return admin, consulta


def test_el_dialogo_de_admin_lista_las_ordenes_sin_cuenta_corriente(db):
    from PyQt5.QtWidgets import QApplication

    from app.ui.load_order_ledger_repair_dialog import LoadOrderLedgerRepairDialog

    app = QApplication.instance() or QApplication([])
    admin, _consulta = _usuarios()
    data = _maestros()
    order = _orden_emitida_sin_cuenta_corriente(data)

    dialog = LoadOrderLedgerRepairDialog("admin_reparar", user=admin)

    assert dialog.table.rowCount() == 1
    assert f"OC-{order.order_number:06d}" in dialog.table.item(0, 0).text()
    assert "PRES-" in dialog.table.item(0, 3).text()
    assert "sin registrar" in dialog.table.item(0, 4).text()
    assert dialog.repair_button.isEnabled()
    dialog.close()
    assert app is not None


def test_un_usuario_que_no_es_admin_no_puede_reparar(db):
    from PyQt5.QtWidgets import QApplication

    from app.ui.load_order_ledger_repair_dialog import LoadOrderLedgerRepairDialog

    app = QApplication.instance() or QApplication([])
    _admin, consulta = _usuarios()
    data = _maestros()
    _orden_emitida_sin_cuenta_corriente(data)

    dialog = LoadOrderLedgerRepairDialog("consulta_reparar", user=consulta)

    assert dialog.table.rowCount() == 1
    assert not dialog.repair_button.isEnabled(), (
        "Un usuario sin perfil Administrador no puede enabled la reparacion."
    )
    dialog.close()
    assert app is not None


def test_el_boton_de_reparar_solo_lo_ve_el_administrador(db):
    from PyQt5.QtWidgets import QApplication, QPushButton

    from app.ui.desktop_app import FemagDesktopWindow

    app = QApplication.instance() or QApplication([])
    admin, consulta = _usuarios()

    ventana_admin = FemagDesktopWindow(user=admin, demo_mode=True)
    page_admin = ventana_admin._load_order_page()
    boton_admin = page_admin.findChild(QPushButton, "repairLedgerLoadOrderButton")
    assert boton_admin is not None
    assert not boton_admin.isHidden(), "El administrador tiene que ver el boton"

    ventana_consulta = FemagDesktopWindow(user=consulta, demo_mode=True)
    page_consulta = ventana_consulta._load_order_page()
    boton_consulta = page_consulta.findChild(QPushButton, "repairLedgerLoadOrderButton")
    assert boton_consulta is not None
    assert boton_consulta.isHidden(), "Un usuario sin perfil Administrador no lo tiene que ver"

    ventana_admin.close()
    ventana_consulta.close()
    assert app is not None
