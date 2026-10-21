"""Generación del PDF de sobres (#740).

El sobre es la etiqueta de un envío: va con el presupuesto, pero es un
documento distinto, sin precios, y tiene una forma física propia (235 x 120 mm
reales, confirmados por FEMAG el 20/10/2026).

Este módulo separa las tres cosas que el issue pide explícitamente:

* **consulta de datos**: de dónde sale el cliente, el domicilio de destino, el
  teléfono y la cantidad de pallets (``data_for_budget``);
* **render**: cómo se dibuja el sobre (``_render`` / ``_draw_envelope``);
* **dispositivo**: qué impresora y qué papel usan, que vive en
  ``app.config.envelope_settings``.

Nada de esto toca el presupuesto, el stock ni la cuenta corriente: el sobre se
genera a partir de datos ya persistidos y no modifica nada.

Sobre el conteo de pallets, que es el punto donde más fácil se inventa un
número: un pallet se vincula al cliente a través de
``LoadOrderPalletAllocation.pallet -> .destination -> .client``. El total de un
cliente es la cantidad de **pallets distintos** que tienen mercadería asignada
a un destino de ese cliente, no la cantidad de renglones de detalle ni el
identificador del pallet. Un pallet compartido entre dos clientes se cuenta en
los dos totales, y eso se avisa en vez de ocultarlo.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from app.config.envelope_settings import (
    EnvelopeSettings,
    load_envelope_settings,
)
from app.models.budgets import Budget
from app.models.load_orders import (
    LoadOrder,
    LoadOrderDestination,
    LoadOrderPalletAllocation,
)
from app.models.masters import Client, ClientAddress
from app.services.audit_service import AuditService

#: Marca que identifica a los PDFs generados por este servicio. Se usa para
#: saber si un archivo que ya existe en la carpeta es nuestro (y se puede
#: regenerar encima) o es de otro origen (y no se toca).
SUBJECT_MARKER = "FEMAG-SOBRE"

#: Logo oficial de FEMAG. Es el mismo asset que usa la aplicación, no una
#: copia dibujada: si el logo no está, el sobre se genera igual y queda
#: avisado, pero nunca se reemplaza por un logo inventado.
LOGO_FILE_NAME = "femag-logo-compact.png"

_LOGO_WIDTH_MM = 26.0

#: Resolucion con la que se embebe el logo. A 26 mm de ancho, 320 px dan algo
#: mas de 300 dpi: de sobra para una impresora de inyeccion de tinta, y el
#: PDF del sobre deja de pesar 375 KB.
_LOGO_TARGET_PX = 320


class EnvelopeDataError(ValueError):
    """No hay datos suficientes para generar un sobre de este presupuesto."""


@dataclass(frozen=True)
class EnvelopeData:
    """Datos de un sobre, ya resueltos y sin dependencias de la base."""

    client_name: str
    address_lines: tuple[str, ...]
    phone: str
    budget_reference: str
    pallet_count: int | None
    warnings: tuple[str, ...] = ()

    @property
    def is_usable(self) -> bool:
        return bool(self.client_name.strip()) and bool(self.address_lines)


@dataclass(frozen=True)
class EnvelopeFailure:
    """Un sobre que no se pudo generar, con el cliente y el motivo."""

    client_name: str
    reason: str


@dataclass
class EnvelopeExportResult:
    """Resultado de generar sobres para varios presupuestos."""

    paths: list[Path] = field(default_factory=list)
    failures: list[EnvelopeFailure] = field(default_factory=list)

    @property
    def failed_count(self) -> int:
        return len(self.failures)


class EnvelopePrintService:
    """Genera el PDF de un sobre a partir de un presupuesto ya guardado."""

    def __init__(
        self,
        current_user: str,
        audit_service: AuditService | None = None,
        settings: EnvelopeSettings | None = None,
    ):
        self.current_user = current_user
        self.audit_service = audit_service or AuditService()
        # Sin configuración inyectada se usa la del puesto: el sobre es un
        # elemento físico y cada equipo puede tener su propia calibración.
        self.settings = settings if settings is not None else load_envelope_settings()

    # ------------------------------------------------------------------
    # Consulta de datos
    # ------------------------------------------------------------------
    def data_for_budget(self, budget: Budget) -> EnvelopeData:
        """Reúne los datos del sobre de un presupuesto, sin inventar nada."""
        budget = Budget.get_by_id(budget.id)
        client = budget.client
        warnings: list[str] = []

        address_lines, address_warnings = self._address_for_budget(budget, client)
        warnings.extend(address_warnings)

        phone = (client.phone or "").strip()
        if not phone:
            warnings.append("El cliente no tiene teléfono cargado.")

        pallet_count, pallet_warnings = self._pallet_count_for_budget(budget)
        warnings.extend(pallet_warnings)

        return EnvelopeData(
            client_name=(client.name or "").strip(),
            address_lines=tuple(address_lines),
            phone=phone,
            budget_reference=budget.display_number,
            pallet_count=pallet_count,
            warnings=tuple(warnings),
        )

    def _address_for_budget(
        self, budget: Budget, client: Client
    ) -> tuple[list[str], list[str]]:
        """Domicilio de destino del presupuesto.

        Para un presupuesto de orden de carga manda el domicilio del destino de
        esa orden, que es adónde va la mercadería. Para un presupuesto manual
        se usa el domicilio principal del cliente, y si no hay, se avisa.
        """
        warnings: list[str] = []
        if budget.load_order_id is not None:
            order = LoadOrder.get_by_id(budget.load_order_id)
            destination = self._destination_for_client(order, client.id)
            if destination is None:
                warnings.append(
                    "La orden de carga no tiene un destino para este cliente: "
                    "no se pudo determinar el domicilio de destino."
                )
                return [], warnings
            address = destination.delivery_address
            lines = self._address_lines(address)
            if not lines:
                warnings.append("El destino de la orden de carga no tiene domicilio.")
            return lines, warnings

        address = self._primary_address(client)
        if address is None:
            warnings.append(
                "El presupuesto es manual y el cliente no tiene un domicilio "
                "principal cargado."
            )
            return [], warnings
        return self._address_lines(address), warnings

    @staticmethod
    def _destination_for_client(order: LoadOrder, client_id: int):
        for destination in order.destinations.order_by(LoadOrderDestination.sequence):
            if destination.client_id == client_id:
                return destination
        return None

    @staticmethod
    def _primary_address(client: Client) -> ClientAddress | None:
        query = client.addresses.where(ClientAddress.active == True)  # noqa: E712
        address = query.where(ClientAddress.is_primary == True).first()  # noqa: E712
        if address is not None:
            return address
        return query.order_by(ClientAddress.id).first()

    @staticmethod
    def _address_lines(address: ClientAddress | None) -> list[str]:
        if address is None:
            return []
        lines: list[str] = []
        street = (address.address or "").strip()
        city = (address.city or "").strip()
        province = (address.province or "").strip()
        if street:
            lines.append(street)
        locality = " - ".join(part for part in (city, province) if part)
        if locality:
            lines.append(locality)
        return lines

    def _pallet_count_for_budget(self, budget: Budget) -> tuple[int | None, list[str]]:
        """Pallets distintos con mercadería del cliente de este presupuesto."""
        warnings: list[str] = []
        if budget.load_order_id is None:
            warnings.append(
                "El presupuesto es manual: no hay orden de carga y por lo tanto "
                "no hay pallets asociados."
            )
            return None, warnings

        order = LoadOrder.get_by_id(budget.load_order_id)
        destinations = [
            destination
            for destination in order.destinations
            if destination.client_id == budget.client_id
        ]
        if not destinations:
            warnings.append(
                "La orden de carga no tiene un destino para este cliente: "
                "no hay pallets asociados."
            )
            return None, warnings

        pallet_ids: set[int] = set()
        for destination in destinations:
            for allocation in destination.pallet_allocations:
                pallet_ids.add(allocation.pallet_id)

        shared = self._shared_pallet_ids(order, budget.client_id, pallet_ids)
        if shared:
            warnings.append(
                f"{len(shared)} pallet(s) comparten mercadería con otro cliente: "
                "el total por cliente puede sumar más que los pallets físicos."
            )
        if not pallet_ids:
            # Cero pallets es un dato real, pero puede significar que la
            # mercaderia de este cliente va suelta. Se avisa para que el
            # operador no lo lea como "no hay nada para cargar".
            loose = sum(
                len(destination.loose_allocations) for destination in destinations
            )
            requested = sum(
                float(row.quantity)
                for destination in destinations
                for row in destination.products
            )
            if loose or requested:
                warnings.append(
                    "El cliente tiene mercadería en la orden pero sin pallets "
                    "asignados: el total de pallets es 0."
                )
        return len(pallet_ids), warnings

    @staticmethod
    def _shared_pallet_ids(
        order: LoadOrder, client_id: int, pallet_ids: set[int]
    ) -> set[int]:
        """Pallets de este cliente que además tienen mercadería de otro."""
        if not pallet_ids:
            return set()
        other_clients = {
            destination.client_id
            for destination in order.destinations
            if destination.client_id != client_id
        }
        if not other_clients:
            return set()
        rows = (
            LoadOrderPalletAllocation.select(LoadOrderPalletAllocation.pallet_id)
            .join(
                LoadOrderDestination,
                on=LoadOrderPalletAllocation.destination,
            )
            .where(LoadOrderPalletAllocation.pallet_id.in_(pallet_ids))
            .where(LoadOrderDestination.client_id.in_(other_clients))
            .distinct()
        )
        return {row.pallet_id for row in rows}

    # ------------------------------------------------------------------
    # Exportación
    # ------------------------------------------------------------------
    def export_envelope(self, budget: Budget, output_dir: str | Path) -> Path:
        """Genera el PDF del sobre de un presupuesto.

        Falla con ``EnvelopeDataError`` si no hay datos suficientes: un sobre
        sin nombre o sin domicilio no es un sobre, y no se genera uno a medias.
        """
        budget = Budget.get_by_id(budget.id)
        data = self.data_for_budget(budget)
        if not data.client_name.strip():
            raise EnvelopeDataError("El presupuesto no tiene cliente.")
        if not data.address_lines:
            raise EnvelopeDataError(
                "No se pudo determinar el domicilio de destino del cliente "
                f"'{data.client_name}'."
            )

        directory = Path(output_dir)
        directory.mkdir(parents=True, exist_ok=True)
        target = self._target_path(directory, budget)
        # Se dibuja aparte y recién después se pone en su lugar: un render
        # fallido no puede dejar un PDF roto con el nombre definitivo.
        partial = target.with_name(f"{target.name}.part")
        try:
            self._render(partial, data, self.settings)
            self._replace_atomically(partial, target)
        finally:
            if partial.exists():
                try:
                    partial.unlink()
                except OSError:
                    pass
        self.audit_service.record(
            user=self.current_user,
            module="Presupuestos",
            action="imprimir_sobre",
            record_ref=f"Budget:{budget.id}",
            new_value={
                "budget_number": budget.budget_number,
                "client_id": budget.client_id,
                "client_name": data.client_name,
                "load_order_id": budget.load_order_id,
                "file_path": str(target),
                "pallet_count": data.pallet_count,
                "warnings": list(data.warnings),
            },
        )
        return target

    def export_envelopes(
        self, budgets: list[Budget], output_dir: str | Path
    ) -> EnvelopeExportResult:
        """Genera un sobre por presupuesto, sin que uno rompa al resto.

        Un sobre que falla se informa con el cliente y el motivo; los demás se
        generan igual. Devuelve el detalle para que la interfaz no presente una
        exportación incompleta como exitosa.
        """
        result = EnvelopeExportResult()
        for budget in budgets:
            client_name = self._client_label(budget)
            try:
                result.paths.append(self.export_envelope(budget, output_dir))
            except Exception as exc:  # noqa: BLE001 - se informa, no se corta el lote
                result.failures.append(
                    EnvelopeFailure(client_name=client_name, reason=str(exc))
                )
        return result

    @staticmethod
    def _client_label(budget: Budget) -> str:
        """Nombre del cliente para informar una falla de forma identificable."""
        if not budget.client_id:
            return "Cliente desconocido"
        name = (budget.client.name or "").strip()
        if name:
            return name
        return f"Cliente {budget.client_id} (sin nombre)"

    def export_calibration_sheet(self, output_dir: str | Path) -> Path:
        """Genera una hoja de calibración para el sobre.

        Lleva el contorno del sobre, las marcas de los márgenes, una regla en
        milímetros y un bloque de dirección de ejemplo. Sirve para ajustar
        los desplazamientos en la Epson L3250 antes de imprimir en serie.
        """
        directory = Path(output_dir)
        directory.mkdir(parents=True, exist_ok=True)
        target = directory / "sobre_calibracion.pdf"
        self._render_calibration(target, self.settings)
        return target

    # ------------------------------------------------------------------
    # Render
    # ------------------------------------------------------------------
    def _render(self, target: Path, data: EnvelopeData, settings: EnvelopeSettings) -> None:
        from reportlab.lib.units import mm
        from reportlab.pdfgen import canvas as pdfcanvas

        page_width_mm, page_height_mm = settings.page_size_mm
        canvas = pdfcanvas.Canvas(
            str(target), pagesize=(page_width_mm * mm, page_height_mm * mm)
        )
        canvas.setTitle(f"Sobre {data.budget_reference} - {data.client_name}")
        canvas.setSubject(SUBJECT_MARKER)
        canvas.setAuthor("FEMAG")
        canvas.setCreator("FEMAG Desktop")

        canvas.saveState()
        # El contenido se dibuja siempre en su propio espacio (235 x 120 mm, en
        # horizontal) y despues se lleva a la pagina.
        #
        # OJO con el orden: reportlab fusiona las transformaciones consecutivas
        # en una sola matriz y las aplica a los puntos en orden INVERSO al de
        # emision (la ultima que se emite es la que actsua primero sobre el
        # punto). Por eso acá se emite al reves de como se aplican:
        # primero la pagina (con el desplazamiento), despues la rotacion, y
        # por ultimo el origen del sobre.
        #
        # Asi el desplazamiento queda en los ejes de la pagina impresa (no se
        # gira con la rotacion) y el sobre entra completo en la pagina: con
        # 90° el contenido cae fuera y el PDF sale en blanco.
        canvas.translate(
            (page_width_mm / 2 + settings.offset_x_mm) * mm,
            (page_height_mm / 2 + settings.offset_y_mm) * mm,
        )
        canvas.rotate(settings.rotation_deg)
        canvas.translate(
            -(settings.envelope_width_mm / 2) * mm,
            -(settings.envelope_height_mm / 2) * mm,
        )
        self._draw_envelope(canvas, data, settings)
        canvas.restoreState()

        canvas.showPage()
        canvas.save()

    def _draw_envelope(
        self, canvas, data: EnvelopeData, settings: EnvelopeSettings
    ) -> None:
        from reportlab.lib.units import mm

        width = settings.envelope_width_mm
        height = settings.envelope_height_mm
        margin = settings.margin_mm

        def mm_points(value: float) -> float:
            return value * mm

        if settings.show_logo:
            logo = self._logo_image()
            if logo is not None:
                canvas.drawImage(
                    logo,
                    mm_points(margin),
                    mm_points(height - margin - _LOGO_WIDTH_MM),
                    width=mm_points(_LOGO_WIDTH_MM),
                    height=mm_points(_LOGO_WIDTH_MM),
                    preserveAspectRatio=True,
                    mask="auto",
                )

        # Columna izquierda, pegada al borde inferior: que el presupuesto se
        # lea de un vistazo sin competir con el logo.
        if settings.show_budget_reference or settings.show_pallet_count:
            cursor = margin + 3.2 + 7 + 5.5
            if settings.show_budget_reference:
                canvas.setFont("Helvetica", 8)
                canvas.setFillColorRGB(0.35, 0.35, 0.35)
                canvas.drawString(mm_points(margin), mm_points(cursor), "Presupuesto")
                cursor -= 5.5
                canvas.setFont("Helvetica-Bold", 12)
                canvas.setFillColorRGB(0, 0, 0)
                canvas.drawString(
                    mm_points(margin), mm_points(cursor), data.budget_reference
                )
                cursor -= 7
            if settings.show_pallet_count:
                canvas.setFont("Helvetica", 9.5)
                canvas.setFillColorRGB(0, 0, 0)
                pallets = (
                    str(data.pallet_count)
                    if data.pallet_count is not None
                    else "sin dato"
                )
                canvas.drawString(
                    mm_points(margin), mm_points(cursor), f"Pallets: {pallets}"
                )

        # Columna derecha: destinatario, centrado verticalmente en el sobre.
        column_width = 105.0
        x = width - margin - column_width
        name_lines = self._wrap(data.client_name, "Helvetica-Bold", 12, column_width)
        address_lines: list[str] = []
        for line in data.address_lines:
            address_lines.extend(self._wrap(line, "Helvetica", 9.5, column_width))
        phone_lines = [f"Tel: {data.phone}"] if data.phone else []

        block_height = len(name_lines) * 5.5
        if address_lines:
            block_height += 1.5 + len(address_lines) * 4.6
        if phone_lines:
            block_height += 1.5 + len(phone_lines) * 4.4
        cursor = height / 2 + block_height / 2 - 4.4

        cursor = self._draw_lines(
            canvas, x, cursor, name_lines, "Helvetica-Bold", 12, 5.5
        )
        if address_lines:
            cursor -= 1.5
            cursor = self._draw_lines(
                canvas, x, cursor, address_lines, "Helvetica", 9.5, 4.6
            )
        if phone_lines:
            cursor -= 1.5
            self._draw_lines(canvas, x, cursor, phone_lines, "Helvetica", 9, 4.4)

    def _draw_lines(
        self,
        canvas,
        x: float,
        cursor: float,
        lines: list[str],
        font: str,
        size: float,
        leading: float,
    ) -> float:
        from reportlab.lib.units import mm

        canvas.setFont(font, size)
        canvas.setFillColorRGB(0, 0, 0)
        for line in lines:
            canvas.drawString(x * mm, cursor * mm, line)
            cursor -= leading
        return cursor

    @staticmethod
    def _wrap(text: str, font: str, size: float, max_width_mm: float) -> list[str]:
        """Parte un texto largo en líneas que entran en el ancho dado."""
        from reportlab.lib.units import mm
        from reportlab.pdfbase.pdfmetrics import stringWidth

        value = (text or "").strip()
        if not value:
            return []
        max_width = max_width_mm * mm
        words = value.split()
        if not words:
            return []
        lines: list[str] = []
        current = words[0]
        for word in words[1:]:
            candidate = f"{current} {word}"
            if stringWidth(candidate, font, size) <= max_width:
                current = candidate
            else:
                lines.append(current)
                current = word
        lines.append(current)
        return lines

    def _render_calibration(self, target: Path, settings: EnvelopeSettings) -> None:
        """Hoja de calibración: contornos, márgenes y regla en milímetros."""
        from reportlab.lib.units import mm
        from reportlab.pdfgen import canvas as pdfcanvas

        width = settings.envelope_width_mm
        height = settings.envelope_height_mm
        margin = settings.margin_mm
        page_width_mm, page_height_mm = settings.page_size_mm

        canvas = pdfcanvas.Canvas(
            str(target), pagesize=(page_width_mm * mm, page_height_mm * mm)
        )
        canvas.setTitle("Calibración de sobre FEMAG")
        canvas.setSubject(SUBJECT_MARKER)
        canvas.setAuthor("FEMAG")

        canvas.saveState()
        # Mismo orden inverso al de emision que en ``_render`` (ver la nota).
        canvas.translate(
            (page_width_mm / 2 + settings.offset_x_mm) * mm,
            (page_height_mm / 2 + settings.offset_y_mm) * mm,
        )
        canvas.rotate(settings.rotation_deg)
        canvas.translate(-(width / 2) * mm, -(height / 2) * mm)

        # Contorno del sobre.
        canvas.setStrokeColorRGB(0.75, 0.75, 0.75)
        canvas.setLineWidth(0.3)
        canvas.rect(0, 0, width * mm, height * mm)

        # Margen de seguridad.
        canvas.setStrokeColorRGB(0.85, 0.55, 0.55)
        canvas.setDash(2, 2)
        canvas.rect(
            margin * mm,
            margin * mm,
            (width - 2 * margin) * mm,
            (height - 2 * margin) * mm,
        )
        canvas.setDash()

        # Cruz de centro.
        canvas.setStrokeColorRGB(0.4, 0.4, 0.4)
        canvas.line((width / 2 - 4) * mm, (height / 2) * mm, (width / 2 + 4) * mm, (height / 2) * mm)
        canvas.line((width / 2) * mm, (height / 2 - 4) * mm, (width / 2) * mm, (height / 2 + 4) * mm)

        # Regla en milímetros.
        canvas.setStrokeColorRGB(0.2, 0.2, 0.2)
        canvas.setFont("Helvetica", 5)
        for step in range(0, int(width) + 1, 10):
            canvas.line(step * mm, 0, step * mm, 4 * mm)
            canvas.drawString(step * mm + 0.6, 4.6 * mm, str(step))
        for step in range(0, int(height) + 1, 10):
            canvas.line(0, step * mm, 4 * mm, step * mm)
            canvas.drawString(4.6 * mm, step * mm + 0.6, str(step))

        sample = EnvelopeData(
            client_name="CLIENTE DE EJEMPLO S.A.",
            address_lines=("CALLE 1234, PISO 2", "CORDOBA - CORDOBA"),
            phone="0351 1234567",
            budget_reference="PRES-000000",
            pallet_count=3,
        )
        self._draw_envelope(canvas, sample, settings)

        canvas.setFont("Helvetica", 6)
        canvas.setFillColorRGB(0.3, 0.3, 0.3)
        canvas.drawString(
            margin * mm,
            (margin - 4) * mm,
            f"Rotación {settings.rotation_deg}° | Offset X {settings.offset_x_mm:g} mm | "
            f"Offset Y {settings.offset_y_mm} mm | Página {page_width_mm:g} x {page_height_mm:g} mm",
        )

        canvas.restoreState()
        canvas.showPage()
        canvas.save()

    # ------------------------------------------------------------------
    # Archivos
    # ------------------------------------------------------------------
    def _target_path(self, directory: Path, budget: Budget) -> Path:
        """Nombre inequívoco del sobre, sin pisar archivos que no son nuestros.

        El nombre lleva cliente y presupuesto, así que la asociación es
        inequívoca y una reexportación vuelve al mismo archivo. Si ese
        nombre ya lo ocupa un archivo que no es un sobre de FEMAG, se usa un
        nombre con sufijo en vez de pisarlo.
        """
        base = f"sobre_{budget.client_id}_{budget.budget_number:06d}"
        candidate = directory / f"{base}.pdf"
        if not candidate.exists() or self._is_ours(candidate):
            return candidate
        index = 2
        while True:
            candidate = directory / f"{base}_{index}.pdf"
            if not candidate.exists() or self._is_ours(candidate):
                return candidate
            index += 1

    @staticmethod
    def _is_ours(path: Path) -> bool:
        try:
            from pypdf import PdfReader

            reader = PdfReader(str(path))
            metadata = reader.metadata
            subject = metadata.get("/Subject") if metadata else None
            return str(subject or "") == SUBJECT_MARKER
        except Exception:  # noqa: BLE001 - un archivo que no se puede leer no es nuestro
            return False

    @staticmethod
    def _logo_path() -> Path | None:
        try:
            from app.ui.branding import branding_asset_path

            path = branding_asset_path(LOGO_FILE_NAME)
        except Exception:  # noqa: BLE001 - sin logo se sigue, no se inventa uno
            return None
        return path if path.exists() else None

    @classmethod
    def _logo_image(cls):
        """El logo oficial, listo para embeber en el PDF.

        El asset original es un PNG de 640x640 que reportlab embebe entero: el
        PDF del sobre pesa 375 KB. A 26 mm de ancho, 320 px dan algo mas de
        300 dpi, que es lo que le sirve a una impresora de inyeccion de tinta,
        asi que se reescala antes de embeberlo. El logo es el oficial, con sus
        proporciones: no se redibuja ni se sustituye.
        """
        path = cls._logo_path()
        if path is None:
            return None
        try:
            from PIL import Image
            from reportlab.lib.utils import ImageReader

            with Image.open(path) as image:
                logo = image.convert("RGBA")
                logo.thumbnail((_LOGO_TARGET_PX, _LOGO_TARGET_PX))
                return ImageReader(logo)
        except Exception:  # noqa: BLE001 - sin reescalar tambien se imprime
            return str(path)

    @staticmethod
    def _replace_atomically(source: Path, target: Path) -> None:
        os.replace(source, target)
