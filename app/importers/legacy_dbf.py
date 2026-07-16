from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.models.base import utc_now
from app.models.masters import Carrier, Client, ClientAddress, Driver, Product, Truck
from app.models.system import ImportBatch


ENTITY_KEYS = ("clients", "carriers", "drivers", "trucks", "products")


@dataclass(frozen=True)
class ImportOutcome:
    action: str
    warnings: tuple[dict[str, str], ...] = ()
    related_actions: tuple[tuple[str, str], ...] = ()


class LegacyDbfMasterImporter:
    def import_dbf_files(
        self,
        paths_by_entity: Mapping[str, str | Path],
        *,
        source_system: str = "legacy_dbf",
        encoding: str = "cp1252",
    ) -> dict[str, dict[str, Any]]:
        rows_by_entity = {
            entity: self._read_dbf(path, encoding=encoding)
            for entity, path in paths_by_entity.items()
            if entity in ENTITY_KEYS
        }
        return self.import_rows(rows_by_entity, source_system=source_system)

    def import_rows(
        self,
        rows_by_entity: Mapping[str, Iterable[Mapping[str, Any]]],
        *,
        source_system: str = "legacy_dbf",
    ) -> dict[str, dict[str, Any]]:
        batch = ImportBatch.create(source_system=source_system, status="running")
        summary = self._empty_summary()

        for entity in ENTITY_KEYS:
            rows = rows_by_entity.get(entity, [])
            handler = getattr(self, f"_import_{entity}")
            for raw_row in rows:
                row = self._normalize_row(raw_row)
                try:
                    outcome = handler(row, source_system, batch)
                    summary[entity][outcome.action] += 1
                    summary[entity]["warnings"].extend(outcome.warnings)
                    for related_entity, related_action in outcome.related_actions:
                        summary[related_entity][related_action] += 1
                except ValueError as exc:
                    summary[entity]["errors"].append(
                        {"source_id": self._value(row, "CODIGO", "ID", "IDLEGACY"), "message": str(exc)}
                    )

        batch.status = "success" if not any(summary[entity]["errors"] for entity in ENTITY_KEYS) else "partial"
        batch.finished_at = utc_now()
        batch.summary = json.dumps(summary, ensure_ascii=True, sort_keys=True)
        batch.save()
        return summary

    def _import_clients(self, row: dict[str, Any], source_system: str, batch: ImportBatch) -> ImportOutcome:
        source_id = self._required(row, "clients", "CODIGO", "ID", "IDLEGACY")
        name = self._required(row, "clients", "RAZON", "NOMBRE", "CLIENTE")
        cuit = self._clean_cuit(self._required(row, "clients", "CUIT", "CUITCLI"))
        values = {
            "name": name,
            "cuit": cuit,
            "iva_condition": self._value(row, "IVA", "CONDIVA", default="RI"),
            "phone": self._value(row, "TELEFONO", "TEL", "PHONE"),
            "email": self._value(row, "EMAIL", "MAIL"),
            "contact": self._value(row, "CONTACTO"),
        }
        action = self._upsert(Client, {"cuit": cuit}, values, source_system, source_id, batch)
        client = Client.get(Client.cuit == cuit)
        self._ensure_client_addresses(client, row)
        return ImportOutcome(action)

    def _ensure_client_addresses(self, client: Client, row: dict[str, Any]) -> None:
        address = self._value(row, "DOMICILIO", "DIRECCION", "ADDRESS")
        if not address:
            return

        city = self._value(row, "IMPOSITIVO", "CIUDAD", "CITY", default="Sin especificar")
        postal_code = self._value(row, "CODPOS", "CODIGOPOSTAL", "CP")
        observations = f"Código postal: {postal_code}" if postal_code else None
        existing_types = {
            item.address_type
            for item in ClientAddress.select(ClientAddress.address_type).where(ClientAddress.client == client)
        }
        for address_type in ("fiscal", "entrega"):
            if address_type in existing_types:
                continue
            ClientAddress.create(
                client=client,
                address_type=address_type,
                province="Sin especificar",
                city=city,
                address=address,
                is_primary=True,
                observations=observations,
            )

    def _import_carriers(self, row: dict[str, Any], source_system: str, batch: ImportBatch) -> ImportOutcome:
        source_id = self._required(row, "carriers", "CODIGO", "ID", "IDLEGACY")
        name = self._required(row, "carriers", "NOMBRE", "RAZON", "TRANSPORTISTA")
        values = {
            "name": name,
            "cuit": self._clean_cuit(self._value(row, "CUIT", "CUITTRA")) or None,
            "phone": self._value(row, "TELEFONO", "TEL", "PHONE"),
        }
        return ImportOutcome(self._upsert(Carrier, {"name": name}, values, source_system, source_id, batch))

    def _import_drivers(self, row: dict[str, Any], source_system: str, batch: ImportBatch) -> ImportOutcome:
        source_id = self._required(row, "drivers", "CODIGO", "ID", "IDLEGACY")
        name = self._required(row, "drivers", "NOMBRE", "CHOFER")
        existing_driver = (
            Driver.select()
            .where((Driver.source_system == source_system) & (Driver.source_id == source_id))
            .first()
        ) or Driver.select().where(Driver.name == name).first()
        explicit_carrier_source_id = self._value(row, "TRANSP", "TRANSPORTISTA", "CARRIER")
        if explicit_carrier_source_id:
            carrier = self._get_carrier(source_system, explicit_carrier_source_id)
            warnings = ()
        else:
            carrier, warnings = self._resolve_driver_carrier(row, source_system)
        if carrier is None and existing_driver is not None and existing_driver.carrier_id is not None:
            carrier = existing_driver.carrier
        usual_truck, truck_action, truck_warnings = self._upsert_habitual_truck(
            row,
            carrier,
            source_system,
            source_id,
            batch,
        )
        if usual_truck is None and existing_driver is not None and existing_driver.usual_truck_id is not None:
            usual_truck = existing_driver.usual_truck
        values = {
            "name": name,
            "carrier": carrier,
            "usual_truck": usual_truck,
            "cuit": self._clean_cuit(self._value(row, "CUIT", "CUITCHOFER")) or None,
            "document": self._value(row, "DNI", "DOCUMENTO", "DOC"),
            "phone": self._value(row, "TELEFONO", "TEL", "PHONE"),
        }
        action = self._upsert(Driver, {"name": name}, values, source_system, source_id, batch)
        related_actions = (("trucks", truck_action),) if truck_action is not None else ()
        return ImportOutcome(action, warnings + truck_warnings, related_actions)

    def _import_trucks(self, row: dict[str, Any], source_system: str, batch: ImportBatch) -> ImportOutcome:
        source_id = self._required(row, "trucks", "CODIGO", "ID", "IDLEGACY")
        domain = self._clean_domain(self._required(row, "trucks", "PATENTE", "DOMINIO", "DOMAIN"))
        carrier_source_id = self._required(row, "trucks", "TRANSP", "TRANSPORTISTA", "CARRIER")
        carrier = self._get_carrier(source_system, carrier_source_id)
        values = {"domain": domain, "carrier": carrier}
        return ImportOutcome(self._upsert(Truck, {"domain": domain}, values, source_system, source_id, batch))

    def _import_products(self, row: dict[str, Any], source_system: str, batch: ImportBatch) -> ImportOutcome:
        source_id = self._required(row, "products", "CODIGO", "ID", "IDLEGACY")
        name = self._required(row, "products", "NOMBRE", "PRODUCTO", "DESCRIP")
        values = {"name": name, "unit": self._value(row, "UNIDAD", "UNI", default="unidad")}
        return ImportOutcome(self._upsert(Product, {"name": name}, values, source_system, source_id, batch))

    def _resolve_driver_carrier(
        self,
        row: dict[str, Any],
        source_system: str,
    ) -> tuple[Carrier | None, tuple[dict[str, str], ...]]:
        source_id = self._value(row, "CODIGO", "ID", "IDLEGACY")
        driver_cuit = self._clean_cuit(self._value(row, "CUIT", "CUITCHOFER"))
        driver_name = self._clean_identity_name(self._value(row, "NOMBRE", "CHOFER"))
        by_code = self._find_carrier_by_source_id(source_system, source_id)

        if by_code is not None and self._carrier_identity_matches(by_code, driver_cuit, driver_name):
            return by_code, ()

        cuit_matches = self._find_carriers_by_cuit(driver_cuit)
        if len(cuit_matches) == 1:
            return cuit_matches[0], ()
        if len(cuit_matches) > 1:
            return None, ({"code": "carrier_cuit_ambiguous", "source_id": source_id},)
        if by_code is not None:
            return None, ({"code": "carrier_code_collision", "source_id": source_id},)
        return None, ({"code": "carrier_not_found", "source_id": source_id},)

    def _upsert_habitual_truck(
        self,
        row: dict[str, Any],
        carrier: Carrier | None,
        source_system: str,
        driver_source_id: str,
        batch: ImportBatch,
    ) -> tuple[Truck | None, str | None, tuple[dict[str, str], ...]]:
        domain = self._clean_domain(self._value(row, "CHASIS"))
        trailer_domain = self._clean_domain(self._value(row, "ACOPLADO")) or None
        if not domain:
            warnings = (
                ({"code": "habitual_truck_missing", "source_id": driver_source_id},)
                if "CHASIS" in row
                else ()
            )
            return None, None, warnings

        now = utc_now()
        warnings: list[dict[str, str]] = []
        truck = Truck.select().where(Truck.domain == domain).first()
        if truck is None:
            truck = Truck.create(
                domain=domain,
                trailer_domain=trailer_domain,
                carrier=carrier,
                source_system=source_system,
                source_id=f"driver:{driver_source_id}",
                imported_at=now,
                updated_from_source_at=now,
                last_import_batch=batch,
            )
            return truck, "created", ()

        if truck.carrier_id is None and carrier is not None:
            truck.carrier = carrier
        elif carrier is not None and truck.carrier_id != carrier.id:
            warnings.append({"code": "truck_carrier_conflict", "source_id": driver_source_id})

        if not truck.trailer_domain and trailer_domain:
            truck.trailer_domain = trailer_domain
        elif trailer_domain and truck.trailer_domain != trailer_domain:
            warnings.append({"code": "truck_trailer_conflict", "source_id": driver_source_id})

        if truck.source_system == source_system and truck.source_id == f"driver:{driver_source_id}":
            truck.updated_from_source_at = now
            truck.last_import_batch = batch
        truck.save()
        return truck, "updated", tuple(warnings)

    def _find_carrier_by_source_id(self, source_system: str, source_id: str) -> Carrier | None:
        if not source_id:
            return None
        return (
            Carrier.select()
            .where((Carrier.source_system == source_system) & (Carrier.source_id == source_id))
            .first()
        )

    def _find_carriers_by_cuit(self, cuit: str) -> list[Carrier]:
        if not cuit:
            return []
        return [carrier for carrier in Carrier.select() if self._clean_cuit(carrier.cuit or "") == cuit]

    def _carrier_identity_matches(self, carrier: Carrier, driver_cuit: str, driver_name: str) -> bool:
        carrier_cuit = self._clean_cuit(carrier.cuit or "")
        if carrier_cuit and driver_cuit:
            return carrier_cuit == driver_cuit
        return self._clean_identity_name(carrier.name) == driver_name

    def _upsert(
        self,
        model,
        natural_lookup: dict[str, Any],
        values: dict[str, Any],
        source_system: str,
        source_id: str,
        batch: ImportBatch,
    ) -> str:
        now = utc_now()
        row = (
            model.select()
            .where((model.source_system == source_system) & (model.source_id == source_id))
            .first()
        )
        if row is None:
            row = model.select().filter(**natural_lookup).first()

        action = "updated" if row is not None else "created"
        if row is None:
            row = model(**values)
            row.imported_at = now
        else:
            for field, value in values.items():
                setattr(row, field, value)
            if row.imported_at is None:
                row.imported_at = now

        row.source_system = source_system
        row.source_id = source_id
        row.updated_from_source_at = now
        row.last_import_batch = batch
        row.save()
        return action

    def _get_carrier(self, source_system: str, source_id: str) -> Carrier:
        carrier = (
            Carrier.select()
            .where((Carrier.source_system == source_system) & (Carrier.source_id == source_id))
            .first()
        )
        if carrier is None:
            raise ValueError(f"No existe transportista legacy {source_id}.")
        return carrier

    def _required(self, row: dict[str, Any], entity: str, *aliases: str) -> str:
        value = self._value(row, *aliases)
        if not value:
            raise ValueError(f"{entity} requiere CODIGO, RAZON y CUIT.")
        return value

    def _value(self, row: dict[str, Any], *aliases: str, default: str = "") -> str:
        for alias in aliases:
            value = row.get(alias.upper())
            if value is not None:
                text = str(value).strip()
                if text:
                    return text
        return default

    def _normalize_row(self, row: Mapping[str, Any]) -> dict[str, Any]:
        return {str(key).upper().strip(): value for key, value in row.items()}

    def _clean_cuit(self, value: str) -> str:
        return re.sub(r"\D", "", value)

    def _clean_domain(self, value: str) -> str:
        return re.sub(r"[^A-Za-z0-9]", "", value).upper()

    def _clean_identity_name(self, value: str) -> str:
        return re.sub(r"[^A-Z0-9]", "", value.upper())

    def _empty_summary(self) -> dict[str, dict[str, Any]]:
        return {
            entity: {"created": 0, "updated": 0, "skipped": 0, "errors": [], "warnings": []}
            for entity in ENTITY_KEYS
        }

    def _read_dbf(self, path: str | Path, *, encoding: str) -> list[dict[str, Any]]:
        try:
            from dbfread import DBF
        except ImportError as exc:
            raise RuntimeError("Instalar dbfread para leer archivos DBF legacy.") from exc

        return [dict(record) for record in DBF(str(path), encoding=encoding, char_decode_errors="ignore")]
