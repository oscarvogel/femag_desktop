"""Codificador del archivo F150 compatible con el formulario legacy.

La estructura se obtuvo del formulario Visual FoxPro ``forms/f150.scx``:
un registro ``C`` por remito y un registro ``D`` por cada renglon, con campos
separados por ``@`` y salida ANSI (Windows-1252).

Este modulo no consulta la base de datos. Recibe snapshots completos para que
la seleccion, persistencia del lote y adaptacion desde MySQL puedan evolucionar
sin cambiar el contrato fiscal del archivo.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Iterable


class F150ValidationError(ValueError):
    """Los datos no permiten generar un archivo F150 consistente."""


@dataclass(frozen=True)
class F150Location:
    locality_code: str = ""
    locality_name: str = ""
    department_code: str = ""
    department_name: str = ""
    province_code: str = ""
    country_code: str = ""
    country_name: str = ""
    postal_code: str = ""


@dataclass(frozen=True)
class F150Party:
    cuit: str
    name: str
    address: str = ""
    door_number: str = ""
    location: F150Location = field(default_factory=F150Location)


@dataclass(frozen=True)
class F150Carrier:
    cuit: str
    name: str
    carrier_type: str = ""
    address: str = ""
    code: str = ""
    location: F150Location = field(default_factory=F150Location)


@dataclass(frozen=True)
class F150Vehicle:
    chassis_plate: str
    trailer_plate: str = ""
    chassis_type: str = ""
    trailer_type: str = ""
    plate_country_code: str = ""


@dataclass(frozen=True)
class F150Driver:
    cuit: str
    name: str
    document_number: str
    document_type: str = "DNI"
    address: str = ""
    door_number: str = ""
    location: F150Location = field(default_factory=F150Location)


@dataclass(frozen=True)
class F150Item:
    category_1: str
    category_2: str
    category_3: str
    category_4: str
    item_code: str
    unit: str
    quantity: Decimal
    unit_price: Decimal
    total: Decimal


@dataclass(frozen=True)
class F150Remittance:
    document_date: date
    point_of_sale: str
    number: str
    origin: F150Location
    destination: F150Party
    carrier: F150Carrier
    vehicle: F150Vehicle
    driver: F150Driver
    items: tuple[F150Item, ...]
    observations: str = ""
    document_type: str = "12"
    movement_type: str = "SAL"

    @property
    def identity(self) -> str:
        return f"{self.point_of_sale}-{self.number}"


class F150Encoder:
    """Valida y serializa snapshots F150 en el formato del sistema anterior."""

    encoding = "cp1252"
    line_ending = "\r\n"

    def encode(self, remittances: Iterable[F150Remittance]) -> str:
        documents = tuple(remittances)
        self._validate(documents)
        lines: list[str] = []
        for header_number, remittance in enumerate(documents, start=1):
            lines.append(self._header_line(header_number, remittance))
            lines.extend(self._detail_lines(header_number, remittance))
        return self.line_ending.join(lines) + self.line_ending

    def write(
        self,
        remittances: Iterable[F150Remittance],
        output_path: str | Path,
        *,
        overwrite: bool = False,
    ) -> Path:
        output = Path(output_path)
        if output.exists() and not overwrite:
            raise FileExistsError(f"El archivo F150 ya existe: {output}")
        content = self.encode(remittances)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(content.encode(self.encoding))
        return output

    @staticmethod
    def suggested_filename(process_date: date) -> str:
        return f"f150-{process_date:%Y%m%d}.TXT"

    def _header_line(self, header_number: int, remittance: F150Remittance) -> str:
        destination = remittance.destination
        carrier = remittance.carrier
        vehicle = remittance.vehicle
        driver = remittance.driver
        origin = remittance.origin
        dest_location = destination.location
        carrier_location = carrier.location
        driver_location = driver.location
        prefix = self._prefix("C", header_number, remittance.document_date)
        fields = (
            "1",
            remittance.document_type,
            remittance.point_of_sale,
            self._display_date(remittance.document_date),
            remittance.movement_type,
            origin.locality_code,
            dest_location.locality_code,
            dest_location.country_code,
            dest_location.province_code,
            carrier.carrier_type,
            carrier.cuit,
            carrier.name,
            carrier.address,
            carrier.code,
            carrier_location.department_code,
            carrier_location.department_name,
            carrier_location.locality_code,
            carrier_location.locality_name,
            carrier_location.province_code,
            carrier_location.country_code,
            vehicle.chassis_type,
            vehicle.chassis_plate,
            vehicle.trailer_type,
            vehicle.trailer_plate,
            vehicle.plate_country_code,
            remittance.observations,
            driver.cuit,
            driver.document_type,
            driver.document_number,
            driver.name,
            driver.address,
            driver.door_number,
            driver_location.department_code,
            driver_location.department_name,
            driver_location.locality_code,
            driver_location.locality_name,
            driver_location.province_code,
            driver_location.country_code,
            destination.cuit,
            destination.name,
            destination.address,
            destination.door_number,
            dest_location.postal_code,
            dest_location.department_name,
            dest_location.department_code,
            dest_location.locality_name,
            dest_location.locality_code,
            dest_location.province_code,
            dest_location.country_code,
            dest_location.country_name,
        )
        return self._join(prefix, fields)

    def _detail_lines(self, header_number: int, remittance: F150Remittance) -> list[str]:
        prefix = self._prefix("D", header_number, remittance.document_date)
        lines = []
        for item in remittance.items:
            fields = (
                "2",
                self._display_date(remittance.document_date),
                remittance.document_type,
                remittance.point_of_sale,
                remittance.number,
                item.category_1,
                item.category_2,
                item.category_3,
                item.category_4,
                item.item_code,
                item.unit,
                self._quantity(item.quantity),
                self._money(item.unit_price),
                self._money(item.total),
            )
            lines.append(self._join(prefix, fields))
        return lines

    @staticmethod
    def _prefix(record_type: str, header_number: int, document_date: date) -> str:
        return f"{record_type}{header_number}F150{document_date:%d%m%Y}"

    @staticmethod
    def _display_date(value: date) -> str:
        return value.strftime("%d-%m-%Y")

    @staticmethod
    def _join(prefix: str, fields: tuple[str, ...]) -> str:
        clean = [F150Encoder._clean(field) for field in fields]
        return prefix + "@" + "@".join(clean) + "@"

    @staticmethod
    def _clean(value: object) -> str:
        text = "" if value is None else str(value).strip()
        return text.replace("@", " ").replace("\r", " ").replace("\n", " ")

    @staticmethod
    def _quantity(value: Decimal) -> str:
        rounded = Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        return f"{rounded:,.0f}"

    @staticmethod
    def _money(value: Decimal) -> str:
        rounded = Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        return f"{rounded:,.2f}"

    @staticmethod
    def _validate(remittances: tuple[F150Remittance, ...]) -> None:
        if not remittances:
            raise F150ValidationError("Debe seleccionar al menos un remito.")
        identities: set[str] = set()
        for remittance in remittances:
            if remittance.identity in identities:
                raise F150ValidationError(f"El remito {remittance.identity} esta repetido.")
            identities.add(remittance.identity)
            if not remittance.point_of_sale.strip() or not remittance.number.strip():
                raise F150ValidationError("Todos los remitos deben tener punto de venta y numero.")
            if not remittance.items:
                raise F150ValidationError(f"El remito {remittance.identity} no tiene detalle.")
            for item in remittance.items:
                if item.quantity <= 0:
                    raise F150ValidationError(
                        f"El remito {remittance.identity} contiene una cantidad no positiva."
                    )
                expected_total = item.quantity * item.unit_price
                if abs(item.total - expected_total) > Decimal("0.01"):
                    raise F150ValidationError(
                        f"El total de un renglon del remito {remittance.identity} no coincide."
                    )
