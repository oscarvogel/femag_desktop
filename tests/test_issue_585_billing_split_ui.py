"""UI del reparto de cantidades en la orden de carga (#585, PR 2).

Este PR agrega la captura de las dos cantidades en la pantalla. No emite
presupuestos ni mueve la cuenta corriente: eso llega en los PR siguientes.
"""
import os

import pytest
from PyQt5.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QLabel,
    QPushButton,
    QTableWidget,
)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from conftest import _master_data  # noqa: E402


def _app():
    return QApplication.instance() or QApplication([])


def _destinations(data, *, cantidad_ahora=None, cantidad=1200.0):
    return [
        {
            "client": data["client"],
            "delivery_address": data["address"],
            "products": [
                {
                    "product": data["product"],
                    "quantity": cantidad,
                    "cantidad_facturar_ahora": cantidad_ahora,
                }
            ],
        }
    ]


def _create_order(data, **kwargs):
    from app.services.load_order_service import LoadOrderService

    return LoadOrderService(current_user="issue585").create_order(
        carrier=data["carrier"],
        driver=data["driver"],
        truck=data["truck"],
        destinations=_destinations(data, **kwargs),
    )


# ------------------------------------------------------------------ servicio


def test_reparto_explicito_se_persiste(db):
    order = _create_order(_master_data(), cantidad_ahora=800.0)
    line = order.products[0]

    assert line.quantity == 1200.0
    assert line.cantidad_facturar_ahora == 800.0
    assert line.cantidad_facturacion_diferida == 400.0
    assert line.tiene_reparto_facturacion is True


def test_sin_reparto_explicito_se_guarda_como_none(db):
    order = _create_order(_master_data())
    line = order.products[0]

    assert line.cantidad_facturar_ahora is None
    assert line.tiene_reparto_facturacion is False
    assert line.cantidad_facturacion_diferida == 0.0


def test_cantidad_completa_explicita_no_marca_reparto(db):
    # Si el operador carga la parte completa, no hay reparto real que guardar.
    order = _create_order(_master_data(), cantidad_ahora=1200.0)

    assert order.products[0].cantidad_facturar_ahora is None
    assert order.products[0].tiene_reparto_facturacion is False


def test_reparto_mayor_que_la_total_se_rechaza(db):
    with pytest.raises(ValueError, match="no puede superar la cantidad total"):
        _create_order(_master_data(), cantidad_ahora=1200.01)


def test_reparto_negativo_se_rechaza(db):
    with pytest.raises(ValueError, match="no puede ser negativa"):
        _create_order(_master_data(), cantidad_ahora=-1.0)


def test_reparto_igual_a_cero_se_acepta(db):
    # Toda la mercaderia queda a facturar despues.
    order = _create_order(_master_data(), cantidad_ahora=0.0)
    line = order.products[0]

    assert line.cantidad_facturar_ahora == 0.0
    assert line.cantidad_facturacion_inmediata == 0.0
    assert line.cantidad_facturacion_diferida == 1200.0


def test_reeditar_una_orden_conserva_el_reparto(db):
    from app.services.load_order_service import LoadOrderService

    data = _master_data()
    order = _create_order(data, cantidad_ahora=800.0)
    service = LoadOrderService(current_user="issue585")

    payload = service._persisted_destination_payload(order)

    assert payload[0]["products"][0]["cantidad_facturar_ahora"] == 800.0


def test_orden_emitida_no_admite_cambio_de_reparto(db):
    """La orden emitida ya no se edita, y el reparto tampoco se toca."""
    from app.models.load_orders import LoadOrder
    from app.services.load_order_service import LoadOrderService

    data = _master_data()
    order = _create_order(data, cantidad_ahora=800.0)
    service = LoadOrderService(current_user="issue585")
    service.change_status(order, LoadOrder.STATUS_ISSUED, reason="Emitida")

    with pytest.raises(ValueError, match="Solo se pueden editar clientes y productos"):
        service.update_order(order, destinations=_destinations(data, cantidad_ahora=400.0))

    assert LoadOrder.get_by_id(order.id).products[0].cantidad_facturar_ahora == 800.0


# -------------------------------------------------------------------- UI


