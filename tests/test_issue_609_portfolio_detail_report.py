"""#609 - Reporte de cuenta corriente por vendedor en version Resumido y Detallado.

Cubre el PDF detallado (vendedor > cliente > movimientos), la conciliacion con
la pantalla y con el reporte resumido, y el caso de regresion de
FRIGORIFICO EL BIERZO SA.
"""

from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from pypdf import PdfReader

BIERZO_CUIT = "30700000091"
BIERZO_SALDO_FINAL = Decimal("83107600.00")
# Secuencia de saldos acumulados, no solo el saldo final.
BIERZO_SECUENCIA = [
    Decimal("50100000.00"),
    Decimal("59400000.00"),
    Decimal("78372000.00"),
    Decimal("69072000.00"),
    Decimal("80455200.00"),
    Decimal("92407600.00"),
    Decimal("83107600.00"),
]


def _pdf_text(path: Path) -> str:
    reader = PdfReader(str(path))
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    return text.replace("\u00a0", " ")


def _pdf_pages_text(path: Path) -> list[str]:
    reader = PdfReader(str(path))
    return [(page.extract_text() or "").replace("\u00a0", " ") for page in reader.pages]


def _pdf_pages(path: Path) -> int:
    return len(PdfReader(str(path)).pages)


def _money(amount: Decimal) -> str:
    """Mismo formato que usa el PDF, para comparar contra el texto extraido."""
    raw = f"{abs(amount):,.2f}"
    integer, decimals = raw.split(".")
    sign = "-" if amount < 0 else ""
    return f"{sign}$ {integer.replace(',', '.')},{decimals}"


def _salesperson(db, name="Luis", **kwargs):
    from app.models.masters import Salesperson

    values = {"name": name}
    values.update(kwargs)
    return Salesperson.create(**values)


def _client(db, name, cuit, salesperson=None):
    from app.models.masters import Client

    return Client.create(
        name=name, cuit=cuit, iva_condition="RI", salesperson=salesperson
    )


def _load_order(db, client, number, order_date):
    from app.models.load_orders import LoadOrder
    from app.models.masters import Carrier, Driver, Truck

    carrier = Carrier.get_or_none(Carrier.name == "Transportes 609")
    if carrier is None:
        carrier = Carrier.create(name="Transportes 609")
    driver = Driver.create(name=f"Chofer 609 {number}", carrier=carrier)
    truck = Truck.create(domain=f"AB{number:03d}CD", carrier=carrier)
    return LoadOrder.create(
        order_number=number,
        date=order_date,
        client=client,
        carrier=carrier,
        driver=driver,
        truck=truck,
        status=LoadOrder.STATUS_ISSUED,
    )


def _payment(db, client, receipt_number, amount, payment_date):
    from app.models.payments import ClientPayment

    return ClientPayment.create(
        receipt_number=receipt_number,
        client=client,
        payment_date=payment_date,
        amount=amount,
        method=ClientPayment.METHOD_TRANSFER,
    )


def _movement(client, movement_type, amount, movement_date, **kwargs):
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


def _bierzo(db, salesperson):
    """Fixture de regresion: 7 movimientos que deben cerrar en 83.107.600,00."""
    from app.models.accounting import ClientAccountMovement as M

    client = _client(db, "FRIGORIFICO EL BIERZO SA", BIERZO_CUIT, salesperson)

    _movement(
        client,
        M.TYPE_MANUAL_DEBIT,
        50_100_000.00,
        date(2026, 8, 31),
        description="Debito manual porimetrial",
        source_ref="AJUSTE-2026-08",
    )
    order_6 = _load_order(db, client, 6, date(2026, 9, 4))
    _movement(
        client,
        M.TYPE_LOAD_ORDER,
        9_300_000.00,
        date(2026, 9, 4),
        load_order=order_6,
        due_date=date(2026, 9, 4),
        description="Orden de carga 6",
        source_ref="OC-000006",
    )
    order_17 = _load_order(db, client, 17, date(2026, 9, 11))
    _movement(
        client,
        M.TYPE_LOAD_ORDER,
        18_972_000.00,
        date(2026, 9, 11),
        load_order=order_17,
        due_date=date(2026, 9, 11),
        description="Orden de carga 17",
        source_ref="OC-000017",
    )
    payment_117 = _payment(db, client, "REC-00000117", 9_300_000.00, date(2026, 9, 14))
    _movement(
        client,
        M.TYPE_PAYMENT,
        -9_300_000.00,
        date(2026, 9, 14),
        payment=payment_117,
        description="Pago REC-00000117",
        source_ref="REC-00000117",
    )
    order_26 = _load_order(db, client, 26, date(2026, 9, 17))
    _movement(
        client,
        M.TYPE_LOAD_ORDER,
        11_383_200.00,
        date(2026, 9, 17),
        load_order=order_26,
        due_date=date(2026, 9, 17),
        description="Orden de carga 26",
        source_ref="OC-000026",
    )
    order_42 = _load_order(db, client, 42, date(2026, 9, 25))
    _movement(
        client,
        M.TYPE_LOAD_ORDER,
        11_952_400.00,
        date(2026, 9, 25),
        load_order=order_42,
        due_date=date(2026, 9, 25),
        description="Orden de carga 42",
        source_ref="OC-000042",
    )
    payment_118 = _payment(db, client, "REC-00000118", 9_300_000.00, date(2026, 9, 25))
    _movement(
        client,
        M.TYPE_PAYMENT,
        -9_300_000.00,
        date(2026, 9, 25),
        payment=payment_118,
        description="Pago REC-00000118",
        source_ref="REC-00000118",
    )
    return client


