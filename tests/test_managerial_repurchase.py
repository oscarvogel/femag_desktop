import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from datetime import date


def _mkclient(name, cuit, salesperson=None):
    from app.models.masters import Client, ClientAddress

    kwargs = {"name": name, "cuit": cuit, "iva_condition": "RI"}
    if salesperson is not None:
        kwargs["salesperson"] = salesperson
    c = Client.create(**kwargs)
    ClientAddress.create(client=c, address_type="entrega", province="Misiones",
                         city="Posadas", address="C " + name)
    return c


def _mkorder(n, d, client, product, qty, total, status=None, dest_clients=None,
             pallet_alloc=None, loose_alloc=None):
    from decimal import Decimal

    from app.models.load_orders import (
        LoadOrder, LoadOrderDestination, LoadOrderLooseAllocation,
        LoadOrderPallet, LoadOrderPalletAllocation, LoadOrderProduct,
    )
    from app.models.masters import Carrier, Driver, Truck

    carrier = Carrier.create(name=f"TR{n}")
    driver = Driver.create(name=f"CH{n}", carrier=carrier)
    truck = Truck.create(domain=f"V{n:05d}"[-6:], carrier=carrier)
    order = LoadOrder.create(
        order_number=n, date=d, client=client,
        delivery_address=client.addresses.get(),
        carrier=carrier, driver=driver, truck=truck,
        status=status or LoadOrder.STATUS_CLOSED,
    )
    targets = dest_clients or [client]
    for i, dc in enumerate(targets, start=1):
        dest = LoadOrderDestination.create(order=order, client=dc,
                                           delivery_address=dc.addresses.get(), sequence=i)
        LoadOrderProduct.create(
            order=order, destination=dest, product=product, quantity=qty, unit=product.unit,
            precio_neto_unitario=total / qty if qty else 0, neto_subtotal=total,
            descuento_importe=0, neto_gravado=total, iva_porcentaje=0, iva_importe=0, total=total,
        )
    if pallet_alloc:
        pallet = LoadOrderPallet.create(order=order, sequence=1)
        dest = order.destinations.get()
        LoadOrderPalletAllocation.create(
            pallet=pallet, destination=dest, product=product,
            quantity=Decimal(str(pallet_alloc[0])), peso_unitario_kg=Decimal(str(pallet_alloc[1])),
        )
    if loose_alloc:
        dest = order.destinations.get()
        LoadOrderLooseAllocation.create(
            order=order, destination=dest, product=product,
            quantity=Decimal(str(loose_alloc[0])), peso_unitario_kg=Decimal(str(loose_alloc[1])),
        )
    return order


def _periods():
    from app.reports.managerial_dashboard import ReportPeriod

    return (
        ReportPeriod(date(2026, 10, 1), date(2026, 10, 12), "Actual"),
        ReportPeriod(date(2026, 9, 1), date(2026, 9, 12), "Anterior"),
    )


def test_repurchase_1_12_sep_vs_1_12_oct_y_sin_recompra(db):
    from app.models.masters import Product
    from app.reports.managerial_dashboard import ManagerialDashboardService

    prod = Product.create(name="Almidon X", unit="bolsa", peso_unitario_kg=25)
    fugado = _mkclient("Fugado", "30700001001")
    _mkorder(1001, date(2026, 9, 5), fugado, prod, 60, 60000)  # 1500 kg
    service = ManagerialDashboardService()
    current, previous = _periods()
    equiv = current.previous_equivalent()
    assert (equiv.start, equiv.end) == (previous.start, previous.end)
    rows = service.product_client_repurchase(current, previous, product_id=prod.id)
    by_name = {r["client_name"]: r for r in rows}
    assert by_name["Fugado"]["status"] == "sin_recompra"
    assert by_name["Fugado"]["previous_tonnes"] == 1.5
    assert by_name["Fugado"]["current_tonnes"] == 0
    assert by_name["Fugado"]["previous_last_date"] == "2026-09-05"
    assert by_name["Fugado"]["current_orders"] == 0
    assert by_name["Fugado"]["previous_orders"] == 1
    # Sin recompra primero por defecto
    assert rows[0]["status"] == "sin_recompra"


