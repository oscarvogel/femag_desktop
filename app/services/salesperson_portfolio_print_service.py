"""Resumen de saldos de la cartera de un vendedor.

Genera un PDF corto con una fila por cliente (nombre, CUIT, saldo) y el total de
la cartera. Reutiliza el kit de impresión de FEMAG del extracto de cuenta corriente
para no duplicar formato de importes, colores ni numeración de páginas.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib.enums import TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.models.masters import Salesperson

# Kit de impresión compartido con el extracto de cuenta corriente (#581).
from app.services.account_statement_print_service import (
    BRAND_ACCENT,
    BRAND_DARK,
    BRAND_LIGHT,
    INK,
    LINE,
    MUTED,
    ROW_ALT,
    WHITE,
    _canvas_factory,
    _format_money,
    _money_decimal,
    _safe_filename_component,
)


FILENAME_PREFIX = "resumen_cuenta_corriente"
ALL_SELLERS_SLUG = "todos"


def portfolio_label(salesperson: Salesperson | None, *, label: str | None = None) -> str:
    """Titular del reporte: el vendedor, o el texto del filtro activo."""
    if label:
        return label
    if salesperson is None:
        return "Todos los vendedores"
    return salesperson.name or "Vendedor"


def portfolio_filename(
    salesperson: Salesperson | None,
    generated_at: datetime,
    *,
    slug: str | None = None,
) -> str:
    if not slug:
        slug = (
            ALL_SELLERS_SLUG
            if salesperson is None
            else _safe_filename_component(salesperson.name, fallback="vendedor")
        )
    # Slug en minusculas para que el nombre sea estable al descargarlo.
    return f"{FILENAME_PREFIX}_{slug.lower()}_{generated_at:%Y%m%d}.pdf"


def portfolio_totals(rows: list[dict]) -> dict[str, Decimal]:
    """Suma neta de las filas incluidas en el resumen.

    Se informan dos cifras porque no son lo mismo y la pantalla las separa:
    - `balance`: suma neta, incluye los saldos a favor del cliente.
    - `collectable`: solo saldos positivos, que es el "Cartera" de la barra
      lateral de Cuenta Corriente.
    """
    balance = sum((_money_decimal(row.get("balance")) for row in rows), Decimal("0.00"))
    overdue = sum((_money_decimal(row.get("overdue")) for row in rows), Decimal("0.00"))
    due_7 = sum((_money_decimal(row.get("due_7")) for row in rows), Decimal("0.00"))
    collectable = sum(
        (
            amount
            for amount in (_money_decimal(row.get("balance")) for row in rows)
            if amount > 0
        ),
        Decimal("0.00"),
    )
    with_balance = sum(
        1 for row in rows if _money_decimal(row.get("balance")) != Decimal("0.00")
    )
    return {
        "balance": balance,
        "collectable": collectable,
        "overdue": overdue,
        "due_7": due_7,
        "clients": len(rows),
        "clients_with_balance": with_balance,
    }


def _sorted_rows(rows: list[dict]) -> list[dict]:
    """Mayor saldo primero, sin depender del orden en que llegan las filas."""
    return sorted(rows, key=lambda row: _money_decimal(row.get("balance")), reverse=True)


def _styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "company": ParagraphStyle(
            "portfolio_company",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=13,
            textColor=BRAND_DARK,
            leading=15,
            alignment=TA_LEFT,
        ),
        "company_subtitle": ParagraphStyle(
            "portfolio_company_subtitle",
            parent=base["Normal"],
            fontSize=8,
            textColor=MUTED,
            leading=10,
        ),
        "document_title": ParagraphStyle(
            "portfolio_title",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=15,
            textColor=BRAND_DARK,
            leading=17,
            alignment=TA_RIGHT,
        ),
        "document_subtitle": ParagraphStyle(
            "portfolio_subtitle",
            parent=base["Normal"],
            fontSize=9,
            textColor=MUTED,
            leading=11,
            alignment=TA_RIGHT,
        ),
        "document_date": ParagraphStyle(
            "portfolio_date",
            parent=base["Normal"],
            fontSize=7.5,
            textColor=MUTED,
            leading=10,
            alignment=TA_RIGHT,
            spaceBefore=3,
        ),
        "section": ParagraphStyle(
            "portfolio_section",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=9.5,
            textColor=BRAND_DARK,
            leading=12,
            spaceAfter=2,
        ),
        "summary_label": ParagraphStyle(
            "portfolio_summary_label",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=6.8,
            textColor=MUTED,
            leading=8,
            alignment=TA_RIGHT,
        ),
        "summary_value": ParagraphStyle(
            "portfolio_summary_value",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=9.3,
            textColor=INK,
            leading=11,
            alignment=TA_RIGHT,
        ),
        "table_header": ParagraphStyle(
            "portfolio_table_header",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=7,
            textColor=WHITE,
            leading=8,
        ),
        "table_header_right": ParagraphStyle(
            "portfolio_table_header_right",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=7,
            textColor=WHITE,
            leading=8,
            alignment=TA_RIGHT,
        ),
        "cell": ParagraphStyle(
            "portfolio_cell",
            parent=base["Normal"],
            fontSize=7.5,
            textColor=INK,
            leading=10,
        ),
        "empty": ParagraphStyle(
            "portfolio_empty",
            parent=base["Normal"],
            fontSize=9,
            textColor=MUTED,
            leading=12,
        ),
    }


def _document_header(
    salesperson: Salesperson | None,
    generated_at: datetime,
    styles: dict[str, ParagraphStyle],
    *,
    label: str | None = None,
) -> Table:
    left = [
        Paragraph("GRAEF HERMANOS S.R.L.", styles["company"]),
        Paragraph("Gestion comercial y cuenta corriente", styles["company_subtitle"]),
    ]
    right = [
        Paragraph("RESUMEN DE CUENTA CORRIENTE", styles["document_title"]),
        Paragraph(escape(portfolio_label(salesperson, label=label)), styles["document_subtitle"]),
        Paragraph(
            f"Emitido el {generated_at:%d/%m/%Y %H:%M}",
            styles["document_date"],
        ),
    ]
    table = Table([[left, right]], colWidths=[88 * mm, 88 * mm])
    table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ("LINEBELOW", (0, 0), (-1, -1), 0.8, BRAND_ACCENT),
            ]
        )
    )
    return table


def _summary_table(totals: dict[str, Decimal], styles: dict) -> Table:
    labels = ["CLIENTES", "CON SALDO", "DEUDA", "VENCIDO", "PROX. 7 DIAS", "TOTAL NETO"]
    values = [
        str(totals["clients"]),
        str(totals["clients_with_balance"]),
        _format_money(totals["collectable"]),
        _format_money(totals["overdue"]),
        _format_money(totals["due_7"]),
        _format_money(totals["balance"]),
    ]
    cards = [
        [Paragraph(label, styles["summary_label"]), Paragraph(value, styles["summary_value"])]
        for label, value in zip(labels, values)
    ]
    # Tres columnas por fila: con seis, los importes grandes se parten en dos lineas.
    rows = [cards[0:3], cards[3:6]]
    table = Table(
        rows,
        colWidths=[60.6 * mm, 60.6 * mm, 60.6 * mm],
    )
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), BRAND_LIGHT),
                ("BOX", (0, 0), (-1, -1), 0.6, LINE),
                ("INNERGRID", (0, 0), (-1, -1), 0.4, LINE),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    return table


def _clients_table(rows: list[dict], styles: dict) -> Table:
    header = [
        Paragraph("CLIENTE", styles["table_header"]),
        Paragraph("CUIT", styles["table_header"]),
        Paragraph("SALDO", styles["table_header_right"]),
    ]
    data = [header]
    for row in rows:
        client = row.get("client")
        name = escape(getattr(client, "name", "") or "-")
        cuit = escape(getattr(client, "cuit", "") or "-")
        data.append(
            [
                Paragraph(name, styles["cell"]),
                Paragraph(cuit, styles["cell"]),
                Paragraph(_format_money(row.get("balance")), styles["cell"]),
            ]
        )
    total = sum((_money_decimal(row.get("balance")) for row in rows), Decimal("0.00"))
    data.append(
        [
            Paragraph("TOTAL NETO", styles["table_header"]),
            "",
            Paragraph(_format_money(total), styles["table_header_right"]),
        ]
    )
    table = Table(data, colWidths=[92 * mm, 38 * mm, 46 * mm], repeatRows=1)
    style_commands = [
        ("BACKGROUND", (0, 0), (-1, 0), BRAND_DARK),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (2, 1), (2, -1), "RIGHT"),
        ("ALIGN", (1, 0), (1, -1), "LEFT"),
        ("LINEBELOW", (0, 0), (-1, -1), 0.4, LINE),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
    ]
    for index in range(1, len(data) - 1):
        if index % 2 == 0:
            style_commands.append(("BACKGROUND", (0, index), (-1, index), ROW_ALT))
    style_commands.append(
        ("BACKGROUND", (0, len(data) - 1), (-1, len(data) - 1), BRAND_DARK)
    )
    table.setStyle(TableStyle(style_commands))
    return table


def export_salesperson_portfolio(
    *,
    salesperson: Salesperson | None,
    rows: list[dict],
    output_dir: str | Path,
    generated_at: datetime | None = None,
    label: str | None = None,
    slug: str | None = None,
) -> Path:
    """Genera el PDF del resumen y devuelve la ruta del archivo.

    `rows` son las filas de `client_portfolio_rows()` ya filtradas por la pantalla
    (búsqueda, "Solo con saldo" y vendedor): el PDF respeta exactamente lo que
    el usuario está viendo.
    """
    moment = generated_at or datetime.now()
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)

    ordered = _sorted_rows(rows)
    totals = portfolio_totals(ordered)
    styles = _styles()
    target = destination / portfolio_filename(salesperson, moment, slug=slug)

    document = SimpleDocTemplate(
        str(target),
        pagesize=A4,
        leftMargin=14 * mm,
        rightMargin=14 * mm,
        topMargin=14 * mm,
        bottomMargin=20 * mm,
        title="Resumen de cuenta corriente",
        author="GRAEF HERMANOS S.R.L.",
    )

    story = [
        _document_header(salesperson, moment, styles, label=label),
        Spacer(1, 7 * mm),
        Paragraph("Resumen de cartera", styles["section"]),
        _summary_table(totals, styles),
        Spacer(1, 7 * mm),
        Paragraph("Saldos por cliente", styles["section"]),
    ]
    if ordered:
        story.append(_clients_table(ordered, styles))
    else:
        story.append(
            Paragraph(
                "No hay clientes para los filtros seleccionados.",
                styles["empty"],
            )
        )

    document.build(story, canvasmaker=_canvas_factory(moment))
    return target
