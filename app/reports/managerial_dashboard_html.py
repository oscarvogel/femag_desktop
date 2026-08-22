from __future__ import annotations

import json
import os
from pathlib import Path
from urllib.request import Request, urlopen
import webbrowser

from app.reports.managerial_dashboard import ManagerialDashboardService, ReportPeriod


CHART_JS_VERSION = "4.4.7"
CHART_JS_URL = f"https://cdn.jsdelivr.net/npm/chart.js@{CHART_JS_VERSION}/dist/chart.umd.min.js"


class ManagerialDashboardHtmlReport:
    """Generate an executive dashboard as a self-contained local HTML report.

    Business data is calculated by :class:`ManagerialDashboardService`. The only
    optional browser dependency is Chart.js, downloaded once and cached locally.
    If the first download cannot be completed, the report still renders cards
    and tables and simply omits charts.
    """

    def __init__(
        self,
        *,
        service: ManagerialDashboardService | None = None,
        root_dir: Path | None = None,
        browser_open=None,
    ) -> None:
        self.service = service or ManagerialDashboardService()
        self.root_dir = root_dir or self._default_root_dir()
        self.browser_open = browser_open or webbrowser.open

    @staticmethod
    def _default_root_dir() -> Path:
        base = os.getenv("LOCALAPPDATA")
        if base:
            return Path(base) / "FEMAG" / "dashboard_gerencial"
        return Path.home() / ".femag" / "dashboard_gerencial"

    @property
    def assets_dir(self) -> Path:
        return self.root_dir / "assets"

    @property
    def chart_js_path(self) -> Path:
        return self.assets_dir / f"chart-{CHART_JS_VERSION}.umd.min.js"

    @property
    def html_path(self) -> Path:
        return self.root_dir / "dashboard.html"

    def ensure_chart_js(self) -> bool:
        path = self.chart_js_path
        if path.exists() and path.stat().st_size > 100_000:
            return True
        self.assets_dir.mkdir(parents=True, exist_ok=True)
        temp = path.with_suffix(path.suffix + ".tmp")
        try:
            request = Request(CHART_JS_URL, headers={"User-Agent": "FEMAG Desktop"})
            with urlopen(request, timeout=20) as response:  # nosec B310 - fixed HTTPS URL
                content = response.read()
            if len(content) < 100_000 or b"Chart" not in content:
                raise RuntimeError("La descarga de Chart.js no parece válida.")
            temp.write_bytes(content)
            temp.replace(path)
            return True
        except Exception:
            try:
                temp.unlink(missing_ok=True)
            except OSError:
                pass
            return False

    def build_payload(self) -> dict:
        presets = (
            ("hoy", "Hoy"),
            ("este_mes", "Este mes"),
            ("mes_anterior", "Mes anterior"),
            ("este_ano", "Este año"),
        )
        payload: dict[str, dict] = {}
        for key, label in presets:
            period = ReportPeriod.preset(label)
            payload[key] = self._snapshot_payload(self.service.snapshot(period))
        return {
            "default_period": "este_mes",
            "periods": payload,
            "chart_available": self.chart_js_path.exists(),
        }

    @staticmethod
    def _snapshot_payload(snapshot) -> dict:
        def comparison(metric) -> dict:
            return {
                "current": metric.current,
                "previous": metric.previous,
                "variation": metric.variation_percent,
            }

        return {
            "label": snapshot.period.label,
            "start": snapshot.period.start.isoformat(),
            "end": snapshot.period.end.isoformat(),
            "currency": snapshot.currency,
            "effective_statuses": list(snapshot.effective_statuses),
            "valued_dispatches": comparison(snapshot.valued_dispatches),
            "tonnes": comparison(snapshot.tonnes),
            "orders": comparison(snapshot.orders),
            "average_ticket": comparison(snapshot.average_ticket),
            "total_receivables": snapshot.total_receivables,
            "overdue_receivables": snapshot.overdue_receivables,
            "monthly_evolution": list(snapshot.monthly_evolution),
            "top_clients": list(snapshot.top_clients),
            "top_products": list(snapshot.top_products),
            "order_statuses": list(snapshot.order_statuses),
        }

    def generate(self) -> Path:
        self.root_dir.mkdir(parents=True, exist_ok=True)
        chart_available = self.ensure_chart_js()
        payload = self.build_payload()
        payload["chart_available"] = chart_available
        chart_src = (
            f'<script src="assets/{self.chart_js_path.name}"></script>'
            if chart_available
            else ""
        )
        html = _HTML_TEMPLATE.replace("__CHART_SCRIPT__", chart_src).replace(
            "__PAYLOAD__", json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")
        )
        self.html_path.write_text(html, encoding="utf-8")
        return self.html_path

    def open(self) -> Path:
        path = self.generate()
        self.browser_open(path.resolve().as_uri())
        return path


