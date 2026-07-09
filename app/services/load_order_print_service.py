from collections import defaultdict
from datetime import datetime
from html import escape
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.models.load_orders import LoadOrder, LoadOrderDestination, LoadOrderProduct
from app.models.masters import Client
from app.services.audit_service import AuditService


class LoadOrderPrintService:
    def __init__(self, current_user: str, audit_service: AuditService | None = None):
        self.current_user = current_user
        self.audit_service = audit_service or AuditService()
        self.styles = _styles()

    def export_pdf(self, order: LoadOrder, output_dir: str | Path) -> Path:
        path = Path(output_dir)
        path.mkdir(parents=True, exist_ok=True)
        target = path / f"orden_carga_{order.order_number}.pdf"
        self._build_pdf(order, target)
        self.audit_service.record(
            user=self.current_user,
            module="Ordenes de carga",
            action="imprimir",
            record_ref=f"LoadOrder:{order.id}",
            new_value={"file_path": str(target), "order_number": order.order_number},
        )
        return target

    def export_order(self, order: LoadOrder, output_dir: str | Path, *, reprint: bool = False) -> Path:
        return self.export_pdf(order, output_dir)

    def export_summary(self, order: LoadOrder, output_dir: str | Path, *, reprint: bool = False) -> Path:
        return self.export_pdf(order, output_dir)

    def export_combined(self, order: LoadOrder, output_dir: str | Path, *, reprint: bool = False) -> Path:
        return self.export_pdf(order, output_dir)

    def render_order(self, order: LoadOrder, *, reprint: bool = False) -> str:
        return self._legacy_html(order)

    def render_summary(self, order: LoadOrder, *, reprint: bool = False) -> str:
        return self._legacy_html(order)

    def _build_pdf(self, order: LoadOrder, target: Path) -> None:
        doc = SimpleDocTemplate(
            str(target),
            pagesize=A4,
            rightMargin=14 * mm,
            leftMargin=14 * mm,
            topMargin=12 * mm,
            bottomMargin=14 * mm,
            title=f"Orden de carga {order.order_number}",
        )
        story = [
            Paragraph("GRAEF HERMANOS S.R.L.", self.styles["company"]),
            Spacer(1, 5 * mm),
            Paragraph("ORDEN DE DESPACHO DE FECULA DE MANDIOCA", self.styles["title"]),
            self._header_table(order),
            Spacer(1, 5 * mm),
        ]
        if order.status == LoadOrder.STATUS_ANNULLED:
            story.extend([Paragraph("ANULADA", self.styles["annulled"]), Spacer(1, 3 * mm)])
        story.extend(
            [
                Paragraph("1. DATOS DEL CLIENTE", self.styles["section"]),
                self._client_table(order),
                Spacer(1, 8 * mm),
                Paragraph("2. DETALLE DEL PRODUCTO A DESPACHAR", self.styles["section"]),
                self._detail_table(order),
                Spacer(1, 9 * mm),
                Paragraph("3. DATOS DEL TRANSPORTE", self.styles["section"]),
                self._transport_table(order),
                Spacer(1, 13 * mm),
                self._observations(order),
                Spacer(1, 15 * mm),
                Paragraph("Firma del encargado de carga: __________________________", self.styles["normal"]),
            ]
        )
        doc.build(story)

    def _header_table(self, order: LoadOrder) -> Table:
        data = [[f"Nro.: {order.order_number:04d}", f"Fecha: {order.date:%d/%m/%Y}", f"Estado: {order.status}"]]
        table = Table(data, colWidths=[45 * mm, 58 * mm, 67 * mm])
        table.setStyle(
            TableStyle(
                [
                    ("FONTNAME", (0, 0), (-1, -1), "Helvetica-Bold"),
                    ("FONTSIZE", (0, 0), (-1, -1), 10),
                    ("ALIGN", (0, 0), (-1, -1), "LEFT"),
                    ("TOPPADDING", (0, 0), (-1, -1), 2),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
                ]
            )
        )
        return table

    def _client_table(self, order: LoadOrder) -> Table:
        client = self._client_label(order)
        destination = self._destination_label(order)
        data = [[self._p("DATOS DEL CLIENTE:"), self._p(client)], [self._p("DESTINO:"), self._p(destination)]]
        table = Table(data, colWidths=[42 * mm, 128 * mm])
        table.setStyle(
            TableStyle(
                [
                    ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
                    ("FONTSIZE", (0, 0), (-1, -1), 9),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ]
            )
        )
        return table

    def _detail_table(self, order: LoadOrder) -> Table:
        article_columns = self._article_columns(order)
        header = [
            self._p("Cliente / destino / detalle de entrega", bold=True),
            *(self._p(article, bold=True) for article in article_columns),
            self._p("Pallet", bold=True),
            self._p("Detalle", bold=True),
            self._p("Lote", bold=True),
            self._p("Elab.", bold=True),
        ]
        rows = [header]
        totals = defaultdict(float)
        for row in self._detail_rows(order):
            rows.append(
                [
                    self._p(row["destination"]),
                    *(_quantity(row["articles"].get(article, 0.0)) for article in article_columns),
                    _quantity(row["pallet"]),
                    self._p(row["detail"]),
                    "-",
                    "-",
                ]
            )
            for article in article_columns:
                totals[article] += row["articles"].get(article, 0.0)
            totals["pallet"] += row["pallet"]
        rows.append(
            [
                self._p("TOTALES", bold=True),
                *(_quantity(totals[article]) for article in article_columns),
                _quantity(totals["pallet"]),
                "",
                "",
                "",
            ]
        )
        article_width = 68 / max(len(article_columns), 1)
        table = Table(
            rows,
            colWidths=[
                42 * mm,
                *(article_width * mm for _article in article_columns),
                13 * mm,
                31 * mm,
                12 * mm,
                16 * mm,
            ],
        )
        table.setStyle(
            TableStyle(
                [
                    ("GRID", (0, 0), (-1, -1), 0.55, colors.black),
                    ("BACKGROUND", (0, 0), (-1, 0), colors.whitesmoke),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
                    ("FONTSIZE", (0, 0), (-1, -1), 7.1),
                    ("ALIGN", (1, 1), (len(article_columns) + 1, -1), "CENTER"),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("TOPPADDING", (0, 0), (-1, -1), 3),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                ]
            )
        )
        return table

    def _transport_table(self, order: LoadOrder) -> Table:
        data = [
            [self._p("Empresa de transporte:", bold=True), self._p(order.carrier.name)],
            [self._p("Dominio del vehiculo:", bold=True), self._p(order.truck.domain)],
            [self._p("Nombre del chofer:", bold=True), self._p(order.driver.name)],
            [self._p("Vehiculo limpio y apto:", bold=True), self._p("Si / No")],
        ]
        table = Table(data, colWidths=[58 * mm, 112 * mm])
        table.setStyle(
            TableStyle(
                [
                    ("GRID", (0, 0), (-1, -1), 0.55, colors.black),
                    ("FONTSIZE", (0, 0), (-1, -1), 9),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("TOPPADDING", (0, 0), (-1, -1), 4),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ]
            )
        )
        return table

    def _observations(self, order: LoadOrder) -> Paragraph:
        value = order.observations or "-"
        return Paragraph(f"<b>Observaciones:</b> {escape(value)}", self.styles["normal"])

    def _detail_rows(self, order: LoadOrder) -> list[dict[str, object]]:
        rows = []
        article_columns = self._article_columns(order)
        destinations = list(order.destinations.order_by())
        if destinations:
            for destination in destinations:
                products = list(destination.products)
                rows.append(
                    self._detail_row(order, self._row_destination(order, destination), products, article_columns)
                )
        else:
            rows.append(self._detail_row(order, self._destination_label(order), list(order.products), article_columns))
        if not rows:
            rows.append(
                {
                    "destination": self._destination_label(order),
                    "articles": {article: 0.0 for article in article_columns},
                    "pallet": self._pallet_total(order),
                    "detail": "-",
                }
            )
        return rows

    def _detail_row(
        self,
        order: LoadOrder,
        destination_label: str,
        products: list,
        article_columns: list[str],
    ) -> dict[str, object]:
        articles = {article: 0.0 for article in article_columns}
        detail_items = []
        for item in products:
            product_name = item.product.name
            if product_name in articles:
                articles[product_name] += item.quantity
            else:
                detail_items.append(self._product_detail(item))
        if not detail_items:
            detail_items = [self._product_detail(item) for item in products]
        return {
            "destination": destination_label,
            "articles": articles,
            "pallet": self._pallet_share_for_products(order, products),
            "detail": " / ".join(detail_items) if detail_items else "-",
        }

    def _pallet_share_for_products(self, order: LoadOrder, products: list) -> float:
        total_quantity = sum(product.quantity for product in order.products)
        if not total_quantity:
            return 0.0
        row_quantity = sum(product.quantity for product in products)
        return round(self._pallet_total(order) * (row_quantity / total_quantity), 2)

    def _article_columns(self, order: LoadOrder) -> list[str]:
        articles = []
        for item in order.products:
            product_name = item.product.name
            if product_name not in articles:
                articles.append(product_name)
            if len(articles) == 4:
                break
        return articles or ["Articulo"]

    def _product_detail(self, item) -> str:
        detail = f"{item.product.name} - {_quantity(item.quantity)} {item.unit}"
        if item.observations:
            detail = f"{detail} - {item.observations}"
        return detail

    def _pallet_total(self, order: LoadOrder) -> float:
        return float(sum(pallet.quantity for pallet in order.pallets))

    def _row_destination(self, order: LoadOrder, destination) -> str:
        if destination is None:
            if order.client is None or order.delivery_address is None:
                return "-"
            return f"{order.client.name} - {order.delivery_address.address} - {order.delivery_address.city}"
        return (
            f"{destination.client.name} - {destination.delivery_address.address} - "
            f"{destination.delivery_address.city}"
        )

    def _client_label(self, order: LoadOrder) -> str:
        destinations = list(order.destinations)
        if len(destinations) > 1:
            return "VARIOS"
        if len(destinations) == 1:
            return destinations[0].client.name
        if order.client is not None:
            return order.client.name
        return "-"

    def _destination_label(self, order: LoadOrder) -> str:
        destinations = list(order.destinations)
        labels = []
        if destinations:
            for destination in destinations:
                address = destination.delivery_address
                labels.append(f"{address.province} - {address.city} - {address.address}")
        elif order.delivery_address is not None:
            address = order.delivery_address
            labels.append(f"{address.province} - {address.city} - {address.address}")
        return " / ".join(labels) if labels else "-"

    def _p(self, value: object, *, bold: bool = False) -> Paragraph:
        style = self.styles["cell_bold"] if bold else self.styles["cell"]
        return Paragraph(escape(str(value or "-")), style)

    def export_budget(self, order: LoadOrder, client: Client, output_dir: str | Path) -> Path:
        path = Path(output_dir)
        path.mkdir(parents=True, exist_ok=True)
        safe_name = client.name.replace(" ", "_").replace("/", "-")
        target = path / f"presupuesto_{safe_name}_{order.order_number}.pdf"
        doc = SimpleDocTemplate(
            str(target),
            pagesize=A4,
            rightMargin=14 * mm,
            leftMargin=14 * mm,
            topMargin=12 * mm,
            bottomMargin=14 * mm,
            title=f"Presupuesto {client.name} - OC {order.order_number}",
        )
        story = [
            Paragraph("GRAEF HERMANOS S.R.L.", self.styles["company"]),
            Spacer(1, 5 * mm),
            Paragraph(f"PRESUPUESTO - Orden de carga Nro. {order.order_number:04d}", self.styles["title"]),
            self._budget_header(order, client),
            Spacer(1, 5 * mm),
            Paragraph(f"Cliente: {client.name}", self.styles["section"]),
            Spacer(1, 3 * mm),
            self._budget_detail_table(order, client),
            Spacer(1, 8 * mm),
            self._budget_totals(order, client),
            Spacer(1, 15 * mm),
            Paragraph("Firma del cliente: __________________________", self.styles["normal"]),
        ]
        doc.build(story)
        self.audit_service.record(
            user=self.current_user,
            module="Ordenes de carga",
            action="presupuesto",
            record_ref=f"LoadOrder:{order.id}",
            new_value={"file_path": str(target), "client": client.name, "order_number": order.order_number},
        )
        return target

    def export_budgets(self, order: LoadOrder, output_dir: str | Path) -> list[Path]:
        paths = []
        clients_seen = set()
        for destination in order.destinations:
            client = destination.client
            if client.id not in clients_seen:
                clients_seen.add(client.id)
                paths.append(self.export_budget(order, client, output_dir))
        return paths

    def export_combined_budget(self, order: LoadOrder, output_dir: str | Path) -> Path:
        path = Path(output_dir)
        path.mkdir(parents=True, exist_ok=True)
        generated_at = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        target = path / f"presupuestos_orden_{order.order_number}_{generated_at}.pdf"
        doc = SimpleDocTemplate(
            str(target),
            pagesize=A4,
            rightMargin=14 * mm,
            leftMargin=14 * mm,
            topMargin=12 * mm,
            bottomMargin=14 * mm,
            title=f"Presupuestos OC {order.order_number}",
        )
        story = []
        destinations = list(order.destinations.order_by(LoadOrderDestination.sequence))
        for index, destination in enumerate(destinations):
            if index:
                story.append(PageBreak())
            story.extend(self._budget_story(order, destination))
        doc.build(story)
        self.audit_service.record(
            user=self.current_user,
            module="Ordenes de carga",
            action="presupuesto",
            record_ref=f"LoadOrder:{order.id}",
            new_value={
                "file_path": str(target),
                "destinations": [destination.id for destination in destinations],
                "order_number": order.order_number,
            },
        )
        return target

    def _budget_story(self, order: LoadOrder, destination: LoadOrderDestination) -> list:
        client = destination.client
        address = destination.delivery_address
        return [
            Paragraph("GRAEF HERMANOS S.R.L.", self.styles["company"]),
            Spacer(1, 5 * mm),
            Paragraph(f"PRESUPUESTO - Orden de carga Nro. {order.order_number:04d}", self.styles["title"]),
            self._budget_header(order, client, destination),
            Spacer(1, 5 * mm),
            Paragraph(f"Cliente: {client.name}", self.styles["section"]),
            Paragraph(f"Destino: {address.province} - {address.city} - {address.address}", self.styles["normal"]),
            Spacer(1, 3 * mm),
            self._budget_detail_table(order, client, destination),
            Spacer(1, 8 * mm),
            self._budget_totals(order, client, destination),
            Spacer(1, 15 * mm),
            Paragraph("Firma del cliente: __________________________", self.styles["normal"]),
        ]

    def _budget_header(
        self,
        order: LoadOrder,
        client: Client,
        destination: LoadOrderDestination | None = None,
    ) -> Table:
        data = [[f"Fecha: {order.date:%d/%m/%Y}", f"Estado: Pendiente"]]
        table = Table(data, colWidths=[85 * mm, 85 * mm])
        table.setStyle(
            TableStyle([
                ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("ALIGN", (0, 0), (-1, -1), "LEFT"),
                ("TOPPADDING", (0, 0), (-1, -1), 2),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
            ])
        )
        return table

    def _budget_detail_table(
        self,
        order: LoadOrder,
        client: Client,
        destination: LoadOrderDestination | None = None,
    ) -> Table:
        products = (
            LoadOrderProduct.select()
            .join(LoadOrderDestination)
            .where(
                (LoadOrderProduct.order == order)
                & (LoadOrderDestination.client == client)
            )
        )
        if destination is not None:
            products = products.where(LoadOrderProduct.destination == destination)
        header = [
            self._p("Cant.", bold=True),
            self._p("Producto", bold=True),
            self._p("P. Unit.", bold=True),
            self._p("Dto %", bold=True),
            self._p("Neto Subt.", bold=True),
            self._p("Dto $", bold=True),
            self._p("Neto Grav.", bold=True),
            self._p("IVA %", bold=True),
            self._p("IVA $", bold=True),
            self._p("Total", bold=True),
        ]
        rows = [header]
        for prod in products:
            rows.append([
                _quantity(prod.quantity),
                self._p(prod.product.name),
                self._p(f"$ {prod.precio_neto_unitario:,.2f}"),
                self._p(f"{prod.descuento_porcentaje:g}%"),
                self._p(f"$ {prod.neto_subtotal:,.2f}"),
                self._p(f"$ {prod.descuento_importe:,.2f}"),
                self._p(f"$ {prod.neto_gravado:,.2f}"),
                self._p(f"{prod.iva_porcentaje:g}%"),
                self._p(f"$ {prod.iva_importe:,.2f}"),
                self._p(f"$ {prod.total:,.2f}"),
            ])
        col_widths = [14 * mm, 34 * mm, 18 * mm, 12 * mm, 18 * mm, 16 * mm, 18 * mm, 12 * mm, 16 * mm, 18 * mm]
        table = Table(rows, colWidths=col_widths, repeatRows=1)
        table.setStyle(TableStyle([
            ("GRID", (0, 0), (-1, -1), 0.55, colors.black),
            ("BACKGROUND", (0, 0), (-1, 0), colors.whitesmoke),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 7),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ]))
        return table

    def _budget_totals(
        self,
        order: LoadOrder,
        client: Client,
        destination: LoadOrderDestination | None = None,
    ) -> Table:
        products = (
            LoadOrderProduct.select()
            .join(LoadOrderDestination)
            .where(
                (LoadOrderProduct.order == order)
                & (LoadOrderDestination.client == client)
            )
        )
        if destination is not None:
            products = products.where(LoadOrderProduct.destination == destination)
        total_neto_subtotal = sum(p.neto_subtotal for p in products)
        total_descuento = sum(p.descuento_importe for p in products)
        total_neto_gravado = sum(p.neto_gravado for p in products)
        total_iva = sum(p.iva_importe for p in products)
        total_general = sum(p.total for p in products)
        data = [
            [self._p("Neto subtotal:", bold=True), self._p(f"$ {total_neto_subtotal:,.2f}")],
            [self._p("Descuento total:", bold=True), self._p(f"$ {total_descuento:,.2f}")],
            [self._p("Neto gravado:", bold=True), self._p(f"$ {total_neto_gravado:,.2f}")],
            [self._p("IVA total:", bold=True), self._p(f"$ {total_iva:,.2f}")],
            [self._p("TOTAL PRESUPUESTO:", bold=True), self._p(f"$ {total_general:,.2f}")],
        ]
        table = Table(data, colWidths=[55 * mm, 55 * mm])
        table.setStyle(TableStyle([
            ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("ALIGN", (1, 0), (1, -1), "RIGHT"),
            ("LINEABOVE", (0, -1), (-1, -1), 1.5, colors.black),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        return table

    def _legacy_html(self, order: LoadOrder) -> str:
        return (
            "<!doctype html><html lang=\"es\"><head><meta charset=\"utf-8\">"
            f"<title>Orden de carga OC-{order.order_number:06d}</title></head>"
            f"<body><h1>Orden de carga Nro. {order.order_number}</h1>"
            "<p>La impresion operativa vigente se genera en PDF.</p></body></html>"
        )


def _styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "company": ParagraphStyle(
            "company",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=11,
            alignment=TA_CENTER,
            leading=13,
        ),
        "title": ParagraphStyle(
            "title",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=10.5,
            alignment=TA_LEFT,
            leading=13,
        ),
        "section": ParagraphStyle(
            "section",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=10,
            alignment=TA_LEFT,
            leading=12,
            spaceAfter=4,
        ),
        "annulled": ParagraphStyle(
            "annulled",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=30,
            textColor=colors.HexColor("#a00000"),
            alignment=TA_CENTER,
            leading=34,
        ),
        "normal": ParagraphStyle("normal", parent=base["Normal"], fontSize=9, leading=12),
        "cell": ParagraphStyle("cell", parent=base["Normal"], fontSize=6.8, leading=8),
        "cell_bold": ParagraphStyle(
            "cell_bold", parent=base["Normal"], fontName="Helvetica-Bold", fontSize=6.8, leading=8, alignment=TA_CENTER
        ),
        "right": ParagraphStyle("right", parent=base["Normal"], fontSize=8, alignment=TA_RIGHT),
    }


def _quantity(value: float) -> str:
    if not value:
        return "-"
    if float(value).is_integer():
        return str(int(value))
    return f"{value:g}"