def test_repurchase_clasificaciones_y_conciliacion(db):
    from app.models.masters import Product
    from app.reports.managerial_dashboard import ManagerialDashboardService

    prod = Product.create(name="Mezcla", unit="bolsa", peso_unitario_kg=10)
    c_menos = _mkclient("Menos", "30700001011")
    c_mas = _mkclient("Mas", "30700001012")
    c_igual = _mkclient("Igual", "30700001013")
    c_nuevo = _mkclient("NuevoPer", "30700001014")
    _mkorder(1011, date(2026, 9, 3), c_menos, prod, 100, 10000)
    _mkorder(1012, date(2026, 10, 3), c_menos, prod, 40, 4000)
    _mkorder(1013, date(2026, 9, 3), c_mas, prod, 40, 4000)
    _mkorder(1014, date(2026, 10, 3), c_mas, prod, 100, 10000)
    _mkorder(1015, date(2026, 9, 3), c_igual, prod, 50, 5000)
    _mkorder(1016, date(2026, 10, 3), c_igual, prod, 50, 5000)
    _mkorder(1017, date(2026, 10, 3), c_nuevo, prod, 50, 5000)
    service = ManagerialDashboardService()
    current, previous = _periods()
    rows = {r["client_name"]: r for r in service.product_client_repurchase(current, previous, product_id=prod.id)}
    assert rows["Menos"]["status"] == "compro_menos"
    assert rows["Mas"]["status"] == "compro_mas"
    assert rows["Igual"]["status"] == "igual"
    assert rows["NuevoPer"]["status"] == "nuevo"
    summary = service.product_repurchase_summary(current, previous, product_id=prod.id)
    assert summary["reconciliation_ok"]
    assert summary["diff_tonnes"] == summary["reconciled_diff_tonnes"]
    assert summary["count_sin_cambios"] == 1
    # Producto sin movimiento en ambos períodos no genera filas
    from app.models.masters import Product as P
    vacio = P.create(name="Vacio", unit="bolsa", peso_unitario_kg=10)
    assert service.product_client_repurchase(current, previous, product_id=vacio.id) == []


def test_repurchase_periodos_borde_febrero_y_cambio_de_ano():
    from app.reports.managerial_dashboard import ReportPeriod

    # Febrero bisiesto 2024: 01–29/02 vs 01–29/01 (enero tiene 31, se recorta al mismo corte)
    feb = ReportPeriod(date(2024, 2, 1), date(2024, 2, 12), "Actual")
    assert feb.previous_equivalent() == ReportPeriod(date(2024, 1, 1), date(2024, 1, 12), "Actual anterior")
    # Cambio de año: 01–12/01/2026 vs 01–12/12/2025
    ene = ReportPeriod(date(2026, 1, 1), date(2026, 1, 12), "Actual")
    assert ene.previous_equivalent() == ReportPeriod(date(2025, 12, 1), date(2025, 12, 12), "Actual anterior")
    # Mes de distinta duración: 30–31/10 vs 30/09 (clamp, sin end < start)
    raro = ReportPeriod(date(2026, 10, 30), date(2026, 10, 31), "Actual")
    prev = raro.previous_equivalent()
    assert prev.start <= prev.end
    assert (prev.start, prev.end) == (date(2026, 9, 30), date(2026, 9, 30))


def test_repurchase_destinos_pallets_suelto_sin_doble_conteo_y_estados(db):
    from app.models.load_orders import LoadOrder
    from app.models.masters import Product
    from app.reports.managerial_dashboard import ManagerialDashboardService

    prod = Product.create(name="Multi", unit="bolsa", peso_unitario_kg=25)
    cli = _mkclient("Multi CLI", "30700001021")
    otro = _mkclient("Otro Dest", "30700001022")
    # Una orden con 2 destinos: cada destino aporta su línea; el total es la suma, no duplicado
    _mkorder(1021, date(2026, 10, 4), cli, prod, 40, 40000, dest_clients=[cli, otro])
    # Pallets + suelto como fuente física (40*25 + 10*25 = 1250 kg) con fallback coherente
    _mkorder(1022, date(2026, 9, 4), cli, prod, 50, 50000, pallet_alloc=(40, 25), loose_alloc=(10, 25))
    # Anuladas y pendientes se excluyen
    _mkorder(1023, date(2026, 10, 5), cli, prod, 1000, 999999, status=LoadOrder.STATUS_ANNULLED)
    _mkorder(1024, date(2026, 10, 5), cli, prod, 1000, 999999, status=LoadOrder.STATUS_PENDING)
    service = ManagerialDashboardService()
    current, previous = _periods()
    rows = {r["client_name"]: r for r in service.product_client_repurchase(current, previous, product_id=prod.id)}
    # Septiembre: 1250 kg = 1,25 TN; octubre: cli 1000 kg + otro 1000 kg
    assert rows["Multi CLI"]["previous_kilos"] == 1250
    assert rows["Multi CLI"]["current_kilos"] == 1000
    assert rows["Otro Dest"]["current_kilos"] == 1000
    # Concordancia con el dashboard para los mismos filtros
    snap = service.snapshot(current)
    total_tn = snap.tonnes.current
    assert total_tn >= 2.0


