from collections import defaultdict
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
            self._document_title(order),
            f"{self._order_body(order, reprint=reprint)}<div class=\"page-break\"></div>{self._summary_body(order, reprint=reprint)}",
        )
        return self._write(output_dir, f"orden_y_resumen_{order.order_number}.html", html, order, reprint)

    def render_order(self, order: LoadOrder, *, reprint: bool = False) -> str:
        return self._document(self._document_title(order), self._order_body(order, reprint=reprint))

    def render_summary(self, order: LoadOrder, *, reprint: bool = False) -> str:
        return self._document(self._document_title(order), self._summary_body(order, reprint=reprint))

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

    def _document(self, title: str, body: str) -> str:
        return f"""<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<title>{escape(title)}</title>
<style>
@page {{ size: A4; margin: 14mm; }}
* {{ box-sizing: border-box; }}
body {{ font-family: Arial, sans-serif; color: #202124; font-size: 11.5px; line-height: 1.35; margin: 0; }}
h1 {{ font-size: 21px; margin: 0; letter-spacing: 0; }}
h2 {{ font-size: 15px; margin: 16px 0 8px; border-bottom: 1px solid #2f3a4a; padding-bottom: 4px; }}
h3 {{ font-size: 13px; margin: 0 0 8px; }}
table {{ width: 100%; border-collapse: collapse; margin-top: 8px; page-break-inside: avoid; }}
th, td {{ border: 1px solid #9aa0a6; padding: 5px 6px; text-align: left; vertical-align: top; }}
th {{ background: #eef2f7; color: #172033; font-weight: bold; }}
.document {{ min-height: 260mm; }}
.topline {{ display: flex; justify-content: space-between; gap: 12px; border-bottom: 2px solid #172033; padding-bottom: 10px; margin-bottom: 12px; }}
.doc-kind {{ text-transform: uppercase; font-size: 11px; font-weight: bold; color: #475569; }}
.badge {{ border: 1px solid #172033; padding: 5px 8px; font-weight: bold; text-transform: uppercase; white-space: nowrap; }}
.copy-badge {{ border-color: #9f1239; color: #9f1239; }}
.meta-grid {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 7px; margin: 10px 0 4px; }}
.box {{ border: 1px solid #c6ccd5; padding: 7px; min-height: 42px; }}
.label {{ display: block; font-size: 10px; text-transform: uppercase; color: #64748b; font-weight: bold; }}
.value {{ font-size: 12px; color: #111827; }}
.destination {{ border: 1px solid #c6ccd5; padding: 9px; margin-top: 10px; page-break-inside: avoid; }}
.destination-title {{ display: flex; justify-content: space-between; gap: 8px; margin-bottom: 6px; }}
.destination-total, .general-total {{ text-align: right; font-weight: bold; margin-top: 7px; }}
.observations {{ white-space: pre-wrap; border: 1px solid #d9e1ec; min-height: 34px; padding: 7px; }}
.summary-list {{ margin: 8px 0 0; padding-left: 18px; }}
.summary-list li {{ margin-bottom: 5px; }}
.footer-note {{ margin-top: 16px; font-size: 10px; color: #64748b; border-top: 1px solid #c6ccd5; padding-top: 6px; }}
.page-break {{ page-break-before: always; }}
</style>
</head>
<body>{body}</body>
</html>"""

    def _order_body(self, order: LoadOrder, *, reprint: bool = False) -> str:
        flag = self._reprint_flag(reprint)
        return f"""
<section class="document">
{self._header(order, "Orden de carga", "Documento logistico interno", flag)}
{self._meta(order)}
{self._destinations(order)}
{self._pallets(order)}
<h2>Observaciones operativas</h2>
<div class="observations">{escape(order.observations or "Sin observaciones.")}</div>
<p class="footer-note">No fiscal. No reemplaza documentacion fiscal ni comprobantes comerciales.</p>
</section>
"""

    def _summary_body(self, order: LoadOrder, *, reprint: bool = False) -> str:
        flag = self._reprint_flag(reprint)
        return f"""
<section class="document summary-document">
{self._header(order, "Hoja resumen / sobre de carga", "Resumen para adjuntar al sobre de la orden", flag)}
{self._meta(order)}
{self._summary_destinations(order)}
<h2>Totales</h2>
<p class="general-total">Total general: {escape(self._total_text(self._order_totals(order)))}</p>
<h2>Observaciones operativas</h2>
<div class="observations">{escape(order.observations or "Sin observaciones.")}</div>
<p class="footer-note">Hoja logistica minima para oficina. No fiscal.</p>
</section>
"""

    def _document_title(self, order: LoadOrder) -> str:
        return f"Orden de carga OC-{order.order_number:06d}"

    def _reprint_flag(self, reprint: bool) -> str:
        if not reprint:
            return ""
        return "<div class=\"badge copy-badge\">Reimpresion operativa - Copia para reimpresion</div>"

    def _header(self, order: LoadOrder, title: str, subtitle: str, flag: str) -> str:
        right = flag or "<div class=\"badge\">Original operativo</div>"
        return f"""
<header class="topline">
<div>
<div class="doc-kind">{escape(subtitle)}</div>
<h1>{escape(title)} OC-{order.order_number:06d}</h1>
<div>Orden de carga Nro. {order.order_number}</div>
</div>
{right}
</header>
"""

    def _meta(self, order: LoadOrder) -> str:
        return f"""
<h2>Cabecera logística</h2>
<section class="meta-grid">
{self._box("Fecha", f"{order.date:%d/%m/%Y}")}
{self._box("Estado", order.status)}
{self._box("Transportista", order.carrier.name)}
{self._box("Chofer", order.driver.name)}
{self._box("Camion / patente", order.truck.domain)}
{self._box("Tipo", "Carga multi-cliente" if len(self._destination_groups(order)) > 1 else "Carga operativa")}
</section>
"""

    def _destinations(self, order: LoadOrder) -> str:
        sections = []
        destinations = self._destination_groups(order)
        if not destinations:
            return self._legacy_products(order)
        for index, destination in enumerate(destinations, start=1):
            rows = "".join(
                f"<tr><td>{escape(item.product.name)}</td><td>{escape(item.product.unit)}</td>"
                f"<td>{item.quantity:g}</td><td>{escape(item.unit)}</td><td>{escape(item.observations or '')}</td></tr>"
                for item in destination.products
            )
            destination_total = self._total_text(self._destination_totals(destination))
            sections.append(
                f"""
<section class="destination">
<div class="destination-title">
<h3>Cliente / destino {index}</h3>
<strong>{escape(destination_total)}</strong>
</div>
<div class="meta-grid">
{self._box("Cliente", destination.client.name)}
{self._box("Destino", f"{destination.delivery_address.address}, {destination.delivery_address.city}")}
{self._box("Provincia", destination.delivery_address.province)}
</div>
<table>
<tr><th>Producto</th><th>Presentacion</th><th>Cantidad</th><th>Unidad</th><th>Obs.</th></tr>
{rows}
</table>
<div class="destination-total">Total destino: {escape(destination_total)}</div>
{self._destination_observations(destination)}
</section>
"""
            )
        return (
            f"<h2>Detalle por cliente / destino</h2>{''.join(sections)}"
            f"<div class=\"general-total\">Total general: {escape(self._total_text(self._order_totals(order)))}</div>"
        )

    def _legacy_products(self, order: LoadOrder) -> str:
        rows = "".join(
            f"<tr><td>{escape(item.product.name)}</td><td>{escape(item.product.unit)}</td>"
            f"<td>{item.quantity:g}</td><td>{escape(item.unit)}</td><td>{escape(item.observations or '')}</td></tr>"
            for item in order.products
        )
        return (
            "<h2>Detalle por cliente / destino</h2>"
            "<section class=\"destination\">"
            "<h3>Cliente / destino historico</h3>"
            f"{self._legacy_destination_meta(order)}"
            "<table><tr><th>Producto</th><th>Presentacion</th><th>Cantidad</th><th>Unidad</th><th>Obs.</th></tr>"
            f"{rows}</table>"
            f"<div class=\"general-total\">Total general: {escape(self._total_text(self._order_totals(order)))}</div>"
            "</section>"
        )

    def _pallets(self, order: LoadOrder) -> str:
        pallets = list(order.pallets)
        if not pallets:
            return "<h2>Pallets</h2><p>Sin pallets declarados.</p>"
        rows = "".join(
            f"<tr><td>{escape(item.pallet_type.type)}</td><td>{escape(item.measure)}</td>"
            f"<td>{item.weight:g}</td><td>{item.quantity}</td><td>{escape(item.observations or '')}</td></tr>"
            for item in pallets
        )
        return (
            "<h2>Pallets</h2><table><tr><th>Tipo</th><th>Medida</th><th>Peso</th>"
            f"<th>Cantidad</th><th>Obs.</th></tr>{rows}</table>"
        )

    def _summary_destinations(self, order: LoadOrder) -> str:
        destinations = self._destination_groups(order)
        count = len(destinations)
        if count == 0:
            return self._legacy_summary(order)
        items = "".join(
            "<li>"
            f"{escape(destination.client.name)} - "
            f"{escape(destination.delivery_address.address)}, {escape(destination.delivery_address.city)}"
            f" ({escape(self._total_text(self._destination_totals(destination)))})"
            "</li>"
            for destination in destinations
        )
        return f"""
<h2>Clientes / destinos</h2>
<p><strong>{count} clientes / destinos</strong></p>
<ul class="summary-list">{items}</ul>
"""

    def _legacy_summary(self, order: LoadOrder) -> str:
        if order.client is None or order.delivery_address is None:
            return "<h2>Clientes / destinos</h2><p>Sin cliente/destino declarado.</p>"
        return f"""
<h2>Clientes / destinos</h2>
<p><strong>1 cliente / destino</strong></p>
<ul class="summary-list">
<li>{escape(order.client.name)} - {escape(order.delivery_address.address)}, {escape(order.delivery_address.city)}</li>
</ul>
"""

    def _legacy_destination_meta(self, order: LoadOrder) -> str:
        if order.client is None or order.delivery_address is None:
            return ""
        return (
            "<div class=\"meta-grid\">"
            f"{self._box('Cliente', order.client.name)}"
            f"{self._box('Destino', f'{order.delivery_address.address}, {order.delivery_address.city}')}"
            f"{self._box('Provincia', order.delivery_address.province)}"
            "</div>"
        )

    def _destination_groups(self, order: LoadOrder):
        return list(order.destinations.order_by())

    def _destination_observations(self, destination) -> str:
        if not destination.observations:
            return ""
        return f"<div class=\"observations\">{escape(destination.observations)}</div>"

    def _destination_totals(self, destination) -> dict[str, float]:
        totals: dict[str, float] = defaultdict(float)
        for item in destination.products:
            totals[item.unit] += item.quantity
        return dict(totals)

    def _order_totals(self, order: LoadOrder) -> dict[str, float]:
        totals: dict[str, float] = defaultdict(float)
        for item in order.products:
            totals[item.unit] += item.quantity
        return dict(totals)

    def _total_text(self, totals: dict[str, float]) -> str:
        if not totals:
            return "Sin cantidades"
        return " / ".join(f"{quantity:g} {escape(unit)}" for unit, quantity in sorted(totals.items()))

    def _box(self, label: str, value: str) -> str:
        return (
            "<div class=\"box\">"
            f"<span class=\"label\">{escape(label)}</span>"
            f"<span class=\"value\">{escape(value or '-')}</span>"
            "</div>"
        )
