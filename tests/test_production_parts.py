from datetime import date
from decimal import Decimal

import pytest

from app.models.masters import (
    PRODUCT_KIND_INTERNAL,
    PRODUCT_KIND_REVIEW,
    PRODUCT_KIND_SERVICE,
    Product,
)
from app.models.production import ProductionBag, ProductionPart
from app.services.production_part_service import ProductionPartService

DAY = date(2026, 9, 29)


def _bagged_product(name="Almidón de mandioca", weight="25.000"):
    return Product.create(
        name=name, unit="bolsa", peso_unitario_kg=Decimal(weight), active=True
    )


def test_production_calculates_kg_from_bags_and_unit_weight(db):
    product = _bagged_product()
    part = ProductionPartService.create(
        production_date=DAY, shift="Mañana", lines=[(product, 280)]
    )
    lines = ProductionPartService.lines_of(part)
    assert len(lines) == 1
    assert lines[0].bags == 280
    assert lines[0].unit_weight_kg == Decimal("25.000")
    assert lines[0].kg == Decimal("7000.00")


def test_production_accepts_several_products_in_one_shift(db):
    almidon = _bagged_product("Almidón de mandioca", "25.000")
    premezcla = _bagged_product("Premezcla industrial", "20.000")
    part = ProductionPartService.create(
        production_date=DAY, shift="Tarde", lines=[(almidon, 100), (premezcla, 50)]
    )
    totals = ProductionPartService.totals([part])
    assert totals.parts == 1
    assert totals.lines == 2
    assert totals.bags == 150
    assert totals.kg == Decimal("3500.00")


def test_production_rejects_product_without_unit_weight(db):
    sin_peso = Product.create(name="Fecula a granel", unit="kg", peso_unitario_kg=Decimal("0"))
    with pytest.raises(ValueError, match="no tiene peso unitario cargado"):
        ProductionPartService.create(
            production_date=DAY, shift="Mañana", lines=[(sin_peso, 10)]
        )
    assert ProductionPart.select().count() == 0
    assert ProductionBag.select().count() == 0


def test_production_rejects_zero_or_negative_bags(db):
    product = _bagged_product()
    with pytest.raises(ValueError, match="mayor a cero"):
        ProductionPartService.create(production_date=DAY, shift="Mañana", lines=[(product, 0)])
    with pytest.raises(ValueError, match="mayor a cero"):
        ProductionPartService.create(production_date=DAY, shift="Mañana", lines=[(product, -5)])
    assert ProductionPart.select().count() == 0


def test_production_rejects_fractional_bags_and_duplicates(db):
    product = _bagged_product()
    with pytest.raises(ValueError, match="número entero"):
        ProductionPartService.create(production_date=DAY, shift="Mañana", lines=[(product, 2.5)])
    with pytest.raises(ValueError, match="dos veces"):
        ProductionPartService.create(
            production_date=DAY, shift="Mañana", lines=[(product, 10), (product, 20)]
        )
    with pytest.raises(ValueError, match="al menos un producto"):
        ProductionPartService.create(production_date=DAY, shift="Mañana", lines=[])


def test_production_requires_shift(db):
    product = _bagged_product()
    with pytest.raises(ValueError, match="turno es obligatorio"):
        ProductionPartService.create(production_date=DAY, shift="  ", lines=[(product, 5)])


def test_kg_snapshot_survives_master_weight_change(db):
    product = _bagged_product(weight="25.000")
    part = ProductionPartService.create(
        production_date=DAY, shift="Mañana", lines=[(product, 100)]
    )
    product.peso_unitario_kg = Decimal("30.000")
    product.save()
    stored = ProductionPartService.lines_of(part)[0]
    assert stored.unit_weight_kg == Decimal("25.000")
    assert stored.kg == Decimal("2500.00")


