"""#726: emitir una orden no puede dejarla "Emitida" sin cuenta corriente.

Reproduce el caso de produccion (OC-000078 y OC-000081):

1. se imprime el presupuesto de la orden **pendiente** (eso crea el presupuesto
   con sus items vinculados a los renglones de ese momento);
2. se **edita** la orden, y cada edicion borra y recrea los renglones, con lo
   que el vinculo del item queda en NULL;
3. se **emite** la orden.

Con la comparacion por identidad de renglon, el paso 3ellia la cuenta
corriente: la orden quedava "Emitida" sin movimiento y sin salida de stock.

Ademas cubre que la emision sea atomica: si el movimiento falla, la orden no
queda emitida, y que la herramienta de reparacion (#726) deje la orden como
estaba.
"""

import pytest
from pytest import approx

from app.models.accounting import ClientAccountMovement
from app.models.budgets import Budget, BudgetItem
from app.models.load_orders import LoadOrder, LoadOrderStatusHistory
from app.models.masters import Carrier, Client, ClientAddress, Driver, Product, TipoIVA, Truck
from app.models.stock import StockMovement
from app.services.budget_service import BudgetService
from app.services.load_order_operation_service import LoadOrderOperationService
from app.services.load_order_service import LoadOrderService
from app.services.load_order_stock_service import dispatch_source_prefix

PRECIO = 20000.0
CANTIDAD = 50


def _maestros():
    iva = TipoIVA.iva_default()
    product = Product.create(
        name="Fecula de mandioca",
        unit="bolsa",
        precio_neto_base=PRECIO,
        peso_unitario_kg=25,
        tipo_iva=iva,
    )
    client = Client.create(name="Cliente FEMAG", cuit="30712345678", iva_condition="RI")
    address = ClientAddress.create(
        client=client,
        address_type="entrega",
        province="Misiones",
        city="Posadas",
        address="Ruta 12",
    )
    carrier = Carrier.create(name="Transporte Norte", cuit="30777777770")
    driver = Driver.create(name="Juan Perez", carrier=carrier, document="123")
    truck = Truck.create(domain="AB123CD", carrier=carrier)
    return {
        "product": product,
        "client": client,
        "address": address,
        "carrier": carrier,
        "driver": driver,
        "truck": truck,
    }


def _crear_orden(data, *, cantidad=CANTIDAD):
    return LoadOrderService(current_user="admin").create_order(
        carrier=data["carrier"],
        driver=data["driver"],
        truck=data["truck"],
        destinations=[
            {
                "client": data["client"],
                "delivery_address": data["address"],
                "products": [{"product": data["product"], "quantity": cantidad}],
            }
        ],
        pallets=[],
    )


def _asignar_pallets(order, data, *, cantidad=CANTIDAD):
    LoadOrderService(current_user="admin").update_order(
        order,
        pallets=[
            {
                "sequence": 1,
                "pallet_type": None,
                "allocations": [
                    {
                        "client": data["client"],
                        "delivery_address": data["address"],
                        "product": data["product"],
                        "quantity": cantidad,
                    }
                ],
            }
        ],
    )
    return LoadOrder.get_by_id(order.id)


def _editar_orden(order, data, *, cantidad=CANTIDAD):
    """Edita la orden: borra y recrea los renglones, como en produccion."""
    LoadOrderService(current_user="admin").update_order(
        order,
        destinations=[
            {
                "client": data["client"],
                "delivery_address": data["address"],
                "products": [{"product": data["product"], "quantity": cantidad}],
            }
        ],
        pallets=[
            {
                "sequence": 1,
                "pallet_type": None,
                "allocations": [
                    {
                        "client": data["client"],
                        "delivery_address": data["address"],
                        "product": data["product"],
                        "quantity": cantidad,
                    }
                ],
            }
        ],
    )
    return LoadOrder.get_by_id(order.id)


def _movimientos_de(order):
    return list(
        ClientAccountMovement.select().where(ClientAccountMovement.load_order == order)
    )


def _despachos_de(order):
    return list(
        StockMovement.select().where(
            StockMovement.source_ref.startswith(f"{dispatch_source_prefix(order.id)}:")
        )
    )


def _renglon_vivo(item):
    """El renglon de orden al que apunta el item, si sigue existiendo."""
    from app.models.load_orders import LoadOrderProduct

    if item.source_order_product_id is None:
        return None
    return LoadOrderProduct.get_or_none(
        LoadOrderProduct.id == item.source_order_product_id
    )


@pytest.fixture()
def foreign_keys_as_mysql(db):
    """Fuerza las foreign keys como en MySQL y las restaura al terminar.

    En SQLite las foreign keys no se fuerzan por defecto: al borrar un renglon
    de la orden, el item del presupuesto queda apuntando a un id que SQLite
    reutiliza, y el defecto de produccion (el vinculo en NULL por ``SET
    NULL``) no se ve. Con las foreign keys activas el comportamiento es el de
    MySQL, que es donde paso.
    """
    db.commit()
    db.execute_sql("PRAGMA foreign_keys = ON")
    try:
        yield db
    finally:
        db.commit()
        db.execute_sql("PRAGMA foreign_keys = OFF")