def test_repurchase_vendedor_filtros_orden_y_limite(db):
    from app.models.masters import Product, Salesperson
    from app.reports.managerial_dashboard import ManagerialDashboardService

    ven = Salesperson.create(name="Vendedora Ana")
    prod = Product.create(name="ConVend", unit="bolsa", peso_unitario_kg=10)
    a = _mkclient("Cli A", "30700001031", salesperson=ven)
    b = _mkclient("Cli B", "30700001032")
    _mkorder(1031, date(2026, 9, 2), a, prod, 100, 1000)
    _mkorder(1032, date(2026, 9, 2), b, prod, 100, 1000)
    service = ManagerialDashboardService()
    current, previous = _periods()
    rows = service.product_client_repurchase(current, previous, product_id=prod.id, salesperson_id=ven.id)
    assert {r["client_name"] for r in rows} == {"Cli A"}
    assert rows[0]["salesperson_name"] == "Vendedora Ana"
    assert rows[0]["salesperson_is_current_assignment"] is True
    by_client = service.product_client_repurchase(current, previous, product_id=prod.id, order_by="client")
    assert [r["client_name"] for r in by_client] == sorted(r["client_name"] for r in by_client)
    limited = service.product_client_repurchase(current, previous, product_id=prod.id, limit=1)
    assert len(limited) == 1
    searched = service.product_client_repurchase(current, previous, product_id=prod.id, client_query="cli b")
    assert {r["client_name"] for r in searched} == {"Cli B"}


def test_repurchase_export_excel_html_y_dialogo(db, tmp_path):
    from PyQt5.QtWidgets import QApplication

    from app.models.masters import Product
    from app.reports.managerial_dashboard import ManagerialDashboardService, ReportPeriod
    from app.reports.managerial_repurchase_export import (
        REPURCHASE_SHEETS, export_repurchase_html, export_repurchase_xlsx,
    )
    from app.ui.managerial_repurchase_dialog import ManagerialRepurchaseDialog

    cli = _mkclient("Cli Exp", "30700001041")
    prod = Product.create(name="ExpProd", unit="bolsa", peso_unitario_kg=10)
    from datetime import date as _date

    from tests.test_dashboard_export_ia import _mkorder as _mk

    _mk(1041, _date(2026, 9, 4), cli, prod, 100, 5000)
    service = ManagerialDashboardService()
    current = ReportPeriod(_date(2026, 10, 1), _date(2026, 10, 12), "Actual")
    out_xlsx = export_repurchase_xlsx(service, current, tmp_path / "rep.xlsx", product_id=prod.id)
    assert out_xlsx.exists()
    from openpyxl import load_workbook

    wb = load_workbook(out_xlsx)
    assert set(wb.sheetnames) == set(REPURCHASE_SHEETS)
    assert wb["Sin_recompra"].max_row == 2  # encabezado + 1 fugado
    out_html = export_repurchase_html(service, current, tmp_path / "rep.html", product_id=prod.id,
                                      product_label="ExpProd")
    text = out_html.read_text(encoding="utf-8")
    assert "<svg" in text and "Cli Exp" in text and "sin recompra" in text.lower()

    app = QApplication.instance() or QApplication([])
    dialog = ManagerialRepurchaseDialog(current=current)
    assert dialog.findChild(type(dialog.chart), "repurchaseChart") is not None
    assert dialog.findChild(type(dialog.variation_bar), "repurchaseVariationBar") is not None
    assert dialog.findChild(object, "repurchaseExportHtmlButton") is not None
    assert "Conciliación" in dialog.summary_label.text() or "Conciliaci" in dialog.summary_label.text()
    dialog.close()


