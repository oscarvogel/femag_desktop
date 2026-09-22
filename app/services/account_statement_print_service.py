from __future__ import annotations

import re
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.models.accounting import ClientAccountMovement
from app.models.masters import Client
from app.models.payments import ClientPayment
from app.services.ledger_query_service import movements_for_client, running_balance


BRAND_DARK = colors.HexColor("#16324A")
BRAND_ACCENT = colors.HexColor("#2F7D7A")
BRAND_LIGHT = colors.HexColor("#EEF4F5")
INK = colors.HexColor("#1F2933")
MUTED = colors.HexColor("#667784")
LINE = colors.HexColor("#D9E2E8")
ROW_ALT = colors.HexColor("#F7F9FA")
WHITE = colors.white

MONEY_QUANTUM = Decimal("0.01")
_CURRENCY_TOKEN = re.compile(r"\$\s*(-?\d[\d,]*\.\d{2})")
_INVALID_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


MOVEMENT_TYPE_LABELS = {
    ClientAccountMovement.TYPE_OPENING_BALANCE: "Saldo inicial",
    ClientAccountMovement.TYPE_LOAD_ORDER: "Orden de carga",
    ClientAccountMovement.TYPE_LOAD_ORDER_REVERSAL: "Reverso de orden",
    ClientAccountMovement.TYPE_BUDGET_MANUAL: "Presupuesto",
    ClientAccountMovement.TYPE_BUDGET_MANUAL_REVERSAL: "Anulación de presupuesto",
    ClientAccountMovement.TYPE_PAYMENT: "Pago",
    ClientAccountMovement.TYPE_PAYMENT_REVERSAL: "Anulación de pago",
    ClientAccountMovement.TYPE_MANUAL_DEBIT: "Débito manual",
    ClientAccountMovement.TYPE_MANUAL_DEBIT_REVERSAL: "Reverso débito manual",
    ClientAccountMovement.TYPE_MANUAL_CREDIT: "Crédito manual",
    ClientAccountMovement.TYPE_MANUAL_CREDIT_REVERSAL: "Reverso crédito manual",
    ClientAccountMovement.TYPE_RETURN_CREDIT: "Nota de crédito por devolución",
    ClientAccountMovement.TYPE_RETURN_CREDIT_REVERSAL: "Reverso nota de crédito por devolución",
}


class _NumberedCanvas(canvas.Canvas):
    """Canvas que agrega pie profesional con numeración Página X de Y."""

    def __init__(self, *args, generated_at: datetime, **kwargs):
        self._generated_at = generated_at
        self._saved_page_states: list[dict] = []
        super().__init__(*args, **kwargs)

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        page_count = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self._draw_footer(page_count)
            super().showPage()
        super().save()

    def _draw_footer(self, page_count: int) -> None:
        page_width, _ = A4
        y = 8 * mm
        self.saveState()
        self.setStrokeColor(LINE)
        self.setLineWidth(0.5)
        self.line(14 * mm, 12 * mm, page_width - 14 * mm, 12 * mm)
        self.setFillColor(MUTED)
        self.setFont("Helvetica", 7)
        self.drawString(
            14 * mm,
            y,
            f"Generado {self._generated_at:%d/%m/%Y %H:%M} · FEMAG · Vogel Consultoría",
        )
        self.drawRightString(
            page_width - 14 * mm,
            y,
            f"Página {self._pageNumber} de {page_count}",
        )
        self.restoreState()


def _canvas_factory(generated_at: datetime):
    def _factory(*args, **kwargs):
        return _NumberedCanvas(*args, generated_at=generated_at, **kwargs)

    return _factory


def _safe_filename_component(value: str | None, *, fallback: str = "cliente") -> str:
    """Devuelve un componente de archivo válido también en Windows."""
    text = _INVALID_FILENAME_CHARS.sub("_", (value or "").strip())
    text = re.sub(r"\s+", "_", text)
    text = re.sub(r"_+", "_", text)
    text = text.strip(" ._")
    if not text:
        text = fallback
    return text[:100].rstrip(" .") or fallback


def _money_decimal(value) -> Decimal:
    return Decimal(str(value or 0)).quantize(MONEY_QUANTUM, rounding=ROUND_HALF_UP)


def _format_money(value) -> str:
    amount = _money_decimal(value)
    sign = "-" if amount < 0 else ""
    absolute = abs(amount)
    raw = f"{absolute:,.2f}"
    integer, decimals = raw.split(".")
    localized = f"{integer.replace(',', '.')},{decimals}"
    return f"{sign}$\u00a0{localized}"


