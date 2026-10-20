"""#732: emitir una orden de carga avisa cuando no hay stock suficiente.

Antes, el despacho descontaba siempre y dejaba el saldo en negativo sin avisar
nada: en la base real hay 53 despachos, ninguna entrada de stock, y los 38
productos con saldo negativo. BOLSAS DE FECULA NATIVA esta en -407.750 kg.

Ahora la emision levanta el faltante por producto y exige un motivo para
despachar igual. Con el motivo, la orden se emite y la decision queda
asentada en la auditoria y en los movimientos del libro.
"""

import os
from decimal import Decimal

import pytest
from conftest import _master_data, _valid_order_payload

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app.models.audit import AuditLog
from app.models.load_orders import LoadOrder
from app.models.stock import StockMovement
from app.services.load_order_operation_service import (
    LoadOrderOperationService,
    LoadOrderStockShortfallError,
)
from app.services.load_order_service import LoadOrderService
from app.services.stock_service import StockService


def _master():
    """Maestros de la orden. Se reutilizan entre ordenes del mismo test."""
    data = _master_data()
    data["product"].peso_unitario_kg = Decimal("2.5")
    data["product"].save()
    return data


def _orden(data, quantity=100):
    payload = _valid_order_payload(data)
    payload["pallets"] = [
        {
            "sequence": 1,
            "pallet_type": data["pallet"],
            "allocations": [
                {
                    "client": data["client"],
                    "delivery_address": data["address"],
                    "product": data["product"],
                    "quantity": quantity,
                }
            ],
        }
    ]
    return LoadOrderService(current_user="admin").create_order(**payload)


def _cargar_stock(producto, kg="1000.000"):
    """Carga el inventario inicial: el libro pasa a saber del producto."""
    return StockService.register(
        product=producto,
        movement_type=StockMovement.TYPE_INITIAL_INVENTORY,
        quantity_kg=Decimal(kg),
        source_ref=f"stock_count:{producto.id}",
        description="Inventario inicial",
        created_by="admin",
    )


def test_una_orden_con_stock_suficiente_se_emite_sin_aviso(db, tmp_path):
    """El dia a dia no cambia: si hay stock, la orden sale como siempre."""
    data = _master()
    order, producto = _orden(data), data["product"]
    _cargar_stock(producto, "1000.000")

    issued = LoadOrderOperationService(current_user="admin", prints_dir=tmp_path).issue(order)

    assert issued.status == LoadOrder.STATUS_ISSUED
    assert StockService.balance_for(producto).balance_kg == Decimal("750.000")


def test_una_orden_sin_stock_suficiente_no_se_emite(db, tmp_path):
    """Sin motivo no se emite: el faltante se avisa y se frena."""
    data = _master()
    order, producto = _orden(data), data["product"]
    _cargar_stock(producto, "100.000")  # la orden pide 250 kg

    with pytest.raises(LoadOrderStockShortfallError) as excinfo:
        LoadOrderOperationService(current_user="admin", prints_dir=tmp_path).issue(order)

    assert "stock suficiente" in str(excinfo.value)
    assert len(excinfo.value.faltantes) == 1
    faltante = excinfo.value.faltantes[0]
    assert faltante.available_kg == Decimal("100.000")
    assert faltante.requested_kg == Decimal("250.000")
    assert faltante.missing_kg == Decimal("150.000")

    # Y nada se toco: la orden sigue pendiente y el libro intacto.
    assert LoadOrder.get_by_id(order.id).status == LoadOrder.STATUS_PENDING
    assert StockMovement.select().where(
        StockMovement.movement_type == StockMovement.TYPE_DISPATCH
    ).count() == 0
    assert StockService.balance_for(producto).balance_kg == Decimal("100.000")