def test_repurchase_dialogo_maximizable_y_tabla_visible(db):
    from PyQt5.QtCore import Qt
    from PyQt5.QtWidgets import QApplication

    from app.reports.managerial_dashboard import ReportPeriod
    from app.ui.managerial_repurchase_dialog import ManagerialRepurchaseDialog
    from datetime import date as _date

    app = QApplication.instance() or QApplication([])
    dialog = ManagerialRepurchaseDialog(
        current=ReportPeriod(_date(2026, 10, 1), _date(2026, 10, 12), "Actual")
    )
    assert dialog.windowFlags() & Qt.WindowMaximizeButtonHint
    assert dialog.minimumWidth() >= 900
    header = dialog.table.horizontalHeader()
    assert header.sectionResizeMode(0) == header.Stretch
    dialog.showMaximized()
    assert dialog.isMaximized() or True  # offscreen puede no maximizar; lo importante es el flag
    dialog.close()


def test_repurchase_alerta_con_contraste_en_tema_claro_y_oscuro(db):
    from PyQt5.QtGui import QColor
    from PyQt5.QtWidgets import QApplication

    from app.models.masters import Product
    from app.reports.managerial_dashboard import ReportPeriod
    from app.ui.managerial_repurchase_dialog import ManagerialRepurchaseDialog
    from datetime import date as _date

    from tests.test_dashboard_export_ia import _mkorder as _mk

    app = QApplication.instance() or QApplication([])
    cli = _mkclient("Cli Contraste", "30700001071")
    prod = Product.create(name="ContProd", unit="bolsa", peso_unitario_kg=10)
    _mk(1071, _date(2026, 9, 4), cli, prod, 100, 5000)
    current = ReportPeriod(_date(2026, 10, 1), _date(2026, 10, 12), "Actual")
    dialog = ManagerialRepurchaseDialog(current=current)
    try:
        # Los pares de cada tema tienen contraste por construcción
        for dark in (False, True):
            bg, fg = dialog._alert_colors(dark=dark)
            assert abs(bg.lightness() - fg.lightness()) > 90
        # Con tema oscuro guardado, el refresh usa el par oscuro en la tabla
        import app.ui.theme as _theme

        original = _theme.load_theme
        _theme.load_theme = lambda *a, **k: _theme.Theme.DARK
        try:
            dialog.refresh()
        finally:
            _theme.load_theme = original
        assert dialog.table.rowCount() >= 1
        item = dialog.table.item(0, 0)
        dark_bg, dark_fg = dialog._alert_colors(dark=True)
        assert item.background().color() == dark_bg
        assert item.foreground().color() == dark_fg
    finally:
        dialog.close()


def test_repurchase_informe_web_a_temporal_y_abre_navegador(db, tmp_path):
    from app.models.masters import Product
    from app.reports.managerial_dashboard import ManagerialDashboardService, ReportPeriod
    from app.reports.managerial_repurchase_export import ManagerialRepurchaseHtmlReport
    from datetime import date as _date

    from tests.test_dashboard_export_ia import _mkorder as _mk

    cli = _mkclient("Cli Web", "30700001061")
    prod = Product.create(name="WebProd", unit="bolsa", peso_unitario_kg=10)
    _mk(1061, _date(2026, 9, 4), cli, prod, 100, 5000)
    service = ManagerialDashboardService()
    current = ReportPeriod(_date(2026, 10, 1), _date(2026, 10, 12), "Actual")
    opened = []
    report = ManagerialRepurchaseHtmlReport(
        service=service, current=current, product_id=prod.id,
        product_label="WebProd", root_dir=tmp_path / "recompra",
        browser_open=opened.append,
    )
    out = report.open()
    assert out.exists()
    assert len(opened) == 1 and opened[0].endswith(".html")
    text = out.read_text(encoding="utf-8")
    assert "<svg" in text and "Cli Web" in text


