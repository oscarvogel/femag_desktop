"""#730: la produccion consume la materia prima que el turno utilizo.

Antes de este issue, confirmar un parte de produccion escribia **un solo**
movimiento: la entrada de las bolsas embolsadas. La materia prima que se
fracciono nunca salia del stock, asi que el mismo kilo quedaba en el stock de
la materia prima y en el del producto terminado, y el stock de almidon solo
crecia.

Ahora la confirmacion escribe los dos movimientos juntos: las bolsas entran y
la materia prima sale. Y si no hay materia prima suficiente, la confirmacion se
bloquea: no se puede producir material que no se compro.
"""

import os
from datetime import date
from decimal import Decimal

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app.models.masters import Product
from app.models.production import ProductionConsumption, ProductionPart
from app.models.stock import StockMovement
from app.services.production_part_service import ProductionPartService
from app.services.stock_service import StockService

DAY = date(2026, 10, 20)


def _bolsa(name="BOLSAS ALMIDON DE MAIZ X 25 KG", weight="25.000"):
    return Product.create(
        name=name,
        unit="unidad",
        peso_unitario_kg=Decimal(weight),
        product_kind="producto",
        stock_role="terminado",
        active=True,
    )


def _materia_prima(name="ALMIDON MAIZ BIG BAG", weight="1000.000", stock_kg=None):
    """Materia prima comprada. Sin ``stock_kg`` no tiene stock: sirve para
    probar que la confirmacion se bloquea."""
    producto = Product.create(
        name=name,
        unit="kg",
        peso_unitario_kg=Decimal(weight),
        product_kind="producto",
        stock_role="materia_prima",
        active=True,
    )
    if stock_kg is not None:
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


def _parte(bolsa, materia, kg="1000.000", bags=40):
    return ProductionPartService.create(
        production_date=DAY,
        shift="Mañana",
        lines=[(bolsa, bags)],
        consumptions=[(materia, Decimal(kg))],
    )


def test_el_parte_guarda_la_materia_prima_consumida(db):
    bolsa = _bolsa()
    materia = _materia_prima(stock_kg="5000.000")
    part = _parte(bolsa, materia, kg="1000.000")

    consumos = ProductionPartService.consumptions_of(part)
    assert len(consumos) == 1
    assert consumos[0].product_id == materia.id
    assert consumos[0].kg == Decimal("1000.00")


def test_confirmar_saca_la_materia_prima_del_stock(db):
    """La bolsa entra y el almidon sale, en la misma confirmacion."""
    bolsa = _bolsa()
    materia = _materia_prima(stock_kg="5000.000")
    part = _parte(bolsa, materia, kg="1000.000", bags=40)

    ProductionPartService.confirm(part, current_user="operador1")

    movimientos = list(
        StockMovement.select().where(
            StockMovement.source_ref == ProductionPartService.source_ref_of(part)
        )
    )
    produccion = [m for m in movimientos if m.movement_type == StockMovement.TYPE_PRODUCTION]
    consumo = [
        m for m in movimientos if m.movement_type == StockMovement.TYPE_PRODUCTION_CONSUMPTION
    ]
    assert len(produccion) == 1
    assert len(consumo) == 1
    assert consumo[0].product_id == materia.id
    assert consumo[0].quantity_kg == Decimal("1000.000")

    # 40 bolsas de 25 kg entran; 1.000 kg de almidon salen.
    assert StockService.balance_for(bolsa).balance_kg == Decimal("1000.000")
    assert StockService.balance_for(materia).balance_kg == Decimal("4000.000")


def test_el_mismo_kilo_no_queda_en_los_dos_stocks(db):
    """La regla de la propuesta: la produccion consume y genera.

    1.000 kg de almidon consumed producen 40 bolsas de 25 kg. Al final hay
    1.000 kg de bolsas y 1.000 kg menos de almidon: el mismo kilo no esta
    counted dos veces.
    """
    bolsa = _bolsa()
    materia = _materia_prima(stock_kg="5000.000")
    part = _parte(bolsa, materia, kg="1000.000", bags=40)

    ProductionPartService.confirm(part, current_user="operador1")

    _embolsado = StockService.balance_for(bolsa).balance_kg
    _restante = StockService.balance_for(materia).balance_kg
    assert _embolsado == Decimal("1000.000")
    assert _restante == Decimal("4000.000")
    assert _embolsado + _restante == Decimal("5000.000"), "no se duplica ni se pierde"


