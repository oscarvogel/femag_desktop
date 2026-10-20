"""Deja la base lista para que el F150 se pueda generar.

Son tres pasos y el orden importa:

1. importar la **referencia DGR** (paises, provincias, localidades, codigos);
2. importar los **maestros** del legacy (clientes, transportistas, choferes,
   productos);
3. dejar elegido el **origen DGR**, que vive en el parametro ``f150.origin``.

El paso 1 tiene que ir antes que el 2, y el modo de falla es silencioso: si los
maestros se importan sin la referencia DGR cargada, ``_find_locality`` devuelve
``None`` y **todos** los enlaces DGR quedan en ``NULL`` sin ningun error. Cuando
la referencia se importa despues, el reimport de maestros es lo unico que los
completa, y hace falta el backfill de #688 para las direcciones de cliente.

Este servicio hace los tres pasos en el orden correcto y despues **verifica**
que quedo todo en su lugar, para que el operador no tenga que confiar.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.importers.dgr_reference import DgrReferenceImporter
from app.importers.legacy_dbf import LegacyDbfMasterImporter
from app.models.dgr import DgrCountry, DgrLocality, DgrProvince
from app.models.masters import (
    Carrier,
    ClientAddress,
    Driver,
    Product,
    Truck,
)
from app.models.remittances import Remittance
from app.services.f150_batch_service import F150BatchService, F150Location


#: Archivos de la referencia DGR dentro de la carpeta de datos del legacy.
DGR_FILES = {
    "paises": "paises.dbf",
    "provincias": "provincias.dbf",
    "localidades": "localidades.dbf",
    "locdgr": "locdgr.dbf",
}

#: Archivos de los maestros dentro de la carpeta de datos del legacy.
MASTER_FILES = {
    "clients": "clientes.dbf",
    "carriers": "transporte.dbf",
    "drivers": "chofer.dbf",
    "products": "productos.dbf",
}

#: Campo del ``param.dbf`` del legacy con la localidad de origen de la empresa.
ORIGIN_LEGACY_FIELD = "LOCORIGEN"

#: Tope de remitos que se revisan uno por uno en la verificacion.
MAX_REMITTENCES_CHECKED = 50


@dataclass(frozen=True)
class F150SetupReport:
    """Como quedo la base despues del setup."""

    dgr: dict[str, Any] = field(default_factory=dict)
    masters: dict[str, Any] = field(default_factory=dict)
    origin: F150Location | None = None
    checks: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    remittances_ready: int = 0
    remittances_blocked: tuple[tuple[str, tuple[str, ...]], ...] = ()
    remittances_not_checked: int = 0

    @property
    def ok(self) -> bool:
        """True cuando no quedan avisos de los que dependen los remitos."""
        return not self.warnings and not self.remittances_blocked


class F150SetupService:
    """Ordena la importacion del legacy y deja la base lista para el F150."""

    def __init__(self, *, current_user: str = "setup"):
        self.batch_service = F150BatchService(current_user=current_user)

    # ------------------------------------------------------------------
    # Rutas
    # ------------------------------------------------------------------
    @staticmethod
    def dgr_paths(dbf_dir: str | Path) -> dict[str, Path]:
        base = Path(dbf_dir)
        return {entity: base / nombre for entity, nombre in DGR_FILES.items()}

    @staticmethod
    def master_paths(dbf_dir: str | Path) -> dict[str, Path]:
        base = Path(dbf_dir)
        return {entity: base / nombre for entity, nombre in MASTER_FILES.items()}

    @staticmethod
    def existing(paths: dict[str, Path]) -> dict[str, Path]:
        """Se queda con las rutas que existen y avisa de las que no."""
        return {entity: path for entity, path in paths.items() if path.exists()}

    @staticmethod
    def missing(paths: dict[str, Path]) -> list[str]:
        return [f"{entity} ({path.name})" for entity, path in paths.items() if not path.exists()]

    # ------------------------------------------------------------------
    # Origen
    # ------------------------------------------------------------------
    @staticmethod
    def origin_code_from_param(
        param_path: str | Path, *, encoding: str = "cp1252"
    ) -> str | None:
        """Lee el ``LOCORIGEN`` del ``param.dbf`` del legacy.

        Es el valor real de la empresa: el legacy guarda ahi la localidad desde
        la que salen los remitos.
        """
        path = Path(param_path)
        if not path.exists():
            return None
        from dbfread import DBF

        for row in DBF(str(path), encoding=encoding, char_decode_errors="ignore"):
            for key in row.keys():
                if str(key).strip().upper() == ORIGIN_LEGACY_FIELD:
                    value = str(row.get(key) or "").strip()
                    if value:
                        return value
        return None

    # ------------------------------------------------------------------
    # Setup
    # ------------------------------------------------------------------
    def run(
        self,
        *,
        dbf_dir: str | Path,
        param_path: str | Path | None = None,
        locality_code: str | None = None,
        encoding: str = "cp1252",
        source_system: str = "legacy_dbf",
        import_dgr: bool = True,
        import_masters: bool = True,
        configure_origin: bool = True,
    ) -> F150SetupReport:
        warnings: list[str] = []

        dgr_summary: dict[str, Any] = {}
        masters_summary: dict[str, Any] = {}

        if import_dgr:
            paths = self.existing(self.dgr_paths(dbf_dir))
            faltan = self.missing(self.dgr_paths(dbf_dir))
            if faltan:
                warnings.append("No se encontraron estos DBF de referencia DGR: " + ", ".join(faltan))
            if paths:
                dgr_summary = DgrReferenceImporter().import_dbf_files(
                    paths, source_system=source_system, encoding=encoding
                )
            self._agregar_fallos(warnings, "referencia DGR", dgr_summary)

        localidades = DgrLocality.select().count()
        if localidades == 0:
            warnings.append(
                "No hay ninguna localidad DGR cargada. Sin la referencia DGR los "
                "maestros se importan sin localidad y sin avisar, y el F150 no "
                "sale."
            )
        elif import_masters:
            paths = self.existing(self.master_paths(dbf_dir))
            faltan = self.missing(self.master_paths(dbf_dir))
            if faltan:
                warnings.append("No se encontraron estos DBF de maestros: " + ", ".join(faltan))
            if paths:
                masters_summary = LegacyDbfMasterImporter().import_dbf_files(
                    paths, source_system=source_system, encoding=encoding
                )
            self._agregar_fallos(warnings, "maestros", masters_summary)

        origin: F150Location | None = None
        if configure_origin:
            codigo = locality_code
            if not codigo:
                # El param.dbf vive en la misma carpeta del legacy: si el que
                # llama no pasa la ruta, se busca ahi.
                param = Path(param_path) if param_path else Path(dbf_dir) / "param.dbf"
                codigo = self.origin_code_from_param(param, encoding=encoding)
            if not codigo:
                warnings.append(
                    "No se pudo determinar el origen DGR: falta el param.dbf o el "
                    "argumento --locality-code. Sin origen, el F150 no sale."
                )
            else:
                locality = DgrLocality.get_or_none(DgrLocality.code == str(codigo).strip())
                if locality is None:
                    warnings.append(
                        f"La localidad de origen {codigo!r} no existe en la "
                        "referencia DGR importada."
                    )
                else:
                    try:
                        origin = F150BatchService.set_origin(locality)
                    except ValueError as exc:
                        warnings.append(f"No se pudo configurar el origen DGR: {exc}")

        checks, remittances_ready, blocked, not_checked = self.verify()
        return F150SetupReport(
            dgr=dgr_summary,
            masters=masters_summary,
            origin=origin,
            checks=checks,
            warnings=tuple(warnings),
            remittances_ready=remittances_ready,
            remittances_blocked=blocked,
            remittances_not_checked=not_checked,
        )

    # ------------------------------------------------------------------
    # Verificacion
    # ------------------------------------------------------------------
    def verify(self) -> tuple[tuple[str, ...], int, tuple[tuple[str, tuple[str, ...]], ...], int]:
        """Mide si la base quedo completa y que remitos podrian generar F150."""
        localidades = DgrLocality.select().count()
        carriers = Carrier.select().count()
        drivers = Driver.select().count()
        direcciones = ClientAddress.select().count()
        productos = Product.select().count()
        camiones = Truck.select().count()

        checks = [
            f"referencia DGR: {localidades} localidades, "
            f"{DgrCountry.select().count()} paises, {DgrProvince.select().count()} provincias",
            f"transportistas: {self._con_localidad(Carrier, carriers)} de {carriers} con localidad DGR",
            f"choferes: {self._con_localidad(Driver, drivers)} de {drivers} con localidad DGR",
            f"direcciones de cliente: {self._con_localidad(ClientAddress, direcciones)} de {direcciones} con localidad DGR",
            f"productos: {self._con_datos(Product, productos)} de {productos} con rubros y unidad DGR",
            f"camiones: {self._con_campo(Truck.chassis_type)} de {camiones} con tipo de chasis",
        ]

        origen = F150BatchService.origin()
        if not F150BatchService.origin_configured():
            checks.append("origen DGR: NO CONFIGURADO (falta el parametro f150.origin)")
        else:
            checks.append(
                f"origen DGR: {origen.locality_code} {origen.locality_name} "
                f"({origen.province_code} {origen.country_name})"
            )

        total_remitos = Remittance.select().count()
        remittances = list(
            Remittance.select().order_by(Remittance.id).limit(MAX_REMITTENCES_CHECKED)
        )
        ready = 0
        blocked: list[tuple[str, tuple[str, ...]]] = []
        for remittance in remittances:
            issues = tuple(self.batch_service.validation_issues(remittance))
            if issues:
                blocked.append((remittance.remittance_number, issues))
            else:
                ready += 1
        not_checked = max(0, total_remitos - len(remittances))
        checks.append(
            f"remitos: {ready} listos para generar F150, {len(blocked)} bloqueados"
            + (f" ({not_checked} sin revisar)" if not_checked else "")
        )
        return tuple(checks), ready, tuple(blocked), not_checked

    @staticmethod
    def _con_localidad(model, total: int) -> int:
        return model.select().where(model.locality.is_null(False)).count()

    @staticmethod
    def _con_campo(field) -> int:
        """Cuantas filas tienen el campo informado (el camion no tiene localidad)."""
        return field.model.select().where(field.is_null(False)).count()

    @staticmethod
    def _agregar_fallos(
        warnings: list[str], que: str, resumen: dict[str, Any]
    ) -> None:
        """Las filas que no entraron tienen que quedar a la vista.

        Sin esto, una importacion que fallo en silencio se lee como una
        importacion exitosa: el resumen tiene los errores, pero nadie los mira.
        """
        for entidad, valores in sorted(resumen.items()):
            if not isinstance(valores, dict):
                continue
            errores = valores.get("errors") or []
            if errores:
                primero = errores[0]
                mensaje = primero.get("message") if isinstance(primero, dict) else str(primero)
                warnings.append(
                    f"La importacion de {que} dejo {len(errores)} filas sin entrar "
                    f"en {entidad}. La primera: {mensaje}"
                )

    @staticmethod
    def _con_datos(model, total: int) -> int:
        return model.select().where(
            model.rh1.is_null(False)
            & model.rh2.is_null(False)
            & model.rh3.is_null(False)
            & model.rh4.is_null(False)
            & model.unidad_dgr.is_null(False)
        ).count()
