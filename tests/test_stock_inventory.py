from datetime import date
from decimal import Decimal

import pytest

from app.models.masters import (
    PRODUCT_KIND_INTERNAL,
    PRODUCT_KIND_PRODUCT,
    PRODUCT_KIND_SERVICE,
    Product,
)
from app.models.stock import StockMovement
from app.services.stock_inventory_service import (
    StockInventoryError,
    StockInventoryService,
    source_ref_of,
)
from app.services.stock_service import StockService

DAY = date(2026, 10, 1)


def _product(name="BOLSAS DE FECULA NATIVA", weight="25.000", kind=PRODUCT_KIND_PRODUCT):
    return Product.create(
        name=name, unit="unidad", peso_unitario_kg=Decimal(weight), product_kind=kind, active=True
    )


def test_el_conteo_define_el_saldo_de_arranque(db):
    """Este es el punto de partida del libro: sin el, el saldo no significa nada."""
    fecula = _product("BOLSAS DE FECULA NATIVA", "25.000")
    almidon = _product("BOLSAS ALMIDON DE MAIZ X 25 KG.", "25.000")

    movimientos = StockInventoryService.load_initial(
        DAY, {fecula.id: Decimal("710025"), almidon.id: Decimal("34600")}, current_user="supervisor"
    )

    assert len(movimientos) == 2
    assert StockService.balance_for(fecula).balance_kg == Decimal("710025.000")
    assert StockService.balance_for(almidon).balance_kg == Decimal("34600.000")
    assert StockMovement.select().count() == 2


def test_cargar_dos_veces_el_mismo_dia_no_reemplaza_nada(db):
    """El indice unico evita el duplicado, pero hace falta el error explicito.

    Sin el, el operador carga un conteo corregido, no ve ningun cambio y se
    queda creyendo que el saldo cambio.
    """
    fecula = _product()
    StockInventoryService.load_initial(DAY, {fecula.id: Decimal("1000")})

    with pytest.raises(StockInventoryError, match="ya tiene inventario inicial"):
        StockInventoryService.load_initial(DAY, {fecula.id: Decimal("9999")})

    assert StockService.balance_for(fecula).balance_kg == Decimal("1000.000")
    assert StockMovement.select().count() == 1


def test_las_filas_en_cero_se_omiten(db):
    """Un movimiento de 0 kg no dice nada y solo ensucia el libro."""
    fecula = _product()
    vacio = _product("ALMIDON", "25.000")

    movimientos = StockInventoryService.load_initial(
        DAY, {fecula.id: Decimal("500"), vacio.id: Decimal("0")}
    )

    assert len(movimientos) == 1
    assert StockMovement.select().count() == 1
    assert StockService.balance_for(vacio).balance_kg == Decimal("0.000")


def test_anular_el_conteo_deja_el_saldo_en_cero_y_el_rastro(db):
    fecula = _product()
    StockInventoryService.load_initial(DAY, {fecula.id: Decimal("1000")})

    reversas = StockInventoryService.reverse_initial(
        DAY, current_user="supervisor", reason="Se conto mal"
    )

    assert len(reversas) == 1
    assert reversas[0].movement_type == StockMovement.TYPE_ADJUSTMENT_NEGATIVE
    assert reversas[0].observations == "Se conto mal"
    assert StockService.balance_for(fecula).balance_kg == Decimal("0.000")
    # El conteo original sigue en el libro.
    assert StockMovement.select().count() == 2


def test_anular_exige_motivo_y_que_exista_un_conteo(db):
    fecula = _product()
    with pytest.raises(StockInventoryError, match="por qué"):
        StockInventoryService.reverse_initial(DAY, reason="   ")
    with pytest.raises(StockInventoryError, match="no tiene inventario inicial"):
        StockInventoryService.reverse_initial(DAY, reason="Error")

    StockInventoryService.load_initial(DAY, {fecula.id: Decimal("10")})
    StockInventoryService.reverse_initial(DAY, reason="Mal conteo")
    # El conteo sigue en el libro pero ya no esta vigente: no se puede anular dos veces.
    assert StockInventoryService.is_voided(DAY)
    with pytest.raises(StockInventoryError, match="ya está anulado"):
        StockInventoryService.reverse_initial(DAY, reason="Otra vez")


def test_despues_de_anular_se_puede_cargar_de_nuevo(db):
    """Corregir un conteo es anular y volver a cargar, no pisar."""
    fecula = _product()
    StockInventoryService.load_initial(DAY, {fecula.id: Decimal("1000")})
    StockInventoryService.reverse_initial(DAY, reason="Mal conteo")

    StockInventoryService.load_initial(date(2026, 10, 2), {fecula.id: Decimal("850")})

    assert StockService.balance_for(fecula).balance_kg == Decimal("850.000")


def test_solo_se_cuentan_productos_de_venta_activos(db):
    venta = _product("BOLSAS DE FECULA")
    _product("FLETE", "1.000", PRODUCT_KIND_SERVICE)
    _product("BANDA FILTRO", "1.000", PRODUCT_KIND_INTERNAL)
    inactivo = _product("PRODUCTO DADO DE BAJA", "25.000")
    inactivo.active = False
    inactivo.save()

    contables = {p.id for p in StockInventoryService.countable_products()}

    assert venta.id in contables
    assert inactivo.id not in contables
    assert len(contables) == 1


def test_el_conteo_guarda_quien_lo_hizo_y_la_fecha(db):
    fecula = _product()
    StockInventoryService.load_initial(
        DAY, {fecula.id: Decimal("1000")}, current_user="oscar", observations="Conteo de arranque"
    )

    movimiento = StockMovement.get(StockMovement.source_ref == source_ref_of(DAY))
    assert movimiento.created_by == "oscar"
    assert movimiento.observations == "Conteo de arranque"
    assert movimiento.movement_date == DAY
    assert movimiento.description == "Inventario inicial al 01/10/2026"