# ---------------------------------------------------------------------------
# El mecanismo
# ---------------------------------------------------------------------------
def test_editar_la_orden_deja_el_presupuesto_sin_vinculo_al_renglon(db, foreign_keys_as_mysql):
    """Documenta por que la comparacion no puede depender del renglon de origen."""
    data = _maestros()
    order = _asignar_pallets(_crear_orden(data), data)

    budgets = BudgetService(current_user="admin").ensure_for_load_order(order)
    assert len(budgets) == 1
    budget = budgets[0]
    item = BudgetItem.get(BudgetItem.budget == budget)
    assert item.source_order_product_id is not None, "El item deberia estar vinculado"

    _editar_orden(order, data)

    item = BudgetItem.get(BudgetItem.budget == budget)
    # En MySQL el vinculo queda en NULL (SET NULL). En SQLite de test sin
    # foreign keys queda apuntando a un renglon que ya no existe. Las dos
    # variantes rompen la comparacion por identidad.
    assert _renglon_vivo(item) is None, (
        "Editar la orden borra y recrea los renglones: el vinculo del item "
        "deja de apuntar a la mercaderia de la orden."
    )
    assert float(item.quantity) == CANTIDAD
    assert float(item.total) == approx(CANTIDAD * PRECIO * 1.21, abs=0.01)


# ---------------------------------------------------------------------------
# La regresión: emitir tiene que dejar el movimiento
# ---------------------------------------------------------------------------
def test_emitir_tras_editar_deja_el_movimiento_en_cuenta_corriente(db, foreign_keys_as_mysql):
    """El caso de la OC-000078: imprimir, editar y emitir."""
    data = _maestros()
    order = _asignar_pallets(_crear_orden(data), data)
    BudgetService(current_user="admin").ensure_for_load_order(order)
    _editar_orden(order, data)

    issued = LoadOrderOperationService(current_user="admin").issue(order)

    assert issued.status == LoadOrder.STATUS_ISSUED
    movements = _movimientos_de(issued)
    assert len(movements) == 1, "La orden emitida tiene que quedar en la cuenta corriente"
    movement = movements[0]
    assert movement.client == data["client"]
    assert movement.total_amount == approx(CANTIDAD * PRECIO * 1.21, abs=0.01)
    assert movement.is_reversal is False


def test_emitir_tras_editar_deja_la_salida_de_stock(db, foreign_keys_as_mysql):
    """La mercaderia tambien tiene que salir del stock al emitir."""
    data = _maestros()
    order = _asignar_pallets(_crear_orden(data), data)
    BudgetService(current_user="admin").ensure_for_load_order(order)
    _editar_orden(order, data)

    issued = LoadOrderOperationService(current_user="admin").issue(order)

    despachos = _despachos_de(issued)
    assert len(despachos) == 1
    assert float(despachos[0].quantity_kg) == approx(CANTIDAD * 25, abs=0.01)


# ---------------------------------------------------------------------------
# La emisión es atómica
# ---------------------------------------------------------------------------
def test_si_el_movimiento_falla_la_orden_no_queda_emitida(db):
    """Un presupuesto con mercaderia distinta corta la emision sin dejar la orden emitida."""
    data = _maestros()
    order = _asignar_pallets(_crear_orden(data), data)
    BudgetService(current_user="admin").ensure_for_load_order(order)
    # La mercaderia cambia de verdad: el presupuesto queda viejo.
    _editar_orden(order, data, cantidad=CANTIDAD + 10)

    with pytest.raises(ValueError, match="no coincide con la mercaderia"):
        LoadOrderOperationService(current_user="admin").issue(order)

    order = LoadOrder.get_by_id(order.id)
    assert order.status == LoadOrder.STATUS_PENDING, (
        "La orden no puede quedar emitida sin su movimiento en la cuenta corriente."
    )
    assert _movimientos_de(order) == []
    assert _despachos_de(order) == []
    emitida = (
        LoadOrderStatusHistory.select()
        .where(LoadOrderStatusHistory.order == order)
        .where(LoadOrderStatusHistory.new_status == LoadOrder.STATUS_ISSUED)
        .count()
    )
    assert emitida == 0, "El cambio de estado a Emitida tambien tiene que revertirse"


def test_emitir_una_orden_sin_presupuesto_pendiente_sigue_andando(db):
    """El camino normal (emitir sin imprimir el presupuesto antes) no cambia."""
    data = _maestros()
    order = _asignar_pallets(_crear_orden(data), data)

    issued = LoadOrderOperationService(current_user="admin").issue(order)

    assert issued.status == LoadOrder.STATUS_ISSUED
    assert len(_movimientos_de(issued)) == 1
    assert len(_despachos_de(issued)) == 1


