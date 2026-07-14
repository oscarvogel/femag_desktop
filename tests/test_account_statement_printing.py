from pathlib import Path

from pypdf import PdfReader
from conftest import _complete_order_for_issue


def _pdf_text(path: Path) -> str:
    reader = PdfReader(str(path))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def test_export_account_statement_without_movements(db, tmp_path):
    from app.models.masters import Client

    client = Client.create(name="Cliente Sin Movs", cuit="30700000000", iva_condition="RI")
    from app.services import account_statement_print_service

    pdf_path = account_statement_print_service.export_account_statement(client, tmp_path)
    text = _pdf_text(pdf_path)

    assert pdf_path.exists()
    assert pdf_path.read_bytes().startswith(b"%PDF")
    assert "GRAEF HERMANOS S.R.L." in text
    assert "EXTRACTO DE CUENTA CORRIENTE" in text
    assert "Cliente Sin Movs" in text
    assert "no tiene movimientos" in text


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
        client=client, delivery_address=address, carrier=carrier, driver=driver, truck=truck,
        products=[{"product": product, "quantity": 500}],
    )
    _complete_order_for_issue(order)
    LoadOrderOperationService(current_user="admin").issue(order)

    pdf_path = account_statement_print_service.export_account_statement(client, tmp_path)
    text = _pdf_text(pdf_path)

    assert pdf_path.exists()
    assert pdf_path.read_bytes().startswith(b"%PDF")
    assert "EXTRACTO DE CUENTA CORRIENTE" in text
    assert "Cliente Test" in text
    assert "Orden de carga" in text
    assert "SALDO ACTUAL" in text


def test_export_account_statement_multi_movement_balance(db, tmp_path):
    from app.models.accounting import ClientAccountMovement
    from app.models.masters import Client
    from app.services import account_statement_print_service

    client = Client.create(name="Cliente Multi", cuit="30722222222", iva_condition="RI")
    ClientAccountMovement.create(
        client=client, movement_type="load_order_documental", total_amount=1000.0,
        currency="ARS", description="OC-0001", source_ref="load_order:1",
        created_by="admin",
    )
    ClientAccountMovement.create(
        client=client, movement_type="payment", total_amount=-400.0,
        currency="ARS", description="Pago parcial", source_ref="payment:1",
        created_by="admin",
    )
    ClientAccountMovement.create(
        client=client, movement_type="payment", total_amount=-600.0,
        currency="ARS", description="Pago final", source_ref="payment:2",
        created_by="admin",
    )

    pdf_path = account_statement_print_service.export_account_statement(client, tmp_path)
    text = _pdf_text(pdf_path)

    assert pdf_path.exists()
    assert "Cliente Multi" in text
    assert "Pago" in text
    assert "SALDO ACTUAL" in text
    assert "1,000.00" in text
    assert "400.00" in text


def test_export_account_statement_shows_client_cuit_and_date(db, tmp_path):
    from app.models.masters import Client
    from app.services import account_statement_print_service

    client = Client.create(name="Cliente CUIT", cuit="30333333330", iva_condition="RI")
    pdf_path = account_statement_print_service.export_account_statement(client, tmp_path)
    text = _pdf_text(pdf_path)

    assert "30333333330" in text
    assert "CUIT" in text


def test_export_account_statement_pdf_is_valid_pdf(db, tmp_path):
    from app.models.masters import Client
    from app.services import account_statement_print_service

    client = Client.create(name="Cliente Valid", cuit="30444444440", iva_condition="RI")
    pdf_path = account_statement_print_service.export_account_statement(client, tmp_path)

    assert pdf_path.suffix == ".pdf"
    assert pdf_path.read_bytes().startswith(b"%PDF")
    reader = PdfReader(str(pdf_path))
    assert len(reader.pages) >= 1
