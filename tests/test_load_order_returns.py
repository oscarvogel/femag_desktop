import os

import pytest

from conftest import _master_data, _valid_order_payload

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _issued_order_with_valued_line():
    from app.models.load_orders import LoadOrder, LoadOrderProduct
    from app.services.load_order_service import LoadOrderService

    data = _master_data()
    service = LoadOrderService(current_user="issue221")
    order = service.create_order(**_valid_order_payload(data))
    line = LoadOrderProduct.select().where(LoadOrderProduct.order == order).first()
    line.precio_neto_unitario = 100.0
    line.total = round(float(line.quantity) * 121.0, 2)
    line.save()
    service.change_status(order, LoadOrder.STATUS_ISSUED, reason="Emitida para devoluciones")
    return order, line


def test_close_order_persists_return_line_and_credit_snapshot(db):
    from app.models.audit import AuditLog
    from app.models.load_orders import LoadOrderReturnLine
    from app.services.load_order_closure_service import LoadOrderClosureService

    order, line = _issued_order_with_valued_line()
    quantity = min(float(line.quantity), 2.0)

    closure = LoadOrderClosureService(current_user="issue221").close_order(
        order,
        returns=[
            {
                "order_product": line,
                "quantity": quantity,
                "reason": "Envases dañados",
            }
        ],
        no_payment_reason="Queda saldo en cuenta corriente",
    )

    returned = LoadOrderReturnLine.get()
    assert returned.closure == closure
    assert returned.order_product == line
    assert returned.quantity == pytest.approx(quantity)
    assert returned.reason == "Envases dañados"
    assert returned.unit_price == pytest.approx(float(line.total) / float(line.quantity))
    assert returned.credit_amount == pytest.approx(
        round((float(line.total) / float(line.quantity)) * quantity, 2)
    )
    assert AuditLog.select().where(
        (AuditLog.action == "registrar devolucion")
        & (AuditLog.record_ref == f"LoadOrderReturnLine:{returned.id}")
    ).exists()


def test_return_rejects_zero_excess_missing_reason_and_foreign_line(db):
    from app.services.load_order_closure_service import LoadOrderClosureError, LoadOrderClosureService

    order, line = _issued_order_with_valued_line()
    service = LoadOrderClosureService(current_user="issue221")

    with pytest.raises(LoadOrderClosureError, match="mayor a cero"):
        service.close_order(
            order,
            returns=[{"order_product": line, "quantity": 0, "reason": "Error"}],
            no_payment_reason="Cuenta corriente",
        )

    with pytest.raises(LoadOrderClosureError, match="supera la cantidad"):
        service.close_order(
            order,
            returns=[
                {
                    "order_product": line,
                    "quantity": float(line.quantity) + 1,
                    "reason": "Exceso",
                }
            ],
            no_payment_reason="Cuenta corriente",
        )

    with pytest.raises(LoadOrderClosureError, match="motivo"):
        service.close_order(
            order,
            returns=[{"order_product": line, "quantity": 1, "reason": "  "}],
            no_payment_reason="Cuenta corriente",
        )

    other_order, other_line = _issued_order_with_valued_line()
    assert other_order.id != order.id
    with pytest.raises(LoadOrderClosureError, match="otra orden"):
        service.close_order(
            order,
            returns=[{"order_product": other_line, "quantity": 1, "reason": "Ajeno"}],
            no_payment_reason="Cuenta corriente",
        )


def test_return_does_not_modify_original_order_line(db):
    from app.models.load_orders import LoadOrderProduct
    from app.services.load_order_closure_service import LoadOrderClosureService

    order, line = _issued_order_with_valued_line()
    original_quantity = float(line.quantity)
    original_total = float(line.total)

    LoadOrderClosureService(current_user="issue221").close_order(
        order,
        returns=[{"order_product": line, "quantity": 1, "reason": "Rechazo parcial"}],
        no_payment_reason="Cuenta corriente",
    )

    reloaded = LoadOrderProduct.get_by_id(line.id)
    assert float(reloaded.quantity) == pytest.approx(original_quantity)
    assert float(reloaded.total) == pytest.approx(original_total)


def test_closure_dialog_collects_return_quantity_reason_and_credit(db):
    from PyQt5.QtWidgets import QApplication, QDoubleSpinBox, QLabel, QLineEdit

    from app.ui.load_order_closure_dialog import LoadOrderClosureDialog

    app = QApplication.instance() or QApplication([])
    order, line = _issued_order_with_valued_line()
    dialog = LoadOrderClosureDialog(order=order, current_user="issue221")

    quantity_input = dialog.findChild(
        QDoubleSpinBox, f"loadOrderClosureReturnQuantityInput_{line.id}"
    )
    reason_input = dialog.findChild(
        QLineEdit, f"loadOrderClosureReturnReasonInput_{line.id}"
    )
    summary = dialog.findChild(QLabel, "loadOrderClosureReturnSummary")

    assert quantity_input is not None
    assert reason_input is not None
    assert quantity_input.maximum() == pytest.approx(float(line.quantity))

    quantity_input.setValue(min(float(line.quantity), 2.0))
    reason_input.setText("Cliente rechazó envases")
    app.processEvents()

    pending = dialog.pending_returns()
    assert len(pending) == 1
    assert pending[0]["order_product"].id == line.id
    assert pending[0]["reason"] == "Cliente rechazó envases"
    assert "Monto estimado a acreditar" in summary.text()
    assert "$ 0.00" not in summary.text()
