"""Confirmacion del parte de produccion y su efecto en el libro de stock (#572).

El parte arranca como borrador y no toca el stock. Al confirmarlo el operador lo
convierte en produccion real y en ese momento se escriben los movimientos. Un
parte confirmado ya no se edita ni se borra: se anula generando los movimientos
contrarios, y queda asentado quien lo hizo y por que.
"""

from datetime import date
from decimal import Decimal

import pytest
from PyQt5.QtCore import QDate

from app.models.masters import Product
from app.models.production import ProductionBag, ProductionPart
from app.models.stock import StockMovement
from app.services.production_part_service import ProductionPartService
from app.services.stock_service import StockService

DAY = date(2026, 10, 2)


def _product(name="Almidon de mandioca", weight="25.000"):
    return Product.create(
        name=name, unit="bolsa", peso_unitario_kg=Decimal(weight), active=True
    )


def _part(product, bags=100, shift="Manana"):
    return ProductionPartService.create(
        production_date=DAY, shift=shift, lines=[(product, bags)]
    )


def _movimientos_de(part):
    return list(
        StockMovement.select().where(
            StockMovement.source_ref == ProductionPartService.source_ref_of(part)
        )
    )


def test_new_part_is_a_draft_and_does_not_touch_stock(db):
    product = _product()
    part = _part(product)

    assert not part.is_confirmed
    assert not part.is_voided
    assert part.status_label == "Borrador"
    assert StockMovement.select().count() == 0
    assert StockService.balance_for(product).balance_kg == Decimal("0.000")


def test_confirm_writes_one_production_movement_per_product(db):
    """El operador confirma el turno y la produccion entra al stock."""
    almidon = _product("Almidon de mandioca", "25.000")
    fecula = _product("Fecula de mandioca", "20.000")
    part = ProductionPartService.create(
        production_date=DAY, shift="Tarde", lines=[(almidon, 100), (fecula, 50)]
    )

    ProductionPartService.confirm(part, current_user="operador1")

    movimientos = _movimientos_de(part)
    assert len(movimientos) == 2
    assert all(m.movement_type == StockMovement.TYPE_PRODUCTION for m in movimientos)
    assert all(m.source_ref == f"production_part:{part.id}" for m in movimientos)
    assert all(m.created_by == "operador1" for m in movimientos)
    assert all(m.movement_date == DAY for m in movimientos)

    assert StockService.balance_for(almidon).balance_kg == Decimal("2500.000")
    assert StockService.balance_for(fecula).balance_kg == Decimal("1000.000")


def test_confirm_marks_the_part_with_who_and_when(db):
    product = _product()
    part = _part(product)

    ProductionPartService.confirm(part, current_user="operador1")

    parte = ProductionPart.get_by_id(part.id)
    assert parte.is_confirmed
    assert parte.status_label == "Confirmado"
    assert parte.confirmed_by == "operador1"
    assert parte.confirmed_at is not None


def test_confirming_twice_does_not_double_the_stock(db):
    """La idempotencia la garantiza el indice unico del libro, no un flag."""
    product = _product()
    part = _part(product, bags=40)

    ProductionPartService.confirm(part, current_user="operador1")
    ProductionPartService.confirm(part, current_user="operador1")

    assert StockMovement.select().count() == 1
    assert StockService.balance_for(product).balance_kg == Decimal("1000.000")


def test_confirmed_part_cannot_be_edited(db):
    product = _product()
    part = _part(product)
    ProductionPartService.confirm(part, current_user="operador1")

    with pytest.raises(ValueError, match="confirmado"):
        ProductionPartService.update(
            part, production_date=DAY, shift="Noche", lines=[(product, 999)]
        )


def test_annulling_a_draft_deletes_it_because_it_never_touched_stock(db):
    """Un borrador se borra: no hay nada que revertir en el libro."""
    product = _product()
    part = _part(product)

    ProductionPartService.annul(part)

    assert ProductionPart.select().count() == 0
    assert StockMovement.select().count() == 0


def test_annulling_a_confirmed_part_reverses_the_stock_instead_of_deleting(db):
    """Aca esta el motivo de todo el diseno: borrar desincronizaria el saldo."""
    product = _product()
    part = _part(product, bags=100)
    ProductionPartService.confirm(part, current_user="operador1")
    assert StockService.balance_for(product).balance_kg == Decimal("2500.000")

    ProductionPartService.annul(
        part, current_user="supervisor", reason="Se conto dos veces"
    )

    assert ProductionPart.select().count() == 1, "el parte no se borra"
    parte = ProductionPart.get_by_id(part.id)
    assert parte.is_voided
    assert parte.status_label == "Anulado"
    assert parte.voided_by == "supervisor"
    assert parte.void_reason == "Se conto dos veces"
    assert ProductionBag.select().count() == 1, "las bolsas se conservan"

    assert StockService.balance_for(product).balance_kg == Decimal("0.000")

    movimientos = _movimientos_de(part)
    assert len(movimientos) == 2
    reversas = [
        m for m in movimientos if m.movement_type == StockMovement.TYPE_ADJUSTMENT_NEGATIVE
    ]
    assert len(reversas) == 1
    assert reversas[0].reverses_id is not None
    assert reversas[0].created_by == "supervisor"
    assert reversas[0].observations == "Se conto dos veces"


