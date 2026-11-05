"""Configuracion central de la carpeta de documentos fiscales (#871).

La ruta se guarda en ``AppParameter`` para que la compartan todos los puestos.
No depende de variables de entorno de cada maquina.
"""

from __future__ import annotations

from pathlib import Path

from app.models.system import AppParameter


class FiscalConfigurationError(ValueError):
    pass


class FiscalConfigurationService:
    DOCS_DIR_KEY = "fiscal.docs_dir"

    @classmethod
    def docs_dir(cls) -> str:
        try:
            row = AppParameter.get_or_none(AppParameter.key == cls.DOCS_DIR_KEY)
        except Exception:
            return ""
        return (row.value or "").strip() if row else ""

    @classmethod
    def is_configured(cls) -> bool:
        return bool(cls.docs_dir())

    @classmethod
    def save_docs_dir(cls, value: str | Path) -> str:
        raw = str(value or "").strip()
        if not raw:
            raise FiscalConfigurationError(
                "Debe indicar la carpeta donde se guardan los certificados."
            )
        path = Path(raw).expanduser()
        normalized = str(path)
        if not path.is_absolute():
            raise FiscalConfigurationError(
                "La carpeta debe ser una ruta absoluta, por ejemplo "
                "D:\\FEMAG\\documentos\\fiscales."
            )
        probe = path / ".femag_fiscal_write_test"
        try:
            path.mkdir(parents=True, exist_ok=True)
            probe.write_text("ok", encoding="utf-8")
        except OSError as exc:
            raise FiscalConfigurationError(
                f"No se pudo crear o escribir en la carpeta: {exc}"
            ) from exc
        finally:
            probe.unlink(missing_ok=True)
        row, _created = AppParameter.get_or_create(key=cls.DOCS_DIR_KEY)
        row.value = normalized
        row.save(only=[AppParameter.value])
        return normalized

    @classmethod
    def clear_docs_dir(cls) -> None:
        row = AppParameter.get_or_none(AppParameter.key == cls.DOCS_DIR_KEY)
        if row is not None:
            row.value = ""
            row.save(only=[AppParameter.value])