def _localize_embedded_money(value: str | None) -> str:
    text = value or ""

    def _replace(match: re.Match) -> str:
        normalized = match.group(1).replace(",", "")
        return _format_money(Decimal(normalized)).replace("\u00a0", " ")

    return _CURRENCY_TOKEN.sub(_replace, text)


def _movement_type_label(movement: ClientAccountMovement) -> str:
    if (
        movement.movement_type == ClientAccountMovement.TYPE_PAYMENT
        and movement.payment is not None
        and movement.payment.status == ClientPayment.STATUS_ANNULLED
    ):
        return "Pago anulado"
    return MOVEMENT_TYPE_LABELS.get(movement.movement_type, "Movimiento")


def _reference(movement: ClientAccountMovement) -> str:
    if movement.load_order is not None:
        return f"OC-{movement.load_order.order_number:06d}"
    if movement.payment is not None:
        return movement.payment.receipt_number
    if movement.reference:
        return movement.reference
    return movement.source_ref or "-"


def _movement_date(movement: ClientAccountMovement) -> str:
    if movement.movement_date is not None:
        return movement.movement_date.strftime("%d/%m/%Y")
    return movement.created_at.strftime("%d/%m/%Y")


def _description(movement: ClientAccountMovement) -> str:
    description = _localize_embedded_money(movement.description)
    observations = _localize_embedded_money(movement.observations)
    if observations:
        return f"{description} - {observations}"
    return description


def _financial_summary(
    movements: list[ClientAccountMovement],
    balances: list[float],
) -> dict[str, Decimal]:
    opening = Decimal("0.00")
    debits = Decimal("0.00")
    credits = Decimal("0.00")

    for movement in movements:
        amount = _money_decimal(movement.total_amount)
        if movement.movement_type == ClientAccountMovement.TYPE_OPENING_BALANCE:
            opening += amount
        elif amount >= 0:
            debits += amount
        else:
            credits += amount

    current = _money_decimal(balances[-1]) if balances else Decimal("0.00")
    return {
        "opening": opening.quantize(MONEY_QUANTUM),
        "debits": debits.quantize(MONEY_QUANTUM),
        "credits": credits.quantize(MONEY_QUANTUM),
        "current": current,
    }


def export_account_statement(client: Client, output_dir: str | Path) -> Path:
    path = Path(output_dir)
    path.mkdir(parents=True, exist_ok=True)
    safe_name = _safe_filename_component(client.name)
    target = path / f"extracto_{safe_name}.pdf"

    generated_at = datetime.now()
    movements = movements_for_client(client)
    balances = running_balance(movements)
    summary = _financial_summary(movements, balances)
    styles = _styles()

    doc = SimpleDocTemplate(
        str(target),
        pagesize=A4,
        rightMargin=14 * mm,
        leftMargin=14 * mm,
        topMargin=14 * mm,
        bottomMargin=18 * mm,
        title=f"Estado de cuenta - {client.name}",
        author="FEMAG · Vogel Consultoría",
    )

    story = [
        _document_header(generated_at, styles),
        Spacer(1, 5 * mm),
        _client_card(client, generated_at, styles),
        Spacer(1, 4 * mm),
        _summary_table(summary, styles),
        Spacer(1, 6 * mm),
    ]

    if not movements:
        story.extend(
            [
                Paragraph("MOVIMIENTOS", styles["section"]),
                Spacer(1, 2 * mm),
                Paragraph(
                    "El cliente no tiene movimientos registrados en su cuenta corriente.",
                    styles["empty"],
                ),
            ]
        )
    else:
        story.extend(
            [
                Paragraph("MOVIMIENTOS", styles["section"]),
                Spacer(1, 2 * mm),
                _movements_table(movements, balances, styles),
                Spacer(1, 5 * mm),
                _balance_block(summary["current"], styles),
            ]
        )

    doc.build(story, canvasmaker=_canvas_factory(generated_at))
    return target


def _document_header(generated_at: datetime, styles: dict) -> Table:
    left = [
        Paragraph("GRAEF HERMANOS S.R.L.", styles["company"]),
        Paragraph("Gestión comercial y cuenta corriente", styles["company_subtitle"]),
    ]
    right = [
        Paragraph("ESTADO DE CUENTA", styles["document_title"]),
        Paragraph("Extracto de cuenta corriente", styles["document_subtitle"]),
        Paragraph(f"Emitido {generated_at:%d/%m/%Y %H:%M}", styles["document_date"]),
    ]
    table = Table(
        [[left, right]],
        colWidths=[100 * mm, 82 * mm],
        hAlign="LEFT",
    )
    table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("ALIGN", (1, 0), (1, 0), "RIGHT"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4 * mm),
                ("LINEBELOW", (0, 0), (-1, -1), 2.0, BRAND_ACCENT),
            ]
        )
    )
    return table


