"""#609 - Servicio comun de detalle de cuenta corriente.

El detalle del reporte por vendedor no puede reimplementar los saldos: consume
este servicio, que se apoya en las mismas funciones que alimentan la pantalla
(`movements_for_client` + `running_balance`).
"""

from datetime import date
from decimal import Decimal


def _client(db, name="Cliente", cuit="30700000001"):
    from app.models.masters import Client

    return Client.create(name=name, cuit=cuit, iva_condition="RI")


def _movement(
    client,
    movement_type,
    amount,
    movement_date=date(2026, 9, 1),
    **kwargs,
):
    from app.models.accounting import ClientAccountMovement

    values = {
        "client": client,
        "movement_type": movement_type,
        "total_amount": amount,
        "movement_date": movement_date,
        "description": kwargs.pop("description", "Movimiento de prueba"),
        "source_ref": kwargs.pop("source_ref", "TEST-609"),
    }
    values.update(kwargs)
    return ClientAccountMovement.create(**values)


def test_running_balance_decimals_matches_the_existing_float_api(db):
    """La nueva API Decimal no puede cambiar el resultado de la que ya usa la UI."""
    from app.models.accounting import ClientAccountMovement
    from app.services.ledger_query_service import running_balance, running_balance_decimals

    client = _client(db)
    _movement(client, ClientAccountMovement.TYPE_MANUAL_DEBIT, 50_100_000.00)
    _movement(client, ClientAccountMovement.TYPE_LOAD_ORDER, 9_300_000.55)
    _movement(client, ClientAccountMovement.TYPE_PAYMENT, -9_300_000.55)

    movements = list(client.account_movements)
    decimals = running_balance_decimals(movements)
    floats = running_balance(movements)

    assert all(isinstance(value, Decimal) for value in decimals)
    assert [float(value) for value in decimals] == floats


def test_detail_uses_the_same_movement_stream_as_the_ledger_screen(db):
    from app.models.accounting import ClientAccountMovement
    from app.services.ledger_query_service import movements_for_client
    from app.services.ledger_statement_detail import client_statement_detail

    client = _client(db)
    _movement(client, ClientAccountMovement.TYPE_MANUAL_DEBIT, 1_000.0, date(2026, 8, 31))
    _movement(client, ClientAccountMovement.TYPE_LOAD_ORDER, 2_000.0, date(2026, 9, 4))
    _movement(client, ClientAccountMovement.TYPE_PAYMENT, -500.0, date(2026, 9, 14))

    detail = client_statement_detail(client)
    screen = movements_for_client(client)

    assert [row.movement.id for row in detail.movements] == [m.id for m in screen]


def test_detail_final_balance_matches_the_screen_running_balance(db):
    from app.models.accounting import ClientAccountMovement
    from app.services.ledger_query_service import running_balance
    from app.services.ledger_statement_detail import client_statement_detail

    client = _client(db)
    _movement(client, ClientAccountMovement.TYPE_MANUAL_DEBIT, 50_100_000.00, date(2026, 8, 31))
    _movement(client, ClientAccountMovement.TYPE_LOAD_ORDER, 9_300_000.00, date(2026, 9, 4))
    _movement(client, ClientAccountMovement.TYPE_PAYMENT, -9_300_000.00, date(2026, 9, 14))

    detail = client_statement_detail(client)
    screen_balances = running_balance(list(client.account_movements))

    assert detail.balance == Decimal(repr(screen_balances[-1]))
    assert detail.balance == Decimal("50100000.00")


def test_detail_splits_debit_and_credit_by_sign(db):
    from app.models.accounting import ClientAccountMovement
    from app.services.ledger_statement_detail import client_statement_detail

    client = _client(db)
    _movement(client, ClientAccountMovement.TYPE_MANUAL_DEBIT, 50_100_000.00)
    _movement(client, ClientAccountMovement.TYPE_MANUAL_CREDIT, -1_250_000.75)

    rows = client_statement_detail(client).movements

    assert (rows[0].debit, rows[0].credit) == (Decimal("50100000.00"), Decimal("0.00"))
    assert (rows[1].debit, rows[1].credit) == (Decimal("0.00"), Decimal("1250000.75"))


