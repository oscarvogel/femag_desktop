from __future__ import annotations

from html import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, Table, TableStyle

from app.services.consolidated_load_order_print_service import (
    ConsolidatedLoadOrderPrintService as BaseConsolidatedLoadOrderPrintService,
)
from app.services.load_order_print_service import _quantity


class ConsolidatedLoadOrderPrintService(BaseConsolidatedLoadOrderPrintService):
    """Impresión consolidada preservando el rowspan de pallets compartidos."""

    def _center_p(self, value: object) -> Paragraph:
        style = ParagraphStyle(
            "load_order_emphasized_quantity",
            parent=self.styles["cell"],
            alignment=TA_CENTER,
            fontName="Helvetica-Bold",
            fontSize=9,
            leading=10.5,
        )
        return Paragraph(escape(str(value or "-")), style)

    def _pallet_signature(self, block: dict[str, object], consolidated_row: dict[str, object]) -> tuple[int, ...]:
        """Devuelve los pallets físicos asociados a la fila consolidada.

        La unidad no forma parte de la identidad operativa de la asignación. Puede venir
        vacía en datos históricos o diferir en snapshots, por lo que usarla para reconstruir
        la relación producto/pallet puede hacer desaparecer un conteo válido.
        """
        target_product = str(consolidated_row.get("product", ""))
        target_lote = self._optional_operational_value(consolidated_row.get("lote"))
        target_elab = self._optional_operational_value(consolidated_row.get("elab"))
        sequences: list[int] = []

        for pallet_block in block.get("pallet_blocks", []):
            for row in pallet_block.get("rows", []):
                if (
                    str(row.get("product", "")) == target_product
                    and self._optional_operational_value(row.get("lote")) == target_lote
                    and self._optional_operational_value(row.get("elab")) == target_elab
                ):
                    sequences.append(int(pallet_block["label"]))
                    break
        return tuple(sorted(set(sequences)))

    def _pallet_count_spans(
        self,
        block: dict[str, object],
        consolidated: list[dict[str, object]],
        *,
        first_table_row: int,
        pallet_column: int,
    ) -> tuple[list[tuple], list[str]]:
        signatures = [self._pallet_signature(block, row) for row in consolidated]
        display_values = [
            str(len(signature)) if signature else (
                str(row.get("pallet_count")) if row.get("pallet_count") else "-"
            )
            for signature, row in zip(signatures, consolidated)
        ]
        spans: list[tuple] = []

        start = 0
        while start < len(signatures):
            signature = signatures[start]
            end = start
            if signature:
                while end + 1 < len(signatures) and signatures[end + 1] == signature:
                    end += 1
            if signature and end > start:
                spans.append(
                    (
                        "SPAN",
                        (pallet_column, first_table_row + start),
                        (pallet_column, first_table_row + end),
                    )
                )
                for index in range(start + 1, end + 1):
                    display_values[index] = ""
            start = end + 1

        return spans, display_values

    def _destination_table(self, block: dict[str, object]) -> Table:
        header = [
            self._p("Producto / detalle", bold=True),
            self._p("Cantidad total", bold=True),
            self._p("Cant. pallets", bold=True),
            self._p("Lote", bold=True),
            self._p("Elab.", bold=True),
        ]
        rows = [header]
        rows.append(
            [
                Paragraph(escape(str(block["destination"] or "-")), self.styles["dest_banner"]),
                "",
                "",
                "",
                "",
            ]
        )

        consolidated = block.get("consolidated_rows") or self._consolidate_rows(block)
        span_commands: list[tuple] = []
        if consolidated:
            span_commands, pallet_values = self._pallet_count_spans(
                block,
                consolidated,
                first_table_row=2,
                pallet_column=2,
            )
            for index, row in enumerate(consolidated):
                rows.append(
                    [
                        self._p(row["product"]),
                        self._center_p(_quantity(row["quantity"])),
                        self._center_p(pallet_values[index]) if pallet_values[index] else "",
                        self._p(row["lote"]) if row["lote"] else "",
                        self._p(row["elab"]) if row["elab"] else "",
                    ]
                )
        else:
            rows.append([self._p("-"), self._center_p("-"), self._center_p("-"), self._p("-"), self._p("-")])

        table = Table(rows, colWidths=[82 * mm, 30 * mm, 26 * mm, 21 * mm, 21 * mm], repeatRows=2)
        table.setStyle(
            TableStyle(
                [
                    ("GRID", (0, 0), (-1, -1), 0.55, colors.black),
                    ("BACKGROUND", (0, 0), (-1, 0), colors.whitesmoke),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("FONTSIZE", (0, 0), (-1, -1), 7.1),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("TOPPADDING", (0, 0), (-1, -1), 3),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                    ("ALIGN", (1, 0), (2, -1), "CENTER"),
                    ("SPAN", (0, 1), (4, 1)),
                    ("BACKGROUND", (0, 1), (4, 1), colors.whitesmoke),
                    *span_commands,
                ]
            )
        )
        return table

    def _preparation_destination_table(self, block: dict[str, object]) -> Table:
        header = [
            self._p("Producto / detalle", bold=True),
            self._p("Unidad", bold=True),
            self._p("Cantidad total", bold=True),
            self._p("Cant. pallets", bold=True),
            self._p("Lote", bold=True),
            self._p("Elab.", bold=True),
        ]
        rows = [header]
        rows.append(
            [
                Paragraph(escape(str(block["destination"] or "-")), self.styles["dest_banner"]),
                "",
                "",
                "",
                "",
                "",
            ]
        )

        consolidated = block.get("consolidated_rows") or self._consolidate_rows(block)
        span_commands: list[tuple] = []
        if consolidated:
            span_commands, pallet_values = self._pallet_count_spans(
                block,
                consolidated,
                first_table_row=2,
                pallet_column=3,
            )
            for index, row in enumerate(consolidated):
                rows.append(
                    [
                        self._p(row["product"]),
                        self._p(row.get("unit") or "-"),
                        self._center_p(_quantity(row["quantity"])),
                        self._center_p(pallet_values[index]) if pallet_values[index] else "",
                        self._p(row["lote"]) if row["lote"] else "",
                        self._p(row["elab"]) if row["elab"] else "",
                    ]
                )
        else:
            rows.append([self._p("-"), self._p("-"), self._center_p("-"), self._center_p("-"), self._p("-"), self._p("-")])

        table = Table(rows, colWidths=[60 * mm, 20 * mm, 27 * mm, 23 * mm, 25 * mm, 25 * mm], repeatRows=2)
        table.setStyle(
            TableStyle(
                [
                    ("GRID", (0, 0), (-1, -1), 0.55, colors.black),
                    ("BACKGROUND", (0, 0), (-1, 0), colors.whitesmoke),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("FONTSIZE", (0, 0), (-1, -1), 6.8),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("TOPPADDING", (0, 0), (-1, -1), 2.5),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
                    ("ALIGN", (1, 0), (3, -1), "CENTER"),
                    ("SPAN", (0, 1), (5, 1)),
                    ("BACKGROUND", (0, 1), (5, 1), colors.whitesmoke),
                    *span_commands,
                ]
            )
        )
        return table
