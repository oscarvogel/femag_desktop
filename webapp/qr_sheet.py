"""Hoja imprimible con un QR por turno de produccion (#754).

El QR lleva la URL de la pantalla de produccion con el turno ya puesto, asi
que el operario de la planta escanea y carga: no tiene que elegir el turno ni
escribir la direccion.

La URL se arma con ``FEMAG_WEB_PUBLIC_URL`` cuando esta definido (es lo
recomendado en un despliegue con Caddy delante, porque el proxy no deja que
Flask sepa el host publico) y, si no, con la URL que ve el propio servidor.
"""

from __future__ import annotations

from io import BytesIO

from reportlab.graphics import renderPDF
from reportlab.graphics.barcode.qr import QrCodeWidget
from reportlab.graphics.shapes import Drawing
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas as pdf_canvas

PAGE_WIDTH = 210 * mm
PAGE_HEIGHT = 297 * mm
MARGIN = 18 * mm
QR_SIZE = 32 * mm


def _qr_drawing(payload: str, size: float = QR_SIZE) -> Drawing:
    widget = QrCodeWidget(payload)
    x1, y1, x2, y2 = widget.getBounds()
    width = x2 - x1
    height = y2 - y1
    drawing = Drawing(
        size,
        size,
        transform=[size / width, 0, 0, size / height, 0, 0],
    )
    drawing.add(widget)
    return drawing


def _draw_wrapped(pdf, text: str, x: float, y: float, width: float, font_size=8) -> float:
    """Escribe el texto partido en lineas que entren en ``width``.

    Devuelve la nueva coordenada ``y`` para seguir escribiendo debajo.
    """
    pdf.setFont("Helvetica", font_size)
    line = ""
    for word in text.split():
        candidate = f"{line} {word}".strip()
        if pdf.stringWidth(candidate, "Helvetica", font_size) > width and line:
            pdf.drawString(x, y, line)
            y -= font_size * 1.3
            line = word
        else:
            line = candidate
    if line:
        pdf.drawString(x, y, line)
        y -= font_size * 1.3
    return y


def build_turno_sheet(turnos, url_builder) -> bytes:
    """Arma el PDF con un QR por turno.

    ``url_builder`` recibe el nombre del turno y devuelve la URL absoluta que
    se imprime en el QR.
    """
    buffer = BytesIO()
    pdf = pdf_canvas.Canvas(buffer, pagesize=(PAGE_WIDTH, PAGE_HEIGHT))
    pdf.setTitle("FEMAG - QR de turnos de produccion")

    y = PAGE_HEIGHT - MARGIN
    pdf.setFont("Helvetica-Bold", 16)
    pdf.drawString(MARGIN, y, "FEMAG - QR de turnos de produccion")
    y -= 7 * mm
    pdf.setFont("Helvetica", 9)
    pdf.drawString(
        MARGIN,
        y,
        "Imprimi este QR y pegalo en la planta. El operario lo escanea con el "
        "celular y el turno queda prellenado.",
    )
    y -= 14 * mm

    for turno in turnos:
        if y < QR_SIZE + 30 * mm:
            pdf.showPage()
            y = PAGE_HEIGHT - MARGIN
        payload = url_builder(turno)
        pdf.setFont("Helvetica-Bold", 12)
        pdf.drawString(MARGIN, y - 5 * mm, str(turno))
        renderPDF.draw(_qr_drawing(payload), pdf, x=MARGIN, y=y - QR_SIZE - 5 * mm)
        text_x = MARGIN + QR_SIZE + 8 * mm
        _draw_wrapped(pdf, payload, text_x, y - 8 * mm, PAGE_WIDTH - MARGIN - text_x)
        y -= QR_SIZE + 18 * mm

    pdf.save()
    return buffer.getvalue()