def test_annulling_a_confirmed_part_requires_a_reason(db):
    product = _product()
    part = _part(product)
    ProductionPartService.confirm(part, current_user="operador1")

    with pytest.raises(ValueError):
        ProductionPartService.annul(part, current_user="supervisor", reason="   ")

    assert StockService.balance_for(product).balance_kg == Decimal("2500.000")


def test_a_voided_part_is_final(db):
    product = _product()
    part = _part(product)
    ProductionPartService.confirm(part, current_user="operador1")
    ProductionPartService.annul(part, current_user="supervisor", reason="Error")

    with pytest.raises(ValueError):
        ProductionPartService.annul(part, current_user="supervisor", reason="Otra vez")
    with pytest.raises(ValueError):
        ProductionPartService.confirm(part, current_user="operador1")
    # Un parte anulado esta confirmado tambien: el mensaje tiene que decir que
    # esta anulado, no "esta confirmado", o manda al motivo equivocado.
    with pytest.raises(ValueError, match="anulado"):
        ProductionPartService.update(
            part, production_date=DAY, shift="Noche", lines=[(product, 5)]
        )


def test_voided_parts_do_not_count_in_the_day_totals(db):
    """Se muestran en la tabla, pero sus kg ya se revirtieron: no pueden sumar."""
    product = _product()
    confirmado = _part(product, bags=100, shift="Manana")
    borrador = _part(product, bags=50, shift="Tarde")
    ProductionPartService.confirm(confirmado, current_user="operador1")
    ProductionPartService.annul(confirmado, current_user="supervisor", reason="Error")

    filas = ProductionPartService.for_day(DAY)
    totales = ProductionPartService.totals(filas)

    assert len(filas) == 2, "los dos partes se listan"
    assert totales.lines == 1, "solo cuenta el borrador"
    assert totales.bags == 50
    assert totales.kg == Decimal("1250.00")


def test_confirm_refuses_a_part_without_bags(db):
    """Un parte sin lineas no representa produccion: no hay que confirmar nada."""
    part = ProductionPart.create(production_date=DAY, shift="Manana")

    with pytest.raises(ValueError, match="bolsas"):
        ProductionPartService.confirm(part, current_user="operador1")

    assert StockMovement.select().count() == 0


_QAPP = None


def _page(db, current_username="operador1"):
    """Construye la pantalla de verdad con la base de tests.

    La ``QApplication`` se guarda a nivel de modulo a proposito: si se recolecta
    se lleva por delante los widgets C++ y PyQt falla con "wrapped C/C++ object
    ... has been deleted".
    """
    global _QAPP
    from PyQt5.QtWidgets import QApplication

    from app.ui.production_parts import ProductionPartPage

    if _QAPP is None:
        _QAPP = QApplication.instance() or QApplication([])
    return ProductionPartPage(current_username=current_username)


def _select_first(page):
    page.day.setDate(QDate(DAY.year, DAY.month, DAY.day))
    page.refresh()
    page.table.selectRow(0)


def test_screen_shows_the_part_state_and_gates_the_buttons(db):
    """Borrador se confirma y se edita; confirmado ya no se toca."""
    product = _product()
    part = _part(product, bags=100)

    page = _page(db)
    _select_first(page)

    assert page.table.item(0, 2).text() == "Borrador", "columna Estado"
    assert page.confirm_button.isEnabled()
    assert page.edit_button.isEnabled()

    ProductionPartService.confirm(part, current_user="operador1")
    _select_first(page)

    assert page.table.item(0, 2).text() == "Confirmado"
    assert not page.confirm_button.isEnabled(), "un parte confirmado no se reconfirma"
    assert not page.edit_button.isEnabled(), "un parte confirmado no se edita"
    assert page.annul_button.isEnabled(), "se puede anular, con motivo"


def test_screen_annul_button_is_disabled_for_a_voided_part(db):
    product = _product()
    part = _part(product, bags=100)
    ProductionPartService.confirm(part, current_user="operador1")
    ProductionPartService.annul(part, current_user="supervisor", reason="Error")

    page = _page(db)
    _select_first(page)

    assert page.table.item(0, 2).text() == "Anulado"
    assert not page.annul_button.isEnabled()
    assert not page.confirm_button.isEnabled()
    assert not page.edit_button.isEnabled()


def test_screen_summary_counts_confirmed_and_draft(db):
    product = _product()
    confirmado = _part(product, bags=100, shift="Manana")
    _part(product, bags=50, shift="Tarde")
    ProductionPartService.confirm(confirmado, current_user="operador1")

    page = _page(db)
    _select_first(page)

    resumen = page.summary.text()
    assert "1 confirmado(s)" in resumen
    assert "1 en borrador" in resumen
