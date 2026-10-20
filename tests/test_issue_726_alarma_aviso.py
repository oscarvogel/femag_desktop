"""#726: la alarma permanente de órdenes sin cuenta corriente.

El incidente no fue sólo que dos órdenes quedaran a medias: fue que **nadie se
enteró**. La mercadería salió de la planta, la cuenta corriente del cliente no
registró nada y el sistema no levantó ninguna señal.

Esta alarma pone la plata que falta en la barra superior, con dos reglas:

1. aparece sola, sin que nadie tenga que abrir un diálogo ni un script;
2. **no se puede silenciar** con "Marcar todo leído" mientras la orden siga
   rota: se apaga cuando la orden queda reparada.
"""

import os

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from test_issue_726_partial_issue import (  # noqa: E402
    CANTIDAD,
    PRECIO,
    _maestros,
    _orden_emitida_sin_cuenta_corriente,
)


def _usuarios():
    from app.models.security import User, UserProfile
    from app.services.permission_service import PermissionService

    PermissionService().seed_defaults()
    admin_profile = UserProfile.get(UserProfile.name == "Administrador")
    secretaria_profile = UserProfile.get(UserProfile.name == "Secretaría")
    admin = User.create(username="admin_alarma", password_hash="x", profile=admin_profile)
    secretaria = User.create(
        username="secretaria_alarma", password_hash="x", profile=secretaria_profile
    )
    return admin, secretaria


def _alarma(avisos):
    return [a for a in avisos if a.tipo == "orden_sin_cuenta_corriente"]


def test_el_admin_ve_el_aviso_con_la_plata_que_falta(db):
    from app.services.aviso_service import AvisoService

    admin, _secretaria = _usuarios()
    data = _maestros()
    order = _orden_emitida_sin_cuenta_corriente(data)

    alarma = _alarma(AvisoService().get_for_user(admin))

    assert len(alarma) == 1
    aviso = alarma[0]
    assert aviso.prioridad == "alta"
    assert aviso.route_key == "load_orders"
    assert aviso.referencia_id == order.id
    assert f"OC-{order.order_number:06d}" in aviso.titulo
    assert "sin registrar" in aviso.descripcion
    assert f"{CANTIDAD * PRECIO * 1.21:,.2f}" in aviso.descripcion, (
        "El aviso tiene que mostrar el monto que no está registrado: "
        "la plata perdida es lo que duele."
    )


def test_la_secretaria_no_ve_la_alarma_de_plata(db):
    """Es una alarma de administración, no un pendiente de operatoria."""
    from app.services.aviso_service import AvisoService

    _admin, secretaria = _usuarios()
    data = _maestros()
    _orden_emitida_sin_cuenta_corriente(data)

    assert _alarma(AvisoService().get_for_user(secretaria)) == []


def test_la_alarma_no_se_apaga_marcandola_leida(db):
    """'Marcar todo leído' no puede dejar al sistema caído sin avisar otra vez."""
    from app.services.aviso_service import AvisoService

    admin, _secretaria = _usuarios()
    data = _maestros()
    _orden_emitida_sin_cuenta_corriente(data)
    service = AvisoService()

    service.mark_all_read(admin)

    assert len(_alarma(service.get_for_user(admin))) == 1, (
        "La alarma tiene que seguir visible mientras la orden siga sin cuenta corriente."
    )


def test_la_alarma_desaparece_cuando_la_orden_queda_reparada(db):
    from app.services.aviso_service import AvisoService
    from app.services.load_order_ledger_repair_service import (
        LoadOrderLedgerRepairService,
    )

    admin, _secretaria = _usuarios()
    data = _maestros()
    order = _orden_emitida_sin_cuenta_corriente(data)

    LoadOrderLedgerRepairService(current_user="admin").repair(order)

    assert _alarma(AvisoService().get_for_user(admin)) == []


