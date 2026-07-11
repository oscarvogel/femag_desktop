from datetime import datetime
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.models.accounting import ClientAccountMovement
from app.models.masters import Client
from app.services.ledger_query_service import movements_for_client, running_balance


MOVEMENT_TYPE_LABELS = {
    "load_order_documental": "Orden de carga",
    "load_order_documental_reversal": "Reverso OC",
    "payment": "Pago",
}


def _reference(movement: ClientAccountMovement) -> str:
    if movement.load_order is not None:
        return f"OC-{movement.load_order.order_number:06d}"
    if movement.payment is not None:
        return movement.payment.receipt_number
    return movement.source_ref or "-"


def export_account_statement(client: Client, output_dir: str | Path) -> Path:
    path = Path(output_dir)
    path.mkdir(parents=True, exist_ok=True)
    safe_name = client.name.replace(" ", "_").replace("/", "-")
    target = path / f"extracto_{safe_name}.pdf"

    movements = movements_for_client(client)
    balances = running_balance(movements)
    styles = _styles()

    doc = SimpleDocTemplate(
        str(target),
        pagesize=A4,
        rightMargin=14 * mm,
        leftMargin=14 * mm,
        topMargin=12 * mm,
        bottomMargin=14 * mm,
        title=f"Extracto cuenta corriente - {client.name}",
    )

    story = [
        Paragraph("GRAEF HERMANOS S.R.L.", styles["company"]),
        Spacer(1, 5 * mm),
        Paragraph("EXTRACTO DE CUENTA CORRIENTE", styles["title"]),
        Spacer(1, 3 * mm),
        _header_table(client, styles),
        Spacer(1, 5 * mm),
    ]

    if not movements:
        story.append(Paragraph("El cliente no tiene movimientos en su cuenta corriente.", styles["normal"]))
    else:
        story.append(Paragraph("MOVIMIENTOS", styles["section"]))
        story.append(Spacer(1, 3 * mm))
        story.append(_movements_table(movements, balances, styles))

    doc.build(story)
    return target


def _header_table(client: Client, styles: dict) -> Table:
    data = [
        [Paragraph("Cliente:", styles["cell_bold"]), Paragraph(client.name, styles["cell"])],
        [Paragraph("CUIT:", styles["cell_bold"]), Paragraph(client.cuit or "-", styles["cell"])],
        [Paragraph("Fecha:", styles["cell_bold"]), Paragraph(datetime.now().strftime("%d/%m/%Y %H:%M"), styles["cell"])],
    ]
    table = Table(data, colWidths=[35 * mm, 135 * mm])
    table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    return table


def _movements_table(movements: list[ClientAccountMovement], balances: list[float], styles: dict) -> Table:
    header = [
        Paragraph("Fecha", styles["cell_bold"]),
        Paragraph("Tipo", styles["cell_bold"]),
        Paragraph("Referencia", styles["cell_bold"]),
        Paragraph("Descripcion", styles["cell_bold"]),
        Paragraph("Importe", styles["cell_bold"]),
        Paragraph("Saldo", styles["cell_bold"]),
    ]
    rows = [header]
    for movement, balance in zip(movements, balances):
        type_label = MOVEMENT_TYPE_LABELS.get(movement.movement_type, movement.movement_type)
        rows.append([
            Paragraph(movement.created_at.strftime("%d/%m/%Y %H:%M"), styles["cell"]),
            Paragraph(type_label, styles["cell"]),
            Paragraph(_reference(movement), styles["cell"]),
            Paragraph(movement.description, styles["cell"]),
            Paragraph(f"$ {movement.total_amount:,.2f}", styles["cell_right"]),
            Paragraph(f"$ {balance:,.2f}", styles["cell_right"]),
        ])
    # Totals row
    total_balance = float(balances[-1]) if balances else 0.0
    rows.append([
        Paragraph("", styles["cell"]),
        Paragraph("", styles["cell"]),
        Paragraph("", styles["cell"]),
        Paragraph("SALDO ACTUAL", styles["cell_bold"]),
        Paragraph(f"$ {total_balance:,.2f}", styles["cell_right_bold"]),
        Paragraph("", styles["cell"]),
    ])
    table = Table(rows, colWidths=[30 * mm, 28 * mm, 28 * mm, 40 * mm, 24 * mm, 24 * mm], repeatRows=1)
    table.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -2), 0.55, colors.black),
        ("BACKGROUND", (0, 0), (-1, 0), colors.whitesmoke),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("ALIGN", (4, 1), (5, -1), "RIGHT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LINEABOVE", (0, -1), (-1, -1), 1.5, colors.black),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    return table


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
        "normal": ParagraphStyle("normal", parent=base["Normal"], fontSize=9, leading=12),
        "cell": ParagraphStyle("cell", parent=base["Normal"], fontSize=8, leading=10),
        "cell_bold": ParagraphStyle(
            "cell_bold", parent=base["Normal"], fontName="Helvetica-Bold", fontSize=8, leading=10
        ),
        "cell_right": ParagraphStyle(
            "cell_right", parent=base["Normal"], fontSize=8, leading=10, alignment=TA_RIGHT
        ),
        "cell_right_bold": ParagraphStyle(
            "cell_right_bold", parent=base["Normal"], fontName="Helvetica-Bold", fontSize=8, leading=10,
            alignment=TA_RIGHT
        ),
    }
