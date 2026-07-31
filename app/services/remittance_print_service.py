from datetime import datetime
from html import escape
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.models.remittances import Remittance, RemittanceItem
from app.services.audit_service import AuditService


class RemittancePrintService:
    def __init__(self, *, current_user: str, audit_service: AuditService | None = None):
        self.current_user = current_user
        self.audit_service = audit_service or AuditService()

    def export_pdf(self, remittance: Remittance, output_dir: str | Path) -> Path:
        remittance = Remittance.get_by_id(remittance.id)
        target_dir = Path(output_dir)
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / f"remito_{remittance.remittance_number}.pdf"
        self._build_pdf(remittance, target)
        self.audit_service.record(
            user=self.current_user,
            module="Remitos",
            action="imprimir",
            record_ref=f"Remittance:{remittance.id}",
            new_value={"file_path": str(target), "status": remittance.status},
        )
        return target

    def _build_pdf(self, remittance: Remittance, target: Path) -> None:
        styles = _styles()
        doc = SimpleDocTemplate(
            str(target),
            pagesize=A4,
            rightMargin=18 * mm,
            leftMargin=18 * mm,
            topMargin=15 * mm,
            bottomMargin=15 * mm,
            title=f"Remito {remittance.remittance_number}",
        )
        story = [
            Paragraph("GRAEF HERMANOS S.R.L.", styles["company"]),
            Paragraph("REMITO INTERNO - DOCUMENTO NO FISCAL", styles["title"]),
            Spacer(1, 4 * mm),
        ]
        if remittance.status == Remittance.STATUS_DRAFT:
            story.append(Paragraph("BORRADOR", styles["warning"]))
        elif remittance.status == Remittance.STATUS_ANNULLED:
            story.append(Paragraph("ANULADO", styles["annulled"]))
        story.extend(
            [
                Spacer(1, 3 * mm),
                _header_table(remittance, styles),
                Spacer(1, 6 * mm),
                Paragraph("PRODUCTOS", styles["section"]),
                Spacer(1, 2 * mm),
                _items_table(remittance, styles),
                Spacer(1, 7 * mm),
                Paragraph(f"Observaciones: {escape(remittance.observations or '-')}", styles["normal"]),
                Spacer(1, 14 * mm),
                Paragraph("Recibido por: ______________________________________________", styles["normal"]),
                Spacer(1, 6 * mm),
                Paragraph(
                    f"Generado el {datetime.now():%d/%m/%Y %H:%M}. No valido como comprobante fiscal.",
                    styles["footer"],
                ),
            ]
        )
        doc.build(story)


def _header_table(remittance: Remittance, styles: dict) -> Table:
    source = f"Orden #{remittance.source_order.order_number}" if remittance.source_order else "Carga manual"
    rows = [
        ["Numero", remittance.remittance_number, "Fecha", remittance.date.strftime("%d/%m/%Y")],
        ["Estado", remittance.status, "Origen", source],
        ["Cliente", remittance.client_name, "CUIT", remittance.client_cuit or "-"],
        ["Entrega", remittance.delivery_address_text, "Transporte", remittance.carrier_name or "-"],
        ["Chofer", remittance.driver_name or "-", "Emitido por", remittance.issued_by or "-"],
    ]
    data = [
        [
            Paragraph(escape(str(value)), styles["cell_bold"] if index in (0, 2) else styles["cell"])
            for index, value in enumerate(row)
        ]
        for row in rows
    ]
    table = Table(data, colWidths=[25 * mm, 65 * mm, 28 * mm, 56 * mm])
    table.setStyle(_grid_style())
    return table


def _items_table(remittance: Remittance, styles: dict) -> Table:
    data = [[
        Paragraph("Producto", styles["cell_bold"]),
        Paragraph("Cantidad", styles["cell_bold"]),
        Paragraph("Unidad", styles["cell_bold"]),
        Paragraph("Observaciones", styles["cell_bold"]),
    ]]
    for item in remittance.items.order_by(RemittanceItem.id):
        data.append([
            Paragraph(escape(item.product_name), styles["cell"]),
            Paragraph(f"{item.quantity:g}", styles["amount"]),
            Paragraph(escape(item.unit), styles["cell"]),
            Paragraph(escape(item.observations or "-"), styles["cell"]),
        ])
    table = Table(data, colWidths=[72 * mm, 30 * mm, 26 * mm, 46 * mm], repeatRows=1)
    style = _grid_style()
    style.add("BACKGROUND", (0, 0), (-1, 0), colors.whitesmoke)
    table.setStyle(style)
    return table


def _grid_style() -> TableStyle:
    return TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.55, colors.black),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ])


def _styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "company": ParagraphStyle("company", parent=base["Normal"], fontName="Helvetica-Bold", fontSize=13, alignment=TA_CENTER),
        "title": ParagraphStyle("title", parent=base["Normal"], fontName="Helvetica-Bold", fontSize=16, alignment=TA_CENTER, spaceBefore=4),
        "section": ParagraphStyle("section", parent=base["Normal"], fontName="Helvetica-Bold", fontSize=10),
        "normal": ParagraphStyle("normal", parent=base["Normal"], fontSize=9, leading=12),
        "cell": ParagraphStyle("cell", parent=base["Normal"], fontSize=8, leading=10, alignment=TA_LEFT),
        "cell_bold": ParagraphStyle("cell_bold", parent=base["Normal"], fontName="Helvetica-Bold", fontSize=8, leading=10),
        "amount": ParagraphStyle("amount", parent=base["Normal"], fontSize=8, alignment=TA_RIGHT),
        "warning": ParagraphStyle("warning", parent=base["Normal"], fontName="Helvetica-Bold", fontSize=12, textColor=colors.darkorange, alignment=TA_CENTER),
        "annulled": ParagraphStyle("annulled", parent=base["Normal"], fontName="Helvetica-Bold", fontSize=14, textColor=colors.red, alignment=TA_CENTER),
        "footer": ParagraphStyle("footer", parent=base["Normal"], fontSize=7, textColor=colors.grey, alignment=TA_CENTER),
    }
