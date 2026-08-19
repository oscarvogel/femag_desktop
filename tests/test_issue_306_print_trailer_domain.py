from types import SimpleNamespace


def _service():
    from app.services.consolidated_load_order_print_service import ConsolidatedLoadOrderPrintService

    return ConsolidatedLoadOrderPrintService(current_user="issue306")


def _order(*, truck_domain="CJR314", truck_trailer="BMG576", snapshot=None):
    return SimpleNamespace(
        carrier=SimpleNamespace(name="TRANSPORTE LOPEZ"),
        truck=SimpleNamespace(domain=truck_domain, trailer_domain=truck_trailer),
        driver=SimpleNamespace(name="CHOFER PRUEBA"),
        trailer_domain=snapshot,
        pallets=[],
        loose_allocations=[],
    )


def _plain_text(value):
    return value.getPlainText() if hasattr(value, "getPlainText") else str(value)


def test_transport_table_prints_truck_and_trailer_domains_for_legacy_order():
    service = _service()
    table = service._transport_table(_order(snapshot=None))
    rows = [[_plain_text(cell) for cell in row] for row in table._cellvalues]

    assert ["Dominio del vehiculo:", "CJR314"] in rows
    assert ["Dominio semi/acoplado:", "BMG576"] in rows


def test_transport_table_prefers_order_trailer_snapshot_when_available():
    service = _service()
    table = service._transport_table(_order(truck_trailer="TRAILERACTUAL", snapshot="TRAILERHISTORICO"))
    rows = [[_plain_text(cell) for cell in row] for row in table._cellvalues]

    assert ["Dominio semi/acoplado:", "TRAILERHISTORICO"] in rows
    assert all("TRAILERACTUAL" not in row for row in rows)


def test_transport_table_keeps_dash_when_no_trailer_data_exists():
    service = _service()
    table = service._transport_table(_order(truck_trailer=None, snapshot=None))
    rows = [[_plain_text(cell) for cell in row] for row in table._cellvalues]

    assert ["Dominio semi/acoplado:", "-"] in rows