def test_dialogo_muestra_las_dos_cantidades(db):
    from app.ui.desktop_app import LoadOrderProductDialog

    app = _app()
    data = _master_data()
    dialog = LoadOrderProductDialog(client=data["client"])
    dialog.show()
    app.processEvents()

    total = dialog.findChild(QDoubleSpinBox, "productDialogQuantityInput")
    despues = dialog.findChild(QDoubleSpinBox, "productDialogCantidadFacturarDespuesInput")
    ahora = dialog.findChild(QLabel, "productDialogCantidadFacturarAhora")

    assert total is not None
    assert despues is not None
    assert ahora is not None

    total.setValue(1200.0)
    despues.setValue(400.0)
    app.processEvents()

    assert ahora.text() == "800"
    assert despues.value() == 400.0


def test_dialogo_sin_reparto_deja_todo_la_cantidad_para_hoy(db):
    from app.ui.desktop_app import LoadOrderProductDialog

    app = _app()
    data = _master_data()
    dialog = LoadOrderProductDialog(client=data["client"])
    combo = dialog.findChild(QComboBox, "productDialogProductInput")
    combo.setCurrentIndex(combo.findData(data["product"].id))
    dialog.findChild(QDoubleSpinBox, "productDialogQuantityInput").setValue(1200.0)
    app.processEvents()

    dialog.findChild(QPushButton, "confirmProductButton").click()
    app.processEvents()

    assert dialog.result() == QDialog.Accepted
    assert dialog.product["quantity"] == 1200.0
    assert dialog.product["cantidad_facturar_ahora"] is None


def test_dialogo_con_reparto_guarda_el_valor(db):
    from app.ui.desktop_app import LoadOrderProductDialog

    app = _app()
    data = _master_data()
    dialog = LoadOrderProductDialog(client=data["client"])
    combo = dialog.findChild(QComboBox, "productDialogProductInput")
    combo.setCurrentIndex(combo.findData(data["product"].id))
    dialog.findChild(QDoubleSpinBox, "productDialogQuantityInput").setValue(1200.0)
    dialog.findChild(QDoubleSpinBox, "productDialogCantidadFacturarDespuesInput").setValue(400.0)
    app.processEvents()

    dialog.findChild(QPushButton, "confirmProductButton").click()
    app.processEvents()

    # El operador carga lo que queda para despues; lo de hoy se deriva.
    assert dialog.product["cantidad_facturar_ahora"] == 800.0


def test_dialogo_rechaza_reparto_mayor_que_la_total(db):
    from app.ui.desktop_app import LoadOrderProductDialog
    from app.ui.form_feedback import FormFeedback

    app = _app()
    data = _master_data()
    dialog = LoadOrderProductDialog(client=data["client"])
    combo = dialog.findChild(QComboBox, "productDialogProductInput")
    combo.setCurrentIndex(combo.findData(data["product"].id))
    dialog.findChild(QDoubleSpinBox, "productDialogQuantityInput").setValue(100.0)
    dialog.findChild(QDoubleSpinBox, "productDialogCantidadFacturarDespuesInput").setValue(200.0)
    app.processEvents()

    dialog.findChild(QPushButton, "confirmProductButton").click()
    app.processEvents()

    feedback = dialog.findChild(FormFeedback, "productDialogFeedback")
    assert feedback.message == "La cantidad a facturar después no puede superar la cantidad total."
    assert feedback.kind == "warning"
    assert dialog.result() != QDialog.Accepted


def test_cambiar_la_total_no_deja_reparto_sobrante(db):
    """Si el operador achica la total, la parte de hoy se recorta sola."""
    from app.ui.desktop_app import LoadOrderProductDialog

    app = _app()
    data = _master_data()
    dialog = LoadOrderProductDialog(client=data["client"])
    total = dialog.findChild(QDoubleSpinBox, "productDialogQuantityInput")
    despues = dialog.findChild(QDoubleSpinBox, "productDialogCantidadFacturarDespuesInput")
    total.setValue(1200.0)
    despues.setValue(800.0)
    app.processEvents()

    total.setValue(500.0)
    app.processEvents()

    assert despues.value() == 500.0
    assert dialog.findChild(QLabel, "productDialogCantidadFacturarAhora").text() == "0"


