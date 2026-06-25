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
<title>Orden de carga</title>
<style>
@page {{ size: A4; margin: 16mm; }}
body {{ font-family: Arial, sans-serif; color: #202124; font-size: 12px; }}
h1 {{ font-size: 20px; margin: 0 0 10px; }}
h2 {{ font-size: 16px; margin: 18px 0 8px; }}
h3 {{ font-size: 14px; margin: 14px 0 4px; }}
table {{ width: 100%; border-collapse: collapse; margin-top: 8px; }}
th, td {{ border: 1px solid #9aa0a6; padding: 6px; text-align: left; }}
.meta {{ display: grid; grid-template-columns: 1fr 1fr; gap: 6px 18px; }}
.label {{ font-weight: bold; }}
.page-break {{ page-break-before: always; }}
</style>
</head>
<body>{body}</body>
</html>"""

    def _order_body(self, order: LoadOrder, *, reprint: bool = False) -> str:
        flag = "<p><strong>Reimpresion</strong></p>" if reprint else ""
        return f"""
<h1>Orden de carga Nro. {order.order_number}</h1>
{flag}
{self._meta(order)}
{self._destinations(order)}
{self._pallets(order)}
<h2>Observaciones</h2>
<p>{escape(order.observations or "")}</p>
"""

    def _summary_body(self, order: LoadOrder, *, reprint: bool = False) -> str:
        flag = "<p><strong>Reimpresion</strong></p>" if reprint else ""
        return f"""
<h1>Orden de carga Nro. {order.order_number}</h1>
<h2>Hoja resumen / sobre de carga</h2>
{flag}
{self._meta(order)}
{self._destinations(order)}
{self._pallets(order)}
<h2>Observaciones</h2>
<p>{escape(order.observations or "")}</p>
"""

    def _meta(self, order: LoadOrder) -> str:
        return f"""
<section class="meta">
<h2>Cabecera logística</h2>
<div><span class="label">Fecha:</span> {order.date:%d/%m/%Y}</div>
<div><span class="label">Estado:</span> {escape(order.status)}</div>
<div><span class="label">Transportista:</span> {escape(order.carrier.name)}</div>
<div><span class="label">Chofer:</span> {escape(order.driver.name)}</div>
<div><span class="label">Camion:</span> {escape(order.truck.domain)}</div>
</section>
"""

    def _destinations(self, order: LoadOrder) -> str:
        sections = []
        destinations = list(order.destinations.order_by())
        if not destinations:
            return self._legacy_products(order)
        for destination in destinations:
            rows = "".join(
                f"<tr><td>{escape(item.product.name)}</td><td>{item.quantity:g}</td>"
                f"<td>{escape(item.unit)}</td><td>{escape(item.observations or '')}</td></tr>"
                for item in destination.products
            )
            title = (
                f"{escape(destination.client.name)} - "
                f"{escape(destination.delivery_address.address)}, {escape(destination.delivery_address.city)}"
            )
            sections.append(
                f"<h3>{title}</h3>"
                "<table><tr><th>Producto</th><th>Cantidad</th><th>Unidad</th><th>Obs.</th></tr>"
                f"{rows}</table>"
            )
        return f"<h2>Detalle por cliente / destino</h2>{''.join(sections)}"

    def _legacy_products(self, order: LoadOrder) -> str:
        rows = "".join(
            f"<tr><td>{escape(item.product.name)}</td><td>{item.quantity:g}</td>"
            f"<td>{escape(item.unit)}</td><td>{escape(item.observations or '')}</td></tr>"
            for item in order.products
        )
        return (
            "<h2>Detalle por cliente / destino</h2>"
            "<table><tr><th>Producto</th><th>Cantidad</th><th>Unidad</th><th>Obs.</th></tr>"
            f"{rows}</table>"
        )

    def _pallets(self, order: LoadOrder) -> str:
        rows = "".join(
            f"<tr><td>{escape(item.pallet_type.type)}</td><td>{escape(item.measure)}</td>"
            f"<td>{item.weight:g}</td><td>{item.quantity}</td><td>{escape(item.observations or '')}</td></tr>"
            for item in order.pallets
        )
        return (
            "<h2>Pallets</h2><table><tr><th>Tipo</th><th>Medida</th><th>Peso</th>"
            f"<th>Cantidad</th><th>Obs.</th></tr>{rows}</table>"
        )
