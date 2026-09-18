from __future__ import annotations

from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side

from app.models.load_orders import LoadOrder
from app.services.audit_service import AuditService
from app.services.rowspan_consolidated_load_order_print_service import (
    ConsolidatedLoadOrderPrintService,
)


class LoadOrderPalletExcelExportService:
    """Crea una planilla externa con la misma grilla operativa del PDF."""

    HEADERS = ("Producto / detalle", "Cantidad total", "Pallet", "Lote", "Elab.")

    def __init__(self, current_user: str, audit_service: AuditService | None = None) -> None:
        self.current_user = current_user
        self.audit_service = audit_service or AuditService()

    def export(self, order: LoadOrder, output_dir: str | Path) -> Path:
        order = LoadOrder.get_by_id(order.id)
        destination = Path(output_dir)
        destination.mkdir(parents=True, exist_ok=True)
        target = destination / f"orden_carga_{order.order_number}_armado_pallets.xlsx"

        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "Armado de pallets"
        sheet.sheet_view.showGridLines = False
        sheet.merge_cells("A1:E1")
        sheet["A1"] = f"2. DETALLE DEL PRODUCTO A DESPACHAR - ORDEN {order.order_number:04d}"
        sheet["A1"].font = Font(bold=True, size=14)
        sheet.merge_cells("A2:E2")
        sheet["A2"] = (
            "Planilla editable para casos especiales. Los cambios realizados aquí no actualizan FEMAG."
        )
        sheet["A2"].alignment = Alignment(wrap_text=True)
        sheet.row_dimensions[2].height = 30
        self._write_detail(sheet, order)

        widths = (58, 20, 16, 16, 16)
        for index, width in enumerate(widths, start=1):
            sheet.column_dimensions[chr(64 + index)].width = width
        thin = Side(style="thin", color="404040")
        for row in sheet.iter_rows(min_row=4, max_row=sheet.max_row, min_col=1, max_col=5):
            for cell in row:
                cell.border = Border(left=thin, right=thin, top=thin, bottom=thin)
                cell.alignment = Alignment(vertical="center", wrap_text=True)

        workbook.save(target)
        self.audit_service.record(
            user=self.current_user,
            module="Ordenes de carga",
            action="exportar_excel_pallets",
            record_ref=f"LoadOrder:{order.id}",
            new_value={"file_path": str(target), "order_number": order.order_number},
        )
        return target

    def _write_detail(self, sheet, order: LoadOrder) -> None:
        printer = ConsolidatedLoadOrderPrintService(current_user=self.current_user)
        current_row = 4
        header_fill = PatternFill("solid", fgColor="F2F2F2")
        destination_fill = PatternFill("solid", fgColor="E7E6E6")

        for block in printer._detail_blocks(order):
            for column, header in enumerate(self.HEADERS, start=1):
                cell = sheet.cell(current_row, column, header)
                cell.font = Font(bold=True)
                cell.fill = header_fill
                cell.alignment = Alignment(horizontal="center", vertical="center")
            current_row += 1

            sheet.merge_cells(start_row=current_row, start_column=1, end_row=current_row, end_column=5)
            destination = sheet.cell(current_row, 1, str(block["destination"] or "-"))
            destination.font = Font(bold=True)
            destination.fill = destination_fill
            current_row += 1

            sub_blocks = [
                *block.get("pallet_blocks", []),
                *([block.get("loose_block")] if block.get("loose_block") else []),
                *([block.get("unassigned_block")] if block.get("unassigned_block") else []),
            ]
            index = 0
            has_rows = False
            while index < len(sub_blocks):
                sub_block = sub_blocks[index]
                rows = list(sub_block.get("rows", []))
                if not rows:
                    index += 1
                    continue

                group_key = printer._single_product_pallet_key(sub_block)
                if group_key is not None:
                    group_end = index + 1
                    while (
                        group_end < len(sub_blocks)
                        and printer._single_product_pallet_key(sub_blocks[group_end]) == group_key
                    ):
                        group_end += 1
                    row = rows[0]
                    self._append_row(
                        sheet,
                        current_row,
                        printer,
                        row,
                        printer._pallet_label(group_end - index),
                    )
                    current_row += 1
                    index = group_end
                    has_rows = True
                    continue

                start_row = current_row
                label = str(sub_block.get("label") or "-")
                for item_index, row in enumerate(rows):
                    self._append_row(sheet, current_row, printer, row, label if item_index == 0 else "")
                    current_row += 1
                if len(rows) > 1:
                    sheet.merge_cells(start_row=start_row, start_column=3, end_row=current_row - 1, end_column=3)
                index += 1
                has_rows = True

            if not has_rows:
                for column in range(1, 6):
                    sheet.cell(current_row, column, "-")
                current_row += 1
            current_row += 1

        sheet.freeze_panes = "A4"

    @staticmethod
    def _append_row(sheet, row_number: int, printer, row: dict, pallet: str) -> None:
        sheet.cell(row_number, 1, row["product"])
        sheet.cell(
            row_number,
            2,
            printer._quantity_with_unit(row["quantity"], row.get("unit")),
        )
        sheet.cell(row_number, 3, pallet)
        sheet.cell(
            row_number,
            4,
            row["lote"] if printer._optional_operational_value(row.get("lote")) else "",
        )
        sheet.cell(
            row_number,
            5,
            row["elab"] if printer._optional_operational_value(row.get("elab")) else "",
        )
        for column in (2, 3):
            sheet.cell(row_number, column).alignment = Alignment(horizontal="center", vertical="center")
