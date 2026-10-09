from datetime import datetime
from decimal import Decimal
from pathlib import Path

from pypdf import PdfReader


def _pdf_text(path: Path) -> str:
    reader = PdfReader(str(path))
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    return text.replace("\u00a0", " ")


def _row(client, balance, overdue=0.0, due_7=0.0):
    return {
        "client": client,
        "salesperson_id": None,
        "balance": balance,
        "movements": 3,
        "overdue": overdue,
        "due_7": due_7,
    }


def _portfolio_salesperson(db, **kwargs):
    from app.models.masters import Salesperson

    values = {"name": "Luis"}
    values.update(kwargs)
    return Salesperson.create(**values)


def test_filename_uses_salesperson_and_date(db):
    from app.services.salesperson_portfolio_print_service import portfolio_filename

    salesperson = _portfolio_salesperson(db)
    moment = datetime(2026, 10, 1, 9, 30)

    assert (
        portfolio_filename(salesperson, moment)
        == "resumen_cuenta_corriente_luis_20261001.pdf"
    )


def test_filename_uses_todos_and_sin_asignar_when_there_is_no_single_seller(db):
    from app.services.salesperson_portfolio_print_service import portfolio_filename

    moment = datetime(2026, 10, 1, 9, 30)

    assert portfolio_filename(None, moment) == "resumen_cuenta_corriente_todos_20261001.pdf"
    assert (
        portfolio_filename(None, moment, slug="sin_asignar")
        == "resumen_cuenta_corriente_sin_asignar_20261001.pdf"
    )


def test_filename_is_safe_on_windows(db):
    from app.services.salesperson_portfolio_print_service import portfolio_filename

    salesperson = _portfolio_salesperson(db, name='"S Y T": sucursal/centro?*')
    moment = datetime(2026, 10, 1, 9, 30)

    name = portfolio_filename(salesperson, moment)

    assert name.startswith("resumen_cuenta_corriente_s_y_t_")
    assert name.endswith("_20261001.pdf")
    assert not set(name) & set('<>:"/\\|?*')


def test_totals_sum_net_amounts_and_count_clients(db):
    from app.models.masters import Client
    from app.services.salesperson_portfolio_print_service import portfolio_totals

    rows = [
        _row(Client.create(name="A", cuit="30700000001", iva_condition="RI"), 1000.0, 400.0, 100.0),
        _row(Client.create(name="B", cuit="30700000002", iva_condition="RI"), -250.5),
        _row(Client.create(name="C", cuit="30700000003", iva_condition="RI"), 0.0),
    ]

    totals = portfolio_totals(rows)

    assert totals["balance"] == Decimal("749.50")
    assert totals["overdue"] == Decimal("400.00")
    assert totals["due_7"] == Decimal("100.00")
    assert totals["clients"] == 3
    assert totals["clients_with_balance"] == 2


def test_collectable_total_ignores_credit_balances_like_the_sidebar(db):
    """El "DEUDA" del PDF debe ser el mismo numero que la "Cartera" de pantalla."""
    from app.models.masters import Client
    from app.services.salesperson_portfolio_print_service import portfolio_totals

    rows = [
        _row(Client.create(name="Deudor", cuit="30700000031", iva_condition="RI"), 1000.0),
        _row(
            Client.create(name="Con Saldo a Favor", cuit="30700000032", iva_condition="RI"),
            -400.0,
        ),
    ]

    totals = portfolio_totals(rows)

    # La barra lateral solo suma saldos positivos (customer_ledger._render_clients).
    assert totals["collectable"] == Decimal("1000.00")
    assert totals["balance"] == Decimal("600.00")


def test_export_writes_one_row_per_client_sorted_by_balance(db, tmp_path):
    from app.models.masters import Client
    from app.services import salesperson_portfolio_print_service

    salesperson = _portfolio_salesperson(db)
    rows = [
        _row(Client.create(name="Cliente Chico", cuit="30700000011", iva_condition="RI"), 500.0),
        _row(Client.create(name="Cliente Grande", cuit="30700000012", iva_condition="RI"), 79_009_859.57),
    ]

    pdf_path = salesperson_portfolio_print_service.export_salesperson_portfolio(
        salesperson=salesperson,
        rows=rows,
        output_dir=tmp_path,
        generated_at=datetime(2026, 10, 1, 9, 30),
    )
    text = _pdf_text(pdf_path)

    assert pdf_path.name == "resumen_cuenta_corriente_luis_20261001.pdf"
    assert pdf_path.read_bytes().startswith(b"%PDF")
    # El titulo se parte en dos lineas al extraer el texto del PDF.
    assert "RESUMEN DE CUENTA" in text and "CORRIENTE" in text
    assert "Luis" in text
    assert "Cliente Grande" in text and "Cliente Chico" in text
    # El mas alto de saldos va primero.
    assert text.index("Cliente Grande") < text.index("Cliente Chico")
    assert "79.009.859,57" in text
    assert "TOTAL NETO" in text
    assert "79.010.359,57" in text


def test_export_keeps_negative_balance_signed_and_in_total(db, tmp_path):
    from app.models.masters import Client
    from app.services import salesperson_portfolio_print_service

    salesperson = _portfolio_salesperson(db)
    rows = [
        _row(Client.create(name="Deudor", cuit="30700000021", iva_condition="RI"), 1000.0),
        _row(
            Client.create(name="Distribuidora Parana", cuit="30700000022", iva_condition="RI"),
            -293_160_175.34,
        ),
    ]

    pdf_path = salesperson_portfolio_print_service.export_salesperson_portfolio(
        salesperson=salesperson,
        rows=rows,
        output_dir=tmp_path,
        generated_at=datetime(2026, 10, 1, 9, 30),
    )
    text = _pdf_text(pdf_path)

    assert "-$ 293.160.175,34" in text
    # 1.000,00 - 293.160.175,34 = -293.159.175,34
    assert "-$ 293.159.175,34" in text


def test_export_without_rows_still_writes_summary(db, tmp_path):
    from app.services import salesperson_portfolio_print_service

    salesperson = _portfolio_salesperson(db)

    pdf_path = salesperson_portfolio_print_service.export_salesperson_portfolio(
        salesperson=salesperson,
        rows=[],
        output_dir=tmp_path,
        generated_at=datetime(2026, 10, 1, 9, 30),
    )
    text = _pdf_text(pdf_path)

    assert pdf_path.exists()
    assert "No hay clientes para los filtros seleccionados." in text


def test_export_uses_filter_label_when_there_is_no_single_seller(db, tmp_path):
    from app.services import salesperson_portfolio_print_service

    pdf_path = salesperson_portfolio_print_service.export_salesperson_portfolio(
        salesperson=None,
        rows=[],
        output_dir=tmp_path,
        generated_at=datetime(2026, 10, 1, 9, 30),
        label="Sin asignar",
        slug="sin_asignar",
    )
    text = _pdf_text(pdf_path)

    assert pdf_path.name == "resumen_cuenta_corriente_sin_asignar_20261001.pdf"
    assert "Sin asignar" in text


def test_export_creates_output_directory(db, tmp_path):
    from app.services import salesperson_portfolio_print_service

    salesperson = _portfolio_salesperson(db)
    destination = tmp_path / "nested" / "cartera"

    pdf_path = salesperson_portfolio_print_service.export_salesperson_portfolio(
        salesperson=salesperson,
        rows=[],
        output_dir=destination,
        generated_at=datetime(2026, 10, 1, 9, 30),
    )

    assert pdf_path.parent == destination
    assert pdf_path.exists()