def test_el_badge_de_la_barra_superior_muestra_la_alarma(db):
    """La señal tiene que estar en la barra superior, no escondida en un diálogo."""
    from PyQt5.QtWidgets import QApplication, QPushButton

    from app.ui.desktop_app import FemagDesktopWindow

    app = QApplication.instance() or QApplication([])
    admin, _secretaria = _usuarios()
    data = _maestros()
    _orden_emitida_sin_cuenta_corriente(data)

    ventana = FemagDesktopWindow(user=admin, demo_mode=True)
    ventana._refresh_aviso_badge()
    boton = ventana.findChild(QPushButton, "avisoButton")

    assert boton is not None
    assert "(" in boton.text(), f"El botón de avisos tiene que contar: {boton.text()!r}"
    cantidad = int(boton.text().split("(")[1].split(")")[0])
    assert cantidad >= 1

    ventana.aviso_dropdown.refresh()
    textos = [
        ventana.aviso_dropdown.list.item(i).text()
        for i in range(ventana.aviso_dropdown.list.count())
    ]
    assert any("sin cuenta corriente" in texto for texto in textos), (
        f"El dropdown tiene que listar la alarma: {textos!r}"
    )
    ventana.close()
    assert app is not None


def test_el_badge_no_muestra_alarma_si_no_hay_ordenes_rotas(db):
    """Sin roturas, la barra superior no inventa pendientes de plata."""
    from PyQt5.QtWidgets import QApplication, QPushButton

    from app.ui.desktop_app import FemagDesktopWindow

    app = QApplication.instance() or QApplication([])
    admin, _secretaria = _usuarios()

    ventana = FemagDesktopWindow(user=admin, demo_mode=True)
    ventana._refresh_aviso_badge()
    boton = ventana.findChild(QPushButton, "avisoButton")

    assert boton is not None
    assert boton.text() == "Avisos" or "(0)" in boton.text()
    ventana.close()
    assert app is not None


def test_el_aviso_de_plata_trae_la_accion_de_reparacion(db):
    """El aviso tiene que abrir la reparación, no sólo navegar a una pantalla."""
    from app.services.aviso_service import ACCION_REPARAR_CUENTA_CORRIENTE, AvisoService

    admin, _secretaria = _usuarios()
    data = _maestros()
    _orden_emitida_sin_cuenta_corriente(data)

    alarma = _alarma(AvisoService().get_for_user(admin))

    assert len(alarma) == 1
    assert alarma[0].accion == ACCION_REPARAR_CUENTA_CORRIENTE


def test_clickear_el_aviso_de_plata_abre_la_pantalla_de_reparacion(db, monkeypatch):
    """Clic en el aviso -> diálogo de reparación (sin adivinar dónde está)."""
    import app.ui.desktop_app as desktop_app
    from PyQt5.QtCore import Qt
    from PyQt5.QtWidgets import QApplication

    from app.ui.desktop_app import FemagDesktopWindow

    app = QApplication.instance() or QApplication([])
    admin, _secretaria = _usuarios()
    data = _maestros()
    _orden_emitida_sin_cuenta_corriente(data)

    abiertas = []

    class DialogoFalso:
        def __init__(self, *args, **kwargs):
            self.repaired = []
            abiertas.append(self)

        def exec_(self):
            return 0

    monkeypatch.setattr(desktop_app, "LoadOrderLedgerRepairDialog", DialogoFalso)

    ventana = FemagDesktopWindow(user=admin, demo_mode=True)
    ventana.aviso_dropdown.refresh()
    item = None
    for indice in range(ventana.aviso_dropdown.list.count()):
        candidate = ventana.aviso_dropdown.list.item(indice)
        aviso = candidate.data(Qt.UserRole)
        if aviso is not None and getattr(aviso, "tipo", "") == "orden_sin_cuenta_corriente":
            item = candidate
    assert item is not None, "El aviso de plata tiene que estar en el desplegable"

    ventana.aviso_dropdown._on_click(item)

    assert len(abiertas) == 1, "El aviso de plata tiene que abrir la pantalla de reparación"
    ventana.close()
    assert app is not None


def test_el_boton_de_reparar_no_queda_fuera_de_la_fila_de_acciones(db):
    """El botón va PRIMERO: al final se caía fuera de la ventana (#726)."""
    from PyQt5.QtWidgets import QApplication, QPushButton

    from app.ui.desktop_app import FemagDesktopWindow

    app = QApplication.instance() or QApplication([])
    admin, _secretaria = _usuarios()

    ventana = FemagDesktopWindow(user=admin, demo_mode=True)
    ventana.show()
    # La pagina tiene que estar visible: si no, su layout no se activa y las
    # coordenadas de los botones no dicen nada.
    ventana.stack.setCurrentIndex(ventana._route_indexes["load_orders"])
    app.processEvents()
    page = ventana.stack.widget(ventana._route_indexes["load_orders"])
    boton = page.findChild(QPushButton, "repairLedgerLoadOrderButton")
    nuevo = page.findChild(QPushButton, "newLoadOrderButton")

    assert boton is not None and nuevo is not None
    x_reparar = boton.mapTo(page, boton.rect().topLeft()).x()
    x_nuevo = nuevo.mapTo(page, nuevo.rect().topLeft()).x()
    assert x_reparar < x_nuevo, (
        f"El boton de reparar tiene que estar antes que el resto de las acciones "
        f"(reparar={x_reparar}, nuevo={x_nuevo})"
    )
    ventana.close()
    assert app is not None


