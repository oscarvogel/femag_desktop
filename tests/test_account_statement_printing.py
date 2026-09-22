from datetime import date
from pathlib import Path

from pypdf import PdfReader
from conftest import _complete_order_for_issue


def _pdf_text(path: Path) -> str:
    reader = PdfReader(str(path))
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    return text.replace("\u00a0", " ")


def test_account_statement_money_formatter_uses_argentine_notation():
    from app.services.account_statement_print_service import _format_money

    assert _format_money(22_046_200) == "$\u00a022.046.200,00"
    assert _format_money(-138_000) == "-$\u00a0138.000,00"
    assert _format_money(57_539_954.06) == "$\u00a057.539.954,06"


def test_account_statement_never_exposes_unknown_internal_type():
    from types import SimpleNamespace

    from app.services.account_statement_print_service import _movement_type_label

    movement = SimpleNamespace(
        movement_type="future_internal_type",
        payment=None,
    )

    assert _movement_type_label(movement) == "Movimiento"


def test_export_account_statement_without_movements(db, tmp_path):
    from app.models.masters import Client
    from app.services import account_statement_print_service

    client = Client.create(name="Cliente Sin Movs", cuit="30700000000", iva_condition="RI")

    pdf_path = account_statement_print_service.export_account_statement(client, tmp_path)
    text = _pdf_text(pdf_path)

    assert pdf_path.exists()
    assert pdf_path.read_bytes().startswith(b"%PDF")
    assert "GRAEF HERMANOS S.R.L." in text
    assert "ESTADO DE CUENTA" in text
    assert "Extracto de cuenta corriente" in text
    assert "Cliente Sin Movs" in text
    assert "SALDO ACTUAL" in text
    assert "no tiene movimientos" in text
    assert "1 de 1" in text


def test_export_account_statement_with_load_order_movement(db, tmp_path):
    from app.models.masters import Carrier, Client, ClientAddress, Driver, Product, Truck
    from app.services import account_statement_print_service
    from app.services.load_order_operation_service import LoadOrderOperationService
    from app.services.load_order_service import LoadOrderService

    client = Client.create(name="Cliente Test", cuit="30711111111", iva_condition="RI")
    address = ClientAddress.create(
        client=client, address_type="entrega", province="Misiones", city="Posadas", address="Ruta 12"
    )
    carrier = Carrier.create(name="Transporte Sur")
    driver = Driver.create(name="Pedro Gomez", carrier=carrier)
    truck = Truck.create(domain="ZZ999ZZ", carrier=carrier)
    product = Product.create(name="Fecula", unit="kg")
    order = LoadOrderService(current_user="admin").create_order(
        client=client,
        delivery_address=address,
        carrier=carrier,
        driver=driver,
        truck=truck,
        products=[{"product": product, "quantity": 500}],
    )
    _complete_order_for_issue(order)
    LoadOrderOperationService(current_user="admin").issue(order)

    pdf_path = account_statement_print_service.export_account_statement(client, tmp_path)
    text = _pdf_text(pdf_path)

    assert pdf_path.exists()
    assert pdf_path.read_bytes().startswith(b"%PDF")
    assert "ESTADO DE CUENTA" in text
    assert "Cliente Test" in text
    assert "Orden de carga" in text
    assert "SALDO ACTUAL" in text
    assert "COMPROBANTE" in text
    assert "CONCEPTO" in text


def test_export_account_statement_multi_movement_balance_and_summary(db, tmp_path):
    from app.models.accounting import ClientAccountMovement
    from app.models.masters import Client
    from app.services import account_statement_print_service

    client = Client.create(name="Cliente Multi", cuit="30722222222", iva_condition="RI")
    ClientAccountMovement.create(
        client=client,
        movement_type=ClientAccountMovement.TYPE_OPENING_BALANCE,
        total_amount=250.0,
        currency="ARS",
        description="Saldo importado",
        source_ref="opening:multi",
        movement_date=date(2026, 1, 1),
        created_by="admin",
    )
    ClientAccountMovement.create(
        client=client,
        movement_type=ClientAccountMovement.TYPE_LOAD_ORDER,
        total_amount=1000.0,
        currency="ARS",
        description="OC-0001",
        source_ref="load_order:1",
        movement_date=date(2026, 1, 2),
        created_by="admin",
    )
    ClientAccountMovement.create(
        client=client,
        movement_type=ClientAccountMovement.TYPE_PAYMENT,
        total_amount=-400.0,
        currency="ARS",
        description="Pago parcial",
        source_ref="payment:1",
        movement_date=date(2026, 1, 3),
        created_by="admin",
    )

    pdf_path = account_statement_print_service.export_account_statement(client, tmp_path)
    text = _pdf_text(pdf_path)

    assert "Cliente Multi" in text
    assert "Saldo inicial" in text
    assert "Pago" in text
    assert "SALDO ANTERIOR" in text
    assert "DÉBITOS / COMPRAS" in text
    assert "PAGOS / CRÉDITOS" in text
    assert "SALDO ACTUAL" in text
    assert "250,00" in text
    assert "1.000,00" in text
    assert "-$ 400,00" in text or "-$400,00" in text
    assert "850,00" in text


