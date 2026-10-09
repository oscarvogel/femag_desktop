"""Inventario inicial contado en bolsas (#651).

El conteo se hace en **bolsas**, igual que Conteo fisico y partes de produccion.
Los kilos se derivan del peso de bolsa del producto y el libro los sigue
guardando en ``quantity_kg``: la bolsa es la forma de *expresar* el conteo, no la
unidad del saldo.

Antes esta pantalla pedia kilos escritos a mano, y el mismo numero significaba
una cosa u otra segun donde se escribiera: 500 en Conteo fisico eran 500 bolsas,
aca 500 kg. A 25 kg por bolsa, el error es de 25 veces.
"""

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
BOLSA_25 = Decimal("25.000")


def _product(name="BOLSAS DE FECULA NATIVA", weight="25.000", kind=PRODUCT_KIND_PRODUCT):
    return Product.create(
        name=name, unit="unidad", peso_unitario_kg=Decimal(weight), product_kind=kind, active=True
    )


def test_el_conteo_define_el_saldo_de_arranque(db):
    """Este es el punto de partida del libro: sin el, el saldo no significa nada.

    40 bolsas de 25 kg son 1.000 kg. El operador cuenta lo que ve en el deposito
    y la cuenta la hace la app, no el.
    """
    fecula = _product("BOLSAS DE FECULA NATIVA", "25.000")
    almidon = _product("BOLSAS ALMIDON DE MAIZ X 25 KG.", "25.000")

    movimientos = StockInventoryService.load_initial(
        DAY, {fecula.id: Decimal("40"), almidon.id: Decimal("16")}, current_user="supervisor"
    )

    assert len(movimientos) == 2
    assert StockService.balance_for(fecula).balance_kg == Decimal("1000.000")
    assert StockService.balance_for(almidon).balance_kg == Decimal("400.000")
    assert StockMovement.select().count() == 2


def test_los_kilos_salen_del_peso_de_cada_producto(db):
    """Cada producto convierte con SU peso, no con uno global de 25.

    Es la diferencia entre contar y estimar: si la bolsa de almidon pesa 20 kg,
    100 bolsas son 2.000 kg y no 2.500.
    """
    fecula = _product("FECULA X 25 KG", "25.000")
    almidon = _product("ALMIDON X 20 KG", "20.000")

    StockInventoryService.load_initial(
        DAY, {fecula.id: Decimal("100"), almidon.id: Decimal("100")}
    )

    assert StockService.balance_for(fecula).balance_kg == Decimal("2500.000")
    assert StockService.balance_for(almidon).balance_kg == Decimal("2000.000")


def test_un_producto_sin_peso_de_bolsa_no_se_puede_cargar(db):
    """Sin peso de bolsa no hay conversion, y arrancar el libro en cero no es una
    carga: es un error. Es el mismo motivo por el que Conteo fisico se niega
    (#650), y por eso el error tiene que decir que cargar y donde."""
    sin_peso = Product.create(
        name="FECULA SIN PESO CARGADO", unit="kg", peso_unitario_kg=Decimal("0.000"),
        product_kind=PRODUCT_KIND_PRODUCT, active=True,
    )

    with pytest.raises(StockInventoryError) as error:
        StockInventoryService.load_initial(DAY, {sin_peso.id: Decimal("100")})

    assert sin_peso.name in str(error.value)
    assert "peso de bolsa" in str(error.value)
    assert "Productos" in str(error.value)
    assert StockService.balance_for(sin_peso).balance_kg == Decimal("0.000")
    assert StockMovement.select().count() == 0


def test_releer_una_carga_devuelve_las_bolsas_que_se_cargaron(db):
    """La pantalla cuenta en bolsas: si al volver a abrir la fecha mostrara los
    kilos en el campo de bolsas, el operador veria 1.000 donde escribio 40 y
    creeria que se cargo otra cosa."""
    fecula = _product()
    StockInventoryService.load_initial(DAY, {fecula.id: Decimal("40")})

    conteos = StockInventoryService.initial_counts_in_bags(DAY)

    assert conteos[fecula.id] == Decimal("40.000")
    # Y los kilos siguen disponibles para quien los necesite.
    assert StockInventoryService.initial_quantities(DAY)[fecula.id] == Decimal("1000.000")


