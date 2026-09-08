"""Tablas de referencia DGR del sistema anterior para el archivo F150.

Replica las relaciones que usa `forms/f150.scx` (`generadatos`):
`localidades.CODIGODGR -> locdgr.IDLOCALIDA` aporta `CODIGODGR/DPTO/PROVINCIA`,
`localidades.PAISDGR -> paises.IDPAIS` aporta `ABR/NOMBRE` y
`localidades.PROVDGR -> provincias.CODIGO` identifica la provincia.
La tabla `dptos.dbf` no se importa: `generadatos` nunca la consulta
(`nombdeptrans` se fuerza a "").
"""

from __future__ import annotations

from peewee import CharField, DateTimeField, ForeignKeyField, IntegerField

from app.models.base import BaseModel
from app.models.system import ImportBatch


class DgrCountry(BaseModel):
    legacy_id = IntegerField(unique=True)
    name = CharField()
    abbr = CharField(null=True)


class DgrProvince(BaseModel):
    code = IntegerField(unique=True)
    name = CharField()


class DgrLocality(BaseModel):
    code = CharField(unique=True)
    name = CharField()
    dgr_id = IntegerField(null=True)
    dgr_code = IntegerField(null=True)
    department_code = IntegerField(null=True)
    province_code = IntegerField(null=True)
    country = ForeignKeyField(DgrCountry, backref="localities", null=True)
    source_system = CharField(null=True)
    source_id = CharField(null=True)
    imported_at = DateTimeField(null=True)
    updated_from_source_at = DateTimeField(null=True)
    last_import_batch = ForeignKeyField(ImportBatch, backref="imported_dgr_localities", null=True)

    @property
    def dgr_code_4(self) -> str:
        """Equivale a Alltrim(StrZero(locdgr.codigodgr, 4)) del VFP."""
        return f"{self.dgr_code:04d}" if self.dgr_code is not None else ""

    @property
    def province_code_2(self) -> str:
        """Equivale a Alltrim(StrZero(locdgr.provincia, 2)) del VFP."""
        return f"{self.province_code:02d}" if self.province_code is not None else ""

    @property
    def department_code_4(self) -> str:
        """Equivale a Alltrim(StrZero(locdgr.dpto, 4)) del VFP."""
        return f"{self.department_code:04d}" if self.department_code is not None else ""
