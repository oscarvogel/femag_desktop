import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from datetime import date


def _mkclient(name, cuit):
    from app.models.masters import Client, ClientAddress

    c = Client.create(name=name, cuit=cuit, iva_condition="RI")
    ClientAddress.create(client=c, address_type="entrega", province="Misiones",
                         city="Posadas", address="C " + name)
    return c


def _mkorder(n, d, client, product, qty, total, carrier=None, status=None):
    from app.models.load_orders import LoadOrder, LoadOrderDestination, LoadOrderProduct
    from app.models.masters import Carrier, Driver, Truck

    if carrier is None:
        carrier = Carrier.create(name=f"T{n}")
    driver = Driver.create(name=f"C{n}", carrier=carrier)
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


def test_dashboard_export_xlsx_con_todas_las_hojas(db, tmp_path):
    from openpyxl import load_workbook

    from app.models.masters import Carrier, Product
    from app.reports.managerial_dashboard import ManagerialDashboardService, ReportPeriod
    from app.reports.managerial_dashboard_export import ALL_SHEETS, export_dashboard_xlsx

    carrier_a = Carrier.create(name="Transporte A")
    carrier_b = Carrier.create(name="Transporte B")
    ca = _mkclient("CLI A", "30700000911")
    cb = _mkclient("CLI B", "30700000912")
    cc = _mkclient("CLI C", "30700000913")
    pa = Product.create(name="PROD A", unit="bolsa", peso_unitario_kg=25)
    pb = Product.create(name="PROD B", unit="bolsa", peso_unitario_kg=50)
    # Periodo actual 01/10 -> 12/10
    _mkorder(911, date(2026, 10, 5), ca, pa, 100, 200000, carrier=carrier_a)
    _mkorder(912, date(2026, 10, 10), cb, pb, 10, 25000, carrier=carrier_b)
    _mkorder(913, date(2026, 10, 11), cc, pa, 10, 10000, carrier=carrier_a)
    # Anterior mismo corte 01/09 -> 12/09
    _mkorder(914, date(2026, 9, 5), ca, pa, 100, 100000, carrier=carrier_a)
    _mkorder(915, date(2026, 9, 20), ca, pa, 100, 999000, carrier=carrier_a)  # fuera del corte

    service = ManagerialDashboardService()
    period = ReportPeriod(date(2026, 10, 1), date(2026, 10, 12), "Este mes")
    out = export_dashboard_xlsx(service, period, tmp_path / "dashboard_ia.xlsx")

    assert out.exists()
    wb = load_workbook(out)
    assert set(wb.sheetnames) == set(ALL_SHEETS)

    # Clientes: todos con movimiento (3), no solo top
    ws_c = wb["Clientes"]
    assert ws_c.max_row == 1 + 3
    headers_c = [c.value for c in ws_c[1]]
    assert "variacion_%" in headers_c
    names = {ws_c.cell(row=r, column=2).value for r in range(2, ws_c.max_row + 1)}
    assert names == {"CLI A", "CLI B", "CLI C"}

    # Articulos: todos (2)
    ws_p = wb["Articulos"]
    assert ws_p.max_row == 1 + 2

    # Cargas: 3 efectivas del periodo
    ws_l = wb["Cargas"]
    assert ws_l.max_row == 1 + 3
    headers_l = [c.value for c in ws_l[1]]
    assert "transportista" in headers_l

    # Lineas reconcilia con KPI (235000, excluye 999000 del 20/09)
    ws_lines = wb["Lineas"]
    assert ws_lines.max_row == 1 + 3
    h_lines = [c.value for c in ws_lines[1]]
    col_val = h_lines.index("valorizado") + 1
    total_lines = sum(ws_lines.cell(row=r, column=col_val).value for r in range(2, ws_lines.max_row + 1))
    assert total_lines == 235000

    # Detalle del período anterior: solo 1 línea en el corte 01-12/09
    ws_prev = wb["Lineas_mes_anterior"]
    assert ws_prev.max_row == 1 + 1
    assert ws_prev.cell(row=2, column=h_lines.index("cliente") + 1).value == "CLI A"
    ws_prev_loads = wb["Cargas_mes_anterior"]
    assert ws_prev_loads.max_row == 1 + 1

    # Recompra cliente x artículo por kilos
    ws_r = wb["Recompra_cliente_articulo"]
    h_r = [c.value for c in ws_r[1]]
    assert "clasificacion" in h_r and "dif_toneladas" in h_r
    col_status = h_r.index("clasificacion") + 1
    col_cli = h_r.index("cliente") + 1
    statuses = {(ws_r.cell(row=r, column=col_cli).value, ws_r.cell(row=r, column=col_status).value)
                for r in range(2, ws_r.max_row + 1)}
    # CLI A/PROD A compró en ambos (menos kilos si cambió peso), CLI B y C son nuevos, nadie sin recompra aquí
    # porque el único de septiembre (CLI A) sí recompró en octubre.
    assert ("CLI B", "nuevo") in statuses
    assert ("CLI C", "nuevo") in statuses

    # Transportistas: 2, con comparativa
    ws_t = wb["Transportistas"]
    assert ws_t.max_row == 1 + 2
    h_t = [c.value for c in ws_t[1]]
    assert "variacion_%" in h_t
    t_names = {ws_t.cell(row=r, column=2).value for r in range(2, ws_t.max_row + 1)}
    assert t_names == {"Transporte A", "Transporte B"}

