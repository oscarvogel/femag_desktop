"""Ensayo de despacho con reparto de cantidades (#585).

Recorre el camino completo que se va a usar en el mostrador: cargar una orden
partida, emitirla, verificar los dos presupuestos y los dos movimientos de
cuenta corriente, generar cada PDF por separado, cerrar la entrega y, en una
segunda orden, anular para comprobar que las dos deudas se reversan.

Se ejecuta con ``pytest -s`` para ver la traza con los importes reales:

    python -m pytest tests/test_issue_585_dispatch_rehearsal.py -s -q
"""
from datetime import date, timedelta
from decimal import Decimal

from tests.conftest import _complete_order_for_issue, _master_data

PRECIO = 14200.0
DESCUENTO = 5.0
CANTIDAD = 1200.0
CANTIDAD_HOY = 800.0
PLAZO_CLIENTE = 30


def _traza(titulo: str) -> None:
    print(f"\n--- {titulo} " + "-" * max(0, 60 - len(titulo)))


def _crear_orden(db, data, *, numero=1, pendiente=400.0):
    from app.services.load_order_service import LoadOrderService

    data["client"].dias_plazo_pago = PLAZO_CLIENTE
    data["client"].save()
    order = LoadOrderService(current_user="rehearsal").create_order(
        carrier=data["carrier"],
        driver=data["driver"],
        truck=data["truck"],
        destinations=[
            {
                "client": data["client"],
                "delivery_address": data["address"],
                "products": [
                    {
                        "product": data["product"],
                        "quantity": CANTIDAD,
                        "cantidad_facturar_ahora": CANTIDAD_HOY,
                        "precio_neto_unitario": PRECIO,
                        "descuento_porcentaje": DESCUENTO,
                    }
                ],
            }
        ],
    )
    _complete_order_for_issue(order, current_user="rehearsal")
    return order


