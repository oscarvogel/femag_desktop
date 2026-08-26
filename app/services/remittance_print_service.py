from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

from app.models.remittances import Remittance
from app.services.audit_service import AuditService


MM = 72.0 / 25.4


@dataclass(frozen=True)
class RemittancePrintTemplate:
    date_x: float = 160
    date_y: float = 252
    client_x: float = 30
    client_y: float = 229
    address_x: float = 30
    address_y: float = 218
    city_x: float = 105
    city_y: float = 218
    province_x: float = 158
    province_y: float = 218
    cuit_x: float = 30
    cuit_y: float = 207
    iva_x: float = 30
    iva_y: float = 197
    document_x: float = 128
    document_y: float = 207
    quantity_x: float = 24
    detail_x: float = 44
    first_detail_y: float = 178
    detail_step: float = 7.2
    max_detail_rows: int = 16
    carrier_x: float = 47
    carrier_y: float = 53
    carrier_cuit_x: float = 118
    carrier_cuit_y: float = 53
    truck_x: float = 160
    truck_y: float = 53
    driver_x: float = 47
    driver_y: float = 42
    driver_document_x: float = 165
    driver_document_y: float = 42
    offset_x: float = 0
    offset_y: float = 0
    content_shift_up_points: float = 5

    def calibrated(self, *, offset_x: float = 0, offset_y: float = 0):
        return replace(self, offset_x=offset_x, offset_y=offset_y)


