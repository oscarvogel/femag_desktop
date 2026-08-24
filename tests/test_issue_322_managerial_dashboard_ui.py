def test_managerial_dashboard_html_renders_v1_sections(db, tmp_path, monkeypatch):
    from app.reports.managerial_dashboard_html import ManagerialDashboardHtmlReport

    report = ManagerialDashboardHtmlReport(root_dir=tmp_path)
    monkeypatch.setattr(report, "ensure_chart_js", lambda: False)

    path = report.generate()
    html = path.read_text(encoding="utf-8")

    assert path == tmp_path / "dashboard.html"
    assert "Dashboard Gerencial" in html
    assert "Despachos valorizados" in html
    assert "Toneladas" in html
    assert "Saldo clientes" in html
    assert "Top clientes" in html
    assert "Top productos" in html
    assert "Estado de órdenes" in html
    assert '<option value="hoy">Hoy</option>' in html
    assert '<option value="este_mes" selected>Este mes</option>' in html
    assert '"default_period": "este_mes"' in html


def test_managerial_dashboard_uses_cached_chart_js_without_redownload(tmp_path):
    from app.reports.managerial_dashboard_html import ManagerialDashboardHtmlReport

    report = ManagerialDashboardHtmlReport(root_dir=tmp_path)
    report.assets_dir.mkdir(parents=True)
    report.chart_js_path.write_bytes(b"Chart" + (b"x" * 100_001))

    assert report.ensure_chart_js() is True
