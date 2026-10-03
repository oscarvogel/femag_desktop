"""La pantalla de inventario inicial: construye de verdad y refleja el estado."""

from datetime import date
from decimal import Decimal

import pytest

from app.models.masters import PRODUCT_KIND_PRODUCT, Product
from app.services.stock_inventory_service import StockInventoryService
from app.services.stock_service import StockService

DAY = date(2026, 10, 1)


def _product(name="BOLSAS DE FECULA NATIVA", weight="25.000"):
    return Product.create(
        name=name, unit="unidad", peso_unitario_kg=Decimal(weight),
        product_kind=PRODUCT_KIND_PRODUCT, active=True,
    )


_QAPP = None
_PAGINAS = []


@pytest.fixture(autouse=True)
def _limpia_paginas():
    """Destruye las pantallas de cada test.

    Sin esto quedan widgets C++ vivos cuando el interprete termina y el
    proceso se va con segmentation fault **despues** de que pytest ya
    imprimio el resumen verde. No es un test que falle: es el proceso que
    muere al salir, y el CI lo marca en rojo.
    """
    yield
    while _PAGINAS:
        pagina = _PAGINAS.pop()
        pagina.close()
        pagina.deleteLater()
    if _QAPP is not None:
        _QAPP.processEvents()


def _page(db):
    """Construye la pantalla real.

    Importarla y construirla a proposito: un error en el constructor de una
    pagina revienta la ventana entera y se lleva por delante los decenas de
    tests que arman la app completa.
    """
    global _QAPP
    from PyQt5.QtCore import QDate
    from PyQt5.QtWidgets import QApplication

    from app.ui.stock_initial_inventory import StockInitialInventoryPage

    if _QAPP is None:
        _QAPP = QApplication.instance() or QApplication([])
    page = StockInitialInventoryPage(current_username="oscar")
    _PAGINAS.append(page)
    page.day.setDate(QDate(DAY.year, DAY.month, DAY.day))
    page.refresh()
    return page


@pytest.fixture(autouse=True)
def _sin_dialogos(monkeypatch):
    """Los QMessageBox bloquean el test esperando a un humano que no esta.

    Se contestan Yes siempre, que es lo que hace falta para el camino de carga,
    y se deja el motivo de anulacion ya puesto.
    """
    from PyQt5.QtWidgets import QMessageBox

    monkeypatch.setattr(
        "app.ui.stock_initial_inventory.QMessageBox.question",
        staticmethod(lambda *a, **k: QMessageBox.Yes),
    )
    monkeypatch.setattr(
        "app.ui.stock_initial_inventory.QInputDialog.getText",
        staticmethod(lambda *a, **k: ("Se contó mal", True)),
    )


def test_la_pantalla_ofrece_los_productos_de_venta_con_kg(db):
    _product("BOLSAS DE FECULA NATIVA")
    _product("BOLSAS ALMIDON DE MAIZ X 25 KG.")

    page = _page(db)

    assert page.table.rowCount() == 2
    assert page.table.item(0, 0).text() == "BOLSAS ALMIDON DE MAIZ X 25 KG."
    assert page.load_button.isEnabled()
    assert not page.void_button.isEnabled()
    assert "cargá los kilos de cada producto" in page.status.text()


def test_cargar_desde_la_pantarma_deja_el_saldo(db):
    """Este es el punto de partida: sin el, el saldo del libro no dice nada."""
    fecula = _product("BOLSAS DE FECULA NATIVA")
    _product("BOLSAS ALMIDON DE MAIZ X 25 KG.")

    page = _page(db)
    page.inputs[fecula.id].setValue(710025.0)
    page.observations.setText("Conteo de arranque")
    page.load_inventory()

    assert StockService.balance_for(fecula).balance_kg == Decimal("710025.000")
    assert _movimientos() == 1
    # Y el operador lo ve en la pantalla, no tiene que creerlo.
    page.refresh()
    assert page.table.item(1, 3).text() == "710,025.000"


def _movimientos() -> int:
    from app.models.stock import StockMovement

    return StockMovement.select().count()


def test_cargar_una_fecha_ya_cargada_no_pisa_y_lo_dice(db):
    """El caso de la perdida silenciosa: el operador corrige y no pasa nada."""
    fecula = _product()
    StockInventoryService.load_initial(DAY, {fecula: Decimal("1000")})

    page = _page(db)

    # La tabla muestra el valor cargado, en solo lectura, y no se puede volver a cargar.
    assert page.inputs[fecula.id].value() == 1000.0
    assert page.inputs[fecula.id].isReadOnly()
    assert not page.load_button.isEnabled()
    assert page.void_button.isEnabled()
    assert "no reemplaza nada" in page.status.text()


def test_anular_deja_la_fecha_lista_para_un_conteo_nuevo(db):
    fecula = _product()
    StockInventoryService.load_initial(DAY, {fecula: Decimal("1000")})

    page = _page(db)
    page.void_inventory()

    assert StockService.balance_for(fecula).balance_kg == Decimal("0.000")
    assert "está anulado" in page.status.text()
    assert not page.load_button.isEnabled()

    # El conteo corregido va en otra fecha y el saldo vuelve a ser real.
    StockInventoryService.load_initial(date(2026, 10, 2), {fecula: Decimal("850")})
    assert StockService.balance_for(fecula).balance_kg == Decimal("850.000")


def test_cargar_sin_kilos_avisa_y_no_hace_nada(db):
    _product()
    page = _page(db)

    page.load_inventory()

    assert _movimientos() == 0