class RemittancePrintService:
    def __init__(
        self,
        *,
        current_user: str,
        audit_service: AuditService | None = None,
        template: RemittancePrintTemplate | None = None,
    ):
        self.current_user = current_user
        self.audit_service = audit_service or AuditService()
        self.template = template or RemittancePrintTemplate()

    def export_preprinted(self, remittance: Remittance, output_path: str | Path) -> Path:
        remittance = Remittance.get_by_id(remittance.id)
        if remittance.status != Remittance.STATUS_ISSUED:
            raise ValueError("Solo se pueden imprimir remitos emitidos.")
        items = self._validated_items(remittance)
        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        pdf = canvas.Canvas(str(output), pagesize=A4)
        pdf.setTitle(f"Remito {remittance.remittance_number}")
        pdf.setFont("Helvetica", 9)
        self._draw_variable_fields(pdf, remittance, items)
        pdf.showPage()
        pdf.save()
        self._audit_export(remittance, output, mode="preimpreso")
        return output

    def export_preview(self, remittance: Remittance, output_path: str | Path) -> Path:
        """Genera una vista esquemática no fiscal para revisar posiciones y contenido.

        A diferencia de ``export_preprinted`` esta salida dibuja referencias visuales
        mínimas para que el operador pueda verificar el layout sin consumir una hoja
        del talonario real. No intenta recrear el formulario fiscal/preimpreso.
        """
        remittance = Remittance.get_by_id(remittance.id)
        items = self._validated_items(remittance)
        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        pdf = canvas.Canvas(str(output), pagesize=A4)
        pdf.setTitle(f"Vista previa no fiscal - {remittance.remittance_number}")

        pdf.setFont("Helvetica-Bold", 11)
        pdf.drawString(15 * MM, 286 * MM, "FEMAG - VISTA PREVIA DE REMITO / NO FISCAL")
        pdf.setFont("Helvetica", 7)
        pdf.drawString(
            15 * MM,
            281 * MM,
            "Referencia para validar datos y alineación. No reemplaza el formulario preimpreso.",
        )

        pdf.setLineWidth(0.4)
        pdf.rect(15 * MM, 188 * MM, 180 * MM, 78 * MM)
        pdf.rect(15 * MM, 62 * MM, 180 * MM, 123 * MM)
        pdf.rect(15 * MM, 30 * MM, 180 * MM, 30 * MM)
        pdf.setFont("Helvetica", 6)
        pdf.drawString(17 * MM, 263 * MM, "CLIENTE / DESTINO")
        pdf.drawString(17 * MM, 179 * MM, "DETALLE")
        pdf.drawString(17 * MM, 52 * MM, "TRANSPORTE")

        pdf.setFont("Helvetica", 9)
        self._draw_variable_fields(pdf, remittance, items)
        pdf.showPage()
        pdf.save()
        self._audit_export(remittance, output, mode="preview_no_fiscal")
        return output

    def export_calibration(self, output_path: str | Path) -> Path:
        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        pdf = canvas.Canvas(str(output), pagesize=A4)
        pdf.setFont("Helvetica", 7)
        for x in range(10, 201, 10):
            pdf.line(x * MM, 10 * MM, x * MM, 287 * MM)
            pdf.drawString((x + 1) * MM, 12 * MM, str(x))
        for y in range(10, 288, 10):
            pdf.line(10 * MM, y * MM, 200 * MM, y * MM)
            pdf.drawString(12 * MM, (y + 1) * MM, str(y))
        pdf.setFont("Helvetica-Bold", 10)
        pdf.drawString(15 * MM, 292 * MM, "FEMAG - hoja de calibracion de remito preimpreso")
        pdf.showPage()
        pdf.save()
        return output

    def _validated_items(self, remittance: Remittance):
        items = list(remittance.items)
        if len(items) > self.template.max_detail_rows:
            raise ValueError(
                f"El remito tiene {len(items)} renglones y el formulario admite "
                f"hasta {self.template.max_detail_rows}."
            )
        return items

    def _draw_variable_fields(self, pdf, remittance: Remittance, items) -> None:
        self._text(
            pdf,
            self.template.date_x,
            self.template.date_y,
            remittance.date.strftime("%d/%m/%Y"),
            shift_up=False,
        )
        self._text(pdf, self.template.client_x, self.template.client_y, remittance.client_name)
        self._text(pdf, self.template.address_x, self.template.address_y, remittance.delivery_address_text)
        self._text(pdf, self.template.city_x, self.template.city_y, remittance.delivery_city or "")
        self._text(pdf, self.template.province_x, self.template.province_y, remittance.delivery_province or "")
        self._text(pdf, self.template.cuit_x, self.template.cuit_y, remittance.client_cuit or "")
        self._text(pdf, self.template.iva_x, self.template.iva_y, remittance.client_iva_condition or "")
        self._text(pdf, self.template.document_x, self.template.document_y, remittance.document_reference or "")

        y = self.template.first_detail_y
        for item in items:
            self._text(pdf, self.template.quantity_x, y, self._quantity_text(item.quantity))
            self._text(pdf, self.template.detail_x, y, item.printed_description)
            y -= self.template.detail_step

        self._text(pdf, self.template.carrier_x, self.template.carrier_y, remittance.carrier_name or "")
        self._text(pdf, self.template.carrier_cuit_x, self.template.carrier_cuit_y, remittance.carrier_cuit or "")
        self._text(
            pdf,
            self.template.truck_x,
            self.template.truck_y,
            self._vehicle_domains(remittance),
        )
        self._text(pdf, self.template.driver_x, self.template.driver_y, remittance.driver_name or "")
        self._text(pdf, self.template.driver_document_x, self.template.driver_document_y, remittance.driver_document or "")

    def _audit_export(self, remittance: Remittance, output: Path, *, mode: str) -> None:
        self.audit_service.record(
            user=self.current_user,
            module="Remitos",
            action="imprimir" if mode == "preimpreso" else "vista previa",
            record_ref=f"Remittance:{remittance.id}",
            new_value={
                "remittance_number": remittance.remittance_number,
                "physical_number": self._physical_number(remittance),
                "mode": mode,
                "output": str(output),
                "offset_x_mm": self.template.offset_x,
                "offset_y_mm": self.template.offset_y,
                "content_shift_up_points": self.template.content_shift_up_points,
            },
        )

    def _text(
        self,
        pdf,
        x_mm: float,
        y_mm_from_bottom: float,
        value: str,
        *,
        shift_up: bool = True,
    ) -> None:
        x = (x_mm + self.template.offset_x) * MM
        y = (y_mm_from_bottom + self.template.offset_y) * MM
        if shift_up:
            y += self.template.content_shift_up_points
        pdf.drawString(x, y, str(value))

    @staticmethod
    def _vehicle_domains(remittance: Remittance) -> str:
        return " / ".join(
            value
            for value in (remittance.truck_domain, remittance.trailer_domain)
            if value
        )

    @staticmethod
    def _quantity_text(quantity) -> str:
        value = f"{quantity:.3f}".rstrip("0").rstrip(".")
        return value

    @staticmethod
    def _physical_number(remittance: Remittance) -> str | None:
        if remittance.physical_point_of_sale and remittance.physical_number:
            return f"{remittance.physical_point_of_sale}-{remittance.physical_number}"
        return None
