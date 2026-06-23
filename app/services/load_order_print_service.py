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
<title>Orden de despacho de fécula de mandioca</title>
<style>
@page {{ size: A4; margin: 16mm; }}
body {{ font-family: Arial, sans-serif; color: #202124; font-size: 11px; }}
h1 {{ font-size: 20px; margin: 0; text-transform: uppercase; }}
h2 {{ font-size: 14px; margin: 16px 0 8px; border-bottom: 1px solid #cbd5e1; padding-bottom: 4px; }}
table {{ width: 100%; border-collapse: collapse; margin-top: 8px; }}
th, td {{ border: 1px solid #94a3b8; padding: 5px; text-align: left; vertical-align: top; }}
th {{ background: #e2e8f0; font-weight: bold; }}
.header {{ display: flex; justify-content: space-between; align-items: flex-start; border-bottom: 2px solid #1f2937; padding-bottom: 10px; margin-bottom: 12px; }}
.company {{ font-size: 18px; font-weight: bold; }}
.meta {{ display: grid; grid-template-columns: 1fr 1fr; gap: 6px 18px; margin-bottom: 10px; }}
.label {{ font-weight: bold; }}
.totals {{ margin-top: 10px; font-weight: bold; }}
.signature {{ margin-top: 34px; display: grid; grid-template-columns: 1fr 1fr; gap: 32px; }}
.signature div {{ border-top: 1px solid #1f2937; padding-top: 6px; text-align: center; }}
.page-break {{ page-break-before: always; }}
</style>
</head>
<body>{body}</body>
</html>"""

    def _order_body(self, order: LoadOrder, *, reprint: bool = False) -> str:
        flag = "<p><strong>Reimpresión</strong></p>" if reprint else ""
        return f"""
<section class="header">
<div><div class="company">FEMAG</div><div>Gestión operativa local</div></div>
<div><h1>Orden de despacho de fécula de mandioca</h1><div>Nro. {order.order_number}</div></div>
</section>
{flag}
{self._meta(order)}
{self._dispatch_table(order)}
{self._totals(order)}
<h2>Observaciones</h2>
<p>{escape(order.observations or "")}</p>
<section class="signature"><div>Firma responsable FEMAG</div><div>Firma transporte</div></section>
"""

    def _summary_body(self, order: LoadOrder, *, reprint: bool = False) -> str:
        flag = "<p><strong>Reimpresión</strong></p>" if reprint else ""
        return f"""
<h1>Orden de carga Nro. {order.order_number}</h1>
<h2>Hoja resumen / sobre de carga</h2>
{flag}
{self._meta(order)}
{self._products(order)}
{self._pallets(order)}
<h2>Observaciones</h2>
<p>{escape(order.observations or "")}</p>
"""

    def _meta(self, order: LoadOrder) -> str:
        return f"""
<section class="meta">
<div><span class="label">Fecha:</span> {order.date:%d/%m/%Y}</div>
<div><span class="label">Estado:</span> {escape(order.status)}</div>
<div><span class="label">Cliente cabecera:</span> {escape(order.client.name)}</div>
<div><span class="label">Destino general:</span> {escape(order.delivery_address.city)} - {escape(order.delivery_address.province)}</div>
<div><span class="label">Transportista:</span> {escape(order.carrier.name)}</div>
<div><span class="label">Chofer:</span> {escape(order.driver.name)}</div>
<div><span class="label">Camión:</span> {escape(order.truck.domain)}</div>
<div><span class="label">Vehículo limpio y apto:</span> Sí</div>
</section>
"""

    def _dispatch_table(self, order: LoadOrder) -> str:
        rows = "".join(self._dispatch_row(order, item) for item in order.products)
        if not rows:
            rows = "<tr><td colspan=\"8\">No hay renglones de despacho cargados.</td></tr>"
        return (
            "<h2>Detalle de despacho</h2>"
            "<table><tr><th>Destinatario / cliente / localidad</th><th>Bolsas x 25 kg</th>"
            "<th>Bolsas x 10 kg</th><th>Pack</th><th>Pallet</th><th>Detalle</th>"
            "<th>Número de lote</th><th>Fecha de elaboración</th></tr>"
            f"{rows}</table>"
        )

    def _dispatch_row(self, order: LoadOrder, item) -> str:
        destination = f"{order.client.name} / {order.delivery_address.city}"
        unit = item.unit.lower()
        bags_25 = item.quantity if "25" in unit else ""
        bags_10 = item.quantity if "10" in unit else ""
        pack = item.quantity if "pack" in unit else ""
        detail = f"{item.product.name} - {item.quantity:g} {item.unit}"
        lot = item.observations or ""
        return (
            f"<tr><td>{escape(destination)}</td><td>{bags_25}</td><td>{bags_10}</td><td>{pack}</td>"
            f"<td>{self._pallet_quantity(order)}</td><td>{escape(detail)}</td>"
            f"<td>{escape(lot)}</td><td>{order.date:%d/%m/%Y}</td></tr>"
        )

    def _pallet_quantity(self, order: LoadOrder) -> int:
        return sum(item.quantity for item in order.pallets)

    def _totals(self, order: LoadOrder) -> str:
        total_products = sum(item.quantity for item in order.products)
        total_pallets = self._pallet_quantity(order)
        return f"<p class=\"totals\">Totales: {total_products:g} unidades declaradas - {total_pallets} pallets</p>"

    def _products(self, order: LoadOrder) -> str:
        rows = "".join(
            f"<tr><td>{escape(item.product.name)}</td><td>{item.quantity:g}</td>"
            f"<td>{escape(item.unit)}</td><td>{escape(item.observations or '')}</td></tr>"
            for item in order.products
        )
        return f"<h2>Productos</h2><table><tr><th>Producto</th><th>Cantidad</th><th>Unidad</th><th>Obs.</th></tr>{rows}</table>"

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