def test_export_account_statement_shows_client_cuit_and_date(db, tmp_path):
    from app.models.masters import Client
    from app.services import account_statement_print_service

    client = Client.create(name="Cliente CUIT", cuit="30333333330", iva_condition="RI")
    pdf_path = account_statement_print_service.export_account_statement(client, tmp_path)
    text = _pdf_text(pdf_path)

    assert "30333333330" in text
    assert "CUIT" in text
    assert "Estado de cuenta al" in text


def test_export_account_statement_pdf_is_valid_pdf(db, tmp_path):
    from app.models.masters import Client
    from app.services import account_statement_print_service

    client = Client.create(name="Cliente Valid", cuit="30444444440", iva_condition="RI")
    pdf_path = account_statement_print_service.export_account_statement(client, tmp_path)

    assert pdf_path.suffix == ".pdf"
    assert pdf_path.read_bytes().startswith(b"%PDF")
    reader = PdfReader(str(pdf_path))
    assert len(reader.pages) >= 1


def test_export_account_statement_includes_manual_debit_and_reversal(db, tmp_path):
    from app.models.masters import Client
    from app.services import account_statement_print_service
    from app.services.client_manual_debit_service import ClientManualDebitService

    client = Client.create(
        name="Cliente Débito PDF",
        cuit="30700001217",
        iva_condition="RI",
    )
    service = ClientManualDebitService(current_user="caja")
    debit = service.register_manual_debit(
        client=client,
        amount=5000,
        debit_date=date(2026, 8, 7),
        description="Interés por mora",
        reference="ND-PDF-217",
    )
    service.reverse_manual_debit(
        debit,
        reversal_date=date(2026, 8, 8),
        reason="Reverso para extracto de prueba",
    )

    pdf_path = account_statement_print_service.export_account_statement(client, tmp_path)
    text = _pdf_text(pdf_path)

    assert "Débito manual" in text
    assert "Reverso de débito" in text
    assert "ND-PDF-217" in text
    assert "Interés por mora" in text
    assert "5.000,00" in text
    assert "0,00" in text
    assert "5,000.00" not in text


def test_export_account_statement_translates_manual_budget_type(db, tmp_path):
    from app.models.accounting import ClientAccountMovement
    from app.models.masters import Client
    from app.services import account_statement_print_service

    client = Client.create(name="Cliente Presupuesto", cuit="30755555551", iva_condition="RI")
    ClientAccountMovement.create(
        client=client,
        movement_type=ClientAccountMovement.TYPE_BUDGET_MANUAL,
        total_amount=859100.0,
        currency="ARS",
        movement_date=date(2026, 9, 21),
        description="Presupuesto de mercadería",
        observations="Prueba comercial",
        source_ref="Budget:4",
        reference="PRES-000004",
        created_by="admin",
    )

    pdf_path = account_statement_print_service.export_account_statement(client, tmp_path)
    text = _pdf_text(pdf_path)

    assert "Presupuesto" in text
    assert "PRES-000004" in text
    assert "859.100,00" in text
    assert "budget_manual" not in text


def test_export_account_statement_localizes_money_embedded_in_description(db, tmp_path):
    from app.models.accounting import ClientAccountMovement
    from app.models.masters import Client
    from app.services import account_statement_print_service

    client = Client.create(name="Cliente Formato", cuit="30766666668", iva_condition="RI")
    ClientAccountMovement.create(
        client=client,
        movement_type=ClientAccountMovement.TYPE_LOAD_ORDER,
        total_amount=22046200.0,
        currency="ARS",
        movement_date=date(2026, 9, 20),
        description="Neto $22,046,200.00 - IVA $3,826,200.00",
        source_ref="format:1",
        reference="OC-990002",
        created_by="admin",
    )

    pdf_path = account_statement_print_service.export_account_statement(client, tmp_path)
    text = _pdf_text(pdf_path)

    assert "22.046.200,00" in text
    assert "3.826.200,00" in text
    assert "22,046,200.00" not in text
    assert "3,826,200.00" not in text


def test_export_account_statement_repeats_header_and_numbers_pages(db, tmp_path):
    from app.models.accounting import ClientAccountMovement
    from app.models.masters import Client
    from app.services import account_statement_print_service

    client = Client.create(name="Cliente Multipágina", cuit="30777777775", iva_condition="RI")
    for index in range(80):
        ClientAccountMovement.create(
            client=client,
            movement_type=ClientAccountMovement.TYPE_MANUAL_DEBIT,
            total_amount=1000 + index,
            currency="ARS",
            movement_date=date(2026, 9, 1),
            description=(
                f"Ajuste comercial {index + 1} con descripción suficientemente extensa "
                "para validar el paginado profesional del estado de cuenta"
            ),
            source_ref=f"multipage:{index}",
            reference=f"AJ-{index + 1:04d}",
            created_by="admin",
        )

    pdf_path = account_statement_print_service.export_account_statement(client, tmp_path)
    reader = PdfReader(str(pdf_path))

    assert len(reader.pages) >= 2
    for page_number, page in enumerate(reader.pages, start=1):
        text = (page.extract_text() or "").replace("\u00a0", " ")
        assert "COMPROBANTE" in text
        assert "CONCEPTO" in text
        assert f"{page_number} de {len(reader.pages)}" in text