# --------------------------------------------------------------------------------------
# Caso de regresion obligatorio
# --------------------------------------------------------------------------------------


def test_bierzo_running_balance_sequence_is_exact(db):
    from app.services.ledger_statement_detail import client_statement_detail

    salesperson = _salesperson(db)
    client = _bierzo(db, salesperson)

    detail = client_statement_detail(client)

    assert [row.balance for row in detail.movements] == BIERZO_SECUENCIA
    assert detail.balance == BIERZO_SALDO_FINAL


def test_bierzo_screen_balance_is_83_107_600(db):
    """El saldo de la fila del vendedor tiene que ser el mismo nÃºmero."""
    from app.services.ledger_query_service import client_portfolio_rows

    salesperson = _salesperson(db)
    _bierzo(db, salesperson)

    row = client_portfolio_rows(salesperson_id=salesperson.id)[0]

    assert Decimal(repr(row["balance"])) == BIERZO_SALDO_FINAL


def test_bierzo_detailed_pdf_prints_the_whole_balance_sequence(db, tmp_path):
    from app.services import salesperson_portfolio_detail_service
    from app.services.ledger_query_service import client_portfolio_rows

    salesperson = _salesperson(db)
    _bierzo(db, salesperson)

    pdf_path = salesperson_portfolio_detail_service.export_salesperson_portfolio_detailed(
        salesperson=salesperson,
        rows=client_portfolio_rows(salesperson_id=salesperson.id),
        output_dir=tmp_path,
        generated_at=datetime(2026, 10, 1, 9, 30),
    )
    text = _pdf_text(pdf_path)

    # El bloque de arriba ya imprime el TOTAL NETO, asi que la secuencia se
    # busca a partir del primer movimiento para no medir el resumen.
    detail_text = text[text.index("Debito manual porimetrial") :]
    positions = [detail_text.index(_money(balance)) for balance in BIERZO_SECUENCIA]
    # La secuencia completa, en orden, no solo el saldo final.
    assert positions == sorted(positions)
    assert _money(BIERZO_SALDO_FINAL) in detail_text


def test_bierzo_detailed_pdf_prints_debe_haber_and_references(db, tmp_path):
    from app.services import salesperson_portfolio_detail_service
    from app.services.ledger_query_service import client_portfolio_rows

    salesperson = _salesperson(db)
    _bierzo(db, salesperson)

    pdf_path = salesperson_portfolio_detail_service.export_salesperson_portfolio_detailed(
        salesperson=salesperson,
        rows=client_portfolio_rows(salesperson_id=salesperson.id),
        output_dir=tmp_path,
        generated_at=datetime(2026, 10, 1, 9, 30),
    )
    text = _pdf_text(pdf_path)

    assert "FRIGORIFICO EL BIERZO SA" in text
    assert "OC-000006" in text and "OC-000042" in text
    assert "REC-00000117" in text and "REC-00000118" in text
    assert _money(Decimal("50100000.00")) in text
    assert _money(Decimal("9300000.00")) in text
    assert "04/09/2026" in text and "25/09/2026" in text


# --------------------------------------------------------------------------------------
# Conciliacion con la pantalla y con el reporte resumido
# --------------------------------------------------------------------------------------


