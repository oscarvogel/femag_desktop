from datetime import date

from app.models.load_orders import (
    LoadOrder,
    LoadOrderDestination,
    LoadOrderPallet,
    LoadOrderPalletAllocation,
    LoadOrderProduct,
)
from app.models.masters import Carrier, Client, ClientAddress, Driver, PalletType, Product, Truck
from app.reports.lot_traceability import LotTraceabilityFilters, LotTraceabilityService
from app.services.consolidated_load_order_print_service import ConsolidatedLoadOrderPrintService


def _order_with_two_lots():
    """Una línea de 10 pallets repartida en dos lotes (#873).

    8 pallets del lote 08 y 2 del lote 09. La línea queda con el lote del grupo
    más grande, como la guarda la web QR.
    """

    client = Client.create(name="Cliente 873", cuit="30700873001", iva_condition="RI")
    address = ClientAddress.create(
        client=client,
        address_type="entrega",
        province="Misiones",
        city="Posadas",
        address="Ruta 873",
    )
    carrier = Carrier.create(name="Transporte 873")
    truck = Truck.create(domain="AB873CD", carrier=carrier)
    driver = Driver.create(name="Chofer 873", carrier=carrier)
    product = Product.create(name="Fécula 873", unit="bolsa", peso_unitario_kg=25)
    pallet_type, _ = PalletType.get_or_create(
        type="Pallet 873", defaults={"measure": "1x1", "weight": 18.0, "active": True}
    )

    order = LoadOrder.create(
        order_number=87301,
        date=date(2026, 11, 3),
        client=client,
        delivery_address=address,
        carrier=carrier,
        driver=driver,
        truck=truck,
        status=LoadOrder.STATUS_CLOSED,
    )
    destination = LoadOrderDestination.create(
        order=order, client=client, delivery_address=address, sequence=1
    )
    LoadOrderProduct.create(
        order=order,
        destination=destination,
        product=product,
        quantity=600,
        unit="bolsa",
        precio_neto_unitario=100.0,
        neto_subtotal=60000.0,
        neto_gravado=60000.0,
        iva_porcentaje=21.0,
        iva_importe=12600.0,
        total=72600.0,
        lote="08",
        fecha_elaboracion=date(2026, 10, 19),
    )
    for sequence in range(1, 11):
        pallet = LoadOrderPallet.create(
            order=order, pallet_type=pallet_type, sequence=sequence, quantity=1
        )
        is_second_lot = sequence > 8
        LoadOrderPalletAllocation.create(
            pallet=pallet,
            destination=destination,
            product=product,
            quantity=60,
            peso_unitario_kg=25,
            lote="09" if is_second_lot else "08",
            fecha_elaboracion=date(2026, 10, 20 if is_second_lot else 19),
        )
    return order, destination, product


def test_consolidated_print_splits_one_line_into_one_row_per_pallet_lot(db):
    order, _destination, product = _order_with_two_lots()

    blocks = ConsolidatedLoadOrderPrintService(current_user="test")._detail_blocks(order)

    assert len(blocks) == 1
    rows = blocks[0]["consolidated_rows"]
    assert [
        (row["product"], row["pallet_count"], row["quantity"], row["lote"], row["elab"])
        for row in rows
    ] == [
        (product.name, 8, 480.0, "08", "19/10/26"),
        (product.name, 2, 120.0, "09", "20/10/26"),
    ]
    assert [row["pallets"] for row in rows] == ["1–8", "9–10"]


def test_consolidated_print_falls_back_to_line_lot_when_content_has_none(db):
    order, destination, product = _order_with_two_lots()
    LoadOrderPalletAllocation.update(lote=None, fecha_elaboracion=None).where(
        LoadOrderPalletAllocation.destination == destination
    ).execute()

    block = ConsolidatedLoadOrderPrintService(current_user="test")._detail_blocks(order)[0]

    assert [
        (row["pallet_count"], row["lote"], row["elab"])
        for row in block["consolidated_rows"]
    ] == [(10, "08", "19/10/26")]
    assert block["consolidated_rows"][0]["product"] == product.name


def test_traceability_shows_the_lot_and_date_of_each_pallet(db):
    _order_with_two_lots()

    rows = LotTraceabilityService().report(
        LotTraceabilityFilters(order_number=87301)
    ).rows

    assert {(row["pallet"], row["lote"], row["elaboration_date"]) for row in rows} == {
        (f"Pallet {sequence}", "08", date(2026, 10, 19))
        for sequence in range(1, 9)
    } | {
        (f"Pallet {sequence}", "09", date(2026, 10, 20))
        for sequence in range(9, 11)
    }


def test_traceability_filters_by_the_lot_of_the_pallet(db):
    _order_with_two_lots()

    result = LotTraceabilityService().report(
        LotTraceabilityFilters(lote="09", order_number=87301)
    )

    assert {row["pallet"] for row in result.rows} == {"Pallet 9", "Pallet 10"}
    assert result.totals.dispatched_quantity == 120
