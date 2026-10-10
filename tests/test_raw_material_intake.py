from datetime import date
from decimal import Decimal

import pytest

from app.models.masters import (
    STOCK_ROLE_FINISHED,
    STOCK_ROLE_RAW,
    Product,
    product_is_raw_material,
)
from app.models.production import RawMaterialIntake, RawMaterialIntakeLine
from app.models.stock import StockMovement
from app.services.raw_material_intake_service import RawMaterialIntakeService
from app.services.stock_service import StockService

DAY = date(2026, 10, 5)


def _raw_material(name="Almidon de maiz en big bag", weight="1300.000"):
    return Product.create(
        name=name,
        unit="big bag",
        peso_unitario_kg=Decimal(weight),
        stock_role=STOCK_ROLE_RAW,
        active=True,
    )


def _finished(name="BOLSAS ALMIDON DE MAIZ X 25 KG", weight="25.000"):
    return Product.create(
        name=name, unit="bolsa", peso_unitario_kg=Decimal(weight), active=True
    )


# --- Conteo de big bags y derivacion de kg -------------------------------


def test_intake_calculates_kg_from_big_bags_and_frozen_unit_weight(db):
    """El operador cuenta big bags; los kg salen del peso congelado del bag."""
    almidon = _raw_material()
    intake = RawMaterialIntakeService.create(
        received_at=DAY, lines=[(almidon, 22)]
    )
    lines = RawMaterialIntakeService.lines_of(intake)
    assert len(lines) == 1
    assert lines[0].bags == 22
    assert lines[0].unit_weight_kg == Decimal("1300.000")
    assert lines[0].kg == Decimal("28600.00")


def test_intake_accepts_several_raw_materials_in_one_receipt(db):
    maiz = _raw_material("Almidon de maiz en big bag", "1300.000")
    arroz = _raw_material("Almidon de arroz en big bag", "1000.000")
    intake = RawMaterialIntakeService.create(
        received_at=DAY, lines=[(maiz, 20), (arroz, 10)]
    )
    totals = RawMaterialIntakeService.totals([intake])
    assert totals.intakes == 1
    assert totals.lines == 2
    assert totals.bags == 30
    assert totals.kg == Decimal("36000.00")


def test_intake_unit_weight_stays_frozen_when_master_changes(db):
    """Si despues se corrige el maestro, el ingreso ya registrado no cambia.

    El movimiento de stock que lo respalda ya se escribio con ese peso: si la
    linea leyera el maestro, el saldo y la linea dirian cosas distintas.
    """
    almidon = _raw_material(weight="1300.000")
    intake = RawMaterialIntakeService.create(
        received_at=DAY, lines=[(almidon, 2)]
    )
    RawMaterialIntakeService.confirm(intake, current_user="tester")
    kg_al_confirmar = StockService.balance_for(almidon).balance_kg

    Product.update(peso_unitario_kg=Decimal("1500.000")).where(Product.id == almidon.id).execute()

    linea = RawMaterialIntakeService.lines_of(intake)[0]
    assert linea.unit_weight_kg == Decimal("1300.000")
    assert linea.kg == Decimal("2600.00")
    assert StockService.balance_for(almidon).balance_kg == kg_al_confirmar


# --- Validaciones --------------------------------------------------------


def test_intake_rejects_finished_product(db):
    """Un producto terminado se vende tal cual: no se fracciona."""
    terminado = _finished()
    with pytest.raises(ValueError, match="no es materia prima"):
        RawMaterialIntakeService.create(received_at=DAY, lines=[(terminado, 5)])
    assert RawMaterialIntake.select().count() == 0
    assert RawMaterialIntakeLine.select().count() == 0