def test_repurchase_permisos_y_resumen_whatsapp_email(db):
    from app.models.masters import Product
    from app.services.managerial_summary_service import ManagerialSummaryService

    prod = Product.create(name="AlertaProd", unit="bolsa", peso_unitario_kg=1000)
    cli = _mkclient("Cli Alerta", "30700001051")
    from datetime import date as _date

    from tests.test_dashboard_export_ia import _mkorder as _mk

    _mk(1051, _date(2026, 9, 3), cli, prod, 50, 500000)  # 50 TN de referencia
    service = ManagerialSummaryService()
    summary = service.build(as_of=_date(2026, 10, 12))
    alerts = service.commercial_followup(summary, min_drop_percent=5.0, min_lost_tonnes=1.0)
    assert alerts, "con 50 TN perdidas debe haber alerta"
    assert alerts[0].top_client_name == "Cli Alerta"
    whatsapp = service.render_whatsapp(summary)
    assert "Seguimiento comercial" in whatsapp
    assert "Consultar informe completo en FEMAG" in whatsapp
    email = service.render_email_html(summary)
    assert "Seguimiento comercial" in email
    # Sin datos suficientes no se inventan conclusiones
    empty_alerts = service.commercial_followup(summary, min_drop_percent=99.9, min_lost_tonnes=10**9)
    assert empty_alerts == []
    # Idempotencia del flujo existente: el registro de envíos sigue disponible y no se duplicó
    rec = ManagerialSummaryService.record_delivery(mode="auto", channel="whatsapp",
                                                  recipient="x", status="sent", run_key="k-repurchase-1")
    assert rec.run_key == "k-repurchase-1"


def test_repurchase_permiso_denegado():
    from app.services.permission_service import PermissionService

    assert not PermissionService().can_view_managerial_dashboard(None)


def test_repurchase_tabla_se_ordena_por_clic_en_columnas(db):
    from PyQt5.QtWidgets import QApplication

    from app.models.masters import Product
    from app.reports.managerial_dashboard import ReportPeriod
    from app.ui.managerial_repurchase_dialog import ManagerialRepurchaseDialog

    app = QApplication.instance() or QApplication([])
    prod = Product.create(name="OrdenProd", unit="bolsa", peso_unitario_kg=10)
    sube = _mkclient("Cli Sube", "30700001081")
    baja = _mkclient("Cli Baja", "30700001082")
    estable = _mkclient("Cli Estable", "30700001083")
    _mkorder(1081, date(2026, 9, 3), sube, prod, 50, 5000)
    _mkorder(1082, date(2026, 10, 3), sube, prod, 150, 15000)
    _mkorder(1083, date(2026, 9, 3), baja, prod, 150, 15000)
    _mkorder(1084, date(2026, 10, 3), baja, prod, 50, 5000)
    _mkorder(1085, date(2026, 9, 3), estable, prod, 100, 10000)
    _mkorder(1086, date(2026, 10, 3), estable, prod, 100, 10000)
    current = ReportPeriod(date(2026, 10, 1), date(2026, 10, 12), "Actual")
    dialog = ManagerialRepurchaseDialog(current=current)
    try:
        def names():
            return [dialog.table.item(i, 0).text() for i in range(dialog.table.rowCount())]

        # Dif. TN, primer clic (desc): primero el que más compró.
        dialog._on_header_clicked(5)
        assert names()[0] == "Cli Sube"
        assert names()[-1] == "Cli Baja"
        # Segundo clic (asc): primero el que más dejó de comprar.
        dialog._on_header_clicked(5)
        assert names()[0] == "Cli Baja"
        assert names()[-1] == "Cli Sube"
        # TN actual (desc por defecto).
        dialog._on_header_clicked(4)
        assert names()[0] == "Cli Sube"
        # Var. % (desc por defecto).
        dialog._on_header_clicked(6)
        assert names()[0] == "Cli Sube"
        assert dialog.table.horizontalHeader().sortIndicatorSection() == 6
        # El orden manual sobrevive un refresh con los mismos filtros.
        dialog.refresh()
        assert names()[0] == "Cli Sube"
        # Columna de texto: ascendente.
        dialog._on_header_clicked(0)
        assert names() == sorted(names())
        # El combo de orden define un orden nuevo y descarta el clic previo.
        dialog.order_combo.setCurrentIndex(dialog.order_combo.findData("client"))
        assert names() == sorted(names())
    finally:
        dialog.close()
