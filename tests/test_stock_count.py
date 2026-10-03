"""Conteo fisico y ajustes auditables (#574).

El conteo no reescribe movimientos: agrega el ajuste que lleva el saldo del
libro a la realidad contada. El libro queda mostrando la foto completa de lo que
entro, salio, se devolvio y se conto.
"""

from datetime import date, timedelta
from decimal import Decimal

import pytest

from app.models.masters import PRODUCT_KIND_PRODUCT, Product
from app.models.stock import StockMovement
from app.models.stock_count import StockCount, StockCountLine
from app.services.stock_count_service import StockCountError, StockCountService
from app.services.stock_service import StockService

DAY = date(2026, 10, 5)


def _product(name="BOLSAS DE FECULA NATIVA", peso="25.000"):
    return Product.create(
        name=name, unit="unidad", peso_unitario_kg=Decimal(peso),
        product_kind=PRODUCT_KIND_PRODUCT, active=True,
    )


def _servicio() -> StockCountService:
    return StockCountService(current_user="admin")


def _inventario_inicial(producto, kg):
    StockService.register(
        product=producto,
        movement_type=StockMovement.TYPE_INITIAL_INVENTORY,
        quantity_kg=kg,
        source_ref=f"stock_take:2026-10-01:init",
        description="Inventario inicial al 01/10/2026",
        movement_date=date(2026, 10, 1),
        created_by="admin",
    )


def test_contar_mas_que_el_libro_genera_un_ajuste_positivo(db):
    producto = _product()
    _inventario_inicial(producto, Decimal("1000"))
    servicio = _servicio()

    conteo = servicio.open_count(DAY)
    linea = servicio.add_line(conteo, producto, Decimal("1200"), reason="Habia bolsa que no estaba en el sistema")

    assert linea.calculated_kg == Decimal("1000.000")
    assert linea.difference_kg == Decimal("200.000")
    assert linea.has_difference

    movimientos = servicio.close_count(conteo)

    assert len(movimientos) == 1
    assert movimientos[0].movement_type == StockMovement.TYPE_ADJUSTMENT_POSITIVE
    assert movimientos[0].quantity_kg == Decimal("200.000")
    assert StockService.balance_for(producto).balance_kg == Decimal("1200.000")


def test_contar_menos_que_el_libro_genera_un_ajuste_negativo(db):
    producto = _product()
    _inventario_inicial(producto, Decimal("1000"))
    servicio = _servicio()

    conteo = servicio.open_count(DAY)
    linea = servicio.add_line(conteo, producto, Decimal("800"), reason="Faltan bolsas rotas")

    assert linea.difference_kg == Decimal("-200.000")
    movimientos = servicio.close_count(conteo)

    assert movimientos[0].movement_type == StockMovement.TYPE_ADJUSTMENT_NEGATIVE
    assert movimientos[0].quantity_kg == Decimal("200.000")
    assert StockService.balance_for(producto).balance_kg == Decimal("800.000")


def test_contar_exacto_no_genera_nada(db):
    """Si el conteo coincide con el libro no hay nada que registrar."""
    producto = _product()
    _inventario_inicial(producto, Decimal("1000"))
    servicio = _servicio()

    conteo = servicio.open_count(DAY)
    linea = servicio.add_line(conteo, producto, Decimal("1000"))

    assert not linea.has_difference
    assert servicio.close_count(conteo) == []
    assert StockMovement.select().count() == 1
    assert StockService.balance_for(producto).balance_kg == Decimal("1000.000")


def test_el_conteo_no_toca_los_movimientos_historicos(db):
    """El ajuste es un movimiento mas. Los anteriores no se reescriben."""
    producto = _product()
    _inventario_inicial(producto, Decimal("1000"))
    servicio = _servicio()
    conteo = servicio.open_count(DAY)
    servicio.add_line(conteo, producto, Decimal("900"), reason="Merma")
    antes = StockMovement.get(StockMovement.source_ref == "stock_take:2026-10-01:init")

    servicio.close_count(conteo)

    assert StockMovement.get_by_id(antes.id).quantity_kg == Decimal("1000.000")
    assert StockMovement.select().count() == 2


def test_cerrar_dos_veces_no_duplica_el_ajuste(db):
    """Idempotencia por el indice unico del libro."""
    producto = _product()
    _inventario_inicial(producto, Decimal("1000"))
    servicio = _servicio()
    conteo = servicio.open_count(DAY)
    servicio.add_line(conteo, producto, Decimal("900"), reason="Merma")

    servicio.close_count(conteo)
    with pytest.raises(StockCountError, match="ya está cerrado"):
        servicio.close_count(conteo)

    assert StockMovement.select().count() == 2
    assert StockService.balance_for(producto).balance_kg == Decimal("900.000")


def test_un_conteo_parcial_solo_ajusta_lo_contado(db):
    """Lo que no se conto no se ajusta.

    Si el operador cuenta 2 de 20 productos, los otros 18 tienen que quedar como
    estaban. Ajustarlos a cero seria la peor forma de romper un inventario.
    """
    contado = _product("FECULA A")
    no_contado = _product("FECULA B")
    _inventario_inicial(contado, Decimal("1000"))
    _inventario_inicial(no_contado, Decimal("1000"))
    servicio = _servicio()

    conteo = servicio.open_count(DAY)
    servicio.add_line(conteo, contado, Decimal("700"), reason="Diferencia")
    servicio.close_count(conteo)

    assert StockService.balance_for(contado).balance_kg == Decimal("700.000")
    assert StockService.balance_for(no_contado).balance_kg == Decimal("1000.000"), (
        "el producto que no se conto no puede moverse"
    )