def test_intake_rejects_raw_material_without_unit_weight(db):
    sin_peso = Product.create(
        name="Almidon sin big bag pesado",
        unit="kg",
        peso_unitario_kg=Decimal("0"),
        stock_role=STOCK_ROLE_RAW,
    )
    with pytest.raises(ValueError, match="no tiene peso unitario cargado"):
        RawMaterialIntakeService.create(received_at=DAY, lines=[(sin_peso, 3)])
    assert RawMaterialIntake.select().count() == 0
    assert RawMaterialIntakeLine.select().count() == 0


def test_intake_rejects_zero_or_negative_big_bags(db):
    almidon = _raw_material()
    with pytest.raises(ValueError, match="debe ser mayor a cero"):
        RawMaterialIntakeService.create(received_at=DAY, lines=[(almidon, 0)])
    with pytest.raises(ValueError, match="debe ser mayor a cero"):
        RawMaterialIntakeService.create(received_at=DAY, lines=[(almidon, -4)])
    assert RawMaterialIntake.select().count() == 0


def test_intake_rejects_fractional_big_bags(db):
    almidon = _raw_material()
    with pytest.raises(ValueError, match="número entero"):
        RawMaterialIntakeService.create(received_at=DAY, lines=[(almidon, 2.5)])
    assert RawMaterialIntake.select().count() == 0


def test_intake_rejects_same_raw_material_twice(db):
    almidon = _raw_material()
    with pytest.raises(ValueError, match="dos veces"):
        RawMaterialIntakeService.create(received_at=DAY, lines=[(almidon, 2), (almidon, 3)])
    assert RawMaterialIntake.select().count() == 0


def test_intake_requires_at_least_one_line(db):
    with pytest.raises(ValueError, match="al menos una materia prima"):
        RawMaterialIntakeService.create(received_at=DAY, lines=[])


# --- Confirmacion: el ingreso entra al stock ------------------------------


def test_draft_does_not_touch_stock(db):
    """Un borrador todavia no es una compra: no escribe nada en el libro."""
    almidon = _raw_material()
    intake = RawMaterialIntakeService.create(received_at=DAY, lines=[(almidon, 5)])
    assert StockMovement.select().count() == 0
    assert StockService.balance_for(almidon).balance_kg == Decimal("0.000")
    assert intake.status_label == "Borrador"


def test_confirm_writes_purchase_movement_and_raises_balance(db):
    almidon = _raw_material()
    intake = RawMaterialIntakeService.create(received_at=DAY, lines=[(almidon, 4)])
    RawMaterialIntakeService.confirm(intake, current_user="tester")

    movimientos = list(StockService.movements_for(almidon))
    assert len(movimientos) == 1
    movimiento = movimientos[0]
    assert movimiento.movement_type == StockMovement.TYPE_PURCHASE
    assert movimiento.quantity_kg == Decimal("5200.000")
    assert movimiento.is_inbound
    assert movimiento.movement_date == DAY
    assert movimiento.created_by == "tester"
    assert StockService.balance_for(almidon).balance_kg == Decimal("5200.000")
    assert intake.is_confirmed
    assert intake.status_label == "Confirmado"


def test_confirming_twice_does_not_duplicate_stock(db):
    """La idempotencia viene del indice unico del libro, no de un flag."""
    almidon = _raw_material()
    intake = RawMaterialIntakeService.create(received_at=DAY, lines=[(almidon, 4)])
    RawMaterialIntakeService.confirm(intake, current_user="tester")
    RawMaterialIntakeService.confirm(intake, current_user="tester")
    RawMaterialIntakeService.confirm(intake, current_user="tester")

    assert StockMovement.select().count() == 1
    assert StockService.balance_for(almidon).balance_kg == Decimal("5200.000")


def test_confirm_moves_each_line_to_its_own_product(db):
    maiz = _raw_material("Almidon de maiz en big bag", "1300.000")
    arroz = _raw_material("Almidon de arroz en big bag", "1000.000")
    intake = RawMaterialIntakeService.create(
        received_at=DAY, lines=[(maiz, 2), (arroz, 3)]
    )
    RawMaterialIntakeService.confirm(intake, current_user="tester")

    assert StockService.balance_for(maiz).balance_kg == Decimal("2600.000")
    assert StockService.balance_for(arroz).balance_kg == Decimal("3000.000")