def test_confirmar_se_bloquea_si_no_hay_materia_prima_suficiente(db):
    """No se puede producir material que no se compro."""
    bolsa = _bolsa()
    materia = _materia_prima(stock_kg="500.000")
    part = _parte(bolsa, materia, kg="1000.000", bags=40)

    with pytest.raises(ValueError, match="materia prima suficiente"):
        ProductionPartService.confirm(part, current_user="operador1")

    # Y el libro no se toco: el parte sigue siendo un borrador.
    parte = ProductionPart.get_by_id(part.id)
    assert not parte.is_confirmed
    assert StockService.balance_for(materia).balance_kg == Decimal("500.000")
    assert StockService.balance_for(bolsa).balance_kg == Decimal("0.000")


def test_confirmar_se_bloquea_si_no_hay_materia_prima_cargada(db):
    bolsa = _bolsa()
    materia = _materia_prima(stock_kg=None)
    part = _parte(bolsa, materia, kg="1000.000", bags=40)

    with pytest.raises(ValueError, match="materia prima suficiente"):
        ProductionPartService.confirm(part, current_user="operador1")

    assert not ProductionPart.get_by_id(part.id).is_confirmed


def test_un_parte_sin_materia_prima_consumida_no_se_puede_confirmar(db):
    """Las bolsas no entran al stock si el almidon no sale.

    Hay dos capas: el servicio no deja **guardar** un parte sin consumo, y
    tampoco deja **confirmar** uno que se haya armado por otro lado (un parte
    viejo, o una fila tocada a mano en la base).
    """
    bolsa = _bolsa()
    _materia_prima(stock_kg="5000.000")

    with pytest.raises(ValueError, match="materia prima que consumi"):
        ProductionPartService.create(
            production_date=DAY, shift="Mañana", lines=[(bolsa, 40)]
        )

    assert ProductionPart.select().count() == 0

    # Un parte armado por fuera del servicio tampoco se puede confirmar.
    parte = ProductionPart.create(production_date=DAY, shift="Mañana")
    from app.models.production import ProductionBag

    ProductionBag.create(
        part=parte, product=bolsa, bags=40, unit_weight_kg=Decimal("25.000"),
        kg=Decimal("1000.00"),
    )

    with pytest.raises(ValueError, match="materia prima consumida"):
        ProductionPartService.confirm(parte, current_user="operador1")

    assert not ProductionPart.get_by_id(parte.id).is_confirmed
    assert StockService.balance_for(bolsa).balance_kg == Decimal("0.000")


def test_no_se_puede_consumir_un_producto_que_no_es_materia_prima(db):
    """El consumo es de materia prima: una bolsa terminada no se consume."""
    bolsa = _bolsa()
    otra_bolsa = _bolsa("BOLSAS FECULA NATIVA", "25.000")
    materia = _materia_prima(stock_kg="5000.000")

    with pytest.raises(ValueError, match="no es materia prima"):
        ProductionPartService.create(
            production_date=DAY, shift="Mañana", lines=[(bolsa, 40)],
            consumptions=[(otra_bolsa, Decimal("1000.000"))],
        )

    assert ProductionPart.select().count() == 0
    assert materia is not None


def test_los_kilos_consumidos_tienen_que_ser_mayores_a_cero(db):
    bolsa = _bolsa()
    materia = _materia_prima(stock_kg="5000.000")

    with pytest.raises(ValueError, match="mayores a cero"):
        ProductionPartService.create(
            production_date=DAY, shift="Mañana", lines=[(bolsa, 40)],
            consumptions=[(materia, Decimal("0"))],
        )


