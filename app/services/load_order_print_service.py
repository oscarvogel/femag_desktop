from html import escape
from pathlib import Path

from app.models.load_orders import LoadOrder
from app.services.audit_service import AuditService


class LoadOrderPrintService:
    def __init__(self, current_user: str, audit_service: AuditService | None = None):
        self.current_user = current_user
        self.audit_service = audit_service or AuditService()

    def export_order(self, order: LoadOrder, output_dir: str | Path, *, reprint: bool = False) -> Path:
        return self._write(
            output_dir,
            f"orden_carga_{order.order_number}.html",
            self.render_order(order, reprint=reprint),
            order,
            reprint,
        )

    def export_summary(self, order: LoadOrder, output_dir: str | Path, *, reprint: bool = False) -> Path:
        return self._write(
            output_dir,
            f"hoja_resumen_{order.order_number}.html",
            self.render_summary(order, reprint=reprint),
            order,
            reprint,
        )

    def export_combined(self, order: LoadOrder, output_dir: str | Path, *, reprint: bool = False) -> Path:
        html = self._document(
            f"{self._order_body(order, reprint=reprint)}<div class=\"page-break\"></div>{self._summary_body(order)}"
        )
        return self._write(output_dir, f"orden_y_resumen_{order.order_number}.html", html, order, reprint)

    def render_order(self, order: LoadOrder, *, reprint: bool = False) -> str:
        return self._document(self._order_body(order, reprint=reprint))

    def render_summary(self, order: LoadOrder, *, reprint: bool = False) -> str:
        return self._document(self._summary_body(order, reprint=reprint))

    def _write(self, output_dir: str | Path, filename: str, html: str, order: LoadOrder, reprint: bool) -> Path:
        path = Path(output_dir)
        path.mkdir(parents=True, exist_ok=True)
        target = path / filename
        target.write_text(html, encoding="utf-8")
        self.audit_service.record(
            user=self.current_user,
            module="Ordenes de carga",
            action="reimprimir" if reprint else "imprimir",
            record_ref=f"LoadOrder:{order.id}",
            new_value={"file_path": str(target), "order_number": order.order_number},
        )
        return target

    def _document(self, body: str) -> str:
        return f"""<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<title>Orden de despacho</title>
<style>
@page {{ size: A4; margin: 16mm; }}
body {{ font-family: Arial, sans-serif; color: #202124; font-size: 12px; }}
h1 {{ font-size: 20px; margin: 0 0 10px; }}
h2 {{ font-size: 16px; margin: 18px 0 8px; }}
table {{ width: 100%; border-collapse: collapse; margin-top: 8px; }}
th, td {{ border: 1px solid #9aa0a6; padding: 6px; text-align: left; }}
.numeric {{ text-align: right; }}
.meta {{ display: grid; grid-template-columns: 1fr 1fr; gap: 6px 18px; }}
.label {{ font-weight: bold; }}
.signature {{ margin-top: 42px; border-top: 1px solid #202124; width: 260px; padding-top: 6px; }}
.page-break {{ page-break-before: always; }}
</style>
</head>
<body>{body}</body>
</html>"""

    def _order_body(self, order: LoadOrder, *, reprint: bool = False) -> str:
        flag = "<p><strong>Reimpresion</strong></p>" if reprint else ""
        return f"""
<h1>Orden de despacho de fecula de mandioca</h1>
{flag}
{self._meta(order)}
{self._lines(order)}
{self._transport(order)}
<h2>Observaciones</h2>
<p>{escape(order.observations or "")}</p>
<div class="signature">Firma del encargado de carga</div>
"""

    def _summary_body(self, order: LoadOrder, *, reprint: bool = False) -> str:
        flag = "<p><strong>Reimpresion</strong></p>" if reprint else ""
        return f"""
<h1>Orden de despacho de fecula de mandioca</h1>
<h2>Hoja resumen / sobre de carga</h2>
{flag}
{self._meta(order)}
{self._lines(order)}
{self._transport(order)}
<h2>Observaciones</h2>
<p>{escape(order.observations or "")}</p>
<div class="signature">Firma del encargado de carga</div>
"""

    def _meta(self, order: LoadOrder) -> str:
        header_client = order.header_client_text or (order.header_client.name if order.header_client else "")
        return f"""
<section class="meta">
<div><span class="label">Numero:</span> {order.order_number}</div>
<div><span class="label">Fecha:</span> {order.date:%d/%m/%Y}</div>
<div><span class="label">Estado:</span> {escape(order.status)}</div>
<div><span class="label">Cliente cabecera:</span> {escape(header_client)}</div>
<div><span class="label">Destino general:</span> {escape(order.destination)}</div>
</section>
"""

    def _lines(self, order: LoadOrder) -> str:
        rows = "".join(
            "<tr>"
            f"<td>{escape(self._recipient(item))}</td>"
            f"<td>{escape(item.destination_text or '')}</td>"
            f"<td class=\"numeric\">{item.bags_25kg}</td>"
            f"<td class=\"numeric\">{item.bags_10kg}</td>"
            f"<td class=\"numeric\">{item.pack}</td>"
            f"<td class=\"numeric\">{item.pallet}</td>"
            f"<td>{escape(self._product_detail(item))}</td>"
            f"<td>{escape(item.lot_number or '')}</td>"
            f"<td>{self._format_date(item.production_date)}</td>"
            f"<td>{escape(item.observations or '')}</td>"
            "</tr>"
            for item in order.lines
        )
        totals = {
            "bags_25kg": sum(item.bags_25kg or 0 for item in order.lines),
            "bags_10kg": sum(item.bags_10kg or 0 for item in order.lines),
            "pack": sum(item.pack or 0 for item in order.lines),
            "pallet": sum(item.pallet or 0 for item in order.lines),
        }
        totals_row = (
            "<tr><th colspan=\"2\">Totales</th>"
            f"<th class=\"numeric\">{totals['bags_25kg']}</th>"
            f"<th class=\"numeric\">{totals['bags_10kg']}</th>"
            f"<th class=\"numeric\">{totals['pack']}</th>"
            f"<th class=\"numeric\">{totals['pallet']}</th>"
            "<th colspan=\"4\"></th></tr>"
        )
        return (
            "<h2>Detalle de despacho</h2><table><tr>"
            "<th>Destinatario / cliente</th><th>Localidad / destino</th>"
            "<th>Bolsas x 25 kg</th><th>Bolsas x 10 kg</th><th>Pack</th><th>Pallet</th>"
            "<th>Detalle</th><th>Numero de lote</th><th>Fecha de elaboracion</th><th>Obs.</th>"
            f"</tr>{rows}{totals_row}</table>"
        )

    def _transport(self, order: LoadOrder) -> str:
        clean = "Si" if order.vehicle_clean_and_suitable else "No"
        return f"""
<h2>Transporte</h2>
<section class="meta">
<div><span class="label">Empresa de transporte:</span> {escape(order.carrier.name)}</div>
<div><span class="label">Dominio del vehiculo:</span> {escape(order.truck.domain)}</div>
<div><span class="label">Nombre del chofer:</span> {escape(order.driver.name)}</div>
<div><span class="label">Vehiculo limpio y apto:</span> {clean}</div>
</section>
"""

    def _recipient(self, line) -> str:
        return line.recipient_text or (line.client.name if line.client else "")

    def _product_detail(self, line) -> str:
        return line.product_detail or (line.product.name if line.product else "")

    def _format_date(self, value) -> str:
        return f"{value:%d/%m/%Y}" if value else ""