def _client_card(client: Client, generated_at: datetime, styles: dict) -> Table:
    client_name = escape(client.name or "-")
    cuit = escape(client.cuit or "-")
    content = Paragraph(
        f"<b>{client_name}</b><br/>"
        f"<font color='#667784'>CUIT {cuit} · Estado de cuenta al {generated_at:%d/%m/%Y}</font>",
        styles["client_card"],
    )
    table = Table([[content]], colWidths=[182 * mm])
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), BRAND_LIGHT),
                ("LINEBEFORE", (0, 0), (0, -1), 4, BRAND_ACCENT),
                ("BOX", (0, 0), (-1, -1), 0.5, LINE),
                ("LEFTPADDING", (0, 0), (-1, -1), 5 * mm),
                ("RIGHTPADDING", (0, 0), (-1, -1), 5 * mm),
                ("TOPPADDING", (0, 0), (-1, -1), 4 * mm),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4 * mm),
            ]
        )
    )
    return table


def _summary_table(summary: dict[str, Decimal], styles: dict) -> Table:
    labels = ["SALDO ANTERIOR", "DÉBITOS / COMPRAS", "PAGOS / CRÉDITOS", "SALDO ACTUAL"]
    values = [
        summary["opening"],
        summary["debits"],
        summary["credits"],
        summary["current"],
    ]
    data = [
        [Paragraph(label, styles["summary_label"]) for label in labels],
        [
            Paragraph(_format_money(value), styles["summary_value_current"] if index == 3 else styles["summary_value"])
            for index, value in enumerate(values)
        ],
    ]
    table = Table(data, colWidths=[45.5 * mm] * 4)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (2, -1), colors.HexColor("#F7F9FA")),
                ("BACKGROUND", (3, 0), (3, -1), BRAND_DARK),
                ("TEXTCOLOR", (3, 0), (3, -1), WHITE),
                ("BOX", (0, 0), (-1, -1), 0.5, LINE),
                ("INNERGRID", (0, 0), (-1, -1), 0.4, LINE),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("ALIGN", (0, 0), (-1, -1), "RIGHT"),
                ("LEFTPADDING", (0, 0), (-1, -1), 4 * mm),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4 * mm),
                ("TOPPADDING", (0, 0), (-1, 0), 3 * mm),
                ("BOTTOMPADDING", (0, 0), (-1, 0), 1 * mm),
                ("TOPPADDING", (0, 1), (-1, 1), 1 * mm),
                ("BOTTOMPADDING", (0, 1), (-1, 1), 3.5 * mm),
            ]
        )
    )
    return table


def _movements_table(
    movements: list[ClientAccountMovement],
    balances: list[float],
    styles: dict,
) -> Table:
    header = [
        Paragraph("FECHA", styles["table_header"]),
        Paragraph("COMPROBANTE", styles["table_header"]),
        Paragraph("CONCEPTO", styles["table_header"]),
        Paragraph("IMPORTE", styles["table_header_right"]),
        Paragraph("SALDO", styles["table_header_right"]),
    ]
    rows = [header]

    for movement, balance in zip(movements, balances):
        label = escape(_movement_type_label(movement))
        description = escape(_description(movement))
        concept = f"<b>{label}</b>"
        if description:
            concept += f"<br/><font color='#667784'>{description}</font>"

        rows.append(
            [
                Paragraph(_movement_date(movement), styles["cell"]),
                Paragraph(escape(_reference(movement)), styles["cell"]),
                Paragraph(concept, styles["concept"]),
                Paragraph(_format_money(movement.total_amount), styles["cell_right"]),
                Paragraph(_format_money(balance), styles["cell_right_balance"]),
            ]
        )

    table = Table(
        rows,
        colWidths=[25 * mm, 32 * mm, 66 * mm, 29 * mm, 30 * mm],
        repeatRows=1,
        hAlign="LEFT",
    )

    commands = [
        ("BACKGROUND", (0, 0), (-1, 0), BRAND_DARK),
        ("TEXTCOLOR", (0, 0), (-1, 0), WHITE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ALIGN", (3, 1), (4, -1), "RIGHT"),
        ("LEFTPADDING", (0, 0), (-1, -1), 2.5 * mm),
        ("RIGHTPADDING", (0, 0), (-1, -1), 2.5 * mm),
        ("TOPPADDING", (0, 0), (-1, 0), 2.5 * mm),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 2.5 * mm),
        ("TOPPADDING", (0, 1), (-1, -1), 2.6 * mm),
        ("BOTTOMPADDING", (0, 1), (-1, -1), 2.6 * mm),
        ("LINEBELOW", (0, 1), (-1, -1), 0.35, LINE),
    ]
    for row_index in range(2, len(rows), 2):
        commands.append(("BACKGROUND", (0, row_index), (-1, row_index), ROW_ALT))

    table.setStyle(TableStyle(commands))
    return table