def test_last_detail_balance_of_every_client_matches_the_screen(db):
    from app.services.ledger_query_service import client_portfolio_rows
    from app.services.ledger_statement_detail import client_statement_detail

    luis = _salesperson(db)
    _bierzo(db, luis)
    other = _client(db, "Mayorista Ruta 12", "30700000092", luis)
    _movement(
        other,
        "load_order_documental",
        1_234_567.89,
        date(2026, 9, 20),
        description="Orden de carga",
        source_ref="OC-MR12",
    )
    maria = _salesperson(db, "Maria")
    maria_client = _client(db, "Distribuidora Parana", "30700000093", maria)
    _movement(
        maria_client,
        "manual_credit",
        -4_500_000.25,
        date(2026, 9, 21),
        description="Credito manual",
        source_ref="CM-1",
    )

    for row in client_portfolio_rows():
        detail = client_statement_detail(row["client"])
        # El ultimo saldo acumulado del detalle es el saldo de la pantalla.
        assert detail.balance == Decimal(repr(row["balance"]))


def test_sum_of_client_balances_matches_the_summarized_seller_total(db):
    from app.services.ledger_query_service import client_portfolio_rows
    from app.services.ledger_statement_detail import client_statement_detail, detail_total
    from app.services.salesperson_portfolio_print_service import portfolio_totals

    luis = _salesperson(db)
    _bierzo(db, luis)
    negative = _client(db, "Distribuidora Parana", "30700000094", luis)
    _movement(
        negative,
        "manual_credit",
        -293_160_175.34,
        date(2026, 9, 22),
        description="Credito manual",
        source_ref="CM-2",
    )

    rows = client_portfolio_rows(salesperson_id=luis.id)
    details = [client_statement_detail(row["client"]) for row in rows]

    # Conciliacion exacta, sin diferencias de redondeo.
    assert detail_total(details) == portfolio_totals(rows)["balance"]


def test_detailed_pdf_total_block_matches_the_summarized_total(db, tmp_path):
    from app.services import salesperson_portfolio_detail_service
    from app.services.ledger_query_service import client_portfolio_rows
    from app.services.salesperson_portfolio_print_service import portfolio_totals

    salesperson = _salesperson(db)
    _bierzo(db, salesperson)
    negative = _client(db, "Distribuidora Parana", "30700000095", salesperson)
    _movement(
        negative,
        "manual_credit",
        -293_160_175.34,
        date(2026, 9, 22),
        description="Credito manual",
        source_ref="CM-3",
    )
    rows = client_portfolio_rows(salesperson_id=salesperson.id)

    pdf_path = salesperson_portfolio_detail_service.export_salesperson_portfolio_detailed(
        salesperson=salesperson,
        rows=rows,
        output_dir=tmp_path,
        generated_at=datetime(2026, 10, 1, 9, 30),
    )
    text = _pdf_text(pdf_path)

    assert _money(portfolio_totals(rows)["balance"]) in text
    assert _money(portfolio_totals(rows)["collectable"]) in text


# --------------------------------------------------------------------------------------
# Estruct vendedor > cliente > movimientos
# --------------------------------------------------------------------------------------


def test_detailed_pdf_groups_clients_by_salesperson(db, tmp_path):
    from app.services import salesperson_portfolio_detail_service
    from app.services.ledger_query_service import client_portfolio_rows

    luis = _salesperson(db)
    _bierzo(db, luis)
    maria = _salesperson(db, "Maria")
    maria_client = _client(db, "Distribuidora Parana", "30700000096", maria)
    _movement(
        maria_client,
        "manual_credit",
        -4_500_000.25,
        date(2026, 9, 21),
        description="Credito manual",
        source_ref="CM-4",
    )

    pdf_path = salesperson_portfolio_detail_service.export_salesperson_portfolio_detailed(
        salesperson=None,
        rows=client_portfolio_rows(),
        output_dir=tmp_path,
        generated_at=datetime(2026, 10, 1, 9, 30),
        label="Todos los vendedores",
        slug="todos",
    )
    text = _pdf_text(pdf_path)

    assert "VENDEDOR: Luis" in text
    assert "VENDEDOR: Maria" in text
    # Cada cliente queda debajo de su vendedor, no mezclado.
    assert text.index("VENDEDOR: Luis") < text.index("FRIGORIFICO EL BIERZO SA")
    assert text.index("FRIGORIFICO EL BIERZO SA") < text.index("VENDEDOR: Maria")
    assert text.index("VENDEDOR: Maria") < text.index("Distribuidora Parana")