def test_dashboard_page_tiene_boton_exportar(db):
    from PyQt5.QtWidgets import QApplication, QPushButton

    from app.ui.managerial_dashboard import ManagerialDashboardPage

    app = QApplication.instance() or QApplication([])
    page = ManagerialDashboardPage()
    btn = page.findChild(QPushButton, "managerialExportExcelButton")
    assert btn is not None
    assert "Excel" in btn.text()
    repurchase_btn = page.findChild(QPushButton, "managerialRepurchaseButton")
    assert repurchase_btn is not None
    page.close()


def test_repurchase_clasifica_por_kilos_no_por_precio(db):
    from app.models.masters import Product
    from app.reports.managerial_dashboard import ManagerialDashboardService, ReportPeriod

    # Mismo producto, mismo cliente: en octubre factura MÁS pero lleva MENOS kilos
    # (suba de precio). Debe clasificar compro_menos por kilos.
    cli = _mkclient("CLI Kilos", "30700000921")
    prod = Product.create(name="Almidon Mod", unit="bolsa", peso_unitario_kg=25)
    _mkorder(921, date(2026, 9, 5), cli, prod, 100, 100000)  # 2500 kg
    _mkorder(922, date(2026, 10, 5), cli, prod, 40, 200000)  # 1000 kg, doble precio
    cli2 = _mkclient("CLI Fuga", "30700000922")
    _mkorder(923, date(2026, 9, 6), cli2, prod, 50, 50000)  # sin recompra en octubre
    cli3 = _mkclient("CLI Nuevo", "30700000923")
    _mkorder(924, date(2026, 10, 6), cli3, prod, 50, 50000)  # nuevo

    service = ManagerialDashboardService()
    current = ReportPeriod(date(2026, 10, 1), date(2026, 10, 12), "Actual")
    rows = service.product_client_repurchase(current, product_id=prod.id)
    by_client = {r["client_name"]: r for r in rows}
    assert by_client["CLI Kilos"]["status"] == "compro_menos"
    assert by_client["CLI Kilos"]["current_kilos"] == 1000
    assert by_client["CLI Kilos"]["previous_kilos"] == 2500
    assert by_client["CLI Fuga"]["status"] == "sin_recompra"
    assert by_client["CLI Fuga"]["current_kilos"] == 0
    assert by_client["CLI Nuevo"]["status"] == "nuevo"
    # Toneladas perdidas por sin recompra = 1,25 TN
    lost = sum(r["previous_tonnes"] for r in rows if r["status"] == "sin_recompra")
    assert lost == 1.25


def test_repurchase_dialog_muestra_resumen(db):
    from PyQt5.QtWidgets import QApplication

    from app.models.masters import Product
    from app.reports.managerial_dashboard import ReportPeriod
    from app.ui.managerial_repurchase_dialog import ManagerialRepurchaseDialog
    from datetime import date as _date

    app = QApplication.instance() or QApplication([])
    cli = _mkclient("CLI Dialog", "30700000931")
    prod = Product.create(name="Prod Dialog", unit="bolsa", peso_unitario_kg=10)
    _mkorder(931, date(2026, 9, 5), cli, prod, 100, 50000)
    dialog = ManagerialRepurchaseDialog(current=ReportPeriod(_date(2026, 10, 1), _date(2026, 10, 12), "Actual"))
    assert "sin recompra" in dialog.summary_label.text()
    assert dialog.table.rowCount() >= 1
    dialog.close()