def _balance_block(balance: Decimal, styles: dict) -> Table:
    table = Table(
        [[
            Paragraph("SALDO ACTUAL", styles["balance_label"]),
            Paragraph(_format_money(balance), styles["balance_value"]),
        ]],
        colWidths=[55 * mm, 55 * mm],
        hAlign="RIGHT",
    )
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), BRAND_DARK),
                ("TEXTCOLOR", (0, 0), (-1, -1), WHITE),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("ALIGN", (1, 0), (1, 0), "RIGHT"),
                ("LEFTPADDING", (0, 0), (-1, -1), 4 * mm),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4 * mm),
                ("TOPPADDING", (0, 0), (-1, -1), 3.5 * mm),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3.5 * mm),
            ]
        )
    )
    return table


def _styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "company": ParagraphStyle(
            "company",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=13,
            textColor=BRAND_DARK,
            leading=15,
            alignment=TA_LEFT,
        ),
        "company_subtitle": ParagraphStyle(
            "company_subtitle",
            parent=base["Normal"],
            fontSize=8,
            textColor=MUTED,
            leading=10,
        ),
        "document_title": ParagraphStyle(
            "document_title",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=17,
            textColor=BRAND_DARK,
            leading=19,
            alignment=TA_RIGHT,
        ),
        "document_subtitle": ParagraphStyle(
            "document_subtitle",
            parent=base["Normal"],
            fontSize=8.5,
            textColor=MUTED,
            leading=10,
            alignment=TA_RIGHT,
        ),
        "document_date": ParagraphStyle(
            "document_date",
            parent=base["Normal"],
            fontSize=7.5,
            textColor=MUTED,
            leading=10,
            alignment=TA_RIGHT,
            spaceBefore=3,
        ),
        "client_card": ParagraphStyle(
            "client_card",
            parent=base["Normal"],
            fontSize=9,
            textColor=INK,
            leading=13,
        ),
        "section": ParagraphStyle(
            "section",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=9.5,
            textColor=BRAND_DARK,
            leading=12,
            spaceAfter=2,
        ),
        "empty": ParagraphStyle(
            "empty",
            parent=base["Normal"],
            fontSize=9,
            textColor=MUTED,
            leading=12,
        ),
        "summary_label": ParagraphStyle(
            "summary_label",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=6.8,
            textColor=MUTED,
            leading=8,
            alignment=TA_RIGHT,
        ),
        "summary_value": ParagraphStyle(
            "summary_value",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=9.3,
            textColor=INK,
            leading=11,
            alignment=TA_RIGHT,
        ),
        "summary_value_current": ParagraphStyle(
            "summary_value_current",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=10.2,
            textColor=WHITE,
            leading=12,
            alignment=TA_RIGHT,
        ),
        "table_header": ParagraphStyle(
            "table_header",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=7,
            textColor=WHITE,
            leading=8,
        ),
        "table_header_right": ParagraphStyle(
            "table_header_right",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=7,
            textColor=WHITE,
            leading=8,
            alignment=TA_RIGHT,
        ),
        "cell": ParagraphStyle(
            "cell",
            parent=base["Normal"],
            fontSize=7.5,
            textColor=INK,
            leading=10,
        ),
        "concept": ParagraphStyle(
            "concept",
            parent=base["Normal"],
            fontSize=7.4,
            textColor=INK,
            leading=10,
        ),
        "cell_right": ParagraphStyle(
            "cell_right",
            parent=base["Normal"],
            fontSize=7.4,
            textColor=INK,
            leading=10,
            alignment=TA_RIGHT,
        ),
        "cell_right_balance": ParagraphStyle(
            "cell_right_balance",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=7.4,
            textColor=INK,
            leading=10,
            alignment=TA_RIGHT,
        ),
        "balance_label": ParagraphStyle(
            "balance_label",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=8,
            textColor=WHITE,
            leading=10,
        ),
        "balance_value": ParagraphStyle(
            "balance_value",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=12,
            textColor=WHITE,
            leading=14,
            alignment=TA_RIGHT,
        ),
    }
