from __future__ import annotations

import hashlib
import json
from datetime import date
from decimal import Decimal
from pathlib import Path

from app.config.database import database_proxy
from app.models.f150 import F150Batch, F150BatchRemittance
from app.models.remittances import Remittance
from app.models.system import AppParameter, NumberSequence
from app.services.audit_service import AuditService
from app.services.f150_encoder import (
    F150Carrier,
    F150Driver,
    F150Encoder,
    F150Item,
    F150Location,
    F150Party,
    F150Remittance,
    F150ValidationError,
    F150Vehicle,
)


F150_ORIGIN_PARAMETER = "f150.origin"


class F150BatchService:
    def __init__(self, current_user: str, audit_service: AuditService | None = None):
        self.current_user = current_user
        self.audit_service = audit_service or AuditService()
        self.encoder = F150Encoder()

    @staticmethod
    def eligible_remittances(
        *,
        date_from: date | None = None,
        date_to: date | None = None,
        client_id: int | None = None,
        number: str | None = None,
        status: str | None = None,
        included: bool | None = None,
    ) -> list[Remittance]:
        query = Remittance.select().order_by(Remittance.date.desc(), Remittance.id.desc())
        if date_from is not None:
            query = query.where(Remittance.date >= date_from)
        if date_to is not None:
            query = query.where(Remittance.date <= date_to)
        if client_id is not None:
            query = query.where(Remittance.client == client_id)
        if number and number.strip():
            pattern = f"%{number.strip()}%"
            query = query.where(
                (Remittance.remittance_number ** pattern)
                | (Remittance.physical_number ** pattern)
            )
        if status and status.strip():
            query = query.where(Remittance.status == status)

        rows = list(query)
        if included is None:
            return rows
        included_ids = {
            row.remittance_id for row in F150BatchRemittance.select(F150BatchRemittance.remittance)
        }
        return [row for row in rows if (row.id in included_ids) is included]

    @staticmethod
    def is_included(remittance: Remittance) -> bool:
        return F150BatchRemittance.select().where(
            F150BatchRemittance.remittance == remittance
        ).exists()

    def generate(
        self,
        remittances: list[Remittance],
        output_path: str | Path,
        *,
        process_date: date | None = None,
    ) -> F150Batch:
        if not remittances:
            raise F150ValidationError("Debe seleccionar al menos un remito.")
        selected = [Remittance.get_by_id(remittance.id) for remittance in remittances]
        documents = [self._to_document(remittance) for remittance in selected]
        content = self.encoder.encode(documents)

        output = Path(output_path)
        if output.suffix.lower() != ".txt":
            output = output.with_suffix(".TXT")
        if output.exists():
            raise FileExistsError(f"El archivo F150 ya existe: {output}")

        encoded = content.encode(self.encoder.encoding)
        digest = hashlib.sha256(encoded).hexdigest()
        created_output = False
        try:
            with database_proxy.atomic():
                repeated = [
                    self._identity(remittance)
                    for remittance in selected
                    if self.is_included(remittance)
                ]
                if repeated:
                    raise F150ValidationError(
                        "Los siguientes remitos ya fueron incluidos: " + ", ".join(repeated)
                    )
                sequence, _created = NumberSequence.get_or_create(
                    name="f150_batch", defaults={"current_number": 0}
                )
                sequence.current_number += 1
                sequence.save()
                batch = F150Batch.create(
                    batch_number=f"F150-{sequence.current_number:08d}",
                    process_date=process_date or date.today(),
                    file_name=output.name,
                    file_path=str(output.resolve()),
                    sha256=digest,
                    remittance_count=len(selected),
                    detail_count=sum(len(document.items) for document in documents),
                    created_by=self.current_user,
                )
                for remittance, document in zip(selected, documents):
                    F150BatchRemittance.create(
                        batch=batch,
                        remittance=remittance,
                        point_of_sale=remittance.physical_point_of_sale,
                        physical_number=remittance.physical_number,
                        snapshot=self._snapshot(remittance, document),
                    )
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_bytes(encoded)
                created_output = True
                self.audit_service.record(
                    user=self.current_user,
                    module="F150",
                    action="generar",
                    record_ref=f"F150Batch:{batch.id}",
                    new_value={
                        "batch_number": batch.batch_number,
                        "file_name": batch.file_name,
                        "sha256": batch.sha256,
                        "remittance_ids": [row.id for row in selected],
                    },
                )
            return batch
        except Exception:
            if created_output and output.exists():
                output.unlink()
            raise

    def _to_document(self, remittance: Remittance) -> F150Remittance:
        issues = self.validation_issues(remittance)
        if issues:
            raise F150ValidationError(
                f"Remito {self._identity(remittance)}: " + "; ".join(issues)
            )
        address = remittance.delivery_address
        carrier = remittance.carrier
        truck = remittance.truck
        driver = remittance.driver
        destination = F150Location(
            locality_name=remittance.delivery_city or address.city or "",
            province_code="",
            country_code="",
            country_name="",
        )
        origin = self._origin_location()
        items = []
        for row in remittance.items:
            product = row.product
            unit_price = Decimal(str(product.precio_neto_base or 0))
            quantity = Decimal(row.quantity)
            items.append(
                F150Item(
                    category_1="",
                    category_2="",
                    category_3="",
                    category_4="",
                    item_code=(product.codigo or product.name).strip(),
                    unit=row.unit,
                    quantity=quantity,
                    unit_price=unit_price,
                    total=quantity * unit_price,
                )
            )
        return F150Remittance(
            document_date=remittance.date,
            point_of_sale=remittance.physical_point_of_sale,
            number=remittance.physical_number,
            origin=origin,
            destination=F150Party(
                cuit=remittance.client_cuit or "",
                name=remittance.client_name,
                address=remittance.delivery_address_text,
                location=destination,
            ),
            carrier=F150Carrier(
                cuit=remittance.carrier_cuit or carrier.cuit or "",
                name=remittance.carrier_name or carrier.name,
            ),
            vehicle=F150Vehicle(
                chassis_plate=remittance.truck_domain or truck.domain,
                trailer_plate=truck.trailer_domain or "",
            ),
            driver=F150Driver(
                cuit=driver.cuit or "",
                name=remittance.driver_name or driver.name,
                document_number=remittance.driver_document or driver.document or "",
            ),
            items=tuple(items),
            observations=remittance.observations or "",
        )

    @staticmethod
    def validation_issues(remittance: Remittance) -> list[str]:
        issues = []
        if remittance.status != Remittance.STATUS_ISSUED:
            issues.append("debe estar emitido")
        if not remittance.physical_point_of_sale or not remittance.physical_number:
            issues.append("falta numeracion fisica")
        if not remittance.client_cuit:
            issues.append("falta CUIT del cliente")
        if remittance.carrier_id is None or not remittance.carrier_cuit:
            issues.append("falta transportista con CUIT")
        if remittance.truck_id is None or not remittance.truck_domain:
            issues.append("falta camion")
        if remittance.driver_id is None:
            issues.append("falta chofer")
        elif not (remittance.driver.cuit or remittance.driver_document):
            issues.append("falta CUIT o documento del chofer")
        if not remittance.items.exists():
            issues.append("no tiene detalle")
        if F150BatchService.is_included(remittance):
            issues.append("ya fue incluido en un lote F150")
        return issues

    @staticmethod
    def _identity(remittance: Remittance) -> str:
        return f"{remittance.physical_point_of_sale or '----'}-{remittance.physical_number or '--------'}"

    @staticmethod
    def _origin_location() -> F150Location:
        parameter = AppParameter.get_or_none(AppParameter.key == F150_ORIGIN_PARAMETER)
        if parameter is None or not parameter.value:
            return F150Location()
        try:
            values = json.loads(parameter.value)
        except (TypeError, ValueError):
            return F150Location()
        allowed = F150Location.__dataclass_fields__.keys()
        return F150Location(**{key: str(value) for key, value in values.items() if key in allowed})

    @staticmethod
    def _snapshot(remittance: Remittance, document: F150Remittance) -> dict:
        return {
            "remittance_id": remittance.id,
            "identity": document.identity,
            "date": document.document_date.isoformat(),
            "client": document.destination.name,
            "client_cuit": document.destination.cuit,
            "carrier": document.carrier.name,
            "carrier_cuit": document.carrier.cuit,
            "truck": document.vehicle.chassis_plate,
            "trailer": document.vehicle.trailer_plate,
            "driver": document.driver.name,
            "items": [
                {
                    "code": item.item_code,
                    "unit": item.unit,
                    "quantity": str(item.quantity),
                    "unit_price": str(item.unit_price),
                    "total": str(item.total),
                }
                for item in document.items
            ],
        }