def test_production_can_be_corrected_replacing_lines(db):
    almidon = _bagged_product("Almidón de mandioca", "25.000")
    premezcla = _bagged_product("Premezcla industrial", "20.000")
    part = ProductionPartService.create(
        production_date=DAY, shift="Mañana", lines=[(almidon, 280)],
        observations="Carga inicial",
    )
    part = ProductionPartService.update(
        part, production_date=DAY, shift="Mañana",
        lines=[(almidon, 200), (premezcla, 10)], observations="Corrección de embolsado",
    )
    totals = ProductionPartService.totals([part])
    assert totals.lines == 2
    assert totals.bags == 210
    assert totals.kg == Decimal("5200.00")
    assert part.observations == "Corrección de embolsado"


def test_annul_removes_part_and_its_bags(db):
    product = _bagged_product()
    part = ProductionPartService.create(
        production_date=DAY, shift="Mañana", lines=[(product, 40)]
    )
    ProductionPartService.annul(part)
    assert ProductionPart.select().count() == 0
    assert ProductionBag.select().count() == 0


def test_for_day_keeps_dates_independent(db):
    product = _bagged_product()
    ProductionPartService.create(
        production_date=date(2026, 9, 28), shift="Mañana", lines=[(product, 100)]
    )
    ProductionPartService.create(production_date=DAY, shift="Mañana", lines=[(product, 200)])
    rows = ProductionPartService.for_day(date(2026, 9, 28))
    assert len(rows) == 1
    assert rows[0].production_date == date(2026, 9, 28)
    assert ProductionPartService.totals(rows).bags == 100


def test_day_totals_add_up_across_shifts(db):
    product = _bagged_product()
    ProductionPartService.create(production_date=DAY, shift="Mañana", lines=[(product, 100)])
    ProductionPartService.create(production_date=DAY, shift="Tarde", lines=[(product, 150)])
    totals = ProductionPartService.totals(ProductionPartService.for_day(DAY))
    assert totals.parts == 2
    assert totals.bags == 250
    assert totals.kg == Decimal("6250.00")


def test_migration_drops_legacy_kilos_columns_and_orphan_parts(db):
    """#580: los kg por turno no eran dato real y se descartan junto al parte."""
    from app.config.schema import _drop_legacy_production_kilos

    db.drop_tables([ProductionPart])
    db.execute_sql(
        "CREATE TABLE production_part ("
        "id INTEGER NOT NULL PRIMARY KEY, "
        "production_date DATE NOT NULL, "
        "shift VARCHAR(40) NOT NULL, "
        "cassava_processed_kg DECIMAL(12,2) NOT NULL, "
        "starch_produced_kg DECIMAL(12,2) NOT NULL, "
        "observations TEXT, "
        "created_at DATETIME NOT NULL, "
        "updated_at DATETIME NOT NULL)"
    )
    db.execute_sql(
        "INSERT INTO production_part (production_date, shift, cassava_processed_kg, "
        "starch_produced_kg, created_at, updated_at) VALUES "
        "('2026-09-29', 'Mañana', 32000, 7050, '2026-09-29 00:00:00', '2026-09-29 00:00:00')"
    )

    _drop_legacy_production_kilos(db)

    columns = {column.name for column in db.get_columns("production_part")}
    assert "cassava_processed_kg" not in columns
    assert "starch_produced_kg" not in columns
    assert {"production_date", "shift", "observations"} <= columns
    assert ProductionPart.select().count() == 0

    # Idempotente: una segunda pasada no debe volver a tocar nada.
    _drop_legacy_production_kilos(db)
    assert {column.name for column in db.get_columns("production_part")} == columns


def test_migration_keeps_parts_that_already_have_bags(db):
    """Un parte con bolsas es produccion real: la migracion no lo borra."""
    from app.config.schema import _drop_legacy_production_kilos

    product = _bagged_product()
    ProductionPartService.create(production_date=DAY, shift="Mañana", lines=[(product, 30)])

    db.execute_sql("ALTER TABLE production_part ADD COLUMN cassava_processed_kg DECIMAL(12,2) NULL")
    _drop_legacy_production_kilos(db)

    columns = {column.name for column in db.get_columns("production_part")}
    assert "cassava_processed_kg" not in columns
    assert ProductionPart.select().count() == 1
    assert ProductionBag.select().count() == 1


