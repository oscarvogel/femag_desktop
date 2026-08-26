import pytest
from pytest import approx


def _issued_order(*, multi_client: bool = False):
    from app.models.accounting import ClientAccountMovement
    from app.models.masters import Carrier, Client, ClientAddress, Driver, Product, TipoIVA, Truck
    from app.services.load_order_operation_service import LoadOrderOperationService
    from app.services.load_order_service import LoadOrderService

    iva = TipoIVA.iva_default()
    carrier = Carrier.create(name="Transporte cierre pagos")
    driver = Driver.create(name="Chofer cierre pagos", carrier=carrier)
    truck = Truck.create(domain="PAG220", carrier=carrier)
    client_a = Client.create(
        name="Cliente cierre A",
        cuit="30111111220",
        iva_condition="RI",
        descuento_porcentaje=0,
    )
    address_a = ClientAddress.create(
        client=client_a,
        address_type="entrega",
        province="Misiones",
        city="Posadas",
        address="Ruta A",
    )
    product_a = Product.create(
        name="Producto cierre A",
        unit="kg",
        precio_neto_base=100,
        peso_unitario_kg=1,
        tipo_iva=iva,
    )
    destinations = [
        {
            "client": client_a,
            "delivery_address": address_a,
            "products": [{"product": product_a, "quantity": 10}],
        }
    ]
    allocations = [
        {
            "client": client_a,
            "delivery_address": address_a,
            "product": product_a,
            "quantity": 10,
        }
    ]
    clients = [client_a]
    if multi_client:
        client_b = Client.create(
            name="Cliente cierre B",
            cuit="30222222220",
            iva_condition="RI",
            descuento_porcentaje=0,
        )
        address_b = ClientAddress.create(
            client=client_b,
            address_type="entrega",
            province="Misiones",
            city="Obera",
            address="Ruta B",
        )
        product_b = Product.create(
            name="Producto cierre B",
            unit="kg",
            precio_neto_base=200,
            peso_unitario_kg=1,
            tipo_iva=iva,
        )
        destinations.append(
            {
                "client": client_b,
                "delivery_address": address_b,
                "products": [{"product": product_b, "quantity": 5}],
            }
        )
        allocations.append(
            {
                "client": client_b,
                "delivery_address": address_b,
                "product": product_b,
                "quantity": 5,
            }
        )
        clients.append(client_b)

    order = LoadOrderService(current_user="admin_220").create_order(
        carrier=carrier,
        driver=driver,
        truck=truck,
        destinations=destinations,
        pallets=[{"sequence": 1, "pallet_type": None, "allocations": allocations}],
    )
    issued = LoadOrderOperationService(current_user="admin_220").issue(order)
    totals = {
        movement.client_id: round(float(movement.total_amount), 2)
        for movement in ClientAccountMovement.select().where(
            (ClientAccountMovement.load_order == issued)
            & (ClientAccountMovement.movement_type == ClientAccountMovement.TYPE_LOAD_ORDER)
        )
    }
    return issued, clients, totals


def test_close_with_multiple_payments_is_paid_and_links_ledger_to_order(db):
    from app.models.accounting import ClientAccountMovement
    from app.models.load_orders import LoadOrder
    from app.models.payments import ClientPayment
    from app.services.ledger_query_service import client_balance
    from app.services.load_order_closure_service import LoadOrderClosureService

    order, clients, totals = _issued_order()
    client = clients[0]
    total = totals[client.id]
    service = LoadOrderClosureService(current_user="caja_220")

    closure = service.close_order(
        order,
        payments=[
            {"client": client, "amount": 400, "method": ClientPayment.METHOD_CASH},
            {
                "client": client,
                "amount": total - 400,
                "method": ClientPayment.METHOD_TRANSFER,
                "reference": "TRF-220",
            },
        ],
    )

    payments = list(closure.payments.order_by(ClientPayment.id))
    payment_movements = list(
        ClientAccountMovement.select().where(
            ClientAccountMovement.movement_type == ClientAccountMovement.TYPE_PAYMENT
        )
    )
    assert LoadOrder.get_by_id(order.id).status == LoadOrder.STATUS_CLOSED
    assert len(payments) == 2
    assert all(payment.closure == closure for payment in payments)
    assert len(payment_movements) == 2
    assert all(movement.load_order == order for movement in payment_movements)
    assert all(f"LoadOrderClosure:{closure.id}" in movement.source_ref for movement in payment_movements)
    assert service.payment_status(closure) == service.PAYMENT_STATUS_PAID
    assert service.payment_summary(closure)[0]["balance"] == 0
    assert client_balance(client) == approx(0)


def test_close_with_partial_payment_preserves_remaining_account_balance(db):
    from app.services.ledger_query_service import client_balance
    from app.services.load_order_closure_service import LoadOrderClosureService

    order, clients, totals = _issued_order()
    client = clients[0]
    service = LoadOrderClosureService(current_user="caja_220")

    closure = service.close_order(order, payments=[{"client": client, "amount": 400}])
    summary = service.payment_summary(closure)[0]

    assert summary["status"] == service.PAYMENT_STATUS_PARTIAL
    assert summary["paid"] == 400
    assert summary["balance"] == approx(totals[client.id] - 400)
    assert client_balance(client) == approx(summary["balance"])


