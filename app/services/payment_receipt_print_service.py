from datetime import datetime
from html import escape
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.models.payments import ClientPayment, ClientPaymentDetail
from app.services.audit_service import AuditService


LEGACY_METHOD_LABELS = {
    ClientPayment.METHOD_CASH: "Efectivo",
    ClientPayment.METHOD_TRANSFER: "Transferencia",
    ClientPayment.METHOD_CHECK: "Cheque",
    ClientPayment.METHOD_RETENTION: "Retenciones / Percepciones",
    ClientPayment.METHOD_HOLISTOR: "Holistor",
    ClientPayment.METHOD_OTHER: "Otros",
    "multiple": "Múltiples medios",
}


class PaymentReceiptPrintService:
    def __init__(
        self,
        *,
        current_user: str,
        audit_service: AuditService | None = None,
    ):
        self.current_user = current_user
        self.audit_service = audit_service or AuditService()

    def export_pdf(
        self,
        payment: ClientPayment,
        output_dir: str | Path,
    ) -> Path:
        payment = ClientPayment.get_by_id(payment.id)
        path = Path(output_dir)
        path.mkdir(parents=True, exist_ok=True)
        target = path / f"recibo_{payment.receipt_number}.pdf"
        self._build_pdf(payment, target)
        self.audit_service.record(
            user=self.current_user,
            module="Cuenta corriente",
            action="imprimir_recibo",
            record_ref=f"ClientPayment:{payment.id}",
            new_value={
                "file_path": str(target),
                "receipt_number": payment.receipt_number,
                "status": payment.status,
            },
        )
        return target

    def _build_pdf(self, payment: ClientPayment, target: Path) -> None:
        styles = _styles()
        doc = SimpleDocTemplate(
            str(target),
            pagesize=A4,
            rightMargin=22 * mm,
            leftMargin=22 * mm,
            topMargin=18 * mm,
            bottomMargin=18 * mm,
            title=f"Recibo {payment.receipt_number}",
        )
        story = [
            Paragraph("GRAEF HERMANOS S.R.L.", styles["company"]),
            Spacer(1, 5 * mm),
            Paragraph("RECIBO DE PAGO", styles["title"]),
            Spacer(1, 4 * mm),
        ]
        if payment.status == ClientPayment.STATUS_ANNULLED:
            story.extend(
                [
                    Paragraph("ANULADO", styles["annulled"]),
                    Spacer(1, 3 * mm),
                ]
            )
        story.extend(
            [
                _header_table(payment, styles),
                Spacer(1, 7 * mm),
                Paragraph("DETALLE DEL PAGO", styles["section"]),
                Spacer(1, 3 * mm),
                _payment_table(payment, styles),
                Spacer(1, 16 * mm),
                Paragraph(
                    "Firma y aclaración: ______________________________________________",
                    styles["normal"],
                ),
                Spacer(1, 7 * mm),
                Paragraph(
                    f"Documento generado el {datetime.now():%d/%m/%Y %H:%M}",
                    styles["footer"],
                ),
            ]
        )
        doc.build(story)


def _header_table(payment: ClientPayment, styles: dict) -> Table:
    status = "ANULADO" if payment.status == ClientPayment.STATUS_ANNULLED else "ACTIVO"
    data = [
        [
            Paragraph("Recibo:", styles["cell_bold"]),
            Paragraph(escape(payment.receipt_number), styles["cell"]),
            Paragraph("Estado:", styles["cell_bold"]),
            Paragraph(status, styles["cell"]),
        ],
        [
            Paragraph("Cliente:", styles["cell_bold"]),
            Paragraph(escape(payment.client.name), styles["cell"]),
            Paragraph("CUIT:", styles["cell_bold"]),
            Paragraph(escape(payment.client.cuit or "-"), styles["cell"]),
        ],
        [
            Paragraph("Fecha de pago:", styles["cell_bold"]),
            Paragraph(payment.payment_date.strftime("%d/%m/%Y"), styles["cell"]),
            Paragraph("Registrado por:", styles["cell_bold"]),
            Paragraph(escape(payment.created_by or "-"), styles["cell"]),
        ],
    ]
    table = Table(data, colWidths=[30 * mm, 61 * mm, 31 * mm, 44 * mm])
    table.setStyle(
        TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 0.55, colors.black),
                ("BACKGROUND", (0, 0), (0, -1), colors.whitesmoke),
                ("BACKGROUND", (2, 0), (2, -1), colors.whitesmoke),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    return table