def test_update_rejected_once_confirmed(db):
    almidon = _raw_material()
    intake = RawMaterialIntakeService.create(received_at=DAY, lines=[(almidon, 4)])
    RawMaterialIntakeService.confirm(intake, current_user="tester")
    with pytest.raises(ValueError, match="no se puede editar"):
        RawMaterialIntakeService.update(intake, received_at=DAY, lines=[(almidon, 9)])


# --- Anulacion -----------------------------------------------------------


def test_annul_draft_deletes_without_touching_stock(db):
    almidon = _raw_material()
    intake = RawMaterialIntakeService.create(received_at=DAY, lines=[(almidon, 4)])
    RawMaterialIntakeService.annul(intake, current_user="tester")

    assert RawMaterialIntake.get_or_none(RawMaterialIntake.id == intake.id) is None
    assert RawMaterialIntakeLine.select().count() == 0
    assert StockMovement.select().count() == 0


def test_annul_confirmed_reverses_and_balance_returns_to_previous(db):
    """Anular un ingreso confirmado deja el stock como estaba antes de el."""
    almidon = _raw_material()
    previo = RawMaterialIntakeService.create(received_at=DAY, lines=[(almidon, 1)])
    RawMaterialIntakeService.confirm(previo, current_user="tester")
    saldo_previo = StockService.balance_for(almidon).balance_kg

    intake = RawMaterialIntakeService.create(received_at=DAY, lines=[(almidon, 4)])
    RawMaterialIntakeService.confirm(intake, current_user="tester")
    assert StockService.balance_for(almidon).balance_kg == Decimal("6500.000")

    RawMaterialIntakeService.annul(intake, current_user="tester", reason="mal counted")

    assert StockService.balance_for(almidon).balance_kg == saldo_previo
    assert intake.is_voided
    assert intake.voided_by == "tester"
    assert intake.void_reason == "mal counted"
    # El original no se reescribe: queda en el libro junto al contrario.
    movimientos = list(StockService.movements_for(almidon))
    assert [m.movement_type for m in movimientos if not m.is_reversal] == [
        StockMovement.TYPE_PURCHASE
    ] * 2
    reversas = [m for m in movimientos if m.is_reversal]
    assert len(reversas) == 1
    assert reversas[0].quantity_kg == Decimal("5200.000")
    assert reversas[0].movement_type == StockMovement.TYPE_ADJUSTMENT_NEGATIVE


def test_annul_confirmed_requires_reason(db):
    almidon = _raw_material()
    intake = RawMaterialIntakeService.create(received_at=DAY, lines=[(almidon, 4)])
    RawMaterialIntakeService.confirm(intake, current_user="tester")
    with pytest.raises(ValueError, match="por qué se anula"):
        RawMaterialIntakeService.annul(intake, current_user="tester", reason="   ")
    assert StockService.balance_for(almidon).balance_kg == Decimal("5200.000")


def test_annul_twice_is_rejected(db):
    almidon = _raw_material()
    intake = RawMaterialIntakeService.create(received_at=DAY, lines=[(almidon, 4)])
    RawMaterialIntakeService.confirm(intake, current_user="tester")
    RawMaterialIntakeService.annul(intake, current_user="tester", reason="error")
    with pytest.raises(ValueError, match="ya está anulado"):
        RawMaterialIntakeService.annul(intake, current_user="tester", reason="otro")


def test_confirm_rejected_after_annul(db):
    almidon = _raw_material()
    intake = RawMaterialIntakeService.create(received_at=DAY, lines=[(almidon, 4)])
    RawMaterialIntakeService.confirm(intake, current_user="tester")
    RawMaterialIntakeService.annul(intake, current_user="tester", reason="error")
    with pytest.raises(ValueError, match="no se puede confirmar"):
        RawMaterialIntakeService.confirm(intake, current_user="tester")


