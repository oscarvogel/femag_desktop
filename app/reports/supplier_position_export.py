"""Exportacion de la posicion con productores a Excel y PDF (#941).

Las dos salidas llevan lo mismo que la pantalla: el renglon por productor, el
detalle de documentos con su pendiente, los totales y lo que quedo excluido de
la importacion. La exclusion va en la misma hoja: excluir no es esconder.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from html import escape
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Font
from openpyxl.utils import get_column_letter

from app.services.supplier_position_service import (
    SupplierDocumentRow,
    SupplierPositionResult,
)

MONEY_FORMAT = "#,##0.00"


def _money(value: Decimal) -> float:
    return float(value)


def _fmt(value: Decimal) -> str:
    text = f"{value:,.2f}"
    return text.replace(",", "_").replace(".", ",").replace("_", ".")


def _date(value: date | None) -> str:
    return value.strftime("%d/%m/%Y") if value else ""


def _filters_text(filters_label: str | None) -> str:
    return filters_label or "Sin filtros"


def export_supplier_position_xlsx(
    result: SupplierPositionResult,
    documents: list[SupplierDocumentRow],
    destination: str | Path,
    *,
    filters_label: str | None = None,
    today: date | None = None,
) -> Path:
    today = today or date.today()
    destination = Path(destination)
    workbook = Workbook()

    summary = workbook.active
    summary.title = "Posicion"
    summary.append(["Cuenta corriente productores"])
    summary["A1"].font = Font(bold=True, size=14)
    summary.append([f"Generado el {today.strftime('%d/%m/%Y')} - {_filters_text(filters_label)}"])
    summary.append([])
    headers = [
        "Productor",
        "Codigos legacy",
        "A pagar (tickets)",
        "A cobrar (pagares)",
        "Neto a pagar",
        "Documento mas antiguo",
        "Dias",
    ]
    summary.append(headers)
    header_row = summary.max_row
    for row in result.rows:
        summary.append(
            [
                row.name,
                row.codes,
                _money(row.payable),
                _money(row.receivable),
                _money(row.net),
                row.oldest_date,
                row.age_days(today),
            ]
        )
    summary.append(
        ["Total", "", _money(result.payable), _money(result.receivable), _money(result.net), None, None]
    )
    total_row = summary.max_row
    summary.append([])
    summary.append(
        [
            "Excluido de la importacion por falta de datos",
            f"{result.excluded_count} documentos",
            _money(result.excluded_amount),
        ]
    )
    exclusion_row = summary.max_row
    for cell in summary[header_row]:
        cell.font = Font(bold=True)
    for cell in summary[total_row]:
        cell.font = Font(bold=True)
    summary.cell(exclusion_row, 1).font = Font(italic=True)
    for row_index in range(header_row + 1, exclusion_row + 1):
        for column in (3, 4, 5):
            summary.cell(row_index, column).number_format = MONEY_FORMAT
        summary.cell(row_index, 6).number_format = "DD/MM/YYYY"
    for index, width in enumerate((42, 16, 18, 18, 18, 14, 8), start=1):
        summary.column_dimensions[get_column_letter(index)].width = width
    summary.freeze_panes = summary.cell(header_row + 1, 1)

    detail = workbook.create_sheet("Documentos")
    names = {row.supplier_id: row.name for row in result.rows}
    detail.append(
        [
            "Productor",
            "Tipo",
            "Numero",
            "Fecha",
            "Fecha inferida",
            "Importe",
            "Saldo importado",
            "Pagado en FEMAG",
            "Pendiente",
        ]
    )
    for cell in detail[1]:
        cell.font = Font(bold=True)
    for document in documents:
        detail.append(
            [
                names.get(document.supplier_id, ""),
                document.kind_label,
                document.code,
                document.issued_at,
                "Si" if document.date_inferred else "",
                _money(document.amount),
                _money(document.imported_balance),
                _money(document.paid),
                _money(document.pending),
            ]
        )
    for row_index in range(2, detail.max_row + 1):
        detail.cell(row_index, 4).number_format = "DD/MM/YYYY"
        for column in (6, 7, 8, 9):
            detail.cell(row_index, column).number_format = MONEY_FORMAT
    for index, width in enumerate((42, 24, 16, 12, 10, 16, 16, 16, 16), start=1):
        detail.column_dimensions[get_column_letter(index)].width = width
    detail.freeze_panes = "A2"

    destination.parent.mkdir(parents=True, exist_ok=True)
    workbook.save(destination)
    return destination


def export_supplier_position_pdf(
    result: SupplierPositionResult,
    documents: list[SupplierDocumentRow],
    destination: str | Path,
    *,
    filters_label: str | None = None,
    today: date | None = None,
) -> Path:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import (
        LongTable,
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        TableStyle,
    )

    today = today or date.today()
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    styles = getSampleStyleSheet()
    doc = SimpleDocTemplate(
        str(destination),
        pagesize=landscape(A4),
        leftMargin=12 * mm,
        rightMargin=12 * mm,
        topMargin=12 * mm,
        bottomMargin=12 * mm,
        title="Cuenta corriente productores",
    )
    story = [
        Paragraph("Cuenta corriente productores", styles["Title"]),
        Paragraph(
            escape(
                f"Generado el {datetime.now().strftime('%d/%m/%Y %H:%M')} - "
                f"{_filters_text(filters_label)}"
            ),
            styles["Normal"],
        ),
        Spacer(1, 4 * mm),
    ]
    def table_style(*, right_from: int, with_total: bool) -> TableStyle:
        commands = [
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1e293b")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#cbd5e1")),
            ("ALIGN", (right_from, 1), (-1, -1), "RIGHT"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ]
        if with_total:
            commands += [
                ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
                ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#f1f5f9")),
            ]
        return TableStyle(commands)

    summary_rows = [["Productor", "Codigos", "A pagar", "A cobrar", "Neto a pagar", "Mas antiguo", "Dias"]]
    for row in result.rows:
        summary_rows.append(
            [
                row.name,
                row.codes,
                _fmt(row.payable),
                _fmt(row.receivable),
                _fmt(row.net),
                _date(row.oldest_date),
                "" if row.age_days(today) is None else str(row.age_days(today)),
            ]
        )
    summary_rows.append(
        ["Total", "", _fmt(result.payable), _fmt(result.receivable), _fmt(result.net), "", ""]
    )
    summary_table = LongTable(
        summary_rows,
        colWidths=[80 * mm, 30 * mm, 32 * mm, 32 * mm, 32 * mm, 24 * mm, 14 * mm],
        repeatRows=1,
    )
    summary_table.setStyle(table_style(right_from=2, with_total=True))
    story.append(summary_table)
    story.append(Spacer(1, 3 * mm))
    story.append(
        Paragraph(
            escape(
                f"Excluido de la importacion por falta de datos: {result.excluded_count} "
                f"documentos por {_fmt(result.excluded_amount)} ARS. No forman parte de los totales."
            ),
            styles["Italic"],
        )
    )

    if documents:
        names = {row.supplier_id: row.name for row in result.rows}
        story.append(Spacer(1, 6 * mm))
        story.append(Paragraph("Documentos", styles["Heading2"]))
        detail_rows = [["Productor", "Tipo", "Numero", "Fecha", "Importe", "Saldo importado", "Pagado", "Pendiente"]]
        for document in documents:
            detail_rows.append(
                [
                    names.get(document.supplier_id, "")[:40],
                    document.kind_label,
                    document.code,
                    _date(document.issued_at) + (" *" if document.date_inferred else ""),
                    _fmt(document.amount),
                    _fmt(document.imported_balance),
                    _fmt(document.paid),
                    _fmt(document.pending),
                ]
            )
        detail_table = LongTable(
            detail_rows,
            colWidths=[66 * mm, 38 * mm, 26 * mm, 22 * mm, 28 * mm, 28 * mm, 28 * mm, 28 * mm],
            repeatRows=1,
        )
        detail_table.setStyle(table_style(right_from=4, with_total=False))
        story.append(detail_table)
        story.append(Spacer(1, 2 * mm))
        story.append(Paragraph("* Fecha inferida de los tickets vecinos.", styles["Italic"]))

    doc.build(story)
    return destination