def test_grouping_keeps_clients_sorted_by_balance(db):
    from app.services.salesperson_portfolio_detail_service import group_rows_by_salesperson
    from app.services.ledger_query_service import client_portfolio_rows

    luis = _salesperson(db)
    _bierzo(db, luis)
    chico = _client(db, "Cliente Chico", "30700000097", luis)
    _movement(chico, "manual_debit", 500.0, date(2026, 9, 1), description="Debito", source_ref="D1")

    rows = {row["client"].id: row for row in client_portfolio_rows(salesperson_id=luis.id)}
    groups = group_rows_by_salesperson(list(rows.values()))

    names = [group.salesperson_name for group in groups]
    assert names == ["Luis"]
    assert [row["client"].name for row in groups[0].rows] == [
        "FRIGORIFICO EL BIERZO SA",
        "Cliente Chico",
    ]


def test_unassigned_clients_are_grouped_apart(db, tmp_path):
    from app.services import salesperson_portfolio_detail_service
    from app.services.ledger_query_service import client_portfolio_rows
    from app.services.salesperson_portfolio_detail_service import group_rows_by_salesperson

    huerfano = _client(db, "Cliente Sin Vendedor", "30700000098")
    _movement(
        huerfano,
        "manual_debit",
        1_000.0,
        date(2026, 9, 1),
        description="Debito",
        source_ref="D2",
    )
    luis = _salesperson(db)
    _bierzo(db, luis)

    groups = group_rows_by_salesperson(client_portfolio_rows())
    assert sorted(group.salesperson_name for group in groups) == ["Luis", "Sin asignar"]

    pdf_path = salesperson_portfolio_detail_service.export_salesperson_portfolio_detailed(
        salesperson=None,
        rows=client_portfolio_rows(),
        output_dir=tmp_path,
        generated_at=datetime(2026, 10, 1, 9, 30),
        label="Todos los vendedores",
        slug="todos",
    )
    assert "VENDEDOR: Sin asignar" in _pdf_text(pdf_path)


# --------------------------------------------------------------------------------------
# Casos de borde
# --------------------------------------------------------------------------------------


def test_client_without_movements_keeps_zero_balance_semantics(db, tmp_path):
    from app.services import salesperson_portfolio_detail_service
    from app.services.ledger_query_service import client_portfolio_rows
    from app.services.salesperson_portfolio_print_service import portfolio_totals

    salesperson = _salesperson(db)
    sin_deuda = _client(db, "Sin Deuda", "30700000099", salesperson)

    rows = client_portfolio_rows(salesperson_id=salesperson.id)
    assert rows[0]["client"].name == "Sin Deuda"
    assert rows[0]["balance"] == 0.0

    pdf_path = salesperson_portfolio_detail_service.export_salesperson_portfolio_detailed(
        salesperson=salesperson,
        rows=rows,
        output_dir=tmp_path,
        generated_at=datetime(2026, 10, 1, 9, 30),
    )
    text = _pdf_text(pdf_path)

    assert "Sin Deuda" in text
    assert _money(Decimal("0.00")) in text
    assert _money(portfolio_totals(rows)["balance"]) in text


def test_detailed_pdf_without_rows_keeps_the_empty_message(db, tmp_path):
    from app.services import salesperson_portfolio_detail_service

    salesperson = _salesperson(db)

    pdf_path = salesperson_portfolio_detail_service.export_salesperson_portfolio_detailed(
        salesperson=salesperson,
        rows=[],
        output_dir=tmp_path,
        generated_at=datetime(2026, 10, 1, 9, 30),
    )
    text = _pdf_text(pdf_path)

    assert pdf_path.exists()
    assert "No hay clientes para los filtros seleccionados." in text


