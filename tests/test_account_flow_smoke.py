import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pytest import approx
from conftest import _complete_order_for_issue

from app.models.accounting import ClientAccountMovement
from app.models.payments import ClientPayment
from app.services.client_payment_service import ClientPaymentService
from app.services.ledger_query_service import client_balance
from app.services.load_order_operation_service import LoadOrderOperationService
from app.services.load_order_service import LoadOrderService


def test_full_account_flow_smoke(db):
    """Smoke punta a punta: OC emitida -> pago parcial -> pago total -> anulacion.

    Politica documentada (#145):
    - Anular una OC revierte solo el debito del cliente.
    - Los pagos ya cobrados sobreviven como saldo a favor del cliente.
    - Para devolver saldo a favor se emite una nota de credito (no un ClientPayment).
    """
    from app.models.masters import Carrier, Client, ClientAddress, Driver, Product, TipoIVA, Truck

    iva = TipoIVA.iva_default()
    product = Product.create(name="Smoke", unit="kg", precio_neto_base=1000.0, tipo_iva=iva)
    client = Client.create(
        name="Cliente Smoke", cuit="30000000007", iva_condition="RI", descuento_porcentaje=0.0
    )
    address = ClientAddress.create(
        client=client,
        address_type="entrega",
        province="Misiones",
        city="Posadas",
        address="Ruta Smoke",
    )
    carrier = Carrier.create(name="Carrier Smoke")
    driver = Driver.create(name="Driver Smoke", carrier=carrier)
    truck = Truck.create(domain="SMK01", carrier=carrier)

    # 1. Crear OC pendiente -> sin movimientos en cta cte.
    order = LoadOrderService(current_user="admin").create_order(
        carrier=carrier,
        driver=driver,
        truck=truck,
        destinations=[
            {
                "client": client,
                "delivery_address": address,
                "products": [{"product": product, "quantity": 10}],
            }
        ],
        pallets=[],
    )
    assert ClientAccountMovement.select().count() == 0
    assert client_balance(client) == 0.0

    # 2. Emitir OC -> debito por el total valorizado.
    _complete_order_for_issue(order)
    LoadOrderOperationService(current_user="admin").issue(order)
    expected_total = 10 * 1000 * 1.21  # 12100.0
    assert client_balance(client) == approx(expected_total)
    debit = ClientAccountMovement.get(
        ClientAccountMovement.movement_type == ClientAccountMovement.TYPE_LOAD_ORDER
    )
    assert debit.total_amount == approx(expected_total)
    assert debit.payment is None
    assert debit.is_reversal is False

    # 3. Pago parcial (50%).
    half = expected_total / 2
    payment_service = ClientPaymentService(current_user="admin")
    payment_half = payment_service.register_payment(client=client, amount=half)
    assert payment_half.receipt_number == "REC-00000001"
    assert client_balance(client) == approx(expected_total - half)

    credit_half = ClientAccountMovement.get(
        ClientAccountMovement.payment == payment_half
    )
    assert credit_half.total_amount == approx(-half)
    assert credit_half.movement_type == ClientAccountMovement.TYPE_PAYMENT
    assert credit_half.load_order is None
    assert credit_half.is_reversal is False

    # 4. Pago restante -> saldo en cero.
    payment_rest = payment_service.register_payment(client=client, amount=expected_total - half)
    assert payment_rest.receipt_number == "REC-00000002"
    assert client_balance(client) == 0.0
    assert ClientPayment.select().count() == 2

    # 5. Anular OC -> solo se revierte el debito. Los pagos sobreviven.
    LoadOrderOperationService(current_user="admin").annul(order, can_annul=True)
    movements = list(ClientAccountMovement.select().order_by(ClientAccountMovement.id))
    # 1 debito OC + 1 reverso OC + 2 pagos = 4 movimientos.
    assert len(movements) == 4
    # Saldo a favor del cliente (pagos no devueltos).
    assert client_balance(client) == approx(-expected_total)

    # 6. Los pagos sobreviven a la anulacion (no se devuelven automaticamente).
    assert ClientPayment.select().count() == 2

    # 7. El movimiento de reverso esta enlazado al debito original via `reverses`.
    reversal = ClientAccountMovement.get(
        ClientAccountMovement.movement_type == ClientAccountMovement.TYPE_LOAD_ORDER_REVERSAL
    )
    assert reversal.is_reversal is True
    assert reversal.reverses == debit
    assert reversal.total_amount == approx(-expected_total)
    assert reversal.payment is None