# --- Totales y consulta --------------------------------------------------


def test_totals_ignore_voided_intakes(db):
    """Un ingreso anulado se muestra igual, pero ya no suma stock."""
    almidon = _raw_material()
    vigente = RawMaterialIntakeService.create(received_at=DAY, lines=[(almidon, 2)])
    RawMaterialIntakeService.confirm(vigente, current_user="tester")
    anulado = RawMaterialIntakeService.create(received_at=DAY, lines=[(almidon, 7)])
    RawMaterialIntakeService.confirm(anulado, current_user="tester")
    RawMaterialIntakeService.annul(anulado, current_user="tester", reason="error")

    rows = RawMaterialIntakeService.for_day(DAY)
    totals = RawMaterialIntakeService.totals(rows)
    assert totals.intakes == 2
    assert totals.bags == 2
    assert totals.kg == Decimal("2600.00")
    assert StockService.balance_for(almidon).balance_kg == Decimal("2600.000")


def test_for_day_filters_by_date(db):
    almidon = _raw_material()
    RawMaterialIntakeService.create(received_at=DAY, lines=[(almidon, 2)])
    RawMaterialIntakeService.create(
        received_at=date(2026, 10, 6), lines=[(almidon, 5)]
    )
    assert len(RawMaterialIntakeService.for_day(DAY)) == 1
    assert len(RawMaterialIntakeService.for_day(date(2026, 10, 6))) == 1
    assert RawMaterialIntakeService.for_day(date(2026, 10, 7)) == []


# --- El rol en el stock --------------------------------------------------


def test_product_defaults_to_finished_role(db):
    producto = Product.create(name="Fecula de mandioca", unit="bolsa")
    assert producto.stock_role == STOCK_ROLE_FINISHED
    assert product_is_raw_material(producto) is False


def test_raw_material_role_is_explicit(db):
    producto = _raw_material()
    assert producto.stock_role == STOCK_ROLE_RAW
    assert product_is_raw_material(producto) is True


def test_raw_material_with_finished_kind_is_still_raw(db):
    """`product_kind` es comercial y `stock_role` es de stock: no se pisan.

    Un big bag de almidon se factura como producto y al mismo tiempo se consume
    para fraccionar. Si el ingreso mirara `product_kind`, dejaria de aceptar
    justamente el caso para el que existe.
    """
    producto = Product.create(
        name="Almidon de maiz en big bag",
        unit="big bag",
        peso_unitario_kg=Decimal("1300.000"),
        product_kind="producto",
        stock_role=STOCK_ROLE_RAW,
    )
    intake = RawMaterialIntakeService.create(received_at=DAY, lines=[(producto, 1)])
    lines = RawMaterialIntakeService.lines_of(intake)
    assert len(lines) == 1
    assert lines[0].bags == 1
    assert lines[0].kg == Decimal("1300.00")


# --- Pantalla ------------------------------------------------------------

_QAPP = None


def _page(db):
    """Construye la pantalla con la base de tests.

    La ``QApplication`` se guarda a nivel de modulo a proposito: si se
    recolecta, se lleva por delante los widgets C++ creados y PyQt falla con
    "wrapped C/C++ object ... has been deleted".
    """
    global _QAPP
    from PyQt5.QtWidgets import QApplication

    from app.ui.raw_material_intake import RawMaterialIntakePage

    if _QAPP is None:
        _QAPP = QApplication.instance() or QApplication([])
    return RawMaterialIntakePage(current_username="tester")


def test_page_only_offers_raw_materials(db):
    """El combo ofrece solo materia prima, aunque el peso este cargado.

    Un producto terminado con peso de bolsa no se fracciona: ofrecerlo dejaría
    al operador marcar un ingreso de algo que en realidad se vende tal cual.
    """
    _raw_material("Almidon de maiz en big bag", "1300.000")
    _raw_material("Almidon de arroz en big bag", "1000.000")
    _finished("BOLSAS ALMIDON DE MAIZ X 25 KG", "25.000")

    page = _page(db)

    assert page.product_combo.count() == 2
    assert "big bag" in page.weight_hint.text().lower()


