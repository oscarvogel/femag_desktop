from __future__ import annotations

from collections import defaultdict
import json
import os
from pathlib import Path
import webbrowser

from app.reports.managerial_dashboard_html import ManagerialDashboardHtmlReport
from app.reports.managerial_sales_dispatch import ManagerialSalesDispatchService, SalesDispatchFilters


class ManagerialSalesDispatchHtmlReport:
    """Visual dashboard for the currently filtered sales/dispatch report."""

    def __init__(self, *, service: ManagerialSalesDispatchService | None = None, root_dir: Path | None = None, browser_open=None) -> None:
        self.service = service or ManagerialSalesDispatchService()
        self.root_dir = root_dir or self._default_root_dir()
        self.browser_open = browser_open or webbrowser.open

    @staticmethod
    def _default_root_dir() -> Path:
        base = os.getenv("LOCALAPPDATA")
        if base:
            return Path(base) / "FEMAG" / "dashboard_ventas_despachos"
        return Path.home() / ".femag" / "dashboard_ventas_despachos"

    @property
    def html_path(self) -> Path:
        return self.root_dir / "dashboard.html"

    def _payload(self, filters: SalesDispatchFilters) -> dict:
        result = self.service.report(filters)
        by_date: dict[str, dict[str, float]] = defaultdict(lambda: {"total": 0.0, "tonnes": 0.0})
        by_client: dict[str, dict[str, float]] = defaultdict(lambda: {"total": 0.0, "tonnes": 0.0})
        by_product: dict[str, dict[str, float]] = defaultdict(lambda: {"total": 0.0, "tonnes": 0.0})
        by_carrier: dict[str, dict[str, float]] = defaultdict(lambda: {"total": 0.0, "tonnes": 0.0})

        for row in result.rows:
            if row["status"] == "Anulada":
                continue
            date_key = row["date"].isoformat()
            for target, key in (
                (by_date, date_key),
                (by_client, row["client_name"] or "Sin cliente"),
                (by_product, row["product_name"] or "Sin producto"),
                (by_carrier, row["carrier_name"] or "Sin transportista"),
            ):
                target[key]["total"] += float(row["total"] or 0)
                target[key]["tonnes"] += float(row["tonnes"] or 0)

        def ranking(source: dict[str, dict[str, float]], limit: int = 8) -> list[dict]:
            rows = [
                {"name": name, "total": round(values["total"], 2), "tonnes": round(values["tonnes"], 3)}
                for name, values in source.items()
            ]
            rows.sort(key=lambda item: item["total"], reverse=True)
            return rows[:limit]

        evolution = [
            {"date": key, "total": round(values["total"], 2), "tonnes": round(values["tonnes"], 3)}
            for key, values in sorted(by_date.items())
        ]
        totals = result.totals
        return {
            "filters": {
                "start": filters.start.isoformat(),
                "end": filters.end.isoformat(),
                "destination": filters.destination or "",
            },
            "totals": {
                "net": totals.net,
                "vat": totals.vat,
                "total": totals.total,
                "tonnes": totals.tonnes,
                "orders": totals.orders,
                "lines": totals.lines,
            },
            "evolution": evolution,
            "clients": ranking(by_client),
            "products": ranking(by_product),
            "carriers": ranking(by_carrier),
        }

    def generate(self, filters: SalesDispatchFilters) -> Path:
        self.root_dir.mkdir(parents=True, exist_ok=True)
        asset_host = ManagerialDashboardHtmlReport(root_dir=self.root_dir)
        chart_available = asset_host.ensure_chart_js()
        chart_src = f'<script src="assets/{asset_host.chart_js_path.name}"></script>' if chart_available else ""
        payload = self._payload(filters)
        html = _HTML_TEMPLATE.replace("__CHART_SCRIPT__", chart_src).replace(
            "__PAYLOAD__", json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")
        )
        self.html_path.write_text(html, encoding="utf-8")
        return self.html_path

    def open(self, filters: SalesDispatchFilters) -> Path:
        path = self.generate(filters)
        self.browser_open(path.resolve().as_uri())
        return path