# ---------------------------------------------------------------------------
# La comparación sigue detectando un presupuesto realmente viejo
# ---------------------------------------------------------------------------
def test_presupuesto_con_mercaneria_distinta_no_considera_que_coincide(db):
    """#585 sigue vigente: mercaderia distinta es mercaderia distinta."""
    from app.services.budget_service import BudgetService as Servicio

    data = _maestros()
    order = _asignar_pallets(_crear_orden(data), data)
    budgets = BudgetService(current_user="admin").ensure_for_load_order(order)
    budget = budgets[0]
    _editar_orden(order, data, cantidad=CANTIDAD + 10)

    rows = list(LoadOrder.get_by_id(order.id).products)
    assert Servicio(current_user="admin")._budget_matches_order(budget, rows, "immediate") is False


def test_presupuesto_con_la_misma_mercaneria_coincide_aunque_no_haya_vinculo(db):
    """La comparacion se resuelve por contenido, no por el renglon de origen."""
    from app.services.budget_service import BudgetService as Servicio

    data = _maestros()
    order = _asignar_pallets(_crear_orden(data), data)
    budgets = BudgetService(current_user="admin").ensure_for_load_order(order)
    budget = budgets[0]
    _editar_orden(order, data)

    rows = list(LoadOrder.get_by_id(order.id).products)
    assert Servicio(current_user="admin")._budget_matches_order(budget, rows, "immediate") is True


# ---------------------------------------------------------------------------
# La herramienta de reparación
# ---------------------------------------------------------------------------
def _orden_emitida_sin_cuenta_corriente(data):
    """Deja la orden como quedo en produccion: emitida, sin movimiento y sin stock."""
    order = _asignar_pallets(_crear_orden(data), data)
    BudgetService(current_user="admin").ensure_for_load_order(order)
    _editar_orden(order, data)
    order = LoadOrder.get_by_id(order.id)
    order.status = LoadOrder.STATUS_ISSUED
    order.save()
    return LoadOrder.get_by_id(order.id)


def test_la_reparacion_detecta_la_orden_sin_cuenta_corriente(db):
    from app.services.load_order_ledger_repair_service import (
        LoadOrderLedgerRepairService,
    )

    data = _maestros()
    order = _orden_emitida_sin_cuenta_corriente(data)

    finding = LoadOrderLedgerRepairService(current_user="admin").find_gap(order)

    assert finding.is_repairable
    assert len(finding.ledger_gaps) == 1
    assert finding.ledger_gaps[0].client_id == data["client"].id
    assert finding.missing_stock is True


def test_la_reparacion_genera_el_movimiento_y_es_idempotente(db):
    from app.services.load_order_ledger_repair_service import (
        LoadOrderLedgerRepairService,
    )

    data = _maestros()
    order = _orden_emitida_sin_cuenta_corriente(data)
    service = LoadOrderLedgerRepairService(current_user="admin")

    resultado = service.repair(order)

    assert len(resultado.movement_ids) == 1
    assert len(resultado.stock_movement_ids) == 1
    movements = _movimientos_de(order)
    assert len(movements) == 1
    assert movements[0].total_amount == approx(CANTIDAD * PRECIO * 1.21, abs=0.01)

    # Repetir la reparacion no duplica nada.
    service.repair(order)
    assert len(_movimientos_de(order)) == 1
    assert len(_despachos_de(order)) == 1
    assert service.find_gap(order).is_repairable is False


def test_la_reparacion_no_toca_una_orden_sana(db):
    from app.services.load_order_ledger_repair_service import (
        LoadOrderLedgerRepairService,
    )

    data = _maestros()
    order = _asignar_pallets(_crear_orden(data), data)
    LoadOrderOperationService(current_user="admin").issue(order)

    finding = LoadOrderLedgerRepairService(current_user="admin").find_gap(
        LoadOrder.get_by_id(order.id)
    )

    assert finding.is_repairable is False
    assert finding.ledger_gaps == ()
    assert finding.missing_stock is False


def test_el_script_de_consola_lista_las_ordenes_rotas(db, capsys):
    """El script de consola y la pantalla usan la misma lógica."""
    from scripts.repair_missing_ledger_movements import run

    data = _maestros()
    order = _orden_emitida_sin_cuenta_corriente(data)

    assert order.order_number > 0
    # El script abre su propia conexión: en el test se valida el render del
    # informe con el servicio, que es lo que el script imprime.
    from app.services.load_order_ledger_repair_service import (
        LoadOrderLedgerRepairService,
    )
    from scripts.repair_missing_ledger_movements import render_finding

    finding = LoadOrderLedgerRepairService(current_user="admin").find_gap(order)
    informe = render_finding(finding)

    assert str(order.order_number) in informe
    assert "falta el movimiento de" in informe
    assert "Stock: falta el despacho" in informe
