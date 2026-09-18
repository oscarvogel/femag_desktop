from __future__ import annotations

from decimal import Decimal, InvalidOperation
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

    @staticmethod
    def _is_one(value: object) -> bool:
        try:
            return Decimal(str(value)) == Decimal("1")
        except (InvalidOperation, TypeError, ValueError):
            return False

    @staticmethod
    def _pallet_label(value: object) -> str:
        text = str(value or "-").strip()
        if text == "-":
            return "-"
        try:
            count = int(text)
        except ValueError:
            return text
        return f"{count} pallet" if count == 1 else f"{count} pallets"

    def _quantity_with_unit(self, quantity: object, unit: object) -> str:
        quantity_text = _quantity(quantity)
        unit_text = str(unit or "").strip().upper()
        if not unit_text:
            return quantity_text

        if self._is_one(quantity):
            label = {
                "BOLSAS": "BOLSA",
                "UNIDADES": "UNIDAD",
                "KILOS": "KILO",
            }.get(unit_text, unit_text)
        else:
            label = {
                "BOLSA": "BOLSAS",
                "UNIDAD": "UNIDADES",
                "KILO": "KILOS",
            }.get(unit_text, unit_text)

        return f"{quantity_text} {label}"

    def _pallet_signature(self, block: dict[str, object], consolidated_row: dict[str, object]) -> tuple[int, ...]:
        """Devuelve los pallets físicos asociados a la fila consolidada.

        La unidad no forma parte de la identidad operativa de la asignación. Puede venir
        vacía en datos históricos o diferir en snapshots, por lo que usarla para reconstruir
        la relación producto/pallet puede hacer desaparecer una asignación válida.
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

    def _pallet_spans(
        self,
        block: dict[str, object],
        consolidated: list[dict[str, object]],
        *,
        first_table_row: int,
        pallet_column: int,
    ) -> tuple[list[tuple], list[str]]:
        """Muestra la cantidad de pallets físicos asociados a cada fila consolidada.

        El conteo se basa en los pallets reales distintos de la asignación. Se conserva
        el rowspan cuando varias filas comparten exactamente el mismo conjunto físico,
        evitando repetir visualmente el mismo dato.
        """
        signatures = [self._pallet_signature(block, row) for row in consolidated]
        display_values = [
            self._pallet_label(len(signature))
            if signature
            else self._pallet_label(row.get("pallet_count") or "-")
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
        """Agrupa corridas de pallets de artículo único sin ocultar los mixtos.

        Un artículo idéntico y exclusivo de varios pallets consecutivos se
        imprime una sola vez con la cantidad por pallet y el número de pallets.
        Los pallets mixtos conservan una fila por artículo y su celda de pallet
        combinada verticalmente, pues esa composición debe permanecer visible.
        """
        header = [
            self._p("Producto / detalle", bold=True),
            self._p("Cantidad total", bold=True),
            self._p("Pallet", bold=True),
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

        span_commands: list[tuple] = []
        table_row = 2
        has_rows = False

        sub_blocks = [
            *block.get("pallet_blocks", []),
            *([block.get("loose_block")] if block.get("loose_block") else []),
            *([block.get("unassigned_block")] if block.get("unassigned_block") else []),
        ]

        block_index = 0
        while block_index < len(sub_blocks):
            sub_block = sub_blocks[block_index]
            physical_rows = list(sub_block.get("rows", []))
            if not physical_rows:
                block_index += 1
                continue

            group_key = self._single_product_pallet_key(sub_block)
            if group_key is not None:
                group_end = block_index + 1
                while (
                    group_end < len(sub_blocks)
                    and self._single_product_pallet_key(sub_blocks[group_end]) == group_key
                ):
                    group_end += 1

                row = physical_rows[0]
                pallet_count = group_end - block_index
                rows.append(
                    [
                        self._p(row["product"]),
                        self._center_p(
                            self._quantity_with_unit(row["quantity"], row.get("unit"))
                        ),
                        self._center_p(self._pallet_label(pallet_count)),
                        self._p(row["lote"])
                        if self._optional_operational_value(row.get("lote"))
                        else "",
                        self._p(row["elab"])
                        if self._optional_operational_value(row.get("elab"))
                        else "",
                    ]
                )
                table_row += 1
                has_rows = True
                block_index = group_end
                continue

            has_rows = True
            start_row = table_row
            label = str(sub_block.get("label") or "-")

            for index, row in enumerate(physical_rows):
                rows.append(
                    [
                        self._p(row["product"]),
                        self._center_p(
                            self._quantity_with_unit(row["quantity"], row.get("unit"))
                        ),
                        self._center_p(label) if index == 0 else "",
                        self._p(row["lote"]) if self._optional_operational_value(row.get("lote")) else "",
                        self._p(row["elab"]) if self._optional_operational_value(row.get("elab")) else "",
                    ]
                )
                table_row += 1

            if len(physical_rows) > 1:
                span_commands.append(
                    ("SPAN", (2, start_row), (2, table_row - 1))
                )
            block_index += 1

        if not has_rows:
            rows.append(
                [
                    self._p("-"),
                    self._center_p("-"),
                    self._center_p("-"),
                    self._p("-"),
                    self._p("-"),
                ]
            )

        table = Table(
            rows,
            colWidths=[82 * mm, 30 * mm, 26 * mm, 21 * mm, 21 * mm],
            repeatRows=2,
        )
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

    def _single_product_pallet_key(self, sub_block: dict[str, object]) -> tuple | None:
        """Identifica un pallet exclusivo que puede resumirse con sus iguales."""
        label = str(sub_block.get("label") or "").strip()
        rows = list(sub_block.get("rows", []))
        if not label.isdigit() or len(rows) != 1:
            return None

        row = rows[0]
        return (
            str(row.get("product", "")),
            str(row.get("unit", "")),
            str(row.get("quantity", "")),
            self._optional_operational_value(row.get("lote")),
            self._optional_operational_value(row.get("elab")),
        )
