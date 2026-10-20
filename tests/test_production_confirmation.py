"""Confirmacion del parte de produccion y su efecto en el libro de stock (#572).

El parte arranca como borrador y no toca el stock. Al confirmarlo el operador lo
convierte en produccion real y en ese momento se escriben los movimientos. Un
parte confirmado ya no se edita ni se borra: se anula generando los movimientos
contrarios, y queda asentado quien lo hizo y por que.

Desde #730 la confirmacion escribe ademas el consumo de materia prima: las
bolsas que entran al stock y el almidon que sale van juntos.
"""

from datetime import date
from decimal import Decimal
from itertools import count

import pytest
from PyQt5.QtCore import QDate

from app.models.masters import Product
from app.models.production import ProductionBag, ProductionPart
from app.models.stock import StockMovement
from app.services.production_part_service import ProductionPartService
from app.services.stock_service import StockService

DAY = date(2026, 10, 2)

_MATERIAS = count(1)


def _product(name="Almidon de mandioca", weight="25.000"):
    return Product.create(
        name=name, unit="bolsa", peso_unitario_kg=Decimal(weight), active=True
    )


def _materia_prima(name=None, weight="1000.000", stock_kg="5000.000"):
    """Materia prima **comprada**: el stock sale de una compra real en el libro.

    No es un detalle del test: desde #730 la confirmacion se bloquea si el
    material no alcanza, asi que un parte no se puede confirmar contra una
    materia prima que nadie compro. El stock tiene que entrar por el mismo
    camino que en planta: el ingreso de big bags (#656).
    """
    producto = Product.create(
        name=name or f"Almidon a granel {next(_MATERIAS)}",
        unit="kg",
        peso_unitario_kg=Decimal(weight),
        product_kind="producto",
        stock_role="materia_prima",
        active=True,
    )
    StockService.register(
        product=producto,
        movement_type=StockMovement.TYPE_PURCHASE,
        quantity_kg=Decimal(stock_kg),
        source_ref=f"raw_material_intake:{producto.id}",
        description="Compra de big bag",
        movement_date=DAY,
        created_by="operador1",
    )
    return producto


def _part(product, bags=100, shift="Manana", materia=None, consumos=None):
    if consumos is None:
        if materia is None:
            materia = _materia_prima()
        consumos = [(materia, Decimal("2500.000"))]
    return ProductionPartService.create(
        production_date=DAY, shift=shift, lines=[(product, bags)],
        consumptions=consumos,
    )


def _movimientos_de(part):
    return list(
        StockMovement.select().where(
            StockMovement.source_ref == ProductionPartService.source_ref_of(part)
        )
    )


def test_new_part_is_a_draft_and_does_not_touch_stock(db):
    product = _product()
    materia = _materia_prima()
    part = _part(product, materia=materia)

    assert not part.is_confirmed
    assert not part.is_voided
    assert part.status_label == "Borrador"
    assert _movimientos_de(part) == [], "un borrador no escribe movimientos"
    assert StockService.balance_for(product).balance_kg == Decimal("0.000")
    # La compra de la materia prima sigue como estaba: el borrador no la toco.
    assert StockService.balance_for(materia).balance_kg == Decimal("5000.000")


def test_confirm_writes_one_production_movement_per_product(db):
    """El operador confirma el turno y la produccion entra al stock."""
    almidon = _product("Almidon de mandioca", "25.000")
    fecula = _product("Fecula de mandioca", "20.000")
    materia = _materia_prima()
    part = ProductionPartService.create(
        production_date=DAY, shift="Tarde", lines=[(almidon, 100), (fecula, 50)],
        consumptions=[(materia, Decimal("4000.000"))],
    )

    ProductionPartService.confirm(part, current_user="operador1")

    movimientos = _movimientos_de(part)
    produccion = [m for m in movimientos if m.movement_type == StockMovement.TYPE_PRODUCTION]
    consumos = [
        m for m in movimientos if m.movement_type == StockMovement.TYPE_PRODUCTION_CONSUMPTION
    ]
    assert len(produccion) == 2
    assert len(consumos) == 1
    assert all(m.source_ref == f"production_part:{part.id}" for m in movimientos)
    assert all(m.created_by == "operador1" for m in movimientos)
    assert all(m.movement_date == DAY for m in movimientos)

    assert StockService.balance_for(almidon).balance_kg == Decimal("2500.000")
    assert StockService.balance_for(fecula).balance_kg == Decimal("1000.000")
    # Y la materia prima salio: 5.000 comprados - 4.000 consumidos.
    assert StockService.balance_for(materia).balance_kg == Decimal("1000.000")


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

    assert len(_movimientos_de(part)) == 2, "produccion y consumo, una vez cada uno"
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
    assert _movimientos_de(part) == []


def test_annulling_a_confirmed_part_reverses_the_stock_instead_of_deleting(db):
    """Aca esta el motivo de todo el diseno: borrar desincronizaria el saldo."""
    product = _product()
    materia = _materia_prima()
    part = _part(product, bags=100, materia=materia)
    ProductionPartService.confirm(part, current_user="operador1")
    assert StockService.balance_for(product).balance_kg == Decimal("2500.000")
    assert StockService.balance_for(materia).balance_kg == Decimal("2500.000")

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
    # Y la materia prima vuelve al stock: anular revierte los dos movimientos.
    assert StockService.balance_for(materia).balance_kg == Decimal("5000.000")

    movimientos = _movimientos_de(part)
    assert len(movimientos) == 4, "dos originales y sus dos reversas"
    reversas = [
        m for m in movimientos if m.movement_type == StockMovement.TYPE_ADJUSTMENT_NEGATIVE
    ]
    assert len(reversas) == 1
    assert reversas[0].reverses_id is not None
    assert reversas[0].created_by == "supervisor"
    assert reversas[0].observations == "Se conto dos veces"
    # La reversa del consumo es una entrada: la materia prima vuelve.
    reversa_consumo = [
        m for m in movimientos if m.movement_type == StockMovement.TYPE_ADJUSTMENT_POSITIVE
    ]
    assert len(reversa_consumo) == 1
    assert reversa_consumo[0].quantity_kg == Decimal("2500.000")


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