def test_con_motivo_la_orden_se_emite_y_el_motivo_queda_asentado(db, tmp_path):
    """El motivo es la traza: va a la auditoria y a los movimientos del libro."""
    data = _master()
    order, producto = _orden(data), data["product"]
    _cargar_stock(producto, "100.000")

    issued = LoadOrderOperationService(current_user="admin", prints_dir=tmp_path).issue(
        order, stock_override_reason="El cliente retiró más de lo facturado"
    )

    assert issued.status == LoadOrder.STATUS_ISSUED

    movimiento = StockMovement.get(
        StockMovement.source_ref == f"LoadOrder:{order.id}:Dispatch:{producto.id}"
    )
    assert movimiento.movement_type == StockMovement.TYPE_DISPATCH
    assert "El cliente retiró más de lo facturado" in (movimiento.observations or "")

    auditoria = AuditLog.get(
        (AuditLog.module == "Stock")
        & (AuditLog.action == "descontar_despacho")
        & (AuditLog.record_ref == f"LoadOrder:{order.id}")
    )
    assert auditoria.new_value["stock_override_reason"] == (
        "El cliente retiró más de lo facturado"
    )


def test_un_producto_sin_stock_cargado_no_avisa(db, tmp_path):
    """No se avisa de un faltante de algo que nunca se contó.

    El libro no tiene opinion sobre las existencias de un producto que nunca
    entro. Avisar seria avisar que falta el inventario inicial, que es otra
    cosa, y apareceria en cada despacho hasta que se cargara.
    """
    data = _master()
    order, producto = _orden(data), data["product"]

    issued = LoadOrderOperationService(current_user="admin", prints_dir=tmp_path).issue(order)

    assert issued.status == LoadOrder.STATUS_ISSUED
    # El saldo queda en negativo, como siempre: no hay stock cargado.
    assert StockService.balance_for(producto).balance_kg == Decimal("-250.000")


def test_el_faltante_sale_del_saldo_real_del_libro(db, tmp_path):
    """El disponible descuenta lo que ya salio, no solo lo que entro."""
    data = _master()
    order, producto = _orden(data), data["product"]
    _cargar_stock(producto, "1000.000")
    # Ya salio 250 kg de otra orden: quedan 750.
    StockService.register(
        product=producto,
        movement_type=StockMovement.TYPE_DISPATCH,
        quantity_kg=Decimal("250.000"),
        source_ref="LoadOrder:999:Dispatch:1",
        description="Despacho anterior",
    )

    faltantes = LoadOrderOperationService(
        current_user="admin", prints_dir=tmp_path
    ).stock.stock_shortfall(order)

    assert len(faltantes) == 0, "750 kg alcanzan para los 250 kg que pide la orden"

    # Y el disponible se recalcula: si salio mas mercaderia, el faltante aparece.
    StockService.register(
        product=producto,
        movement_type=StockMovement.TYPE_DISPATCH,
        quantity_kg=Decimal("600.000"),
        source_ref="LoadOrder:998:Dispatch:1",
        description="Otro despacho anterior",
    )

    faltantes = LoadOrderOperationService(
        current_user="admin", prints_dir=tmp_path
    ).stock.stock_shortfall(order)
    assert len(faltantes) == 1
    assert faltantes[0].available_kg == Decimal("150.000")
    assert faltantes[0].requested_kg == Decimal("250.000")
    assert faltantes[0].missing_kg == Decimal("100.000")


_QAPP = None


def _app():
    """La ``QApplication`` se guarda a nivel de modulo a proposito.

    Si se recolecta se lleva por delante los widgets C++ y PyQt falla con
    "wrapped C/C++ object ... has been deleted" (o tira el proceso). Es el
    mismo motivo por el que la guardan los demas tests de UI del repo.
    """
    global _QAPP
    from PyQt5.QtWidgets import QApplication

    if _QAPP is None:
        _QAPP = QApplication.instance() or QApplication([])
    return _QAPP


