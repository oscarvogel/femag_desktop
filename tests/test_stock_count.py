"""Conteo fisico y ajustes auditables (#574).

El operador cuenta **bolsas**, no kilos. El libro vive en kilos y la conversion
sale del peso de bolsa del producto, igual que en la pantalla de partes de
produccion.

El conteo no reescribe movimientos: agrega el ajuste que lleva el saldo del
libro a la realidad contada.
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
PESO_BOLSA = Decimal("25.000")  # cada bolsa pesa 25 kg


def _product(name="BOLSAS DE FECULA NATIVA", peso=PESO_BOLSA):
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
        source_ref="stock_take:2026-10-01:init",
        description="Inventario inicial al 01/10/2026",
        movement_date=date(2026, 10, 1),
        created_by="admin",
    )


def test_el_operador_cuenta_bolsas_y_los_kilos_se_derivan(db):
    """50 bolsas de 25 kg son 1.250 kg. Preguntar kilos seria poner la cuenta
    en el operador, que es justo lo que #580 vino a eliminar."""
    producto = _product()
    _inventario_inicial(producto, Decimal("1000"))
    servicio = _servicio()

    conteo = servicio.open_count(DAY)
    linea = servicio.add_line(conteo, producto, Decimal("50"), reason="Conteo de bolsas")

    assert linea.counted_units == Decimal("50.000")
    assert linea.unit_weight_kg == PESO_BOLSA
    assert linea.counted_kg == Decimal("1250.000"), "50 x 25 = 1.250 kg"
    assert linea.calculated_kg == Decimal("1000.000")
    assert linea.difference_kg == Decimal("250.000")


def test_contar_mas_que_el_libro_genera_un_ajuste_positivo(db):
    producto = _product()
    _inventario_inicial(producto, Decimal("1000"))
    servicio = _servicio()

    conteo = servicio.open_count(DAY)
    # El libro dice 1.000 kg = 40 bolsas. Hay 48: sobran 8 bolsas (200 kg).
    linea = servicio.add_line(conteo, producto, Decimal("48"), reason="Habia bolsa sin cargar")
    assert linea.difference_kg == Decimal("200.000")

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
    # Faltan 8 bolsas de 25 kg.
    linea = servicio.add_line(conteo, producto, Decimal("32"), reason="Faltan bolsas rotas")
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
    linea = servicio.add_line(conteo, producto, Decimal("40"))  # 40 x 25 = 1.000

    assert not linea.has_difference
    assert servicio.close_count(conteo) == []
    assert StockMovement.select().count() == 1
    assert StockService.balance_for(producto).balance_kg == Decimal("1000.000")


def test_el_conteo_no_toca_los_movimientos_historicos(db):
    producto = _product()
    _inventario_inicial(producto, Decimal("1000"))
    servicio = _servicio()
    conteo = servicio.open_count(DAY)
    servicio.add_line(conteo, producto, Decimal("36"), reason="Merma")
    antes = StockMovement.get(StockMovement.source_ref == "stock_take:2026-10-01:init")

    servicio.close_count(conteo)

    assert StockMovement.get_by_id(antes.id).quantity_kg == Decimal("1000.000")
    assert StockMovement.select().count() == 2


def test_cerrar_dos_veces_no_duplica_el_ajuste(db):
    producto = _product()
    _inventario_inicial(producto, Decimal("1000"))
    servicio = _servicio()
    conteo = servicio.open_count(DAY)
    servicio.add_line(conteo, producto, Decimal("36"), reason="Merma")

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
    servicio.add_line(conteo, contado, Decimal("28"), reason="Diferencia")
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

    El operador vio 1.000 kg. Despues se emiten 400 kg y el conteo dice que
    habia 1.000. La diferencia es de la orden, no del conteo: el ajuste tiene
    que ser cero. Por eso la linea guarda el saldo del momento en que se agrego,
    no el de ahora.
    """
    producto = _product()
    _inventario_inicial(producto, Decimal("1000"))
    servicio = _servicio()
    conteo = servicio.open_count(DAY)
    linea = servicio.add_line(conteo, producto, Decimal("40"))  # 40 x 25 = 1.000
    assert linea.calculated_kg == Decimal("1000.000")

    StockService.register(
        product=producto,
        movement_type=StockMovement.TYPE_DISPATCH,
        quantity_kg=Decimal("400"),
        source_ref="LoadOrder:1:Dispatch:1",
        description="Despacho OC-000001",
        movement_date=DAY,
        created_by="admin",
    )

    assert StockService.balance_for(producto).balance_kg == Decimal("600.000")
    assert servicio.close_count(conteo) == []
    assert StockService.balance_for(producto).balance_kg == Decimal("600.000")


def test_el_peso_usado_queda_auditado(db):
    """El conteo guarda el peso con el que convertingio, no el de hoy.

    Si despues se corrige el peso de bolsa del maestro, el conteo ya realizado
    tiene que seguir diciendo lo que conto y lo que valia al momento.
    """
    producto = _product()
    _inventario_inicial(producto, Decimal("1000"))
    servicio = _servicio()
    conteo = servicio.open_count(DAY)
    linea = servicio.add_line(conteo, producto, Decimal("50"))

    producto.peso_unitario_kg = Decimal("30.000")
    producto.save()

    assert linea.counted_kg == Decimal("1250.000")
    assert linea.unit_weight_kg == PESO_BOLSA


def test_el_ajuste_queda_asentado_con_usuario_motivo_y_fecha(db):
    """Un ajuste sin rastro de quien lo hizo y por que no sirve de nada."""
    producto = _product()
    _inventario_inicial(producto, Decimal("1000"))
    servicio = StockCountService(current_user="supervisor_1")
    conteo = servicio.open_count(DAY)
    conteo.counted_by = "supervisor_1"
    conteo.save()
    servicio.add_line(conteo, producto, Decimal("30"), reason="Se Romano con el conteo")

    movimiento = servicio.close_count(conteo)[0]

    assert movimiento.created_by == "supervisor_1"
    assert movimiento.observations == "Se Romano con el conteo"
    assert movimiento.movement_date == DAY
    # Y la descripcion dice cuantas bolsas se contaron, no solo los kilos.
    assert "30,000 bolsa(s)" in movimiento.description
    assert "750,000 kg" in movimiento.description


def test_el_conteo_queda_cerrado_con_quien_y_cuando(db):
    producto = _product()
    _inventario_inicial(producto, Decimal("1000"))
    servicio = _servicio()
    conteo = servicio.open_count(DAY)
    servicio.add_line(conteo, producto, Decimal("32"), reason="Merma")
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

    servicio.add_line(conteo, producto, Decimal("36"), reason="Primera vez")
    linea = servicio.add_line(conteo, producto, Decimal("38"), reason="Me corregi")

    assert StockCountLine.select().where(StockCountLine.count == conteo).count() == 1
    assert linea.counted_units == Decimal("38.000")
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
    servicio.add_line(conteo, producto, Decimal("36"), reason="Merma")
    movimiento = servicio.close_count(conteo)[0]

    assert movimiento.movement_date == DAY - timedelta(days=3)