def test_detail_keeps_decimal_for_every_amount(db):
    """Regla monetaria: nada de float en debe, haber ni saldo."""
    from app.models.accounting import ClientAccountMovement
    from app.services.ledger_statement_detail import client_statement_detail

    client = _client(db)
    _movement(client, ClientAccountMovement.TYPE_LOAD_ORDER, 11_383_200.00)

    detail = client_statement_detail(client)
    row = detail.movements[0]

    assert isinstance(row.debit, Decimal)
    assert isinstance(row.credit, Decimal)
    assert isinstance(row.balance, Decimal)
    assert isinstance(detail.balance, Decimal)
    assert detail.balance == Decimal("11383200.00")


def test_detail_covers_every_movement_type_of_the_ledger(db):
    """Saldo inicial, orden de carga, pago, debito y credito manual."""
    from app.models.accounting import ClientAccountMovement
    from app.services.ledger_statement_detail import client_statement_detail

    client = _client(db)
    _movement(client, ClientAccountMovement.TYPE_OPENING_BALANCE, 5_000_000.00, date(2026, 1, 5))
    _movement(client, ClientAccountMovement.TYPE_BUDGET_MANUAL, 1_000_000.00, date(2026, 2, 2))
    _movement(client, ClientAccountMovement.TYPE_LOAD_ORDER, 2_000_000.00, date(2026, 3, 3))
    _movement(client, ClientAccountMovement.TYPE_MANUAL_DEBIT, 500_000.00, date(2026, 4, 4))
    _movement(client, ClientAccountMovement.TYPE_MANUAL_CREDIT, -300_000.00, date(2026, 5, 5))
    _movement(client, ClientAccountMovement.TYPE_PAYMENT, -1_200_000.00, date(2026, 6, 6))
    _movement(client, ClientAccountMovement.TYPE_RETURN_CREDIT, -100_000.00, date(2026, 7, 7))

    rows = client_statement_detail(client).movements

    assert [row.movement_type for row in rows] == [
        ClientAccountMovement.TYPE_OPENING_BALANCE,
        ClientAccountMovement.TYPE_BUDGET_MANUAL,
        ClientAccountMovement.TYPE_LOAD_ORDER,
        ClientAccountMovement.TYPE_MANUAL_DEBIT,
        ClientAccountMovement.TYPE_MANUAL_CREDIT,
        ClientAccountMovement.TYPE_PAYMENT,
        ClientAccountMovement.TYPE_RETURN_CREDIT,
    ]
    assert rows[-1].balance == Decimal("6900000.00")


def test_detail_of_a_client_without_movements_has_zero_balance(db):
    from app.services.ledger_statement_detail import client_statement_detail

    detail = client_statement_detail(_client(db))

    assert detail.movements == []
    assert detail.balance == Decimal("0.00")


def test_detail_running_balance_is_exact_for_long_sequences(db):
    """Sin drift: el saldo acumulado se lleva con Decimal, no con float."""
    from app.models.accounting import ClientAccountMovement
    from app.services.ledger_statement_detail import client_statement_detail

    client = _client(db)
    for index in range(50):
        _movement(
            client,
            ClientAccountMovement.TYPE_LOAD_ORDER,
            0.10,
            date(2026, 6, 1),
            source_ref=f"DRIFT-{index}",
        )

    rows = client_statement_detail(client).movements

    # Con float, 50 x 0.10 acumulado no da 5.00 de forma confiable.
    assert rows[-1].balance == Decimal("5.00")
    assert client_statement_detail(client).balance == Decimal("5.00")


def test_detail_carries_the_due_date_only_when_it_exists(db):
    from app.models.accounting import ClientAccountMovement
    from app.services.ledger_statement_detail import client_statement_detail

    client = _client(db)
    _movement(
        client,
        ClientAccountMovement.TYPE_LOAD_ORDER,
        9_300_000.00,
        date(2026, 9, 4),
        due_date=date(2026, 9, 4),
    )
    _movement(client, ClientAccountMovement.TYPE_PAYMENT, -9_300_000.00, date(2026, 9, 14))

    rows = client_statement_detail(client).movements

    assert rows[0].due_date == date(2026, 9, 4)
    assert rows[1].due_date is None