_HTML_TEMPLATE = r'''<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>FEMAG · Dashboard Gerencial</title>
<style>
:root{--bg:#f4f7fb;--panel:#fff;--ink:#172033;--muted:#677489;--line:#e1e7f0;--brand:#1559d6;--brand2:#0b3d91;--ok:#11875d;--bad:#c43b47;--warn:#bd7415;--shadow:0 8px 28px rgba(24,40,72,.08)}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.45 Inter,Segoe UI,Arial,sans-serif}.shell{max-width:1500px;margin:auto;padding:28px}.header{display:flex;align-items:flex-start;gap:24px;justify-content:space-between;margin-bottom:22px}.eyebrow{font-size:12px;font-weight:800;letter-spacing:.12em;color:var(--brand);text-transform:uppercase}.title{font-size:30px;line-height:1.1;margin:6px 0 5px}.subtitle{color:var(--muted);max-width:760px}.filters{display:flex;align-items:center;gap:10px;background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:10px 12px;box-shadow:var(--shadow)}select{border:0;background:#f7f9fc;border-radius:9px;padding:10px 34px 10px 12px;font-weight:700;color:var(--ink);outline:none}.range{font-size:12px;color:var(--muted);white-space:nowrap}.kpis{display:grid;grid-template-columns:repeat(6,minmax(0,1fr));gap:14px}.card,.panel{background:var(--panel);border:1px solid var(--line);border-radius:16px;box-shadow:var(--shadow)}.card{padding:18px;min-height:132px}.klabel{font-size:12px;font-weight:800;text-transform:uppercase;letter-spacing:.045em;color:var(--muted)}.kvalue{font-size:25px;font-weight:800;margin:12px 0 8px;white-space:nowrap}.delta{font-size:12px;font-weight:700}.up{color:var(--ok)}.down{color:var(--bad)}.flat{color:var(--muted)}.grid{display:grid;grid-template-columns:1.35fr 1fr;gap:16px;margin-top:16px}.panel{padding:18px}.panel h2{font-size:16px;margin:0 0 14px}.panel-sub{color:var(--muted);font-size:12px;margin-top:-8px;margin-bottom:12px}.chart-wrap{height:290px}.two{display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-top:16px}table{width:100%;border-collapse:collapse}th{text-align:left;color:var(--muted);font-size:11px;text-transform:uppercase;letter-spacing:.045em;border-bottom:1px solid var(--line);padding:9px 8px}td{padding:10px 8px;border-bottom:1px solid #edf1f6}td.num,th.num{text-align:right}.status{display:inline-flex;padding:4px 9px;border-radius:999px;background:#eef3fb;font-size:12px;font-weight:700}.notice{display:none;margin-top:16px;padding:12px 14px;border-radius:12px;background:#fff7e8;border:1px solid #f0d6a5;color:#815716}.foot{margin:18px 2px 0;color:var(--muted);font-size:11px}.empty{padding:28px;text-align:center;color:var(--muted)}
@media(max-width:1250px){.kpis{grid-template-columns:repeat(3,1fr)}}@media(max-width:850px){.shell{padding:18px}.header{display:block}.filters{margin-top:14px;justify-content:space-between}.kpis{grid-template-columns:repeat(2,1fr)}.grid,.two{grid-template-columns:1fr}}@media(max-width:520px){.kpis{grid-template-columns:1fr}}
</style>
__CHART_SCRIPT__
</head>
<body>
<div class="shell">
  <div class="header">
    <div><div class="eyebrow">FEMAG · Gestión ejecutiva</div><h1 class="title">Dashboard Gerencial</h1><div class="subtitle">Despachos, volumen, exposición de clientes y evolución comercial en una sola vista.</div></div>
    <div class="filters"><select id="period"><option value="hoy">Hoy</option><option value="este_mes" selected>Este mes</option><option value="mes_anterior">Mes anterior</option><option value="este_ano">Este año</option></select><span class="range" id="range"></span></div>
  </div>
  <div class="kpis">
    <div class="card"><div class="klabel">Despachos valorizados</div><div class="kvalue" id="dispatches"></div><div class="delta" id="dispatchesDelta"></div></div>
    <div class="card"><div class="klabel">Toneladas</div><div class="kvalue" id="tonnes"></div><div class="delta" id="tonnesDelta"></div></div>
    <div class="card"><div class="klabel">Órdenes / cargas</div><div class="kvalue" id="orders"></div><div class="delta" id="ordersDelta"></div></div>
    <div class="card"><div class="klabel">Saldo clientes</div><div class="kvalue" id="receivables"></div><div class="delta flat">Saldo consolidado actual</div></div>
    <div class="card"><div class="klabel">Saldo vencido</div><div class="kvalue" id="overdue"></div><div class="delta flat" id="overdueDate"></div></div>
    <div class="card"><div class="klabel">Ticket promedio</div><div class="kvalue" id="ticket"></div><div class="delta" id="ticketDelta"></div></div>
  </div>
  <div class="notice" id="chartNotice">El dashboard funciona normalmente, pero los gráficos no están disponibles porque Chart.js todavía no pudo descargarse. FEMAG volverá a intentarlo en la próxima apertura.</div>
  <div class="grid">
    <div class="panel"><h2>Evolución mensual</h2><div class="panel-sub">Últimos 12 meses de despachos valorizados</div><div class="chart-wrap"><canvas id="evolutionChart"></canvas></div></div>
    <div class="panel"><h2>Top clientes</h2><div class="panel-sub">Ranking por despachos valorizados</div><div class="chart-wrap"><canvas id="clientsChart"></canvas></div></div>
  </div>
  <div class="two">
    <div class="panel"><h2>Top productos</h2><table><thead><tr><th>Producto</th><th class="num">Valorizado</th><th class="num">TN</th></tr></thead><tbody id="productsBody"></tbody></table></div>
    <div class="panel"><h2>Estado de órdenes</h2><table><thead><tr><th>Estado</th><th class="num">Órdenes</th></tr></thead><tbody id="statusBody"></tbody></table></div>
  </div>
  <div class="foot" id="policy"></div>
</div>
<script>
const DATA=__PAYLOAD__; let charts=[];
const money=n=>new Intl.NumberFormat('es-AR',{style:'currency',currency:'ARS',maximumFractionDigits:2}).format(Number(n||0));
const num=(n,d=2)=>new Intl.NumberFormat('es-AR',{minimumFractionDigits:d,maximumFractionDigits:d}).format(Number(n||0));
const dateAR=s=>{const [y,m,d]=s.split('-');return `${d}/${m}/${y}`};
function delta(metric){const v=metric.variation;if(v===null)return metric.current?'Sin base comparable':'0,0% vs período anterior'; const p=v>0?'+':'';return `${p}${num(v,1)}% vs período anterior`}
function deltaClass(metric){const v=metric.variation;return v>0?'up':v<0?'down':'flat'}
function setMetric(id,deltaId,value,metric){document.getElementById(id).textContent=value;const el=document.getElementById(deltaId);el.textContent=delta(metric);el.className='delta '+deltaClass(metric)}
function tableRows(id,rows,render,cols){const body=document.getElementById(id);body.innerHTML=rows.length?rows.map(render).join(''):`<tr><td colspan="${cols}" class="empty">Sin datos para el período</td></tr>`}
function destroyCharts(){charts.forEach(c=>c.destroy());charts=[]}
function drawCharts(d){destroyCharts(); if(typeof Chart==='undefined'){document.getElementById('chartNotice').style.display='block';return} document.getElementById('chartNotice').style.display='none';
 const common={responsive:true,maintainAspectRatio:false,plugins:{legend:{display:false}},scales:{x:{grid:{display:false}},y:{beginAtZero:true,grid:{color:'#edf1f6'}}}};
 charts.push(new Chart(document.getElementById('evolutionChart'),{type:'line',data:{labels:d.monthly_evolution.map(x=>x.label),datasets:[{data:d.monthly_evolution.map(x=>x.total),borderColor:'#1559d6',backgroundColor:'rgba(21,89,214,.10)',fill:true,tension:.32,pointRadius:3}]},options:common}));
 charts.push(new Chart(document.getElementById('clientsChart'),{type:'bar',data:{labels:d.top_clients.map(x=>x.name),datasets:[{data:d.top_clients.map(x=>x.total),backgroundColor:'#1559d6',borderRadius:7}]},options:{...common,indexAxis:'y'}}));
}
function render(key){const d=DATA.periods[key];document.getElementById('range').textContent=`${dateAR(d.start)} — ${dateAR(d.end)}`;
 setMetric('dispatches','dispatchesDelta',money(d.valued_dispatches.current),d.valued_dispatches);setMetric('tonnes','tonnesDelta',num(d.tonnes.current,3)+' TN',d.tonnes);setMetric('orders','ordersDelta',num(d.orders.current,0),d.orders);setMetric('ticket','ticketDelta',money(d.average_ticket.current),d.average_ticket);
 document.getElementById('receivables').textContent=money(d.total_receivables);document.getElementById('overdue').textContent=money(d.overdue_receivables);document.getElementById('overdueDate').textContent='Vencido al '+dateAR(d.end);
 tableRows('productsBody',d.top_products,x=>`<tr><td>${esc(x.name)}</td><td class="num">${money(x.total)}</td><td class="num">${num(x.tonnes,3)}</td></tr>`,3);
 tableRows('statusBody',d.order_statuses,x=>`<tr><td><span class="status">${esc(x.status)}</span></td><td class="num">${x.count}</td></tr>`,2);
 document.getElementById('policy').textContent=`Criterio V1: despachos efectivos = ${d.effective_statuses.join(', ')}. Las devoluciones aún no se descuentan del KPI valorizado.`; drawCharts(d)}
function esc(v){return String(v??'').replace(/[&<>'"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]))}
document.getElementById('period').addEventListener('change',e=>render(e.target.value));render(DATA.default_period);
</script>
</body></html>'''