_QAPP = None


def _page(db):
    """Construye la pantalla con la base de tests.

    La ``QApplication`` se guarda a nivel de modulo a proposito: si se
    recolecta, se lleva por delante los widgets C++ creados y PyQt falla con
    "wrapped C/C++ object ... has been deleted".
    """
    global _QAPP
    from PyQt5.QtWidgets import QApplication

    from app.ui.production_parts import ProductionPartPage

    if _QAPP is None:
        _QAPP = QApplication.instance() or QApplication([])
    return ProductionPartPage()


def test_production_page_only_offers_products_with_unit_weight(db):
    """Sin peso de bolsa no se puede calcular kg: no debe aparecer en el combo."""
    _bagged_product("Almidón de mandioca", "25.000")
    _bagged_product("Premezcla industrial", "20.000")
    Product.create(name="Fecula a granel", unit="kg", peso_unitario_kg=Decimal("0"), active=True)

    page = _page(db)

    assert page.product_combo.count() == 2
    assert "Peso por bolsa" in page.weight_hint.text()


def test_production_page_only_offers_sale_products(db):
    """Lo que se embolsa es lo que se vende.

    Un servicio, un interno o un articulo todavia en revision no se embolsan,
    aunque tengan peso de bolsa cargado.
    """
    _bagged_product("Almidón de mandioca", "25.000")
    Product.create(
        name="Flete", unit="viaje", peso_unitario_kg=Decimal("1.000"),
        active=True, product_kind=PRODUCT_KIND_SERVICE,
    )
    Product.create(
        name="Merma de proceso", unit="kg", peso_unitario_kg=Decimal("5.000"),
        active=True, product_kind=PRODUCT_KIND_INTERNAL,
    )
    Product.create(
        name="Fecula nueva presentacion", unit="bolsa", peso_unitario_kg=Decimal("20.000"),
        active=True, product_kind=PRODUCT_KIND_REVIEW,
    )

    page = _page(db)

    assert page.product_combo.count() == 1
    assert page.product_combo.itemText(0) == "Almidón de mandioca"


def test_production_page_explains_where_to_load_the_unit_weight(db):
    """Con el combo vacio la pantalla tiene que decir donde cargar el peso.

    El maestro ya muestra «Peso pendiente» en la columna Peso, pero sin esta
    pista el operador se queda sin salida: es el mismo sintoma que reporto la
    validacion manual.
    """
    Product.create(name="Fecula a granel", unit="kg", peso_unitario_kg=Decimal("0"), active=True)

    page = _page(db)

    texto = page.weight_hint.text()
    assert "Maestros" in texto
    assert "Peso" in texto


def test_production_page_computes_kg_while_adding_lines(db):
    """Regresion: el combo dispara currentIndexChanged al agregar el primer
    producto, antes de que _products_by_id estuviera poblado. El slot lanzaba
    AttributeError y PyQt5 abortaba el proceso entero (0xC0000409)."""
    _bagged_product("Almidón de mandioca", "25.000")
    _bagged_product("Premezcla industrial", "20.000")

    page = _page(db)

    page.bags_input.setValue(10)
    page._add_line()
    page.product_combo.setCurrentIndex(1)
    page.bags_input.setValue(4)
    page._add_line()

    assert [(product.name, bags) for product, bags in page.pending] == [
        ("Almidón de mandioca", 10), ("Premezcla industrial", 4)
    ]
    assert page.lines_table.item(0, 2).text() == "250.00"
    assert page.lines_table.item(1, 2).text() == "80.00"
    assert "14 bolsa(s)" in page.weight_hint.text()
