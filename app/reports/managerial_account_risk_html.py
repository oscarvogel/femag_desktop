from __future__ import annotations

from collections import defaultdict
from html import escape
from pathlib import Path
from tempfile import gettempdir
import webbrowser

from app.reports.managerial_account_risk import AccountRiskFilters, AccountRiskReportResult, ManagerialAccountRiskService


class ManagerialAccountRiskHtmlReport:
    def __init__(self, *, service: ManagerialAccountRiskService | None = None) -> None:
        self.service = service or ManagerialAccountRiskService()

    def open(self, filters: AccountRiskFilters) -> Path:
        result = self.service.report(filters)
        path = Path(gettempdir()) / "femag_dashboard_cuenta_corriente.html"
        path.write_text(self.render(result), encoding="utf-8")
        webbrowser.open(path.resolve().as_uri())
        return path

    def render(self, result: AccountRiskReportResult) -> str:
        totals = result.totals
        ranked = sorted(result.rows, key=lambda row: row["balance"], reverse=True)[:10]
        overdue_ranked = sorted(result.rows, key=lambda row: row["overdue"], reverse=True)[:10]

        def money(value: float) -> str:
            return f"$ {value:,.2f}"

        def ranking(rows, field):
            maximum = max((float(row[field]) for row in rows), default=0.0) or 1.0
            items = []
            for row in rows:
                value = float(row[field])
                width = max((value / maximum) * 100.0, 0.0)
                items.append(
                    f'<div class="rank"><div><strong>{escape(row["client_name"])}</strong>'
                    f'<span>{money(value)}</span></div><div class="bar"><i style="width:{width:.1f}%"></i></div></div>'
                )
            return "".join(items) or '<p class="muted">Sin datos para los filtros seleccionados.</p>'

        rows_html = "".join(
            "<tr>"
            f"<td>{escape(row['client_name'])}</td>"
            f"<td>{money(row['balance'])}</td>"
            f"<td>{money(row['overdue'])}</td>"
            f"<td>{money(row['due_future'])}</td>"
            f"<td>{money(row['due_7'])}</td>"
            f"<td>{money(row['due_15'])}</td>"
            f"<td>{money(row['due_30'])}</td>"
            f"<td>{row['max_days_overdue']}</td>"
            f"<td>{row['oldest_unpaid_due'].strftime('%d/%m/%Y') if row['oldest_unpaid_due'] else ''}</td>"
            "</tr>"
            for row in result.rows
        )
        return f"""<!doctype html>
<html lang="es"><head><meta charset="utf-8"><title>FEMAG · Cuenta corriente</title>
<style>
*{{box-sizing:border-box}} body{{font-family:Arial,sans-serif;margin:0;background:#f1f5f9;color:#0f172a}}
main{{max-width:1500px;margin:auto;padding:28px}} h1{{margin:0 0 4px}} .muted{{color:#64748b}}
.cards{{display:grid;grid-template-columns:repeat(6,1fr);gap:12px;margin:22px 0}} .card,.panel{{background:white;border:1px solid #e2e8f0;border-radius:14px;padding:18px}}
.card span{{display:block;color:#64748b;font-size:13px}} .card strong{{display:block;font-size:22px;margin-top:8px}}
.grid{{display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-bottom:16px}} .rank{{margin:14px 0}} .rank>div:first-child{{display:flex;justify-content:space-between;gap:12px}}
.bar{{height:9px;background:#e2e8f0;border-radius:999px;overflow:hidden;margin-top:6px}} .bar i{{display:block;height:100%;background:#2563eb}}
table{{width:100%;border-collapse:collapse;font-size:13px}} th,td{{padding:9px 10px;border-bottom:1px solid #e2e8f0;text-align:right}} th:first-child,td:first-child{{text-align:left}} th{{background:#f8fafc;position:sticky;top:0}}
.table-wrap{{max-height:460px;overflow:auto}} @media(max-width:1000px){{.cards{{grid-template-columns:repeat(2,1fr)}}.grid{{grid-template-columns:1fr}}}}
</style></head><body><main>
<h1>Cuenta corriente y deuda vencida</h1><div class="muted">Al {result.filters.as_of.strftime('%d/%m/%Y')} · {escape(result.currency)}</div>
<div class="cards">
<div class="card"><span>Saldo total</span><strong>{money(totals.balance)}</strong></div>
<div class="card"><span>Deuda vencida</span><strong>{money(totals.overdue)}</strong></div>
<div class="card"><span>Vence en 7 días</span><strong>{money(totals.due_7)}</strong></div>
<div class="card"><span>Vence en 15 días</span><strong>{money(totals.due_15)}</strong></div>
<div class="card"><span>Vence en 30 días</span><strong>{money(totals.due_30)}</strong></div>
<div class="card"><span>Clientes vencidos</span><strong>{totals.clients_overdue}</strong></div>
</div>
<div class="grid"><section class="panel"><h2>Mayor exposición</h2>{ranking(ranked,'balance')}</section><section class="panel"><h2>Mayor deuda vencida</h2>{ranking(overdue_ranked,'overdue')}</section></div>
<section class="panel"><h2>Detalle consolidado</h2><div class="table-wrap"><table><thead><tr><th>Cliente</th><th>Saldo</th><th>Vencido</th><th>A vencer</th><th>7 días</th><th>15 días</th><th>30 días</th><th>Días atraso</th><th>Venc. más antiguo</th></tr></thead><tbody>{rows_html}</tbody></table></div></section>
</main></body></html>"""
