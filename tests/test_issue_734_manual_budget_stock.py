"""#734: el presupuesto manual descuenta el stock de la mercaderia que sale.

El presupuesto manual es la segunda puerta por la que la mercaderia sale de la
planta, despues del despacho de la orden de carga. Antes no tocaba el libro:
en la base real hay 19 presupuestos manuales (14 clientes, del 21/09 al 14/10) y
ninguno dejo rastro en el stock. Esa mercaderia salio y el aviso de faltante de
#732 no la veia.

Ahora el presupuesto manual descuenta el stock, y si no alcanza aparece el
mismo aviso de #732: el faltante por producto y un motivo obligatorio. Con el
motivo, el presupuesto se crea y la decision queda asentada en la auditoria y
en los movimientos del libro.
"""

import os
from decimal import Decimal

import pytest
from conftest import _master_data

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app.models.audit import AuditLog
from app.models.budgets import Budget
from app.models.stock import StockMovement
from app.services.budget_service import BudgetService
from app.services.budget_stock_service import BudgetStockShortfallError
from app.services.stock_service import StockService

_QAPP = None


def _app():
    """La QApplication tiene que quedar viva: si se pierde, PyQt se rompe."""
    global _QAPP
    from PyQt5.QtWidgets import QApplication

    if _QAPP is None:
        _QAPP = QApplication.instance() or QApplication([])
    return _QAPP


def _maestro():
    """Maestros: un producto con peso de bolsa y otro que no lo tiene."""
    data = _master_data()
    data["product"].peso_unitario_kg = Decimal("25.000")
    data["product"].save()
    data["other_product"].peso_unitario_kg = Decimal("0")
    data["other_product"].save()
    return data


def _items(producto, cantidad=100, precio=1000.0):
    """Items de un presupuesto manual, como los arma el dialogo."""
    return [
        {
            "product": producto,
            "quantity": float(cantidad),
            "unit": "bolsa",
            "unit_price": float(precio),
            "discount_percentage": 0.0,
            "vat_percentage": 21.0,
        }
    ]


def _cargar_stock(producto, kg="10000.000"):
    """Carga inventario inicial: el libro pasa a saber del producto."""
    return StockService.register(
        product=producto,
        movement_type=StockMovement.TYPE_INITIAL_INVENTORY,
        quantity_kg=Decimal(kg),
        source_ref=f"stock_count:{producto.id}",
        description="Inventario inicial",
        created_by="admin",
    )


def test_un_presupuesto_manual_descuenta_el_stock(db):
    """El dia a dia: la mercaderia que sale por esta via sale del deposito."""
    data = _maestro()
    producto = data["product"]
    _cargar_stock(producto, "10000.000")

    presupuesto = BudgetService(current_user="admin").create_manual(
        client=data["client"], items=_items(producto, 100)
    )

    assert presupuesto.origin == Budget.ORIGIN_MANUAL
    # 100 bolsas de 25 kg = 2.500 kg
    assert StockService.balance_for(producto).balance_kg == Decimal("7500.000")
    movimiento = StockMovement.get(
        StockMovement.source_ref == f"Budget:{presupuesto.id}:Dispatch:{producto.id}"
    )
    assert movimiento.movement_type == StockMovement.TYPE_DISPATCH
    assert movimiento.quantity_kg == Decimal("2500.000")


def test_sin_stock_suficiente_no_se_crea_el_presupuesto(db):
    """Sin motivo no se crea: el faltante se avisa y se frena."""
    data = _maestro()
    producto = data["product"]
    _cargar_stock(producto, "100.000")  # el presupuesto pide 2.500 kg

    with pytest.raises(BudgetStockShortfallError) as excinfo:
        BudgetService(current_user="admin").create_manual(
            client=data["client"], items=_items(producto, 100)
        )

    assert "stock suficiente" in str(excinfo.value)
    assert len(excinfo.value.faltantes) == 1
    faltante = excinfo.value.faltantes[0]
    assert faltante.available_kg == Decimal("100.000")
    assert faltante.requested_kg == Decimal("2500.000")
    assert faltante.missing_kg == Decimal("2400.000")

    # Y nada se toco: no hay presupuesto, no hay movimiento, el saldo esta como estaba.
    assert Budget.select().where(Budget.origin == Budget.ORIGIN_MANUAL).count() == 0
    assert StockMovement.select().where(
        StockMovement.movement_type == StockMovement.TYPE_DISPATCH
    ).count() == 0
    assert StockService.balance_for(producto).balance_kg == Decimal("100.000")


