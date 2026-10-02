"""#613 - Filtro por fecha en los movimientos del panel de Cuenta corriente.

Regla central: el filtro ACOTA LAS FILAS, no recalcula el saldo. La columna
Saldo de cada fila visible sigue siendo el acumulado real del cliente desde su
origen, y el saldo del encabezado no se mueve.
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from datetime import date

from PyQt5.QtCore import QDate


def _ledger_page(**callbacks):
    from PyQt5.QtWidgets import QApplication

    from app.ui.customer_ledger import CustomerLedgerPage

    # La referencia debe sobrevivir: si el QApplication se libera, Qt aborta.
    app = QApplication.instance() or QApplication([])
    page = CustomerLedgerPage(current_user="admin", **callbacks)
    page._test_app = app
    return page


def _client_with_movements(db, name="Cliente Filtro", cuit="30700006101"):
    from app.models.accounting import ClientAccountMovement
    from app.models.masters import Client

    client = Client.create(name=name, cuit=cuit, iva_condition="RI")
    _add(client, ClientAccountMovement.TYPE_LOAD_ORDER, 1_000.00, date(2026, 1, 10), "OC-1")
    _add(client, ClientAccountMovement.TYPE_LOAD_ORDER, 500.00, date(2026, 2, 10), "OC-2")
    _add(client, ClientAccountMovement.TYPE_PAYMENT, -700.00, date(2026, 3, 10), "REC-1")
    _add(client, ClientAccountMovement.TYPE_LOAD_ORDER, 2_000.00, date(2026, 4, 10), "OC-3")
    _add(client, ClientAccountMovement.TYPE_MANUAL_CREDIT, -300.00, date(2026, 5, 10), "MC-1")
    return client


def _add(client, movement_type, amount, movement_date, reference):
    from app.models.accounting import ClientAccountMovement

    return ClientAccountMovement.create(
        client=client,
        movement_type=movement_type,
        total_amount=amount,
        movement_date=movement_date,
        description=f"Movimiento {reference}",
        source_ref=reference,
    )


def _select_client(page, client):
    page.refresh()
    for row in range(page.clients_table.rowCount()):
        if page.clients_table.item(row, 0).data(256) == client.id:
            page.clients_table.setCurrentCell(row, 0)
            return
    raise AssertionError("El cliente no aparece en la lista")


def _set_filter(page, *, date_from=None, date_to=None):
    if date_from is not None:
        page.movement_date_from_enabled.setChecked(True)
        page.movement_date_from.setDate(QDate(*date_from))
    if date_to is not None:
        page.movement_date_to_enabled.setChecked(True)
        page.movement_date_to.setDate(QDate(*date_to))


def _rows(page):
    return [
        page.movements_table.item(row, 0).text()
        for row in range(page.movements_table.rowCount())
    ]


def _saldos(page):
    return [
        page.movements_table.item(row, 6).text()
        for row in range(page.movements_table.rowCount())
    ]


# --------------------------------------------------------------------------------------
# Linea base: sin filtro, la pantalla no cambia
# --------------------------------------------------------------------------------------


def test_el_filtro_arranca_desactivado(db):
    _client_with_movements(db)
    page = _ledger_page()

    assert not page.movement_date_from_enabled.isChecked()
    assert not page.movement_date_to_enabled.isChecked()
    assert not page.movement_date_from.isEnabled()
    assert not page.movement_date_to.isEnabled()


def test_sin_filtro_se_ven_todos_los_movimientos(db):
    client = _client_with_movements(db)
    page = _ledger_page()
    _select_client(page, client)

    assert page.movements_table.rowCount() == 5
    assert page.detail_movements.text() == "5 movimientos"


def test_la_lista_de_clientes_no_cambia_al_filtrar(db):
    """El filtro es del panel de movimientos, no de la cartera."""
    client = _client_with_movements(db)
    page = _ledger_page()
    _select_client(page, client)
    saldo_encabezado = page.detail_balance.text()
    clientes_antes = page.clients_table.rowCount()
    totales_antes = page.totals_label.text()

    _set_filter(page, date_from=(2026, 4, 1))

    assert page.clients_table.rowCount() == clientes_antes
    assert page.totals_label.text() == totales_antes
    assert page.detail_balance.text() == saldo_encabezado


# --------------------------------------------------------------------------------------
# El filtro acota filas
# --------------------------------------------------------------------------------------


def test_filtro_desde_oculta_los_movimientos_anteriores(db):
    client = _client_with_movements(db)
    page = _ledger_page()
    _select_client(page, client)

    _set_filter(page, date_from=(2026, 3, 1))

    assert _rows(page) == ["10/03/2026", "10/04/2026", "10/05/2026"]


def test_filtro_hasta_oculta_los_movimientos_posteriores(db):
    client = _client_with_movements(db)
    page = _ledger_page()
    _select_client(page, client)

    _set_filter(page, date_to=(2026, 2, 28))

    assert _rows(page) == ["10/01/2026", "10/02/2026"]


def test_filtro_entre_dos_fechas(db):
    client = _client_with_movements(db)
    page = _ledger_page()
    _select_client(page, client)

    _set_filter(page, date_from=(2026, 2, 1), date_to=(2026, 4, 30))

    assert _rows(page) == ["10/02/2026", "10/03/2026", "10/04/2026"]


def test_un_periodo_sin_movimientos_muestra_el_vacio(db):
    client = _client_with_movements(db)
    page = _ledger_page()
    _select_client(page, client)

    _set_filter(page, date_from=(2027, 1, 1))

    assert page.movements_table.rowCount() == 0
    # En offscreen el widget no esta en una ventana visible: se mide la
    # visibilidad relativa al padre, que es lo que importa.
    assert page.empty_label.isVisibleTo(page) is True
    assert page.movements_table.isVisibleTo(page) is False


# --------------------------------------------------------------------------------------
# La regla critica: el saldo NO se recalcula
# --------------------------------------------------------------------------------------


def test_el_saldo_de_las_filas_no_se_recalcula_al_filtrar(db):
    """Filtrar desde febrero no puede hacer que la primera fila "arranque" en 500."""
    client = _client_with_movements(db)
    page = _ledger_page()
    _select_client(page, client)
    saldos_completos = _saldos(page)

    _set_filter(page, date_from=(2026, 2, 1))

    # El saldo real del cliente a esa fecha, igual que sin filtro.
    assert _saldos(page) == saldos_completos[1:]


def test_el_saldo_del_encabezado_no_cambia_al_filtrar(db):
    client = _client_with_movements(db)
    page = _ledger_page()
    _select_client(page, client)
    encabezado = page.detail_balance.text()

    _set_filter(page, date_from=(2026, 4, 1), date_to=(2026, 5, 31))

    assert page.detail_balance.text() == encabezado == "$2,500.00"


def test_el_contador_dice_cuantos_se_ven_de_cuantos_hay(db):
    client = _client_with_movements(db)
    page = _ledger_page()
    _select_client(page, client)

    _set_filter(page, date_from=(2026, 2, 1))

    assert page.detail_movements.text() == "4 de 5 movimientos"


def test_limpiar_el_filtro_restituye_todas_las_filas(db):
    client = _client_with_movements(db)
    page = _ledger_page()
    _select_client(page, client)
    _set_filter(page, date_from=(2026, 4, 1))
    assert page.movements_table.rowCount() == 2

    page.movement_date_from_enabled.setChecked(False)

    assert page.movements_table.rowCount() == 5
    assert page.detail_movements.text() == "5 movimientos"


# --------------------------------------------------------------------------------------
# Movimientos sin movement_date
# --------------------------------------------------------------------------------------


def test_los_movimientos_sin_fecha_se_filtran_por_created_at(db):
    """Misma regla que la columna Fecha: si no hay movement_date, manda created_at."""
    client = _client_with_movements(db)
    from app.models.accounting import ClientAccountMovement

    sin_fecha = ClientAccountMovement.create(
        client=client,
        movement_type=ClientAccountMovement.TYPE_MANUAL_DEBIT,
        total_amount=1_234.56,
        movement_date=None,
        description="Sin fecha de movimiento",
        source_ref="SIN-FECHA",
        created_at="2026-06-15 10:00:00",
    )
    assert sin_fecha.movement_date is None

    page = _ledger_page()
    _select_client(page, client)
    assert page.movements_table.rowCount() == 6

    _set_filter(page, date_from=(2026, 6, 1))

    # Aparece en junio, no se pierde por no tener movement_date. La columna
    # Fecha cae a created_at y por eso muestra la hora.
    assert _rows(page) == ["15/06/2026 10:00"]

    # Y un periodo que no incluye su created_at lo deja fuera.
    page.movement_date_from.setDate(QDate(2026, 7, 1))
    assert _rows(page) == []


# --------------------------------------------------------------------------------------
# Estado y costo
# --------------------------------------------------------------------------------------


def test_cambiar_de_cliente_conserva_el_filtro(db):
    from app.models.masters import Client

    primero = _client_with_movements(db, "Cliente Uno", "30700006201")
    segundo = _client_with_movements(db, "Cliente Dos", "30700006202")
    page = _ledger_page()
    _select_client(page, primero)
    _set_filter(page, date_from=(2026, 4, 1))
    assert page.movements_table.rowCount() == 2

    page.clients_table.setCurrentCell(_row_of(page, segundo.id), 0)

    assert page.detail_header.text() == segundo.name
    assert page.movements_table.rowCount() == 2
    assert Client.get_by_id(segundo.id).id == segundo.id


def test_filtrar_no_vuelve_a_consultar_los_movimientos(db, monkeypatch):
    """Mismo criterio de #535/#551: el filtro trabaja sobre lo ya cargado."""
    from app.ui import customer_ledger as modulo

    client = _client_with_movements(db)
    page = _ledger_page()
    _select_client(page, client)

    llamadas = []
    original = modulo.movements_for_client
    monkeypatch.setattr(
        modulo,
        "movements_for_client",
        lambda c: (llamadas.append(c.id), original(c))[1],
    )

    _set_filter(page, date_from=(2026, 2, 1), date_to=(2026, 5, 1))

    assert llamadas == []


def test_el_filtro_no_usa_float_para_el_saldo(db):
    """El saldo sigue viniendo del acumulado de la pantalla, sin recalculos."""
    from decimal import Decimal

    from app.services.ledger_query_service import running_balance

    client = _client_with_movements(db)
    page = _ledger_page()
    _select_client(page, client)
    _set_filter(page, date_from=(2026, 3, 1))

    esperado = [f"${b:,.2f}" for b in running_balance(list(client.account_movements))][2:]

    assert _saldos(page) == esperado
    assert all(isinstance(b, float) for b in running_balance(list(client.account_movements)))
    assert Decimal(repr(running_balance(list(client.account_movements))[-1])) == Decimal("2500.00")


def _row_of(page, client_id):
    for row in range(page.clients_table.rowCount()):
        if page.clients_table.item(row, 0).data(256) == client_id:
            return row
    raise AssertionError("El cliente no aparece en la lista")