def test_el_dialogo_muestra_el_faltante_por_producto(db):
    from app.ui.load_order_stock_shortfall_dialog import LoadOrderStockShortfallDialog

    _app()
    data = _master()
    order, producto = _orden(data), data["product"]
    _cargar_stock(producto, "100.000")

    faltantes = LoadOrderOperationService(current_user="admin").stock.stock_shortfall(order)
    dialogo = LoadOrderStockShortfallDialog(order, faltantes)

    assert dialogo.table.rowCount() == 1
    assert dialogo.table.item(0, 0).text() == producto.name
    assert dialogo.table.item(0, 1).text() == "100.000"
    assert dialogo.table.item(0, 2).text() == "250.000"
    assert dialogo.table.item(0, 3).text() == "150.000"


def test_el_dialogo_no_acepta_sin_motivo(db):
    """Sin motivo no se acepta: es la unica forma de que quede la traza."""
    from PyQt5.QtWidgets import QDialog

    from app.ui.load_order_stock_shortfall_dialog import LoadOrderStockShortfallDialog

    _app()
    data = _master()
    order, producto = _orden(data), data["product"]
    _cargar_stock(producto, "100.000")

    faltantes = LoadOrderOperationService(current_user="admin").stock.stock_shortfall(order)
    dialogo = LoadOrderStockShortfallDialog(order, faltantes)

    dialogo._validate_and_accept()

    assert dialogo.result() != QDialog.Accepted
    assert "motivo" in dialogo.validation_label.text().lower()

    dialogo.reason_input.setPlainText("  Error de conteo en depósito  ")
    dialogo._validate_and_accept()

    assert dialogo.result() == QDialog.Accepted
    assert dialogo.reason() == "Error de conteo en depósito"


def test_cancelar_el_dialogo_no_emite_la_orden(db, tmp_path, monkeypatch):
    """Si el operador cancela, la orden queda como estaba."""
    from PyQt5.QtWidgets import QDialog

    from app.ui.load_order_stock_shortfall_dialog import (
        LoadOrderStockShortfallDialog,
        emit_order_with_stock_check,
    )

    _app()
    data = _master()
    order, producto = _orden(data), data["product"]
    _cargar_stock(producto, "100.000")

    monkeypatch.setattr(
        LoadOrderStockShortfallDialog, "exec_", lambda _dialog: QDialog.Rejected
    )

    resultado = emit_order_with_stock_check(
        LoadOrderOperationService(current_user="admin", prints_dir=tmp_path), order
    )

    assert resultado is None
    assert LoadOrder.get_by_id(order.id).status == LoadOrder.STATUS_PENDING
    assert StockMovement.select().where(
        StockMovement.movement_type == StockMovement.TYPE_DISPATCH
    ).count() == 0


def test_confirmar_el_dialogo_emite_la_orden_con_el_motivo(db, tmp_path, monkeypatch):
    """El camino feliz: el operador confirma y la orden sale."""
    from PyQt5.QtWidgets import QDialog

    from app.ui.load_order_stock_shortfall_dialog import (
        LoadOrderStockShortfallDialog,
        emit_order_with_stock_check,
    )

    _app()
    data = _master()
    order, producto = _orden(data), data["product"]
    _cargar_stock(producto, "100.000")

    def _aceptar(dialog):
        dialog.reason_input.setPlainText("Se regulariza con el próximo ingreso")
        return QDialog.Accepted

    monkeypatch.setattr(LoadOrderStockShortfallDialog, "exec_", _aceptar)

    issued = emit_order_with_stock_check(
        LoadOrderOperationService(current_user="admin", prints_dir=tmp_path), order
    )

    assert issued is not None
    assert issued.status == LoadOrder.STATUS_ISSUED
    movimiento = StockMovement.get(
        StockMovement.source_ref == f"LoadOrder:{order.id}:Dispatch:{producto.id}"
    )
    assert "Se regulariza con el próximo ingreso" in (movimiento.observations or "")