def _payment_table(payment: ClientPayment, styles: dict) -> Table:
    details = list(
        ClientPaymentDetail.select()
        .where(ClientPaymentDetail.payment == payment)
        .order_by(ClientPaymentDetail.sequence, ClientPaymentDetail.id)
    )
    if details:
        rows = [[
            Paragraph("Medio", styles["cell_bold"]),
            Paragraph("Referencia / comprobante", styles["cell_bold"]),
            Paragraph("Importe", styles["cell_bold"]),
        ]]
        for detail in details:
            rows.append(
                [
                    Paragraph(escape(detail.payment_method.name), styles["cell"]),
                    Paragraph(escape(detail.reference or "-"), styles["cell"]),
                    Paragraph(f"$ {detail.amount:,.2f}", styles["amount_small"]),
                ]
            )
        total_row = len(rows)
        rows.append(
            [
                Paragraph("TOTAL", styles["cell_bold"]),
                "",
                Paragraph(f"$ {payment.amount:,.2f}", styles["amount"]),
            ]
        )
        spans = [("SPAN", (0, total_row), (1, total_row))]
        if payment.observations:
            row = len(rows)
            rows.append(
                [
                    Paragraph("Observaciones", styles["cell_bold"]),
                    Paragraph(escape(payment.observations), styles["cell"]),
                    "",
                ]
            )
            spans.append(("SPAN", (1, row), (2, row)))
        if payment.status == ClientPayment.STATUS_ANNULLED:
            for label, value in (
                ("Anulado por", payment.annulled_by or "-"),
                (
                    "Fecha de anulación",
                    _display_datetime(payment.annulled_at) if payment.annulled_at else "-",
                ),
                ("Motivo", payment.annulment_reason or "-"),
            ):
                row = len(rows)
                rows.append(
                    [
                        Paragraph(label, styles["cell_bold"]),
                        Paragraph(escape(str(value)), styles["cell"]),
                        "",
                    ]
                )
                spans.append(("SPAN", (1, row), (2, row)))
        table = Table(rows, colWidths=[52 * mm, 76 * mm, 38 * mm])
        table.setStyle(
            TableStyle(
                [
                    ("GRID", (0, 0), (-1, -1), 0.55, colors.black),
                    ("BACKGROUND", (0, 0), (-1, 0), colors.whitesmoke),
                    ("BACKGROUND", (0, total_row), (-1, total_row), colors.whitesmoke),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("TOPPADDING", (0, 0), (-1, -1), 6),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                    *spans,
                ]
            )
        )
        return table

    # Compatibilidad con recibos creados antes de la grilla de medios.
    rows = [
        [Paragraph("Importe", styles["cell_bold"]), Paragraph(f"$ {payment.amount:,.2f}", styles["amount"])],
        [
            Paragraph("Medio de pago", styles["cell_bold"]),
            Paragraph(escape(LEGACY_METHOD_LABELS.get(payment.method, payment.method)), styles["cell"]),
        ],
        [Paragraph("Referencia", styles["cell_bold"]), Paragraph(escape(payment.reference or "-"), styles["cell"])],
        [Paragraph("Observaciones", styles["cell_bold"]), Paragraph(escape(payment.observations or "-"), styles["cell"])],
    ]
    if payment.status == ClientPayment.STATUS_ANNULLED:
        rows.extend(
            [
                [Paragraph("Anulado por", styles["cell_bold"]), Paragraph(escape(payment.annulled_by or "-"), styles["cell"])],
                [
                    Paragraph("Fecha de anulación", styles["cell_bold"]),
                    Paragraph(_display_datetime(payment.annulled_at) if payment.annulled_at else "-", styles["cell"]),
                ],
                [Paragraph("Motivo", styles["cell_bold"]), Paragraph(escape(payment.annulment_reason or "-"), styles["cell"])],
            ]
        )
    table = Table(rows, colWidths=[46 * mm, 120 * mm])
    table.setStyle(
        TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 0.55, colors.black),
                ("BACKGROUND", (0, 0), (0, -1), colors.whitesmoke),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    return table


def _display_datetime(value) -> str:
    if value.tzinfo is not None:
        value = value.astimezone()
    return value.strftime("%d/%m/%Y %H:%M")


def _styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "company": ParagraphStyle(
            "company",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=13,
            alignment=TA_CENTER,
            leading=16,
        ),
        "title": ParagraphStyle(
            "title",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=16,
            alignment=TA_CENTER,
            leading=20,
        ),
        "annulled": ParagraphStyle(
            "annulled",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=22,
            textColor=colors.HexColor("#b91c1c"),
            alignment=TA_CENTER,
            leading=26,
        ),
        "section": ParagraphStyle(
            "section",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=10,
            alignment=TA_LEFT,
            leading=13,
        ),
        "normal": ParagraphStyle(
            "normal",
            parent=base["Normal"],
            fontSize=9,
            leading=12,
        ),
        "cell": ParagraphStyle(
            "cell",
            parent=base["Normal"],
            fontSize=9,
            leading=12,
        ),
        "cell_bold": ParagraphStyle(
            "cell_bold",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=9,
            leading=12,
        ),
        "amount": ParagraphStyle(
            "amount",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=13,
            alignment=TA_RIGHT,
            leading=16,
        ),
        "amount_small": ParagraphStyle(
            "amount_small",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=9,
            alignment=TA_RIGHT,
            leading=12,
        ),
        "footer": ParagraphStyle(
            "footer",
            parent=base["Normal"],
            fontSize=7,
            textColor=colors.HexColor("#64748b"),
            alignment=TA_RIGHT,
            leading=9,
        ),
    }