def test_con_motivo_el_presupuesto_se_crea_y_el_motivo_queda_asentado(db):
    """El motivo es la traza: va a la auditoria y a los movimientos del libro."""
    data = _maestro()
    producto = data["product"]
    _cargar_stock(producto, "100.000")

    presupuesto = BudgetService(current_user="admin").create_manual(
        client=data["client"],
        items=_items(producto, 100),
        stock_override_reason="El cliente retiró más de lo facturado",
    )

    movimiento = StockMovement.get(
        StockMovement.source_ref == f"Budget:{presupuesto.id}:Dispatch:{producto.id}"
    )
    assert "El cliente retiró más de lo facturado" in (movimiento.observations or "")

    auditoria = AuditLog.get(
        (AuditLog.module == "Stock")
        & (AuditLog.action == "descontar_despacho")
        & (AuditLog.record_ref == f"Budget:{presupuesto.id}")
    )
    assert auditoria.new_value["stock_override_reason"] == (
        "El cliente retiró más de lo facturado"
    )


def test_un_producto_sin_peso_de_bolsa_no_descuenta_stock(db):
    """Sin peso no hay conversion a kilos, y un movimiento de 0 kg no dice nada."""
    data = _maestro()
    producto = data["other_product"]  # sin peso de bolsa cargado
    _cargar_stock(data["product"], "10000.000")

    presupuesto = BudgetService(current_user="admin").create_manual(
        client=data["client"], items=_items(producto, 100)
    )

    assert presupuesto is not None
    assert StockMovement.select().where(
        StockMovement.movement_type == StockMovement.TYPE_DISPATCH
    ).count() == 0


def test_un_presupuesto_solo_con_servicios_no_toca_el_stock(db):
    """Un flete o un gasto administrativo no sale del deposito.

    El servicio tiene peso de bolsa cargado a proposito: lo que lo excluye es
    que no es mercaderia, no que le falte el peso.
    """
    data = _maestro()
    servicio = data["other_product"]
    servicio.product_kind = "servicio"
    servicio.peso_unitario_kg = Decimal("25.000")
    servicio.save()

    presupuesto = BudgetService(current_user="admin").create_manual(
        client=data["client"], items=_items(servicio, 1)
    )

    assert presupuesto is not None
    assert StockMovement.select().count() == 0


def test_anular_el_presupuesto_manual_repone_el_stock(db):
    """Si la mercaderia vuelve, el stock vuelve: no se reescribe nada."""
    data = _maestro()
    producto = data["product"]
    _cargar_stock(producto, "10000.000")

    servicio = BudgetService(current_user="admin")
    presupuesto = servicio.create_manual(
        client=data["client"], items=_items(producto, 100)
    )
    assert StockService.balance_for(producto).balance_kg == Decimal("7500.000")

    servicio.annul_manual(presupuesto, reason="Error de carga")

    assert StockService.balance_for(producto).balance_kg == Decimal("10000.000")
    reversa = StockMovement.get(
        (StockMovement.source_ref == f"Budget:{presupuesto.id}:Dispatch:{producto.id}")
        & (StockMovement.is_reversal == True)  # noqa: E712
    )
    assert reversa.movement_type == StockMovement.TYPE_ADJUSTMENT_POSITIVE
    assert "Error de carga" in (reversa.observations or "")


def test_un_producto_sin_stock_conocido_no_avisa_faltante(db):
    """De un producto que nunca se conto no se puede afirmar que falte.

    El libro no tiene opinion sobre lo que no conto: avisar seria decir que el
    inventario todavia no esta cargado, que es otra cosa.
    """
    data = _maestro()
    producto = data["product"]
    # Sin _cargar_stock: el producto nunca entro al libro.

    presupuesto = BudgetService(current_user="admin").create_manual(
        client=data["client"], items=_items(producto, 100)
    )

    assert presupuesto is not None
    assert StockService.balance_for(producto).balance_kg == Decimal("-2500.000")


def test_el_dialogo_del_presupuesto_muestra_el_faltante(db, monkeypatch):
    """El aviso es el mismo que el del despacho: faltante por producto."""
    from PyQt5.QtWidgets import QDialog

    from app.ui.load_order_stock_shortfall_dialog import LoadOrderStockShortfallDialog
    from app.ui.manual_budget_dialog import ManualBudgetDialog

    _app()
    data = _maestro()
    producto = data["product"]
    _cargar_stock(producto, "100.000")

    dialogo = ManualBudgetDialog(client=data["client"], current_user="admin")
    dialogo.product_combo.setCurrentIndex(
        dialogo.product_combo.findData(producto.id)
    )
    dialogo.quantity_input.setValue(100)
    dialogo._add_item()

    faltantes = BudgetService(current_user="admin").stock.shortfall(
        BudgetService(current_user="admin").stock.plan(_items(producto, 100))
    )
    aviso = LoadOrderStockShortfallDialog(
        None,
        faltantes,
        titulo="Stock insuficiente - Nuevo presupuesto",
        subtitulo="El presupuesto pide más mercadería de la que hay en stock",
    )

    assert aviso.table.rowCount() == 1
    assert aviso.table.item(0, 0).text() == producto.name
    assert aviso.table.item(0, 1).text() == "100.000"
    assert aviso.table.item(0, 2).text() == "2,500.000"
    assert aviso.table.item(0, 3).text() == "2,400.000"