def test_detailed_filename_does_not_collide_with_the_summarized_one(db, tmp_path):
    """Generar los dos en el mismo dia no puede pisarse."""
    from app.services import salesperson_portfolio_detail_service
    from app.services import salesperson_portfolio_print_service

    salesperson = _salesperson(db)
    moment = datetime(2026, 10, 1, 9, 30)

    summarized = salesperson_portfolio_print_service.export_salesperson_portfolio(
        salesperson=salesperson,
        rows=[],
        output_dir=tmp_path,
        generated_at=moment,
    )
    detailed = salesperson_portfolio_detail_service.export_salesperson_portfolio_detailed(
        salesperson=salesperson,
        rows=[],
        output_dir=tmp_path,
        generated_at=moment,
    )

    assert summarized.name == "resumen_cuenta_corriente_luis_20261001.pdf"
    assert detailed.name != summarized.name
    assert detailed.name.startswith("resumen_cuenta_corriente_luis_")
    assert detailed.name.endswith("20261001.pdf")


# --------------------------------------------------------------------------------------
# PDF multipagina legible
# --------------------------------------------------------------------------------------


def test_detailed_pdf_is_multipage_and_repeats_the_client_headers(db, tmp_path):
    from app.services import salesperson_portfolio_detail_service
    from app.services.ledger_query_service import client_portfolio_rows

    salesperson = _salesperson(db)
    largo = _client(db, "Cliente Con Muchos Movimientos", "30700100001", salesperson)
    for index in range(120):
        _movement(
            largo,
            "load_order_documental",
            125_000.35,
            date(2026, 9, 28),
            description=f"Orden de carga numero {index}",
            source_ref=f"OC-{index:06d}",
        )

    pdf_path = salesperson_portfolio_detail_service.export_salesperson_portfolio_detailed(
        salesperson=salesperson,
        rows=client_portfolio_rows(salesperson_id=salesperson.id),
        output_dir=tmp_path,
        generated_at=datetime(2026, 10, 1, 9, 30),
    )

    pages = _pdf_pages_text(pdf_path)
    assert _pdf_pages(pdf_path) > 1
    # Toda pagina que trae movimientos repite el encabezado del cliente y las
    # columnas: ningun cliente queda separado de sus movimientos.
    pages_with_movements = 0
    for page in pages:
        if "Orden de carga numero" not in page:
            continue
        pages_with_movements += 1
        assert "Cliente Con Muchos Movimientos" in page
        assert "VENCIMIENTO" in page
        assert "SALDO" in page
    assert pages_with_movements > 1


def test_detailed_pdf_never_splits_a_client_header_from_its_first_movement(db, tmp_path):
    """Con dos clientes chicos, cada encabezado tiene que quedar con su tabla."""
    from app.services import salesperson_portfolio_detail_service
    from app.services.ledger_query_service import client_portfolio_rows

    salesperson = _salesperson(db)
    for index, amount in enumerate((1_000.0, 2_000.0, 3_000.0), start=1):
        client = _client(db, f"Cliente {index}", f"3070010000{index}", salesperson)
        _movement(
            client,
            "manual_debit",
            amount,
            date(2026, 9, 10),
            description=f"Debito manual {index}",
            source_ref=f"D-{index}",
        )

    pdf_path = salesperson_portfolio_detail_service.export_salesperson_portfolio_detailed(
        salesperson=salesperson,
        rows=client_portfolio_rows(salesperson_id=salesperson.id),
        output_dir=tmp_path,
        generated_at=datetime(2026, 10, 1, 9, 30),
    )
    pages = _pdf_pages_text(pdf_path)

    for page in pages:
        for index in (1, 2, 3):
            name = f"Cliente {index}"
            if name in page:
                assert f"Debito manual {index}" in page


# --------------------------------------------------------------------------------------
# El reporte resumido no cambia
# --------------------------------------------------------------------------------------


def test_summarized_report_still_behaves_exactly_as_before(db, tmp_path):
    from app.services import salesperson_portfolio_print_service
    from app.services.ledger_query_service import client_portfolio_rows

    salesperson = _salesperson(db)
    _bierzo(db, salesperson)

    pdf_path = salesperson_portfolio_print_service.export_salesperson_portfolio(
        salesperson=salesperson,
        rows=client_portfolio_rows(salesperson_id=salesperson.id),
        output_dir=tmp_path,
        generated_at=datetime(2026, 10, 1, 9, 30),
    )
    text = _pdf_text(pdf_path)

    assert pdf_path.name == "resumen_cuenta_corriente_luis_20261001.pdf"
    assert "RESUMEN DE CUENTA" in text and "CORRIENTE" in text
    assert "Saldos por cliente" in text
    assert "TOTAL NETO" in text
    assert _money(BIERZO_SALDO_FINAL) in text
    # El resumen no imprime movimientos: es el reporte corto de siempre.
    assert "OC-000006" not in text