def test_el_menu_otros_tiene_la_opcion_de_reparar_para_el_admin(db):
    """El acceso tiene que estar en la barra superior, que siempre se ve."""
    from PyQt5.QtWidgets import QApplication, QPushButton

    from app.ui.desktop_app import FemagDesktopWindow

    app = QApplication.instance() or QApplication([])
    admin, _secretaria = _usuarios()

    ventana = FemagDesktopWindow(user=admin, demo_mode=True)
    boton = ventana.findChild(QPushButton, "topbarMoreButton")

    assert boton is not None, "El boton 'Otros' tiene que estar en la barra superior"
    assert not boton.isHidden()
    ventana.close()
    assert app is not None


def test_el_boton_de_reparar_esta_en_la_pantalla_real_de_ordenes(db):
    """La pantalla que se ve en runtime la arma una EXTENSIÓN que reemplaza a la
    del código base.

    El botón estaba en la página del código base, que en runtime no se ve: por
    eso el administrador no lo encontraba aunque tuviera el build instalado
    (#726). Este test construye la pantalla de la extensión (igual que el
    arranque real) para que no vuelva a pasar.
    """
    from PyQt5.QtWidgets import QApplication, QPushButton

    from app.ui.desktop_app import FemagDesktopWindow
    from app.ui.load_order_workspace_restore_extension import (
        _restored_load_order_page,
    )

    app = QApplication.instance() or QApplication([])
    admin, _secretaria = _usuarios()

    ventana = FemagDesktopWindow(user=admin, demo_mode=True)
    ventana.show()
    app.processEvents()
    page = _restored_load_order_page(ventana)
    app.processEvents()

    boton = page.findChild(QPushButton, "repairLedgerLoadOrderButton")
    assert boton is not None, (
        "El boton de reparar tiene que estar en la pantalla REAL de ordenes "
        "(la de la extension), no solo en la del codigo base."
    )
    # ``isHidden`` dice si el botón está oculto a propósito; ``isVisible`` exige
    # que la página esté mostrada en una ventana, y acá la página se construye
    # suelta para no tocar la ventana del test.
    assert not boton.isHidden(), "El boton de reparar no puede quedar oculto"
    page.deleteLater()
    ventana.close()
    assert app is not None


def test_la_cli_de_reparacion_lista_sin_escribir(db, monkeypatch, capsys):
    """La CLI del EXE permite resolverlo sin depender de la pantalla."""
    import app.services.load_order_ledger_repair_service as servicio
    from app.main import main
    from app.models.accounting import ClientAccountMovement

    monkeypatch.setattr(servicio, "open_repair_database", lambda *a, **k: db)
    data = _maestros()
    _orden_emitida_sin_cuenta_corriente(data)

    codigo = main(["--repair-ledger"])
    salida = capsys.readouterr().out

    assert codigo == 0
    assert "OC-" in salida, f"La CLI tiene que listar las ordenes rotas: {salida!r}"
    assert "DRY-RUN" in salida
    assert ClientAccountMovement.select().count() == 0, "El dry-run no escribe nada"


def test_la_cli_de_reparacion_escribe_con_apply(db, monkeypatch, capsys):
    import app.services.load_order_ledger_repair_service as servicio
    from app.main import main
    from app.models.accounting import ClientAccountMovement

    monkeypatch.setattr(servicio, "open_repair_database", lambda *a, **k: db)
    data = _maestros()
    order = _orden_emitida_sin_cuenta_corriente(data)

    codigo = main(["--repair-ledger", "--order", str(order.order_number), "--apply"])
    salida = capsys.readouterr().out

    assert codigo == 0
    assert "APPLIED" in salida
    assert ClientAccountMovement.select().count() == 1