def test_sacar_una_linea_no_genera_ajuste(db):
    producto = _product()
    _inventario_inicial(producto, Decimal("1000"))
    servicio = _servicio()
    conteo = servicio.open_count(DAY)
    linea = servicio.add_line(conteo, producto, Decimal("10"), reason="Me equivoque de fila")
    servicio.remove_line(conteo, linea)

    assert servicio.close_count(conteo) == []
    assert StockService.balance_for(producto).balance_kg == Decimal("1000.000")


def test_el_ajuste_compara_con_el_saldo_visto_al_contar(db):
    """Si despues de contar se emite una orden, el ajuste no la absorbe.

    El operador vio 1.000 kg en el deposito. Despues se emiten 400 kg y el
    conteo dice que habia 1.000. El ajuste tiene que ser de 0: la diferencia es
    de la orden, no del conteo. Por eso la linea guarda el saldo del momento en
    que se agrego, no el de ahora.
    """
    producto = _product()
    _inventario_inicial(producto, Decimal("1000"))
    servicio = _servicio()
    conteo = servicio.open_count(DAY)
    linea = servicio.add_line(conteo, producto, Decimal("1000"))
    assert linea.calculated_kg == Decimal("1000.000")

    # Se emite una orden despues de contar.
    StockService.register(
        product=producto,
        movement_type=StockMovement.TYPE_DISPATCH,
        quantity_kg=Decimal("400"),
        source_ref="LoadOrder:1:Dispatch:1",
        description="Despacho OC-000001",
        movement_date=DAY,
        created_by="admin",
    )

    # El conteo dice 1.000, el libro ahora dice 600: la diferencia es de la orden.
    assert StockService.balance_for(producto).balance_kg == Decimal("600.000")
    assert servicio.close_count(conteo) == []
    assert StockService.balance_for(producto).balance_kg == Decimal("600.000")


def test_el_ajuste_queda_asentado_con_usuario_motivo_y_fecha(db):
    """Un ajuste sin rastro de quien lo hizo y por que no sirve de nada."""
    producto = _product()
    _inventario_inicial(producto, Decimal("1000"))
    servicio = StockCountService(current_user="supervisor_1")
    conteo = servicio.open_count(DAY)
    conteo.counted_by = "supervisor_1"
    conteo.save()
    servicio.add_line(conteo, producto, Decimal("750"), reason="Se Romano con el conteo")

    movimiento = servicio.close_count(conteo)[0]

    assert movimiento.created_by == "supervisor_1"
    assert movimiento.observations == "Se Romano con el conteo"
    assert movimiento.movement_date == DAY
    assert "1.000,000" in movimiento.description or "1.000" in movimiento.description


def test_el_conteo_queda_cerrado_con_quien_y_cuando(db):
    producto = _product()
    _inventario_inicial(producto, Decimal("1000"))
    servicio = _servicio()
    conteo = servicio.open_count(DAY)
    servicio.add_line(conteo, producto, Decimal("800"), reason="Merma")
    servicio.close_count(conteo)

    cerrado = StockCount.get_by_id(conteo.id)
    assert cerrado.status == StockCount.STATUS_CLOSED
    assert cerrado.closed_by == "admin"
    assert cerrado.closed_at is not None
    assert cerrado.count_date == DAY


def test_no_se_puede_contar_un_producto_dos_veces_en_el_mismo_conteo(db):
    producto = _product()
    _inventario_inicial(producto, Decimal("1000"))
    servicio = _servicio()
    conteo = servicio.open_count(DAY)

    servicio.add_line(conteo, producto, Decimal("900"), reason="Primera vez")
    linea = servicio.add_line(conteo, producto, Decimal("950"), reason="Me corregi")

    assert StockCountLine.select().where(StockCountLine.count == conteo).count() == 1
    assert linea.counted_kg == Decimal("950.000")
    # Y al recargar el conteo no recalcula contra el libro.
    assert linea.calculated_kg == Decimal("1000.000")


def test_abrir_un_conteo_para_la_misma_fecha_devuelve_el_que_ya_esta_abierto(db):
    servicio = _servicio()
    primero = servicio.open_count(DAY)
    segundo = servicio.open_count(DAY, notes="otro intento")

    assert primero.id == segundo.id
    assert StockCount.select().count() == 1


def test_se_puede_contar_desde_una_fecha_distinta_a_la_del_conteo(db):
    """El ajuste se fecha el dia del conteo, no el de hoy."""
    producto = _product()
    _inventario_inicial(producto, Decimal("1000"))
    servicio = _servicio()
    conteo = servicio.open_count(DAY - timedelta(days=3))
    servicio.add_line(conteo, producto, Decimal("900"), reason="Merma")
    movimiento = servicio.close_count(conteo)[0]

    assert movimiento.movement_date == DAY - timedelta(days=3)
