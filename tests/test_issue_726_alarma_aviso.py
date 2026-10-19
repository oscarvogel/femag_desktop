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