def test_close_without_payment_requires_and_persists_reason(db):
    from app.models.load_orders import LoadOrder, LoadOrderClosure
    from app.services.load_order_closure_service import LoadOrderClosureError, LoadOrderClosureService

    order, _clients, _totals = _issued_order()
    service = LoadOrderClosureService(current_user="caja_220")

    with pytest.raises(LoadOrderClosureError, match="motivo"):
        service.close_order(order)

    assert LoadOrder.get_by_id(order.id).status == LoadOrder.STATUS_ISSUED
    assert LoadOrderClosure.select().count() == 0

    closure = service.close_order(order, no_payment_reason="Cliente paga a 30 dias")

    assert closure.no_payment_reason == "Cliente paga a 30 dias"
    assert service.payment_status(closure) == service.PAYMENT_STATUS_UNPAID


def test_multi_client_status_is_derived_per_client_and_overpayment_is_allowed_as_credit(db):
    from app.models.load_orders import LoadOrder
    from app.services.ledger_query_service import client_balance
    from app.services.load_order_closure_service import LoadOrderClosureService

    order, clients, totals = _issued_order(multi_client=True)
    client_a, client_b = clients
    service = LoadOrderClosureService(current_user="caja_220")

    # Overpayment must not block: excess stays as saldo a favor (credit).
    closure = service.close_order(
        order,
        payments=[{"client": client_a, "amount": totals[client_a.id] + 100}],
    )
    summary = {row["client"].id: row for row in service.payment_summary(closure)}

    assert LoadOrder.get_by_id(order.id).status == LoadOrder.STATUS_CLOSED
    assert summary[client_a.id]["status"] == service.PAYMENT_STATUS_PAID
    assert summary[client_a.id]["paid"] == totals[client_a.id] + 100
    assert summary[client_a.id]["balance"] == approx(-100)
    assert summary[client_a.id]["credit"] == approx(100)
    assert summary[client_b.id]["status"] == service.PAYMENT_STATUS_UNPAID
    assert service.payment_status(closure) == service.PAYMENT_STATUS_PARTIAL
    # Overpayment leaves credit in ledger (negative balance).
    assert client_balance(client_a) == approx(-100)


def test_active_closure_payments_block_reopening_until_annulled(db):
    from app.models.accounting import ClientAccountMovement
    from app.models.load_orders import LoadOrder
    from app.models.payments import ClientPayment
    from app.models.security import User, UserProfile
    from app.services.permission_service import PermissionService
    from app.services.load_order_closure_service import LoadOrderClosureError, LoadOrderClosureService

    order, clients, _totals = _issued_order()
    service = LoadOrderClosureService(current_user="caja_220")
    closure = service.close_order(order, payments=[{"client": clients[0], "amount": 100}])

    with pytest.raises(LoadOrderClosureError, match="anular los pagos activos"):
        service.reopen_order(order, reason="Corregir entrega")

    assert closure.is_active is True

    PermissionService().seed_defaults()
    profile = UserProfile.get(UserProfile.name == "Administrador")
    admin = User.create(username="admin_reabre_220", password_hash="x", profile=profile)
    payment = closure.payments.get()
    service.payments.annul_payment(payment, authorized_by=admin, reason="Reabrir entrega")
    reopened = service.reopen_order(order, reason="Corregir entrega")
    reversal = ClientAccountMovement.get(
        ClientAccountMovement.movement_type == ClientAccountMovement.TYPE_PAYMENT_REVERSAL
    )

    assert reopened.status == LoadOrder.STATUS_ISSUED
    assert ClientPayment.get_by_id(payment.id).status == ClientPayment.STATUS_ANNULLED
    assert reversal.load_order == order


def test_closure_dialog_lists_lines_and_registers_payment(db):
    from PyQt5.QtWidgets import QApplication, QDialog

    from app.models.payments import ClientPayment
    from app.ui.load_order_closure_dialog import LoadOrderClosureDialog

    app = QApplication.instance() or QApplication([])
    order, clients, totals = _issued_order()
    dialog = LoadOrderClosureDialog(order=order, current_user="caja_220")

    assert dialog.lines_table.rowCount() == 1
    assert clients[0].name in dialog.lines_table.item(0, 0).text()
    dialog.amount_input.setValue(totals[clients[0].id])
    dialog.method_combo.setCurrentIndex(
        dialog.method_combo.findData(ClientPayment.METHOD_TRANSFER)
    )
    dialog.reference_input.setText("TRF-UI-220")
    dialog.add_payment_button.click()
    app.processEvents()

    assert dialog.payments_table.rowCount() == 1
    dialog._on_accept()
    app.processEvents()

    assert dialog.result() == QDialog.Accepted
    assert dialog.closure() is not None
    assert dialog.closure().payments.get().reference == "TRF-UI-220"


def test_closure_dialog_keeps_data_open_on_database_error(db, monkeypatch):
    from PyQt5.QtWidgets import QApplication, QMessageBox

    from app.ui.load_order_closure_dialog import LoadOrderClosureDialog

    app = QApplication.instance() or QApplication([])
    order, _clients, _totals = _issued_order()
    dialog = LoadOrderClosureDialog(order=order, current_user="caja_220")
    dialog.no_payment_reason_input.setText("Cuenta corriente")
    warnings = []

    def fail_close(*_args, **_kwargs):
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(dialog.service, "close_order", fail_close)
    monkeypatch.setattr(
        QMessageBox,
        "warning",
        lambda _parent, title, message: warnings.append((title, message)),
    )

    dialog._on_accept()
    app.processEvents()

    assert dialog.closure() is None
    assert dialog.no_payment_reason_input.text() == "Cuenta corriente"
    assert warnings == [
        (
            "Cierre de entrega",
            "No se pudo registrar el cierre. Verifique la conexion e intente nuevamente.",
        )
    ]
