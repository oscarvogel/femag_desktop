"""PDF imprimible del informe de recompra por producto.

No vuelve a consultar la base: recibe lo que la pantalla está mostrando
(título, KPIs, resumen, gráfico y filas ya ordenadas/filtradas) para que el
papel coincida con lo que el operador ve. Se genera con reportlab, la misma
dependencia que usan los demás comprobantes de FEMAG.
"""

from __future__ import annotations

from datetime import datetime
from html import escape
from pathlib import Path
from typing import Iterable, Sequence

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    Image,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

_HEADER_BG = colors.HexColor("#1f3d63")
_GRID = colors.HexColor("#b8c2cc")
_ALERT_BG = colors.HexColor("#fdf0ef")
_MUTED = colors.HexColor("#4b5563")


def _clean(value: object) -> str:
    text = str(value or "")
    return (
        escape(text)
        .replace("\r\n", "<br/>")
        .replace("\n", "<br/>")
        .replace("→", "-&gt;")
        .replace("⚠", "")
        .replace("—", "-")
    )


def _styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "RepurchaseTitle",
            parent=base["Title"],
            fontName="Helvetica-Bold",
            fontSize=15,
            leading=18,
            alignment=0,
            textColor=_HEADER_BG,
            spaceAfter=4,
        ),
        "meta": ParagraphStyle(
            "RepurchaseMeta",
            parent=base["Normal"],
            fontName="Helvetica",
            fontSize=8.5,
            leading=11,
            textColor=_MUTED,
        ),
        "body": ParagraphStyle(
            "RepurchaseBody",
            parent=base["Normal"],
            fontName="Helvetica",
            fontSize=8.5,
            leading=11,
        ),
        "caption": ParagraphStyle(
            "RepurchaseCaption",
            parent=base["Normal"],
            fontName="Helvetica-Oblique",
            fontSize=8,
            leading=10,
            textColor=_MUTED,
        ),
        "cell": ParagraphStyle(
            "RepurchaseCell",
            parent=base["Normal"],
            fontName="Helvetica",
            fontSize=7,
            leading=8.5,
        ),
        "cell_right": ParagraphStyle(
            "RepurchaseCellRight",
            parent=base["Normal"],
            fontName="Helvetica",
            fontSize=7,
            leading=8.5,
            alignment=2,
        ),
        "head": ParagraphStyle(
            "RepurchaseHead",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=7,
            leading=8.5,
            textColor=colors.white,
        ),
        "head_right": ParagraphStyle(
            "RepurchaseHeadRight",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=7,
            leading=8.5,
            textColor=colors.white,
            alignment=2,
        ),
    }


def _paragraph(text: object, style: ParagraphStyle) -> Paragraph:
    return Paragraph(_clean(text), style)


def _kpi_block(previous_kpi: str, current_kpi: str, styles: dict[str, ParagraphStyle], width: float) -> Table:
    table = Table(
        [[_paragraph(previous_kpi, styles["body"]), _paragraph(current_kpi, styles["body"])]],
        colWidths=[width / 2.0, width / 2.0],
    )
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f3f6fa")),
                ("BOX", (0, 0), (-1, -1), 0.5, _GRID),
                ("INNERGRID", (0, 0), (-1, -1), 0.5, _GRID),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    return table


def _data_table(
    headers: Sequence[str],
    rows: Iterable[Sequence[str]],
    styles: dict[str, ParagraphStyle],
    width: float,
) -> Table:
    right_columns = {3, 4, 5, 6, 7}
    data: list[list[Paragraph]] = [
        [
            _paragraph(header, styles["head_right"] if index in right_columns else styles["head"])
            for index, header in enumerate(headers)
        ]
    ]
    alert_rows: list[int] = []
    for row_index, row in enumerate(rows, start=1):
        if row and "sin recompra" in str(row[-1]).lower():
            alert_rows.append(row_index)
        data.append(
            [
                _paragraph(value, styles["cell_right"] if index in right_columns else styles["cell"])
                for index, value in enumerate(row)
            ]
        )

    widths_mm = [70, 36, 22, 22, 22, 22, 19, 28, 26]
    col_widths = [value * mm for value in widths_mm]
    scale = width / sum(col_widths)
    col_widths = [value * scale for value in col_widths]

    table = Table(data, colWidths=col_widths, repeatRows=1)
    commands = [
        ("BACKGROUND", (0, 0), (-1, 0), _HEADER_BG),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.35, _GRID),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 3),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]
    for row_index in range(1, len(data)):
        if row_index % 2 == 0:
            commands.append(("BACKGROUND", (0, row_index), (-1, row_index), colors.HexColor("#f7f9fb")))
    for row_index in alert_rows:
        commands.append(("BACKGROUND", (0, row_index), (-1, row_index), _ALERT_BG))
    table.setStyle(TableStyle(commands))
    return table


def _page_footer(canvas, doc) -> None:
    canvas.saveState()
    canvas.setFont("Helvetica", 7)
    canvas.setFillColor(_MUTED)
    canvas.drawRightString(
        landscape(A4)[0] - 12 * mm,
        7 * mm,
        f"FEMAG Desktop · página {canvas.getPageNumber()}",
    )
    canvas.restoreState()


def export_repurchase_pdf(
    target: str | Path,
    *,
    title: str,
    previous_kpi: str,
    current_kpi: str,
    variation_text: str,
    summary_text: str,
    headers: Sequence[str],
    rows: Iterable[Sequence[str]],
    chart_caption: str = "",
    chart_image: str | Path | None = None,
    filters_note: str = "",
    generated_at: datetime | None = None,
) -> Path:
    path = Path(target)
    path.parent.mkdir(parents=True, exist_ok=True)
    styles = _styles()
    page_width, _ = landscape(A4)
    width = page_width - 24 * mm

    story = [
        _paragraph(title, styles["title"]),
        _paragraph(
            f"Generado el {generated_at or datetime.now():%d/%m/%Y %H:%M}"
            + (f" · {filters_note}" if filters_note else ""),
            styles["meta"],
        ),
        Spacer(1, 5 * mm),
        _kpi_block(previous_kpi, current_kpi, styles, width),
        Spacer(1, 4 * mm),
        _paragraph(variation_text, styles["body"]),
        Spacer(1, 3 * mm),
    ]

    if chart_image:
        try:
            story.append(Image(str(chart_image), width=min(width, 190 * mm)))
            story.append(Spacer(1, 2 * mm))
        except Exception:
            pass
    if chart_caption:
        story.append(_paragraph(chart_caption, styles["caption"]))
        story.append(Spacer(1, 3 * mm))

    story.append(_paragraph(summary_text, styles["body"]))
    story.append(Spacer(1, 4 * mm))
    story.append(_data_table(headers, rows, styles, width))
    story.append(Spacer(1, 3 * mm))
    story.append(
        _paragraph(
            "Sin recompra es una alerta comercial (el cliente no volvió a comprar en el corte), "
            "no una pérdida confirmada. Criterio: kilos/toneladas; el valorizado es contexto.",
            styles["caption"],
        )
    )

    document = SimpleDocTemplate(
        str(path),
        pagesize=landscape(A4),
        leftMargin=12 * mm,
        rightMargin=12 * mm,
        topMargin=12 * mm,
        bottomMargin=12 * mm,
        title=title,
        author="FEMAG Desktop",
    )
    document.build(story, onFirstPage=_page_footer, onLaterPages=_page_footer)
    return path
