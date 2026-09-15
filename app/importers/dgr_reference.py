"""Importa las tablas de referencia DGR desde DBF legacy (solo lectura).

Replica los joins de `forms/f150.scx` (`generadatos`) para dejar resuelta cada
localidad con sus códigos DGR. Idempotente por (`source_system`, `source_id`).
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.models.base import utc_now
from app.models.dgr import DgrCountry, DgrLocality, DgrProvince
from app.models.system import ImportBatch


REFERENCE_KEYS = ("paises", "provincias", "localidades", "locdgr")


@dataclass(frozen=True)
class ReferenceImportOutcome:
    action: str
    warnings: tuple[dict[str, str], ...] = ()


class DgrReferenceImporter:
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
            if entity in REFERENCE_KEYS
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
        locdgr_by_id = {
            self._to_int(row.get("IDLOCALIDA")): self._normalize_row(row)
            for row in rows_by_entity.get("locdgr", [])
        }
        for row in rows_by_entity.get("paises", []):
            self._tally(summary, "paises", self._import_country(row, source_system, batch))
        for row in rows_by_entity.get("provincias", []):
            self._tally(summary, "provincias", self._import_province(row, source_system, batch))
        for row in rows_by_entity.get("localidades", []):
            self._tally(
                summary,
                "localidades",
                self._import_locality(row, locdgr_by_id, source_system, batch),
            )
        batch.status = (
            "success"
            if not any(summary[entity]["errors"] for entity in summary)
            else "partial"
        )
        batch.finished_at = utc_now()
        batch.summary = json.dumps(summary, ensure_ascii=True, sort_keys=True)
        batch.save()
        return summary

    def _import_country(self, raw: Mapping[str, Any], source_system: str, batch: ImportBatch) -> ReferenceImportOutcome:
        row = self._normalize_row(raw)
        legacy_id = self._to_int(row.get("IDPAIS"))
        if legacy_id is None:
            return ReferenceImportOutcome("skipped", ({"code": "country_without_id"},))
        country, _ = DgrCountry.get_or_create(
            legacy_id=legacy_id,
            defaults={"name": str(row.get("NOMBRE") or "").strip() or f"País {legacy_id}"},
        )
        country.name = str(row.get("NOMBRE") or "").strip() or country.name
        country.abbr = str(row.get("ABR") or "").strip() or None
        country.save()
        return ReferenceImportOutcome("imported")

    def _import_province(self, raw: Mapping[str, Any], source_system: str, batch: ImportBatch) -> ReferenceImportOutcome:
        row = self._normalize_row(raw)
        code = self._to_int(row.get("CODIGO"))
        if code is None:
            return ReferenceImportOutcome("skipped", ({"code": "province_without_code"},))
        province, _ = DgrProvince.get_or_create(
            code=code,
            defaults={"name": str(row.get("DESCRIPCIO") or "").strip() or f"Provincia {code}"},
        )
        province.name = str(row.get("DESCRIPCIO") or "").strip() or province.name
        province.save()
        return ReferenceImportOutcome("imported")

    def _import_locality(
        self,
        raw: Mapping[str, Any],
        locdgr_by_id: dict[int | None, dict[str, Any]],
        source_system: str,
        batch: ImportBatch,
    ) -> ReferenceImportOutcome:
        row = self._normalize_row(raw)
        code = str(row.get("CODIGO") or "").strip()
        if not code:
            return ReferenceImportOutcome("skipped", ({"code": "locality_without_code"},))
        dgr_id = self._to_int(row.get("CODIGODGR"))
        dgr_row = locdgr_by_id.get(dgr_id)
        warnings: list[dict[str, str]] = []
        if dgr_row is None:
            warnings.append({"code": "locality_without_dgr", "source_id": code})
        country = self._find_country(self._to_int(row.get("PAISDGR")))
        if country is None and self._to_int(row.get("PAISDGR")) is not None:
            warnings.append({"code": "locality_without_country", "source_id": code})
        now = utc_now()
        locality, created = DgrLocality.get_or_create(
            code=code,
            defaults={
                "name": str(row.get("LOCALIDAD") or "").strip(),
                "source_system": source_system,
                "source_id": code,
                "imported_at": now,
            },
        )
        locality.name = str(row.get("LOCALIDAD") or "").strip() or locality.name
        locality.dgr_id = dgr_id
        locality.dgr_code = self._to_int((dgr_row or {}).get("CODIGODGR"))
        locality.department_code = self._to_int((dgr_row or {}).get("DPTO"))
        locality.province_code = self._to_int((dgr_row or {}).get("PROVINCIA"))
        locality.country = country
        locality.source_system = source_system
        locality.source_id = code
        locality.updated_from_source_at = now
        locality.last_import_batch = batch
        if locality.imported_at is None:
            locality.imported_at = now
        locality.save()
        return ReferenceImportOutcome("created" if created else "updated", tuple(warnings))

    def _find_country(self, legacy_id: int | None) -> DgrCountry | None:
        if legacy_id is None:
            return None
        return DgrCountry.select().where(DgrCountry.legacy_id == legacy_id).first()

    def _tally(
        self,
        summary: dict[str, dict[str, Any]],
        entity: str,
        outcome: ReferenceImportOutcome,
    ) -> None:
        summary[entity][outcome.action] += 1
        summary[entity]["warnings"].extend(outcome.warnings)

    def _empty_summary(self) -> dict[str, dict[str, Any]]:
        return {
            entity: {"created": 0, "updated": 0, "imported": 0, "skipped": 0, "errors": [], "warnings": []}
            for entity in ("paises", "provincias", "localidades")
        }

    def _normalize_row(self, row: Mapping[str, Any]) -> dict[str, Any]:
        return {str(key).upper().strip(): value for key, value in row.items()}

    @staticmethod
    def _to_int(value: Any) -> int | None:
        if value is None or value == "":
            return None
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return None

    def _read_dbf(self, path: str | Path, *, encoding: str) -> list[dict[str, Any]]:
        try:
            from dbfread import DBF
        except ImportError as exc:
            raise RuntimeError("Instalar dbfread para leer archivos DBF legacy.") from exc

        return [dict(record) for record in DBF(str(path), encoding=encoding, char_decode_errors="ignore")]