def test_anular_revierte_el_consumo_y_devuelve_la_materia_prima(db):
    bolsa = _bolsa()
    materia = _materia_prima(stock_kg="5000.000")
    part = _parte(bolsa, materia, kg="1000.000", bags=40)

    ProductionPartService.confirm(part, current_user="operador1")
    assert StockService.balance_for(materia).balance_kg == Decimal("4000.000")

    ProductionPartService.annul(
        part, current_user="supervisor", reason="Se conto dos veces"
    )

    assert StockService.balance_for(materia).balance_kg == Decimal("5000.000")
    assert StockService.balance_for(bolsa).balance_kg == Decimal("0.000")
    # Las lineas del parte se conservan: queda el rastro de que existio.
    assert ProductionConsumption.select().count() == 1


def test_confirmar_dos_veces_no_descuenta_dos_veces(db):
    bolsa = _bolsa()
    materia = _materia_prima(stock_kg="5000.000")
    part = _parte(bolsa, materia, kg="1000.000", bags=40)

    ProductionPartService.confirm(part, current_user="operador1")
    ProductionPartService.confirm(part, current_user="operador1")

    assert StockService.balance_for(materia).balance_kg == Decimal("4000.000")
    assert (
        StockMovement.select()
        .where(StockMovement.movement_type == StockMovement.TYPE_PRODUCTION_CONSUMPTION)
        .count()
        == 1
    )


def test_dos_turnos_consumen_de_a_materia_prima_seguida(db):
    """El segundo turno ve el stock que dejo el primero."""
    bolsa = _bolsa()
    materia = _materia_prima(stock_kg="5000.000")

    primero = _parte(bolsa, materia, kg="3000.000", bags=40)
    ProductionPartService.confirm(primero, current_user="operador1")
    assert StockService.balance_for(materia).balance_kg == Decimal("2000.000")

    segundo = ProductionPartService.create(
        production_date=DAY, shift="Tarde", lines=[(bolsa, 40)],
        consumptions=[(materia, Decimal("1500.000"))],
    )
    ProductionPartService.confirm(segundo, current_user="operador1")
    assert StockService.balance_for(materia).balance_kg == Decimal("500.000")

    # Y un tercer turno que pida mas de lo que queda se bloquea.
    tercero = ProductionPartService.create(
        production_date=DAY, shift="Noche", lines=[(bolsa, 40)],
        consumptions=[(materia, Decimal("1000.000"))],
    )
    with pytest.raises(ValueError, match="materia prima suficiente"):
        ProductionPartService.confirm(tercero, current_user="operador1")


def test_el_esquema_crea_la_tabla_de_consumo(db):
    """La tabla nueva aparece sola: ``ensure_runtime_schema`` la crea."""
    from app.config.schema import ensure_runtime_schema, validate_runtime_schema

    ensure_runtime_schema(db)
    validate_runtime_schema(db)

    assert "production_consumption" in db.get_tables()
    columnas = {column.name for column in db.get_columns("production_consumption")}
    assert {"part_id", "product_id", "kg"} <= columnas


def test_la_pantalla_muestra_el_stock_disponible_de_la_materia_prima(db):
    """El operador tiene que ver cuanto hay antes de elegir, no despues."""
    from PyQt5.QtWidgets import QApplication

    from app.ui.production_parts import ProductionPartPage

    app = QApplication.instance() or QApplication([])

    bolsa = _bolsa()
    materia = _materia_prima(stock_kg="5000.000")

    page = ProductionPartPage(current_username="operador1")

    nombres = [
        page.raw_material_combo.itemText(indice)
        for indice in range(page.raw_material_combo.count())
    ]
    assert "ALMIDON MAIZ BIG BAG" in nombres
    assert "BOLSAS ALMIDON DE MAIZ X 25 KG" not in nombres, "las bolsas no se consumen"

    indice = page.raw_material_combo.findData(materia.id)
    page.raw_material_combo.setCurrentIndex(indice)
    app.processEvents()

    assert "5,000.000 kg" in page.consumption_hint.text()
    assert bolsa is not None