def test_ensayo_de_despacho_con_reparto(db, tmp_path):
    from app.models.accounting import ClientAccountMovement
    from app.models.budgets import Budget
    from app.models.load_orders import LoadOrder, LoadOrderBudgetStatus
    from app.services.load_order_closure_service import LoadOrderClosureService
    from app.services.load_order_operation_service import LoadOrderOperationService
    from app.models.payments import ClientPayment

    data = _master_data()
    service = LoadOrderOperationService(current_user="rehearsal")
    service.prints_dir = tmp_path

    # ------------------------------------------------------------ emitir
    _traza("1. Cargar la orden partida")
    order = _crear_orden(db, data)
    linea = order.products[0]
    print(f"   OC-{order.order_number:06d}  {data['client'].name}  plazo {PLAZO_CLIENTE} dias")
    print(f"   {linea.product.name}")
    print(f"   cantidad total {CANTIDAD:g}  hoy {linea.cantidad_facturacion_inmediata:g}  "
          f"despues {linea.cantidad_facturacion_diferida:g}")
    print(f"   total del renglon $ {linea.total:,.2f}")
    assert linea.cantidad_facturacion_diferida == 400.0

    order = service.issue(order)
    order = LoadOrder.get_by_id(order.id)

    # --------------------------------------------------- dos presupuestos
    _traza("2. Los dos presupuestos emitidos")
    budgets = {
        budget.timing: budget
        for budget in Budget.select().where(Budget.load_order == order)
    }
    assert set(budgets) == {Budget.TIMING_IMMEDIATE, Budget.TIMING_DEFERRED}
    for timing in (Budget.TIMING_IMMEDIATE, Budget.TIMING_DEFERRED):
        budget = budgets[timing]
        item = budget.items[0]
        print(f"   {budget.display_number}  {budget.timing_label:<22} "
              f"{item.quantity:>7g} u   $ {budget.total_amount:>16,.2f}")
    suma = sum(Decimal(str(b.total_amount)) for b in budgets.values())
    print(f"   {'suma de las dos partes':<31}       $ {suma:>16,.2f}")
    assert suma == Decimal(str(linea.total))

    # --------------------------------------------- dos movimientos de deuda
    _traza("3. La cuenta corriente del cliente")
    movements = list(
        ClientAccountMovement.select().where(
            (ClientAccountMovement.load_order == order)
            & (ClientAccountMovement.is_reversal == False)  # noqa: E712
        ).order_by(ClientAccountMovement.id)
    )
    assert len(movements) == 2
    for movement in movements:
        print(f"   {movement.reference}  {movement.movement_type:<32} "
              f"vence {movement.due_date}   $ {movement.total_amount:>16,.2f}")
    vencimientos = {m.movement_type: m.due_date for m in movements}
    assert vencimientos[ClientAccountMovement.TYPE_LOAD_ORDER_IMMEDIATE] == order.date
    assert (
        vencimientos[ClientAccountMovement.TYPE_LOAD_ORDER_DEFERRED]
        == order.date + timedelta(days=PLAZO_CLIENTE)
    )
    print(f"   la parte de hoy vence el {order.date} (contado), "
          f"la diferida el {order.date + timedelta(days=PLAZO_CLIENTE)}")

    estados = LoadOrderBudgetStatus.select().where(
        LoadOrderBudgetStatus.order == order
    )
    print(f"   estado de presupuesto por parte: "
          f"{sorted({s.timing for s in estados})}")
    assert estados.count() == 2

    # ------------------------------------------------------- enviar PDFs
    _traza("4. Enviar cada presupuesto por separado")
    for timing in (Budget.TIMING_IMMEDIATE, Budget.TIMING_DEFERRED):
        paths = service.export_budgets(order, timing=timing)
        assert len(paths) == 1
        print(f"   {budgets[timing].display_number} -> {paths[0].name}")
    todos = service.export_budgets(order)
    print(f"   sin filtro se generan {len(todos)}: "
          f"{', '.join(sorted(p.name for p in todos))}")
    assert len(todos) == 2

    # ------------------------------------------------- cerrar la entrega
    _traza("5. Cerrar la entrega pagando solo lo facturado hoy")
    servicio_cierre = LoadOrderClosureService(current_user="rehearsal")
    cierre = servicio_cierre.close_order(
        order,
        payments=[
            {
                "client": data["client"],
                "amount": budgets[Budget.TIMING_IMMEDIATE].total_amount,
                "method": ClientPayment.METHOD_TRANSFER,
                "reference": "TRANSFER-1234",
            }
        ],
        returns=[
            {
                "order_product": linea,
                "quantity": 100.0,
                "reason": "Envase danado",
            }
        ],
    )
    print(f"   pago $ {budgets[Budget.TIMING_IMMEDIATE].total_amount:,.2f} por transferencia")
    print(f"   devolucion 100 u contra la parte a facturar despues")
    print(f"   credito por devolucion $ {servicio_cierre.return_credit_total(cierre):,.2f}")
    print(f"   estado de pago: {servicio_cierre.payment_status(cierre)}")
    print(f"   orden en estado: {LoadOrder.get_by_id(order.id).status}")
    assert servicio_cierre.return_credit_total(cierre) > 0

    # ------------------------------------------------------------ anular
    _traza("6. Anular una segunda orden: las dos deudas se reversan")
    otra = _crear_orden(db, data, numero=2)
    service.issue(otra)
    otra = LoadOrder.get_by_id(otra.id)
    antes = ClientAccountMovement.select().where(
        (ClientAccountMovement.load_order == otra)
        & (ClientAccountMovement.is_reversal == False)  # noqa: E712
    ).count()
    service.annul(otra, can_annul=True, reason="Ensayo de anulacion")
    reversals = list(
        ClientAccountMovement.select().where(
            (ClientAccountMovement.load_order == otra)
            & (ClientAccountMovement.is_reversal == True)  # noqa: E712
        ).order_by(ClientAccountMovement.id)
    )
    print(f"   OC-{LoadOrder.get_by_id(otra.id).order_number:06d} "
          f"tenia {antes} movimientos, se revirtieron {len(reversals)}")
    for reversal in reversals:
        print(f"   {reversal.reference}  {reversal.movement_type:<42} "
              f"$ {reversal.total_amount:>16,.2f}")
    assert len(reversals) == 2
    assert all(reversal.total_amount < 0 for reversal in reversals)

    print("\nEnsayo completo sin incidentes.")
