"""Tests del maestro de proveedores importado de `femagfab.proveedo` (#938)."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app.importers.femagfab import LegacySupplier
from app.services.supplier_import_service import (
    SupplierImportService,
    normalize_supplier_name,
)


class _FakeSource:
    """Doble de `FemagFabSource` que devuelve filas fijas."""

    instance = "femagfab"

    def __init__(self, rows):
        self.rows = rows

    def fetch_suppliers(self):
        return list(self.rows)

    def supplier_source_key(self, code):
        return f"femagfab:femagfab:proveedo:{code}"


def supplier(code, name, locality="", phone=""):
    return LegacySupplier(
        code=code, name=name, locality=locality, phone=phone
    )


def test_normaliza_nombres_para_detectar_duplicados():
    assert normalize_supplier_name("Nuñez  Julio ") == "NUNEZ JULIO"
    assert normalize_supplier_name("  silveRío  ") == "SILVERIO"
    assert normalize_supplier_name("") == ""


def test_importa_el_maestro_como_una_persona_por_ficha(db):
    from app.models.suppliers import Supplier, SupplierLegacyCode

    service = SupplierImportService(
        source=_FakeSource([supplier("0999", "KLEM JORGE", "ANDRESITO")])
    )
    report = service.import_suppliers()

    assert report.created == 1
    assert report.merged == 0
    assert Supplier.select().count() == 1
    assert SupplierLegacyCode.select().count() == 1

    persona = Supplier.get()
    assert persona.name == "KLEM JORGE"
    assert persona.locality == "ANDRESITO"
    assert persona.identity_verified is False
    assert persona.legacy_code_list == ["0999"]


def test_unifica_dos_codigos_del_mismo_productor(db):
    """La misma persona con dos codigos del legacy es UNA sola persona."""
    from app.models.suppliers import Supplier, SupplierLegacyCode

    service = SupplierImportService(
        source=_FakeSource(
            [
                supplier("0993", "TERESCHUK ALBERTO CESAR"),
                supplier("1025", "TERESCHUK ALBERTO CESAR"),
            ]
        )
    )
    report = service.import_suppliers()

    assert report.created == 1
    assert report.merged == 1
    assert Supplier.select().count() == 1
    assert SupplierLegacyCode.select().count() == 2
    assert Supplier.get().legacy_code_list == ["0993", "1025"]


def test_unifica_cuando_el_nombre_solo_difiere_en_tildes_y_espacios(db):
    from app.models.suppliers import Supplier

    service = SupplierImportService(
        source=_FakeSource(
            [
                supplier("0125", "NUNEZ JULIO"),
                supplier("0126", "Nuñez  Julio "),
            ]
        )
    )
    report = service.import_suppliers()

    assert report.created == 1
    assert report.merged == 1
    assert Supplier.select().count() == 1


def test_descarta_el_codigo_0000_que_no_es_una_persona(db):
    from app.models.suppliers import Supplier, SupplierLegacyCode

    service = SupplierImportService(
        source=_FakeSource([supplier("0000", ".", "PUERTO RICO")])
    )
    report = service.import_suppliers()

    assert report.created == 0
    assert report.skipped_count == 1
    assert report.skipped[0].reason == SupplierImportService.SKIPPED_PLACEHOLDER
    assert Supplier.select().count() == 0
    assert SupplierLegacyCode.select().count() == 0


def test_reimportar_no_duplica_ni_rompe_nada(db):
    from app.models.suppliers import Supplier, SupplierLegacyCode

    filas = [
        supplier("0999", "KLEM JORGE", "ANDRESITO"),
        supplier("1025", "TERESCHUK ALBERTO CESAR"),
    ]
    SupplierImportService(source=_FakeSource(filas)).import_suppliers()
    segundo = SupplierImportService(source=_FakeSource(filas)).import_suppliers()

    assert segundo.created == 0
    assert segundo.merged == 0
    assert segundo.updated == 0
    assert segundo.unchanged == 2
    assert Supplier.select().count() == 2
    assert SupplierLegacyCode.select().count() == 2


def test_reimportar_actualiza_el_telefono_y_no_crea_otra_persona(db):
    from app.models.suppliers import Supplier

    SupplierImportService(
        source=_FakeSource([supplier("0999", "KLEM JORGE", "ANDRESITO", "123")])
    ).import_suppliers()
    SupplierImportService(
        source=_FakeSource([supplier("0999", "KLEM JORGE", "ANDRESITO", "456")])
    ).import_suppliers()

    assert Supplier.select().count() == 1
    persona = Supplier.get()
    assert persona.phone == "123"  # el canonico no se pisa con la ficha
    from app.models.suppliers import SupplierLegacyCode

    assert SupplierLegacyCode.get().phone == "456"