_HTML_TEMPLATE = r'''<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>FEMAG · Ventas y despachos</title>
<style>
:root{--bg:#f4f7fb;--panel:#fff;--ink:#172033;--muted:#64748b;--line:#e2e8f0;--brand:#1559d6;--shadow:0 8px 28px rgba(24,40,72,.08)}*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.45 Segoe UI,Arial,sans-serif}.shell{max-width:1500px;margin:auto;padding:28px}.header{display:flex;justify-content:space-between;gap:20px;align-items:flex-start}.eyebrow{color:var(--brand);font-size:12px;font-weight:800;text-transform:uppercase;letter-spacing:.1em}.title{font-size:30px;margin:5px 0}.subtitle,.range{color:var(--muted)}.range{background:#fff;border:1px solid var(--line);border-radius:12px;padding:10px 14px;box-shadow:var(--shadow)}.kpis{display:grid;grid-template-columns:repeat(6,1fr);gap:12px;margin-top:20px}.card,.panel{background:var(--panel);border:1px solid var(--line);border-radius:16px;box-shadow:var(--shadow)}.card{padding:16px}.label{font-size:11px;font-weight:800;text-transform:uppercase;color:var(--muted)}.value{font-size:22px;font-weight:800;margin-top:8px}.grid{display:grid;grid-template-columns:1.35fr 1fr;gap:16px;margin-top:16px}.panel{padding:18px}.panel h2{font-size:16px;margin:0 0 12px}.chart{height:310px}.two{display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-top:16px}table{width:100%;border-collapse:collapse}th{font-size:11px;text-transform:uppercase;color:var(--muted);text-align:left;border-bottom:1px solid var(--line);padding:8px}td{padding:9px 8px;border-bottom:1px solid #edf1f6}.num{text-align:right}.notice{display:none;margin:16px 0;background:#fff7e8;border:1px solid #f0d6a5;border-radius:12px;padding:12px;color:#815716}@media(max-width:1200px){.kpis{grid-template-columns:repeat(3,1fr)}}@media(max-width:850px){.grid,.two{grid-template-columns:1fr}.kpis{grid-template-columns:repeat(2,1fr)}}
</style>__CHART_SCRIPT__</head><body><div class="shell"><div class="header"><div><div class="eyebrow">FEMAG · Informe gerencial</div><h1 class="title">Dashboard de ventas y despachos</h1><div class="subtitle">Visualización de los mismos datos y filtros del informe detallado.</div></div><div class="range" id="range"></div></div><div class="kpis"><div class="card"><div class="label">Total valorizado</div><div class="value" id="total"></div></div><div class="card"><div class="label">Neto</div><div class="value" id="net"></div></div><div class="card"><div class="label">IVA</div><div class="value" id="vat"></div></div><div class="card"><div class="label">Toneladas</div><div class="value" id="tonnes"></div></div><div class="card"><div class="label">Órdenes</div><div class="value" id="orders"></div></div><div class="card"><div class="label">Renglones</div><div class="value" id="lines"></div></div></div><div class="notice" id="notice">Los gráficos no están disponibles; los rankings siguen visibles.</div><div class="grid"><div class="panel"><h2>Evolución del período</h2><div class="chart"><canvas id="evolution"></canvas></div></div><div class="panel"><h2>Top clientes</h2><div class="chart"><canvas id="clients"></canvas></div></div></div><div class="two"><div class="panel"><h2>Top productos</h2><table><thead><tr><th>Producto</th><th class="num">Valorizado</th><th class="num">TN</th></tr></thead><tbody id="products"></tbody></table></div><div class="panel"><h2>Transportistas</h2><table><thead><tr><th>Transportista</th><th class="num">Valorizado</th><th class="num">TN</th></tr></thead><tbody id="carriers"></tbody></table></div></div></div><script>
const D=__PAYLOAD__;const money=n=>new Intl.NumberFormat('es-AR',{style:'currency',currency:'ARS',maximumFractionDigits:2}).format(Number(n||0));const num=(n,d=3)=>new Intl.NumberFormat('es-AR',{minimumFractionDigits:d,maximumFractionDigits:d}).format(Number(n||0));const date=s=>{const [y,m,d]=s.split('-');return `${d}/${m}/${y}`};document.getElementById('range').textContent=`${date(D.filters.start)} — ${date(D.filters.end)}`+(D.filters.destination?` · ${D.filters.destination}`:'');document.getElementById('total').textContent=money(D.totals.total);document.getElementById('net').textContent=money(D.totals.net);document.getElementById('vat').textContent=money(D.totals.vat);document.getElementById('tonnes').textContent=num(D.totals.tonnes)+' TN';document.getElementById('orders').textContent=D.totals.orders;document.getElementById('lines').textContent=D.totals.lines;function rows(id,data){document.getElementById(id).innerHTML=data.length?data.map(x=>`<tr><td>${esc(x.name)}</td><td class="num">${money(x.total)}</td><td class="num">${num(x.tonnes)}</td></tr>`).join(''):'<tr><td colspan="3">Sin datos</td></tr>'}function esc(v){return String(v??'').replace(/[&<>'"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]))}rows('products',D.products);rows('carriers',D.carriers);if(typeof Chart==='undefined'){document.getElementById('notice').style.display='block'}else{new Chart(document.getElementById('evolution'),{type:'line',data:{labels:D.evolution.map(x=>date(x.date)),datasets:[{data:D.evolution.map(x=>x.total),borderColor:'#1559d6',backgroundColor:'rgba(21,89,214,.10)',fill:true,tension:.3}]},options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{display:false}},scales:{y:{beginAtZero:true}}}});new Chart(document.getElementById('clients'),{type:'bar',data:{labels:D.clients.map(x=>x.name),datasets:[{data:D.clients.map(x=>x.total),backgroundColor:'#1559d6',borderRadius:7}]},options:{responsive:true,maintainAspectRatio:false,indexAxis:'y',plugins:{legend:{display:false},tooltip:{callbacks:{label:c=>money(c.raw)}}},scales:{x:{beginAtZero:true},y:{grid:{display:false}}}}})}
</script></body></html>'''
