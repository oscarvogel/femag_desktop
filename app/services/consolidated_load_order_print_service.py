from __future__ import annotations

from collections import OrderedDict
from html import escape

from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, Table, TableStyle

from app.services.load_order_print_service import LoadOrderPrintService, _quantity


class ConsolidatedLoadOrderPrintService(LoadOrderPrintService):
    """Vista consolidada de pallets para la impresión operativa de órdenes."""

    def _destination_detail_block(self, order, destination) -> dict[str, object]:
        block = super()._destination_detail_block(order, destination)
        block["consolidated_rows"] = self._consolidate_rows(block)
        return block

    def _legacy_destination_block(self, order) -> dict[str, object]:
        block = super()._legacy_destination_block(order)
        block["consolidated_rows"] = self._consolidate_rows(block)
        return block

    def _consolidate_rows(self, block: dict[str, object]) -> list[dict[str, object]]:
        grouped: OrderedDict[tuple[str, str, str], dict[str, object]] = OrderedDict()

        for pallet_block in block.get("pallet_blocks", []):
            sequence = int(pallet_block["label"])
            for row in pallet_block["rows"]:
                key = (str(row["product"]), str(row.get("lote") or "-"), str(row.get("elab") or "-"))
                item = grouped.setdefault(
                    key,
                    {
                        "product": row["product"],
                        "lote": row.get("lote") or "-",
                        "elab": row.get("elab") or "-",
                        "pallet_quantities": OrderedDict(),
                        "loose_quantity": 0.0,
                        "unassigned_quantity": 0.0,
                    },
                )
                quantities = item["pallet_quantities"]
                quantities[sequence] = quantities.get(sequence, 0.0) + float(row["quantity"])

        loose = block.get("loose_block")
        if loose:
            for row in loose["rows"]:
                key = (str(row["product"]), str(row.get("lote") or "-"), str(row.get("elab") or "-"))
                item = grouped.setdefault(
                    key,
                    {
                        "product": row["product"],
                        "lote": row.get("lote") or "-",
                        "elab": row.get("elab") or "-",
                        "pallet_quantities": OrderedDict(),
                        "loose_quantity": 0.0,
                        "unassigned_quantity": 0.0,
                    },
                )
                item["loose_quantity"] += float(row["quantity"])

        unassigned = block.get("unassigned_block")
        if unassigned:
            for row in unassigned["rows"]:
                key = (str(row["product"]), str(row.get("lote") or "-"), str(row.get("elab") or "-"))
                item = grouped.setdefault(
                    key,
                    {
                        "product": row["product"],
                        "lote": row.get("lote") or "-",
                        "elab": row.get("elab") or "-",
                        "pallet_quantities": OrderedDict(),
                        "loose_quantity": 0.0,
                        "unassigned_quantity": 0.0,
                    },
                )
                item["unassigned_quantity"] += float(row["quantity"])

        result = []
        for item in grouped.values():
            pallet_quantities = item["pallet_quantities"]
            total = sum(pallet_quantities.values()) + item["loose_quantity"] + item["unassigned_quantity"]
            result.append(
                {
                    "product": item["product"],
                    "pallets": self._pallet_description(pallet_quantities, item["loose_quantity"], item["unassigned_quantity"]),
                    "pallet_count": len(pallet_quantities),
                    "quantity": total,
                    "lote": item["lote"],
                    "elab": item["elab"],
                }
            )
        return result

    @classmethod
    def _pallet_description(cls, pallet_quantities, loose_quantity: float = 0.0, unassigned_quantity: float = 0.0) -> str:
        parts = []
        if pallet_quantities:
            values = list(pallet_quantities.values())
            if cls._same_quantity(values):
                parts.append(cls._compact_ranges(list(pallet_quantities.keys())))
            else:
                by_quantity: OrderedDict[float, list[int]] = OrderedDict()
                for sequence, quantity in pallet_quantities.items():
                    by_quantity.setdefault(quantity, []).append(sequence)
                for quantity, sequences in by_quantity.items():
                    parts.append(f"{cls._compact_ranges(sequences)} ({_quantity(quantity)} c/u)")
        if loose_quantity > 0:
            parts.append(f"Suelto ({_quantity(loose_quantity)})")
        if unassigned_quantity > 0:
            parts.append(f"Sin asignar ({_quantity(unassigned_quantity)})")
        return " · ".join(parts) if parts else "-"

    @staticmethod
    def _same_quantity(values: list[float]) -> bool:
        if not values:
            return True
        first = values[0]
        return all(abs(value - first) < 1e-9 for value in values[1:])

    @staticmethod
    def _compact_ranges(sequences: list[int]) -> str:
        values = sorted(set(int(value) for value in sequences))
        if not values:
            return "-"
        ranges = []
        start = previous = values[0]
        for value in values[1:]:
            if value == previous + 1:
                previous = value
                continue
            ranges.append(str(start) if start == previous else f"{start}–{previous}")
            start = previous = value
        ranges.append(str(start) if start == previous else f"{start}–{previous}")
        return ", ".join(ranges)

    def _destination_table(self, block: dict[str, object]) -> Table:
        header = [
            self._p("Producto / detalle", bold=True),
            self._p("Pallets", bold=True),
            self._p("Cant. pallets", bold=True),
            self._p("Cantidad total", bold=True),
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
        if consolidated:
            for row in consolidated:
                rows.append(
                    [
                        self._p(row["product"]),
                        self._p(row["pallets"]),
                        self._p(row["pallet_count"] if row["pallet_count"] else "-"),
                        self._p(_quantity(row["quantity"])),
                        self._p(row["lote"]),
                        self._p(row["elab"]),
                    ]
                )
        else:
            rows.append([self._p("-"), self._p("-"), self._p("-"), self._p("-"), self._p("-"), self._p("-")])

        table = Table(rows, colWidths=[58 * mm, 42 * mm, 20 * mm, 24 * mm, 18 * mm, 18 * mm], repeatRows=2)
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
                    ("ALIGN", (2, 0), (3, -1), "CENTER"),
                    ("SPAN", (0, 1), (5, 1)),
                    ("BACKGROUND", (0, 1), (5, 1), colors.whitesmoke),
                ]
            )
        )
        return table
