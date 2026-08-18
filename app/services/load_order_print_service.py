from collections import defaultdict
from datetime import datetime
from html import escape
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.models.load_orders import (
    LoadOrder,
    LoadOrderDestination,
    LoadOrderLooseAllocation,
    LoadOrderPallet,
    LoadOrderPalletAllocation,
    LoadOrderProduct,
)
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

    def export_reprint(
        self,
        order: LoadOrder,
        output_dir: str | Path,
        *,
        copy_number: int,
        reprinted_at: datetime,
    ) -> Path:
        path = Path(output_dir)
        path.mkdir(parents=True, exist_ok=True)
        target = path / f"orden_carga_{order.order_number}_reimpresion_{copy_number}.pdf"
        self._build_pdf(
            order,
            target,
            reprint_copy=copy_number,
            reprinted_at=reprinted_at,
        )
        self.audit_service.record(
            user=self.current_user,
            module="Ordenes de carga",
            action="reimprimir",
            record_ref=f"LoadOrder:{order.id}",
            new_value={
                "file_path": str(target),
                "order_number": order.order_number,
                "copy_number": copy_number,
                "reprinted_at": reprinted_at.isoformat(timespec="seconds"),
            },
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

    def _build_pdf(
        self,
        order: LoadOrder,
        target: Path,
        *,
        reprint_copy: int | None = None,
        reprinted_at: datetime | None = None,
    ) -> None:
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
            Paragraph("ORDEN DE DESPACHO DE FECULA DE MANDIOCA", self.styles["title"]),
            self._header_table(order),
            Spacer(1, 5 * mm),
        ]
        if reprint_copy is not None and reprinted_at is not None:
            story.extend(
                [
                    Paragraph(
                        f"REIMPRESIÓN - copia {reprint_copy} - {reprinted_at:%d/%m/%Y %H:%M}",
                        self.styles["reprint"],
                    ),
                    Spacer(1, 3 * mm),
                ]
            )
        if order.status == LoadOrder.STATUS_ANNULLED:
            story.extend([Paragraph("ANULADA", self.styles["annulled"]), Spacer(1, 3 * mm)])
        story.extend(
            [
                Paragraph("1. DATOS DEL CLIENTE", self.styles["section"]),
                self._client_table(order),
                Spacer(1, 8 * mm),
                Paragraph("2. DETALLE DEL PRODUCTO A DESPACHAR", self.styles["section"]),
                *self._detail_flowables(order),
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

    def _detail_flowables(self, order: LoadOrder) -> list:
        blocks = self._detail_blocks(order)
        flowables = [KeepTogether(self._destination_table(block)) for block in blocks]
        flowables.append(Spacer(1, 4 * mm))
        flowables.append(self._totals_table(order, blocks))
        return flowables

    def _detail_blocks(self, order: LoadOrder) -> list[dict[str, object]]:
        destinations = list(order.destinations.order_by(LoadOrderDestination.sequence))
        if not destinations:
            return [self._legacy_destination_block(order)]
        return [self._destination_detail_block(order, destination) for destination in destinations]

    def _destination_detail_block(self, order: LoadOrder, destination) -> dict[str, object]:
        requested = self._requested_by_destination_product(order)
        assigned = defaultdict(float)
        pallet_blocks = []
        for pallet, allocations in self._pallet_allocations_by_destination(destination):
            rows = []
            for allocation in allocations:
                lote, elab = self._lote_elab(requested, destination, allocation.product)
                rows.append(self._allocation_row(allocation, lote, elab))
                assigned[(destination.id, allocation.product_id)] += float(allocation.quantity)
            pallet_blocks.append({"label": str(pallet.sequence), "rows": rows})
        loose_block = None
        loose_rows = []
        for allocation in destination.loose_allocations:
            lote, elab = self._lote_elab(requested, destination, allocation.product)
            loose_rows.append(self._allocation_row(allocation, lote, elab))
            assigned[(destination.id, allocation.product_id)] += float(allocation.quantity)
        if loose_rows:
            loose_block = {"label": "SUELTO", "rows": loose_rows}
        unassigned_block = None
        unassigned_rows = []
        for product_row in destination.products.order_by(LoadOrderProduct.id):
            key = (destination.id, product_row.product_id)
            remaining = float(product_row.quantity) - assigned.get(key, 0.0)
            if remaining > 0:
                unassigned_rows.append(
                    {
                        "quantity": remaining,
                        "product": product_row.product.name,
                        "lote": product_row.lote or "-",
                        "elab": self._elab_text(product_row.fecha_elaboracion),
                    }
                )
        if unassigned_rows:
            unassigned_block = {"label": "-", "rows": unassigned_rows}
        return {
            "destination": self._row_destination(order, destination),
            "pallet_blocks": pallet_blocks,
            "loose_block": loose_block,
            "unassigned_block": unassigned_block,
        }

    def _legacy_destination_block(self, order: LoadOrder) -> dict[str, object]:
        rows = []
        for product_row in order.products.order_by(LoadOrderProduct.id):
            rows.append(
                {
                    "quantity": float(product_row.quantity),
                    "product": product_row.product.name,
                    "lote": product_row.lote or "-",
                    "elab": self._elab_text(product_row.fecha_elaboracion),
                }
            )
        return {
            "destination": self._row_destination(order, None),
            "pallet_blocks": [],
            "loose_block": None,
            "unassigned_block": {"label": "-", "rows": rows} if rows else None,
        }

    @staticmethod
    def _allocation_row(allocation, lote: str, elab: str) -> dict[str, object]:
        return {
            "quantity": float(allocation.quantity),
            "product": allocation.product.name,
            "lote": lote,
            "elab": elab,
        }

    def _pallet_allocations_by_destination(self, destination) -> list:
        allocations = (
            LoadOrderPalletAllocation.select()
            .join(LoadOrderPallet)
            .where(LoadOrderPalletAllocation.destination == destination)
            .order_by(LoadOrderPallet.sequence, LoadOrderPalletAllocation.id)
        )
        grouped = defaultdict(list)
        for allocation in allocations:
            grouped[allocation.pallet].append(allocation)
        return list(grouped.items())

    def _requested_by_destination_product(self, order: LoadOrder) -> dict:
        return {
            (product.destination_id, product.product_id): product
            for product in order.products
            if product.destination_id is not None
        }

    def _lote_elab(self, requested: dict, destination, product) -> tuple[str, str]:
        product_row = requested.get((destination.id, product.id))
        if product_row is None:
            return "-", "-"
        return product_row.lote or "-", self._elab_text(product_row.fecha_elaboracion)

    @staticmethod
    def _elab_text(value) -> str:
        return "-" if value is None else f"{value:%d/%m/%y}"

    def _destination_table(self, block: dict[str, object]) -> Table:
        header = [
            self._p("Cliente / destino", bold=True),
            self._p("Cant.", bold=True),
            self._p("Pallet", bold=True),
            self._p("Detalle", bold=True),
            self._p("Lote", bold=True),
            self._p("Elab.", bold=True),
        ]
        rows = [header]
        rows.append([Paragraph(escape(block["destination"] or "-"), self.styles["dest_banner"]), "", "", "", "", ""])
        row_index = 2
        spans = []
        has_rows = False
        sub_blocks = [
            *block["pallet_blocks"],
            *([block["loose_block"]] if block["loose_block"] else []),
            *([block["unassigned_block"]] if block["unassigned_block"] else []),
        ]
        for sub_block in sub_blocks:
            if not sub_block["rows"]:
                continue
            has_rows = True
            start = row_index
            for row in sub_block["rows"]:
                rows.append(
                    [
                        "",
                        _quantity(row["quantity"]),
                        self._p(""),
                        self._p(row["product"]),
                        "",
                        "",
                    ]
                )
                row_index += 1
            rows[start][2] = self._p(str(sub_block["label"]), bold=True)
            if row_index - 1 > start:
                spans.append((2, start, 2, row_index - 1))
        if not has_rows:
            rows.append(["", self._p("-"), self._p("-"), self._p("-"), "", ""])
        table = Table(rows, colWidths=[44 * mm, 24 * mm, 16 * mm, 62 * mm, 18 * mm, 18 * mm], repeatRows=2)
        style_commands = [
            ("GRID", (0, 0), (-1, -1), 0.55, colors.black),
            ("BACKGROUND", (0, 0), (-1, 0), colors.whitesmoke),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 7.1),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ("ALIGN", (1, 0), (1, -1), "CENTER"),
            ("ALIGN", (2, 0), (2, -1), "CENTER"),
            ("SPAN", (0, 1), (5, 1)),
            ("BACKGROUND", (0, 1), (5, 1), colors.whitesmoke),
        ]
        for span in spans:
            style_commands.append(("SPAN", (span[0], span[1]), (span[2], span[3])))
        table.setStyle(TableStyle(style_commands))
        return table

    def _totals_table(self, order: LoadOrder, blocks: list[dict[str, object]]) -> Table:
        totals: dict[str, float] = {}
        order_of_products: list[str] = []
        for block in blocks:
            for sub_block in [
                *block["pallet_blocks"],
                *([block["loose_block"]] if block["loose_block"] else []),
                *([block["unassigned_block"]] if block["unassigned_block"] else []),
            ]:
                for row in sub_block["rows"]:
                    name = row["product"]
                    if name not in totals:
                        totals[name] = 0.0
                        order_of_products.append(name)
                    totals[name] += row["quantity"]
        used_pallets = self._used_pallet_total(order)
        rows = []
        for name in order_of_products:
            rows.append(["", _quantity(totals[name]), "", self._p(name), "", ""])
        rows.append(
            [
                self._p("TOTALES", bold=True),
                "",
                self._p(f"{used_pallets} pallet" + ("s" if used_pallets != 1 else ""), bold=True),
                "",
                "",
                "",
            ]
        )
        table = Table(rows, colWidths=[44 * mm, 24 * mm, 16 * mm, 62 * mm, 18 * mm, 18 * mm])
        table.setStyle(
            TableStyle(
                [
                    ("GRID", (0, 0), (-1, -1), 0.55, colors.black),
                    ("BACKGROUND", (0, 0), (-1, -1), colors.whitesmoke),
                    ("FONTNAME", (0, 0), (-1, -1), "Helvetica-Bold"),
                    ("FONTSIZE", (0, 0), (-1, -1), 7.1),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("TOPPADDING", (0, 0), (-1, -1), 3),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                    ("ALIGN", (1, 0), (1, -1), "CENTER"),
                    ("ALIGN", (2, 0), (2, -1), "CENTER"),
                ]
            )
        )
        return table

    def _transport_table(self, order: LoadOrder) -> Table:
        data = [
            [self._p("Empresa de transporte:", bold=True), self._p(order.carrier.name)],
            [self._p("Dominio del vehiculo:", bold=True), self._p(order.truck.domain)],
            [self._p("Nombre del chofer:", bold=True), self._p(order.driver.name)],
            [self._p("Dominio semi/acoplado:", bold=True), self._p(self._snapshot_trailer_domain(order))],
            [self._p("TOTAL MERCADERIA:", bold=True), self._p(self._kg_text(self._merchandise_kg_total(order)), bold=True)],
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
        return self._observations_paragraph(value)

    def _observations_paragraph(self, value: str) -> Paragraph:
        return Paragraph(f"<b>Observaciones:</b> {escape(value)}", self.styles["normal"])

    def _used_pallet_total(self, order: LoadOrder) -> int:
        return sum(1 for pallet in order.pallets if pallet.allocations.exists())

    def _merchandise_kg_total(self, order: LoadOrder):
        return sum((pallet.kilos for pallet in order.pallets), 0) + sum(
            (allocation.kilos for allocation in order.loose_allocations), 0
        )

    def _kg_text(self, value) -> str:
        whole, fraction = f"{value:.3f}".split(".")
        fraction = fraction.rstrip("0")
        localized_whole = f"{int(whole):,}".replace(",", ".")
        localized_fraction = f",{fraction}" if fraction else ""
        return f"{localized_whole}{localized_fraction} kg"

    @staticmethod
    def _snapshot_trailer_domain(order: LoadOrder) -> str:
        value = (order.trailer_domain or "").strip()
        return value or "-"

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
            Paragraph(f"PRESUPUESTO - Orden de carga Nro. {order.order_number:04d}", self.styles["title"]),
            self._budget_header(order, client),
            Spacer(1, 5 * mm),
            Paragraph(f"Cliente: {client.name}", self.styles["section"]),
            Spacer(1, 3 * mm),
            self._budget_detail_table(order, client),
            Spacer(1, 8 * mm),
            *self._budget_observations(order, client=client),
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
            Paragraph(f"PRESUPUESTO - Orden de carga Nro. {order.order_number:04d}", self.styles["title"]),
            self._budget_header(order, client, destination),
            Spacer(1, 5 * mm),
            Paragraph(f"Cliente: {client.name}", self.styles["section"]),
            Paragraph(f"Destino: {address.province} - {address.city} - {address.address}", self.styles["normal"]),
            Spacer(1, 3 * mm),
            self._budget_detail_table(order, client, destination),
            Spacer(1, 8 * mm),
            *self._budget_observations(order, destination=destination),
            self._budget_totals(order, client, destination),
            Spacer(1, 15 * mm),
            Paragraph("Firma del cliente: __________________________", self.styles["normal"]),
        ]

    def _budget_observations(
        self,
        order: LoadOrder,
        *,
        client: Client | None = None,
        destination: LoadOrderDestination | None = None,
    ) -> list:
        if destination is not None:
            descriptions = [(destination.observations or "").strip()]
        elif client is not None:
            descriptions = [
                (item.observations or "").strip()
                for item in order.destinations.order_by(LoadOrderDestination.sequence)
                if item.client_id == client.id
            ]
        else:
            descriptions = []
        descriptions = list(dict.fromkeys(value for value in descriptions if value))
        if not descriptions:
            return []
        value = " / ".join(descriptions)
        return [self._observations_paragraph(value), Spacer(1, 4 * mm)]

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
        products = list(products)
        show_vat_columns = any(product.iva_porcentaje != 0 for product in products)
        header = [
            self._p("Cant.", bold=True),
            self._p("Producto", bold=True),
            self._p("P. Unit.", bold=True),
            self._p("Dto %", bold=True),
            self._p("Neto Subt.", bold=True),
            self._p("Dto $", bold=True),
            self._p("Neto Grav.", bold=True),
        ]
        if show_vat_columns:
            header.extend([self._p("IVA %", bold=True), self._p("IVA $", bold=True)])
        header.append(self._p("Total", bold=True))
        rows = [header]
        for prod in products:
            row = [
                _quantity(prod.quantity),
                self._p(prod.product.name),
                self._p(f"$ {prod.precio_neto_unitario:,.2f}"),
                self._p(f"{prod.descuento_porcentaje:g}%"),
                self._p(f"$ {prod.neto_subtotal:,.2f}"),
                self._p(f"$ {prod.descuento_importe:,.2f}"),
                self._p(f"$ {prod.neto_gravado:,.2f}"),
            ]
            if show_vat_columns:
                row.extend([
                    self._p("-" if prod.iva_porcentaje == 0 else f"{prod.iva_porcentaje:g}%"),
                    self._p("-" if prod.iva_porcentaje == 0 else f"$ {prod.iva_importe:,.2f}"),
                ])
            row.append(self._p(f"$ {prod.total:,.2f}"))
            rows.append(row)
        if show_vat_columns:
            col_widths = [
                14 * mm, 34 * mm, 18 * mm, 12 * mm, 18 * mm,
                16 * mm, 18 * mm, 12 * mm, 16 * mm, 18 * mm,
            ]
        else:
            col_widths = [14 * mm, 46 * mm, 18 * mm, 12 * mm, 20 * mm, 18 * mm, 20 * mm, 28 * mm]
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
        ]
        if total_iva > 0:
            data.append([self._p("IVA total:", bold=True), self._p(f"$ {total_iva:,.2f}")])
        data.append([self._p("TOTAL PRESUPUESTO:", bold=True), self._p(f"$ {total_general:,.2f}")])
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
        "reprint": ParagraphStyle(
            "reprint",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=11,
            textColor=colors.HexColor("#9a3412"),
            alignment=TA_CENTER,
            leading=14,
        ),
        "normal": ParagraphStyle("normal", parent=base["Normal"], fontSize=9, leading=12),
        "cell": ParagraphStyle("cell", parent=base["Normal"], fontSize=6.8, leading=8),
        "cell_bold": ParagraphStyle(
            "cell_bold", parent=base["Normal"], fontName="Helvetica-Bold", fontSize=6.8, leading=8, alignment=TA_CENTER
        ),
        "dest_banner": ParagraphStyle(
            "dest_banner",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=8.5,
            leading=10,
        ),
        "right": ParagraphStyle("right", parent=base["Normal"], fontSize=8, alignment=TA_RIGHT),
    }


def _quantity(value: float) -> str:
    if not value:
        return "-"
    if float(value).is_integer():
        return str(int(value))
    return f"{value:g}"