def test_cargar_dos_veces_el_mismo_dia_no_reemplaza_nada(db):
    """El indice unico evita el duplicado, pero hace falta el error explicito.

    Sin el, el operador carga un conteo corregido, no ve ningun cambio y se
    queda creyendo que el saldo cambio.
    """
    fecula = _product()
    StockInventoryService.load_initial(DAY, {fecula.id: Decimal("40")})

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
    StockInventoryService.load_initial(DAY, {fecula.id: Decimal("40")})

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
    StockInventoryService.load_initial(DAY, {fecula.id: Decimal("40")})
    StockInventoryService.reverse_initial(DAY, reason="Mal conteo")

    StockInventoryService.load_initial(date(2026, 10, 2), {fecula.id: Decimal("34")})

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
        DAY, {fecula.id: Decimal("40")}, current_user="oscar", observations="Conteo de arranque"
    )

    movimiento = StockMovement.get(StockMovement.source_ref == source_ref_of(DAY))
    assert movimiento.created_by == "oscar"
    assert movimiento.observations == "Conteo de arranque"
    assert movimiento.movement_date == DAY
    assert movimiento.description == "Inventario inicial al 01/10/2026"
    # El libro sigue en kilos, aunque el operador haya contado bolsas.
    assert movimiento.quantity_kg == Decimal("1000.000")


def test_la_pantalla_tiene_el_mismo_rotulo_que_conteo_fisico(db):
    """Las dos pantallas de conteo tienen que leerse como la misma operacion."""
    from app.ui.stock_count import HEADERS as HEADERS_CONTEO
    from app.ui.stock_initial_inventory import HEADERS as HEADERS_INVENTARIO

    assert HEADERS_INVENTARIO[1] == HEADERS_CONTEO[2]
    assert HEADERS_INVENTARIO[2] == HEADERS_CONTEO[3]


def test_la_pantalla_no_ofrece_campo_para_un_producto_sin_peso(db):
    """Sin peso de bolsa no hay campo editable, y el motivo se ve en la fila y en
    el estado de la pantalla."""
    from PyQt5.QtWidgets import QApplication

    from app.ui.stock_initial_inventory import StockInitialInventoryPage

    contable = _product("FECULA CON PESO", "25.000")
    sin_peso = Product.create(
        name="FECULA SIN PESO", unit="kg", peso_unitario_kg=Decimal("0.000"),
        product_kind=PRODUCT_KIND_PRODUCT, active=True,
    )

    app = QApplication.instance() or QApplication([])
    pagina = StockInitialInventoryPage(current_username="admin")

    assert contable.id in pagina.inputs
    assert sin_peso.id not in pagina.inputs
    fila = next(
        indice for indice in range(pagina.entradas.rowCount())
        if pagina.entradas.item(indice, 0).text() == "FECULA SIN PESO"
    )
    assert pagina.entradas.item(fila, 1).text() == "falta peso de bolsa"
    assert "sin peso de bolsa" in pagina.status.text()
    pagina.close()
    app.processEvents()


def test_la_pantalla_muestra_la_equivalencia_en_kilos(db):
    """40 bolsas de 25 kg tienen que leerse 1.000,000 mientras el operador
    escribe. Sin esta columna, el error de unidad vuelve a ser invisible."""
    from PyQt5.QtWidgets import QApplication

    from app.ui.stock_initial_inventory import StockInitialInventoryPage

    fecula = _product("FECULA CON PESO", "25.000")

    app = QApplication.instance() or QApplication([])
    pagina = StockInitialInventoryPage(current_username="admin")
    fila = pagina.filas[fecula.id]

    pagina.inputs[fecula.id].setValue(40)

    assert pagina.entradas.item(fila, 2).text() == "1.000,000"
    assert pagina.entradas.cellWidget(fila, 1).suffix() == " bolsas"
    pagina.close()
    app.processEvents()
