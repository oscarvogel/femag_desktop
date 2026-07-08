from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from app.models.base import utc_now
from app.models.masters import Carrier, Client, Driver, Product, Truck
from app.models.system import ImportBatch


ENTITY_KEYS = ("clients", "carriers", "drivers", "trucks", "products")


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
                    action = handler(row, source_system, batch)
                    summary[entity][action] += 1
                except ValueError as exc:
                    summary[entity]["errors"].append(
                        {"source_id": self._value(row, "CODIGO", "ID", "IDLEGACY"), "message": str(exc)}
                    )

        batch.status = "success" if not any(summary[entity]["errors"] for entity in ENTITY_KEYS) else "partial"
        batch.finished_at = utc_now()
        batch.summary = json.dumps(summary, ensure_ascii=True, sort_keys=True)
        batch.save()
        return summary

    def _import_clients(self, row: dict[str, Any], source_system: str, batch: ImportBatch) -> str:
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
        return self._upsert(Client, {"cuit": cuit}, values, source_system, source_id, batch)

    def _import_carriers(self, row: dict[str, Any], source_system: str, batch: ImportBatch) -> str:
        source_id = self._required(row, "carriers", "CODIGO", "ID", "IDLEGACY")
        name = self._required(row, "carriers", "NOMBRE", "RAZON", "TRANSPORTISTA")
        values = {
            "name": name,
            "cuit": self._clean_cuit(self._value(row, "CUIT", "CUITTRA")) or None,
            "phone": self._value(row, "TELEFONO", "TEL", "PHONE"),
        }
        return self._upsert(Carrier, {"name": name}, values, source_system, source_id, batch)

    def _import_drivers(self, row: dict[str, Any], source_system: str, batch: ImportBatch) -> str:
        source_id = self._required(row, "drivers", "CODIGO", "ID", "IDLEGACY")
        name = self._required(row, "drivers", "NOMBRE", "CHOFER")
        carrier_source_id = self._required(row, "drivers", "TRANSP", "TRANSPORTISTA", "CARRIER")
        carrier = self._get_carrier(source_system, carrier_source_id)
        values = {
            "name": name,
            "carrier": carrier,
            "document": self._value(row, "DNI", "DOCUMENTO", "DOC"),
            "phone": self._value(row, "TELEFONO", "TEL", "PHONE"),
        }
        return self._upsert(Driver, {"name": name}, values, source_system, source_id, batch)

    def _import_trucks(self, row: dict[str, Any], source_system: str, batch: ImportBatch) -> str:
        source_id = self._required(row, "trucks", "CODIGO", "ID", "IDLEGACY")
        domain = self._clean_domain(self._required(row, "trucks", "PATENTE", "DOMINIO", "DOMAIN"))
        carrier_source_id = self._required(row, "trucks", "TRANSP", "TRANSPORTISTA", "CARRIER")
        carrier = self._get_carrier(source_system, carrier_source_id)
        values = {"domain": domain, "carrier": carrier}
        return self._upsert(Truck, {"domain": domain}, values, source_system, source_id, batch)

    def _import_products(self, row: dict[str, Any], source_system: str, batch: ImportBatch) -> str:
        source_id = self._required(row, "products", "CODIGO", "ID", "IDLEGACY")
        name = self._required(row, "products", "NOMBRE", "PRODUCTO", "DESCRIP")
        values = {"name": name, "unit": self._value(row, "UNIDAD", "UNI", default="unidad")}
        return self._upsert(Product, {"name": name}, values, source_system, source_id, batch)

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

    def _empty_summary(self) -> dict[str, dict[str, Any]]:
        return {
            entity: {"created": 0, "updated": 0, "skipped": 0, "errors": []}
            for entity in ENTITY_KEYS
        }

    def _read_dbf(self, path: str | Path, *, encoding: str) -> list[dict[str, Any]]:
        try:
            from dbfread import DBF
        except ImportError as exc:
            raise RuntimeError("Instalar dbfread para leer archivos DBF legacy.") from exc

        return [dict(record) for record in DBF(str(path), encoding=encoding, char_decode_errors="ignore")]
