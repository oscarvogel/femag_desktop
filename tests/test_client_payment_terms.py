from datetime import date

import pytest

from conftest import _complete_order_for_issue

from app.models.accounting import ClientAccountMovement
from app.models.masters import Carrier, Client, ClientAddress, Driver, Product, TipoIVA, Truck
from app.services.client_service import ClientService
from app.services.load_order_operation_service import LoadOrderOperationService
from app.services.load_order_service import LoadOrderService


def _issued_order(db, *, payment_term_days: int, order_date: date):
    iva = TipoIVA.iva_default()
    product = Product.create(
        name=f"Producto plazo {payment_term_days}",
        unit="kg",
        precio_neto_base=100.0,
        tipo_iva=iva,
    )
    client = Client.create(
        name=f"Cliente plazo {payment_term_days}",
        cuit=f"3070000{payment_term_days:04d}",
        iva_condition="RI",
        dias_plazo_pago=payment_term_days,
    )
    address = ClientAddress.create(
        client=client,
        address_type="entrega",
        province="Misiones",
        city="Posadas",
        address=f"Ruta {payment_term_days}",
    )
    carrier = Carrier.create(name=f"Carrier {payment_term_days}")
    driver = Driver.create(name=f"Driver {payment_term_days}", carrier=carrier)
    truck = Truck.create(domain=f"P{payment_term_days:05d}", carrier=carrier)

    order = LoadOrderService(current_user="admin").create_order(
        carrier=carrier,
        driver=driver,
        truck=truck,
        order_date=order_date,
        destinations=[
            {
                "client": client,
                "delivery_address": address,
                "products": [{"product": product, "quantity": 1}],
            }
        ],
        pallets=[],
    )
    _complete_order_for_issue(order)
    LoadOrderOperationService(current_user="admin").issue(order)
    movement = ClientAccountMovement.get(
        (ClientAccountMovement.load_order == order)
        & (ClientAccountMovement.client == client)
        & (ClientAccountMovement.movement_type == ClientAccountMovement.TYPE_LOAD_ORDER)
    )
    return client, order, movement


def test_client_service_defaults_payment_term_to_cash(db):
    client = ClientService("admin").create_client(
        "Cliente contado",
        "30711111119",
        "RI",
    )

    assert client.dias_plazo_pago == 0


def test_client_service_rejects_negative_payment_term(db):
    with pytest.raises(ValueError, match="no pueden ser negativos"):
        ClientService("admin").create_client(
            "Cliente invalido",
            "30722222229",
            "RI",
            dias_plazo_pago=-1,
        )


def test_load_order_due_date_uses_client_payment_term(db):
    client, order, movement = _issued_order(
        db,
        payment_term_days=15,
        order_date=date(2026, 8, 12),
    )

    assert client.dias_plazo_pago == 15
    assert movement.movement_date == date(2026, 8, 12)
    assert movement.due_date == date(2026, 8, 27)


def test_due_date_is_historical_when_client_term_changes(db):
    client, order, movement = _issued_order(
        db,
        payment_term_days=15,
        order_date=date(2026, 8, 12),
    )
    original_due_date = movement.due_date

    client.dias_plazo_pago = 30
    client.save()

    movement = ClientAccountMovement.get_by_id(movement.id)
    assert movement.due_date == original_due_date == date(2026, 8, 27)
    assert Client.get_by_id(client.id).dias_plazo_pago == 30