def test_grillas_muestran_las_dos_columnas(db):
    from app.services.load_order_service import LoadOrderService
    from app.ui.desktop_app import LoadOrderEntryDialog

    app = _app()
    data = _master_data()
    dialog = LoadOrderEntryDialog(LoadOrderService(current_user="issue585"), "issue585")
    app.processEvents()

    product_table = dialog.findChild(QTableWidget, "loadOrderProductDraftTable")
    review_table = dialog.findChild(QTableWidget, "loadOrderReviewTable")

    product_headers = [
        product_table.horizontalHeaderItem(index).text()
        for index in range(product_table.columnCount())
    ]
    review_headers = [
        review_table.horizontalHeaderItem(index).text()
        for index in range(review_table.columnCount())
    ]

    assert "A facturar ahora" in product_headers
    assert "A facturar después" in product_headers
    assert "A facturar ahora" in review_headers
    assert "A facturar después" in review_headers


def test_editar_la_orden_conserva_el_reparto_en_pantalla(db):
    """El reparto tiene que sobrevivir a la reapertura de la orden.

    El dialogo de edicion reconstruye los borradores por su cuenta. Si ese payload
    no trae el reparto, al reabrir una orden guardada el operador ve la parte
    pendiente en cero, y al guardar de nuevo el reparto se pierde en silencio.
    """
    from app.services.load_order_service import LoadOrderService
    from app.ui.desktop_app import LoadOrderEntryDialog

    app = _app()
    data = _master_data()
    order = _create_order(data, cantidad_ahora=800.0)

    dialog = LoadOrderEntryDialog(
        LoadOrderService(current_user="issue585"), "issue585", order=order
    )
    app.processEvents()

    draft = dialog.destinations[0]["products"][0]
    assert draft["cantidad_facturar_ahora"] == 800.0

    # Y la grilla del paso Productos tiene que mostrar las dos partes.
    assert dialog.product_table.item(0, 2).text() == "800"
    assert dialog.product_table.item(0, 3).text() == "400"


def test_editar_una_orden_sin_reparto_no_marca_reparto(db):
    from app.services.load_order_service import LoadOrderService
    from app.ui.desktop_app import LoadOrderEntryDialog

    app = _app()
    order = _create_order(_master_data())

    dialog = LoadOrderEntryDialog(
        LoadOrderService(current_user="issue585"), "issue585", order=order
    )
    app.processEvents()

    assert dialog.destinations[0]["products"][0]["cantidad_facturar_ahora"] is None
    assert dialog.product_table.item(0, 2).text() == "1200"
    assert dialog.product_table.item(0, 3).text() == "0"


def test_el_reparto_sobrevive_al_ciclo_completo_de_edicion(db):
    """Reabrir y guardar una orden no puede perder el reparto.

    El dialogo arma el payload de guardado con una lista explicita de campos. Si el
    reparto no esta en esa lista, la orden se guarda igual y el reparto se pierde sin
    ningun error: por eso esta prueba va del alta a la reapertura y al guardado.
    """
    from app.models.load_orders import LoadOrder
    from app.services.load_order_service import LoadOrderService
    from app.ui.desktop_app import LoadOrderEntryDialog

    app = _app()
    order = _create_order(_master_data(), cantidad_ahora=800.0)
    service = LoadOrderService(current_user="issue585")

    dialog = LoadOrderEntryDialog(service, "issue585", order=order)
    app.processEvents()

    dialog._save()
    app.processEvents()

    line = LoadOrder.get_by_id(order.id).products[0]
    assert line.quantity == 1200.0
    assert line.cantidad_facturar_ahora == 800.0


def test_guardar_sin_reparto_no_deja_partido_el_renglon(db):
    from app.models.load_orders import LoadOrder
    from app.services.load_order_service import LoadOrderService
    from app.ui.desktop_app import LoadOrderEntryDialog

    app = _app()
    order = _create_order(_master_data())
    service = LoadOrderService(current_user="issue585")

    dialog = LoadOrderEntryDialog(service, "issue585", order=order)
    app.processEvents()
    dialog._save()
    app.processEvents()

    line = LoadOrder.get_by_id(order.id).products[0]
    assert line.cantidad_facturar_ahora is None
    assert line.tiene_reparto_facturacion is False


