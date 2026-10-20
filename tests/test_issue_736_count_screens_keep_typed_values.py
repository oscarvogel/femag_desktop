"""#736: el refresco automatico no puede borrar lo que el operador escribe.

El refresco multi-estacion recarga la pantalla visible cada 10 segundos, para
que un operador vea lo que hacen los demás. En las pantallas de conteo, esa
recarga reconstruia la tabla y los campos: el operador perdia lo que estaba
escribiendo a los 10 segundos de empezar, sin llegar a grabar nada.

Estas pruebas fijan el comportamiento: lo escrito se conserva, lo que viene de
la base se actualiza, y cambiar la fecha de corte descarta lo escrito.
"""

import os
from datetime import date
from decimal import Decimal

import pytest
from conftest import _master_data

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtCore import QDate
from PyQt5.QtWidgets import QApplication

from app.models.masters import Product
from app.models.stock import StockMovement
from app.services.stock_inventory_service import source_ref_of
from app.services.stock_service import StockService

_QAPP = None
PESO = Decimal("25.000")
DAY = date(2026, 10, 20)


def _app():
    """La QApplication tiene que quedar viva: si se pierde, PyQt se rompe."""
    global _QAPP
    if _QAPP is None:
        _QAPP = QApplication.instance() or QApplication([])
    return _QAPP


def _producto(nombre="FECULA CON PESO"):
    return Product.create(
        name=nombre,
        unit="unidad",
        peso_unitario_kg=PESO,
        product_kind="producto",
        active=True,
    )


# ---------------------------------------------------------------- Inventario inicial


def test_el_inventario_inicial_conserva_las_bolsas_escritas(db):
    """El caso del operador: escribe, llega el refresco, y sigue escrito."""
    from app.ui.stock_initial_inventory import StockInitialInventoryPage

    _app()
    producto = _producto()

    pagina = StockInitialInventoryPage(current_username="admin")
    pagina.inputs[producto.id].setValue(40)

    # Esto es lo que hace el timer multi-estacion cada 10 segundos.
    pagina.refresh()

    assert pagina.inputs[producto.id].value() == 40


def test_el_inventario_inicial_actualiza_el_saldo_del_libro(db):
    """El refresco tiene que seguiractualizando lo que viene de la base.

    Si se dejara de refrescar, un operador no veria el despacho de otra
    estacion y creeria que hay mas stock del que hay.
    """
    from app.ui.stock_initial_inventory import StockInitialInventoryPage

    _app()
    producto = _producto()
    StockService.register(
        product=producto,
        movement_type=StockMovement.TYPE_INITIAL_INVENTORY,
        quantity_kg=Decimal("1000.000"),
        source_ref="stock_count:1",
        description="Inventario inicial",
        created_by="admin",
    )

    pagina = StockInitialInventoryPage(current_username="admin")
    pagina.inputs[producto.id].setValue(40)
    pagina.refresh()

    fila = pagina.filas[producto.id]
    # El saldo del libro se lee en la ultima columna.
    assert pagina.entradas.item(fila, 3).text() == "1.000,000"
    # Y la equivalencia de lo que escribio el operador, en vivo.
    assert pagina.entradas.item(fila, 2).text() == "1.000,000"


def test_cambiar_la_fecha_descarta_las_bolsas_escritas(db):
    """Lo que se conto es de una fecha: en otra fecha no aplica."""
    from app.ui.stock_initial_inventory import StockInitialInventoryPage

    _app()
    producto = _producto()

    pagina = StockInitialInventoryPage(current_username="admin")
    pagina.inputs[producto.id].setValue(40)

    pagina.day.setDate(QDate(2026, 10, 21))

    assert pagina.inputs[producto.id].value() == 0


def test_con_el_inventario_ya_cargado_manda_lo_cargado(db):
    """Si la fecha ya tiene inventario cargado, el campo esta bloqueado y
    muestra lo que dice la base, no lo que quedo escrito antes."""
    from app.ui.stock_initial_inventory import StockInitialInventoryPage

    _app()
    producto = _producto()

    pagina = StockInitialInventoryPage(current_username="admin")
    pagina.inputs[producto.id].setValue(40)
    pagina.day.setDate(QDate(DAY.year, DAY.month, DAY.day))

    StockService.register(
        product=producto,
        movement_type=StockMovement.TYPE_INITIAL_INVENTORY,
        quantity_kg=Decimal("500.000"),
        source_ref=source_ref_of(DAY),
        description="Inventario inicial",
        movement_date=DAY,
        created_by="admin",
    )

    pagina.refresh()

    assert pagina.inputs[producto.id].isReadOnly()
    assert pagina.inputs[producto.id].value() == 20  # 500 kg / 25 kg por bolsa


# ---------------------------------------------------------------- Conteo fisico


def test_el_conteo_fisico_conserva_las_bolsas_escritas(db):
    """Mismo defecto, misma pantalla hermana: el conteo tampoco se perdia."""
    from app.ui.stock_count import StockCountPage

    _app()
    producto = _producto()

    pagina = StockCountPage(current_username="admin")
    pagina.inputs[producto.id].setValue(12)

    pagina.refresh()

    assert pagina.inputs[producto.id].value() == 12


def test_el_conteo_fisico_descarta_las_bolsas_al_cambiar_la_fecha(db):
    from app.ui.stock_count import StockCountPage

    _app()
    producto = _producto()

    pagina = StockCountPage(current_username="admin")
    pagina.inputs[producto.id].setValue(12)

    pagina.day.setDate(QDate(2026, 10, 21))

    assert pagina.inputs[producto.id].value() == 0


def test_el_timer_multi_estacion_no_puede_tirar_la_pantalla(db):
    """El refresh del timer es el mismo metodo: la prueba de arriba lo cubre.

    Este test cierra el circuito: reproduce lo que hace la extension (llamar a
    ``refresh()`` de la pagina visible) y comprueba que el numero sobrevive.
    """
    from app.ui.multi_station_refresh_extension import _refresh_visible_route
    from app.ui.stock_initial_inventory import StockInitialInventoryPage

    _app()
    producto = _producto()

    pagina = StockInitialInventoryPage(current_username="admin")
    pagina.inputs[producto.id].setValue(40)

    class _PaginaVisible:
        """La pagina como la ve el timer: visible y con su refresh."""

        def isVisible(self):
            return True

        def refresh(self):
            pagina.refresh()

    class _Stack:
        def widget(self, index):
            return _PaginaVisible()

    class _Ventana:
        def isVisible(self):
            return True

        _current_route = "stock_initial_inventory"
        _route_indexes = {"stock_initial_inventory": 0}

        def __init__(self):
            self.stack = _Stack()

        def _refresh_route(self, route):
            pagina.refresh()

    _refresh_visible_route(_Ventana())

    assert pagina.inputs[producto.id].value() == 40