def test_page_explains_how_to_mark_a_raw_material(db):
    """Sin ninguna materia prima cargada, la pantalla tiene que decir qué hacer.

    El campo «Rol en el stock» es nuevo: sin esta pista el operador se queda
    sin salida, que es el mismo sintoma que reporto la validacion manual de
    partes de produccion.
    """
    _finished("BOLSAS ALMIDON DE MAIZ X 25 KG", "25.000")

    page = _page(db)

    texto = page.weight_hint.text()
    assert "Maestros" in texto
    assert "Materia prima" in texto


def test_page_computes_big_bags_and_kg_while_adding_lines(db):
    """Regresion: el combo dispara currentIndexChanged al agregar el primer
    producto, antes de que _products_by_id estuviera poblado. El slot lanzaba
    AttributeError y PyQt5 abortaba el proceso entero (0xC0000409)."""
    almidon = _raw_material("Almidon de maiz en big bag", "1300.000")
    _raw_material("Almidon de arroz en big bag", "1000.000")

    page = _page(db)

    # El combo viene ordenado por nombre, asi que se elige explicitamente la
    # linea que este test mira: el nombre solo no dice cual quedo seleccionada.
    indice = page.product_combo.findText(almidon.name)
    assert indice >= 0
    page.product_combo.setCurrentIndex(indice)

    page.bags_input.setValue(22)
    page._add_line()

    assert page.lines_table.rowCount() == 1
    assert page.lines_table.item(0, 0).text() == almidon.name
    assert page.lines_table.item(0, 1).text() == "22"
    assert page.lines_table.item(0, 3).text() == "28,600.00"
    assert "28,600.00" in page.weight_hint.text()


def test_page_refuses_the_same_raw_material_twice(db):
    _raw_material("Almidon de maiz en big bag", "1300.000")

    page = _page(db)
    page.bags_input.setValue(3)
    page._add_line()
    page.bags_input.setValue(4)
    page._add_line()

    assert page.lines_table.rowCount() == 1


def test_page_saves_and_confirms_the_intake(db, monkeypatch):
    """Recorre el camino real del operador: agregar linea, guardar, confirmar.

    Sin monkeypatchear el dialogo de confirmacion: el botón tiene que llevar a
    un ingreso confirmado y con stock, no solo a una fila en la grilla.
    """
    from PyQt5.QtWidgets import QMessageBox

    almidon = _raw_material("Almidon de maiz en big bag", "1300.000")
    page = _page(db)
    page.bags_input.setValue(22)
    page._add_line()
    page.save()
    page.refresh()
    page.table.selectRow(0)
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)

    page.confirm_selected()

    assert RawMaterialIntakeService.lines_of(RawMaterialIntake.get())[0].bags == 22
    assert StockService.balance_for(almidon).balance_kg == Decimal("28600.000")


def test_page_buttons_follow_the_intake_state(db):
    almidon = _raw_material("Almidon de maiz en big bag", "1300.000")
    page = _page(db)
    page.bags_input.setValue(2)
    page._add_line()
    page.save()
    page.refresh()

    page.table.selectRow(0)
    page._sync_row_buttons()
    assert page.edit_button.isEnabled() is True
    assert page.confirm_button.isEnabled() is True

    intake = page.rows[0]
    RawMaterialIntakeService.confirm(intake, current_user="tester")
    page.refresh()
    page.table.selectRow(0)
    page._sync_row_buttons()
    assert page.edit_button.isEnabled() is False
    assert page.confirm_button.isEnabled() is False
    assert page.annul_button.isEnabled() is True
    assert StockService.balance_for(almidon).balance_kg == Decimal("2600.000")
