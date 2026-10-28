from reportlab.graphics.barcode.qr import QrCodeWidget
from reportlab.graphics.shapes import Drawing
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, Table, TableStyle

from app.models.load_orders import LoadOrder
from app.services.rowspan_consolidated_load_order_print_service import (
    ConsolidatedLoadOrderPrintService as BaseConsolidatedLoadOrderPrintService,
)
from app.services.webapp_configuration_service import WebappConfigurationService


class ConsolidatedLoadOrderPrintService(BaseConsolidatedLoadOrderPrintService):
    """Impresión operativa de órdenes con QR navegable hacia la webapp."""

    def _qr_payload(self, order: LoadOrder) -> str | None:
        """URL absoluta del QR o ``None`` si falta configurar el servidor.

        Devolver ``None`` es a propósito: sin URL base no se imprime un QR con
        el formato viejo, porque desde un lector genérico no abriría nada y
        parecería un acceso web válido.
        """
        if not WebappConfigurationService.public_url():
            return None
        return WebappConfigurationService.order_url(order.ensure_qr_token())

    def _qr_drawing(self, order: LoadOrder) -> Drawing | None:
        payload = self._qr_payload(order)
        if payload is None:
            return None
        widget = QrCodeWidget(payload)
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
        """Mantiene el encabezado actual y agrega debajo el QR navegable."""
        header = super()._header_table(order)
        base_url = WebappConfigurationService.public_url()
        qr_drawing = self._qr_drawing(order)
        order_label = f"Orden Nro. {order.order_number:04d}"

        if qr_drawing is None:
            qr_note = Paragraph(
                "<b>QR de acceso no configurado</b><br/>"
                "<font size='7'>Configure la URL del servidor web en "
                "Sistema &gt; Servidor web. La orden se imprime sin QR para no "
                f"imprimir un acceso engañoso. {order_label}.</font>",
                self.styles["normal"],
            )
            qr_panel = Table([[qr_note]], colWidths=[170 * mm])
            qr_panel.setStyle(
                TableStyle(
                    [
                        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                        ("TOPPADDING", (0, 0), (-1, -1), 2),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
                    ]
                )
            )
        else:
            qr_note = Paragraph(
                "<b>QR de la orden</b><br/>"
                "<font size='7'>Abra la orden desde el celular para cargar lote y "
                f"fecha de elaboración.<br/><b>Servidor:</b> {base_url}<br/>"
                f"<b>{order_label}</b></font>",
                self.styles["normal"],
            )
            qr_panel = Table(
                [[qr_note, qr_drawing]],
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