def test_el_reparto_sobrevive_al_ciclo_completo_de_edicion(db):
    """Reabrir y guardar una orden no puede perder el reparto.

    El dialogo arma el payload de guardado con una lista explicita de campos. Si el
    reparto no esta en esa lista, la orden se guarda igual y el reparto se pierde sin
    ningun error: por eso esta prueba va del alta a la reapertura y al guardado.
    """
    from app.models.load_orders import LoadOrder
    from app.services.load_order_service import LoadOrderService
    from app.ui.desktop_app import LoadOrderEntryDialog

    app = _app()
    order = _create_order(_master_data(), cantidad_ahora=800.0)
    service = LoadOrderService(current_user="issue585")

    dialog = LoadOrderEntryDialog(service, "issue585", order=order)
    app.processEvents()

    dialog._save()
    app.processEvents()

    line = LoadOrder.get_by_id(order.id).products[0]
    assert line.quantity == 1200.0
    assert line.cantidad_facturar_ahora == 800.0


def test_guardar_sin_reparto_no_deja_partido_el_renglon(db):
    from app.models.load_orders import LoadOrder
    from app.services.load_order_service import LoadOrderService
    from app.ui.desktop_app import LoadOrderEntryDialog

    app = _app()
    order = _create_order(_master_data())
    service = LoadOrderService(current_user="issue585")

    dialog = LoadOrderEntryDialog(service, "issue585", order=order)
    app.processEvents()
    dialog._save()
    app.processEvents()

    line = LoadOrder.get_by_id(order.id).products[0]
    assert line.cantidad_facturar_ahora is None
    assert line.tiene_reparto_facturacion is False


def test_editar_un_producto_no_deja_el_iva_en_cero(db):
    """Editar una linea de una orden existente no puede perder el IVA.

    El payload de carga no traia el IVA, el dialogo lo mostraba en 0 y lo guardaba
    en 0. Como el servicio solo recalcula el IVA cuando el valor es None, la linea
    se persistia sin impuesto y su total perdia el IVA entero.
    """
    from app.models.load_orders import LoadOrder
    from app.services.load_order_service import LoadOrderService
    from app.ui.desktop_app import LoadOrderEntryDialog, LoadOrderProductDialog

    app = _app()
    data = _master_data()
    order = _create_order(data)
    service = LoadOrderService(current_user="issue585")
    before = LoadOrder.get_by_id(order.id).products[0]
    assert before.iva_porcentaje == 21.0
    total_esperado = before.total

    dialog = LoadOrderEntryDialog(service, "issue585", order=order)
    app.processEvents()

    borrador = dialog.destinations[0]["products"][0]
    assert borrador["iva_porcentaje"] == 21.0

    # El operador edita la linea y toca el reparto de paso.
    editor = LoadOrderProductDialog(dialog, client=data["client"], product=borrador)
    editor.findChild(QDoubleSpinBox, "productDialogCantidadFacturarDespuesInput").setValue(400.0)
    editor.findChild(QPushButton, "confirmProductButton").click()
    app.processEvents()
    assert editor.product["iva_porcentaje"] == 21.0

    dialog.destinations[0]["products"][0] = editor.product
    dialog._save()
    app.processEvents()

    after = LoadOrder.get_by_id(order.id).products[0]
    assert after.iva_porcentaje == 21.0
    assert after.total == total_esperado
    assert after.cantidad_facturar_ahora == 800.0


def test_billing_split_values_por_defecto_y_con_reparto():
    from app.ui.desktop_app import _billing_split_values

    assert _billing_split_values({"quantity": 1200}) == (1200.0, 0.0)
    assert _billing_split_values({"quantity": 1200, "cantidad_facturar_ahora": 800}) == (800.0, 400.0)
    assert _billing_split_values({"quantity": 1200, "cantidad_facturar_ahora": 0}) == (0.0, 1200.0)
    # Dato inconsistente: el residuo nunca puede ser negativo.
    assert _billing_split_values({"quantity": 1200, "cantidad_facturar_ahora": 1500}) == (1200.0, 0.0)