def test_el_dialogo_del_presupuesto_tiene_su_propia_columna(db):
    """La columna dice "pide el presupuesto", no "pide la orden".

    El aviso es el mismo widget, pero la columna que nombra al documento que
    pide la mercaderia tiene que decir la verdad.
    """
    from app.ui.load_order_stock_shortfall_dialog import LoadOrderStockShortfallDialog

    _app()
    data = _maestro()
    producto = data["product"]
    _cargar_stock(producto, "100.000")

    faltantes = BudgetService(current_user="admin").stock.shortfall(
        BudgetService(current_user="admin").stock.plan(_items(producto, 100))
    )
    aviso = LoadOrderStockShortfallDialog(
        None,
        faltantes,
        headers=(
            "Producto",
            "Stock en el libro (kg)",
            "Pide el presupuesto (kg)",
            "Falta (kg)",
        ),
    )

    assert aviso.table.horizontalHeaderItem(2).text() == "Pide el presupuesto (kg)"


def test_el_dialogo_avisa_que_no_descuenta_stock(db):
    """La pantalla dice que renglones no tocan el stock, y por que."""
    from app.ui.manual_budget_dialog import ManualBudgetDialog

    _app()
    data = _maestro()

    dialogo = ManualBudgetDialog(client=data["client"], current_user="admin")
    dialogo.product_combo.setCurrentIndex(
        dialogo.product_combo.findData(data["other_product"].id)
    )
    dialogo.quantity_input.setValue(5)
    dialogo._add_item()

    assert "No descuentan stock" in dialogo.stock_note.text()
    assert data["other_product"].name in dialogo.stock_note.text()


def test_cancelar_el_aviso_no_crea_el_presupuesto(db, monkeypatch):
    """Si el operador cancela, no se crea presupuesto ni se toca el libro."""
    from PyQt5.QtWidgets import QDialog

    from app.ui.load_order_stock_shortfall_dialog import LoadOrderStockShortfallDialog
    from app.ui.manual_budget_dialog import ManualBudgetDialog

    _app()
    data = _maestro()
    producto = data["product"]
    _cargar_stock(producto, "100.000")

    dialogo = ManualBudgetDialog(client=data["client"], current_user="admin")
    dialogo.product_combo.setCurrentIndex(dialogo.product_combo.findData(producto.id))
    dialogo.quantity_input.setValue(100)
    dialogo._add_item()

    monkeypatch.setattr(
        LoadOrderStockShortfallDialog, "exec_", lambda _dialog: QDialog.Rejected
    )

    dialogo._confirm()

    assert dialogo.budget() is None
    assert Budget.select().where(Budget.origin == Budget.ORIGIN_MANUAL).count() == 0
    assert StockMovement.select().where(
        StockMovement.movement_type == StockMovement.TYPE_DISPATCH
    ).count() == 0
    assert StockService.balance_for(producto).balance_kg == Decimal("100.000")


def test_confirmar_el_aviso_crea_el_presupuesto_con_el_motivo(db, monkeypatch):
    """El camino feliz: el operador confirma y el presupuesto sale."""
    from PyQt5.QtWidgets import QDialog

    from app.ui.load_order_stock_shortfall_dialog import LoadOrderStockShortfallDialog
    from app.ui.manual_budget_dialog import ManualBudgetDialog

    _app()
    data = _maestro()
    producto = data["product"]
    _cargar_stock(producto, "100.000")

    dialogo = ManualBudgetDialog(client=data["client"], current_user="admin")
    dialogo.product_combo.setCurrentIndex(dialogo.product_combo.findData(producto.id))
    dialogo.quantity_input.setValue(100)
    dialogo._add_item()

    def _aceptar(aviso):
        aviso.reason_input.setPlainText("Se regulariza con el próximo ingreso")
        return QDialog.Accepted

    monkeypatch.setattr(LoadOrderStockShortfallDialog, "exec_", _aceptar)

    dialogo._confirm()

    presupuesto = dialogo.budget()
    assert presupuesto is not None
    assert StockService.balance_for(producto).balance_kg == Decimal("-2400.000")
    movimiento = StockMovement.get(
        StockMovement.source_ref == f"Budget:{presupuesto.id}:Dispatch:{producto.id}"
    )
    assert "Se regulariza con el próximo ingreso" in (movimiento.observations or "")
