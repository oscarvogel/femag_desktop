import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from datetime import date


def _mkclient(name, cuit):
    from app.models.masters import Client, ClientAddress

    client = Client.create(name=name, cuit=cuit, iva_condition="RI")
    ClientAddress.create(client=client, address_type="entrega", province="Misiones",
                         city="Posadas", address="C " + name)
    return client


def _mkorder(n, d, client, product, qty, total, status=None):
    from app.models.load_orders import (
        LoadOrder, LoadOrderDestination, LoadOrderProduct,
    )
    from app.models.masters import Carrier, Driver, Truck

    carrier = Carrier.create(name=f"TRD{n}")
    driver = Driver.create(name=f"CHD{n}", carrier=carrier)
    truck = Truck.create(domain=f"V{n:05d}"[-6:], carrier=carrier)
    order = LoadOrder.create(
        order_number=n, date=d, client=client,
        delivery_address=client.addresses.get(),
        carrier=carrier, driver=driver, truck=truck,
        status=status or LoadOrder.STATUS_CLOSED,
    )
    dest = LoadOrderDestination.create(order=order, client=client,
                                       delivery_address=client.addresses.get(), sequence=1)
    LoadOrderProduct.create(
        order=order, destination=dest, product=product, quantity=qty, unit=product.unit,
        precio_neto_unitario=total / qty if qty else 0, neto_subtotal=total,
        descuento_importe=0, neto_gravado=total, iva_porcentaje=0, iva_importe=0, total=total,
    )
    return order


def _periods():
    from app.reports.managerial_dashboard import ReportPeriod

    return (
        ReportPeriod(date(2026, 10, 1), date(2026, 10, 12), "Actual"),
        ReportPeriod(date(2026, 9, 1), date(2026, 9, 12), "Anterior"),
    )


def test_drilldown_product_buyers_ordered_by_current_tn(db):
    """Dante: clic en el producto -> a quién se le vendió en el rango, mayor comprador primero."""
    from app.models.masters import Product
    from app.reports.managerial_dashboard import ManagerialDashboardService

    prod = Product.create(name="DrillProd", unit="bolsa", peso_unitario_kg=10)
    grande = _mkclient("Drill Grande", "30700002001")
    chico = _mkclient("Drill Chico", "30700002002")
    fugado = _mkclient("Drill Fugado", "30700002003")
    _mkorder(2001, date(2026, 10, 4), grande, prod, 200, 20000)  # 2000 kg
    _mkorder(2002, date(2026, 10, 5), chico, prod, 50, 5000)  # 500 kg
    _mkorder(2003, date(2026, 9, 4), fugado, prod, 100, 10000)  # solo anterior

    service = ManagerialDashboardService()
    current, previous = _periods()
    rows = service.product_client_repurchase(current, previous, product_id=prod.id,
                                             order_by="current_tonnes")
    assert [r["client_name"] for r in rows] == ["Drill Grande", "Drill Chico", "Drill Fugado"]
    assert rows[0]["current_tonnes"] == 2.0
    assert rows[1]["current_tonnes"] == 0.5
    assert rows[2]["current_tonnes"] == 0
    buyers = {r["client_name"] for r in rows if r["current_kilos"] > 0.5}
    assert buyers == {"Drill Grande", "Drill Chico"}


def test_drilldown_dialog_applies_presets(db):
    from PyQt5.QtWidgets import QApplication

    from app.models.masters import Product
    from app.reports.managerial_dashboard import ManagerialDashboardService, ReportPeriod
    from app.ui.managerial_repurchase_dialog import ManagerialRepurchaseDialog

    cli = _mkclient("Drill Cli Preset", "30700002011")
    prod = Product.create(name="DrillProd Preset", unit="bolsa", peso_unitario_kg=10)
    _mkorder(2011, date(2026, 10, 4), cli, prod, 100, 10000)

    app = QApplication.instance() or QApplication([])
    service = ManagerialDashboardService()
    current = ReportPeriod(date(2026, 10, 1), date(2026, 10, 12), "Actual")
    dialog = ManagerialRepurchaseDialog(
        service=service, current=current,
        initial_product_id=prod.id,
        initial_client_query="Preset",
        initial_order_by="current_tonnes",
    )
    try:
        assert dialog.product_combo.currentData() == prod.id
        assert dialog.search_input.text() == "Preset"
        assert dialog.order_combo.currentData() == "current_tonnes"
        assert dialog.table.rowCount() >= 1
        names = {dialog.table.item(r, 0).text() for r in range(dialog.table.rowCount())}
        assert names == {"Drill Cli Preset"}
    finally:
        dialog.close()


def test_dashboard_stores_ids_for_double_click(db):
    from PyQt5.QtCore import Qt
    from PyQt5.QtWidgets import QApplication

    from app.models.masters import Product
    from app.reports.managerial_dashboard import ManagerialDashboardService
    from app.ui.managerial_dashboard import ManagerialDashboardPage

    today = date.today()
    cli = _mkclient("Drill Dash Cli", "30700002021")
    prod = Product.create(name="DrillDashProd", unit="bolsa", peso_unitario_kg=10)
    _mkorder(2021, today, cli, prod, 100, 10000)

    app = QApplication.instance() or QApplication([])
    page = ManagerialDashboardPage(service=ManagerialDashboardService())
    try:
        page.refresh()
        found_product = found_client = False
        for r in range(page.products_table.rowCount()):
            item = page.products_table.item(r, 0)
            if item is not None and item.text() == "DrillDashProd":
                assert item.data(Qt.UserRole) == prod.id
                found_product = True
        for r in range(page.clients_table.rowCount()):
            item = page.clients_table.item(r, 0)
            if item is not None and item.text() == "Drill Dash Cli":
                assert item.data(Qt.UserRole) == cli.id
                found_client = True
        assert found_product and found_client
        assert "doble clic" in page.findChild(object, "managerialDrilldownHint").text().lower()
    finally:
        page.close()
