from reportlab.graphics.barcode.qr import QrCodeWidget
from reportlab.graphics.shapes import Drawing
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, Table, TableStyle

from app.models.load_orders import LoadOrder
from app.services.rowspan_consolidated_load_order_print_service import (
    ConsolidatedLoadOrderPrintService as BaseConsolidatedLoadOrderPrintService,
)


class ConsolidatedLoadOrderPrintService(BaseConsolidatedLoadOrderPrintService):
    """Impresión operativa de órdenes con QR preparado para la futura webapp."""

    @staticmethod
    def _qr_payload(order: LoadOrder) -> str:
        return order.qr_payload()

    def _qr_drawing(self, order: LoadOrder) -> Drawing:
        widget = QrCodeWidget(self._qr_payload(order))
        x1, y1, x2, y2 = widget.getBounds()
        width = x2 - x1
        height = y2 - y1
        size = 22 * mm
        drawing = Drawing(
            size,
            size,
            transform=[size / width, 0, 0, size / height, 0, 0],
        )
        drawing.add(widget)
        return drawing

    def _header_table(self, order: LoadOrder) -> Table:
        """Mantiene el encabezado actual y agrega debajo un QR compacto."""
        header = super()._header_table(order)
        qr_note = Paragraph(
            "<b>QR de la orden</b><br/>"
            "<font size='7'>Identificador para carga de lote y fecha de elaboración.</font>",
            self.styles["normal"],
        )
        qr_panel = Table(
            [[qr_note, self._qr_drawing(order)]],
            colWidths=[145 * mm, 25 * mm],
        )
        qr_panel.setStyle(
            TableStyle(
                [
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("ALIGN", (1, 0), (1, 0), "RIGHT"),
                    ("TOPPADDING", (0, 0), (-1, -1), 2),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
                ]
            )
        )
        outer = Table([[header], [qr_panel]], colWidths=[170 * mm])
        outer.setStyle(
            TableStyle(
                [
                    ("LEFTPADDING", (0, 0), (-1, -1), 0),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                    ("TOPPADDING", (0, 0), (-1, -1), 0),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
                ]
            )
        )
        return outer
