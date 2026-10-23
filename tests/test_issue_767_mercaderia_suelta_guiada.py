"""#767 - la mercaderia suelta vuelve a tener via de operacion.

El backend de mercaderia suelta ya existia (#273): modelo, servicio,
impresion, export y webapp. Lo que faltaba era la accion en la pantalla
guiada de "Preparacion de pallets", porque el panel legacy que la tenia
queda oculto desde que se quito el boton de edicion avanzada (#719).

Estos tests cubren la via de operacion: marcar como suelta, verla, quitarla
y que el reparto automatico no la reempaque.
"""

from decimal import Decimal

import pytest


def _data(db, *, quantity=5, weight=Decimal("25.000")):
    from app.models.masters import Client, ClientAddress, Product

    client = Client.create(
        name="Cliente suelto 767",
        cuit="30700767001",
        iva_condition="RI",
    )
    address = ClientAddress.create(
        client=client,
        address_type="entrega",
        province="Misiones",
        city="Posadas",
        address="Destino suelto 767",
    )
    product = Product.create(
        name="Bolsa almidon 767",
        unit="bolsa",
        peso_unitario_kg=weight,
    )
    return {
        "client": client,
        "address": address,
        "product": product,
        "quantity": quantity,
    }


def _destinations(data):
    return [
        {
            "client_id": data["client"].id,
            "address_id": data["address"].id,
            "client_label": data["client"].name,
            "address_label": data["address"].address,
            "products": [
                {
                    "product_id": data["product"].id,
                    "product_label": data["product"].name,
                    "quantity": data["quantity"],
                    "unit": data["product"].unit,
                }
            ],
        }
    ]


_APP = None


def _app():
    """La QApplication tiene que quedar viva durante todo el proceso.

    Si se construye en una funcion y se pierde la referencia, Qt destruye el
    objeto y los widgets que se construyan despues revientan.
    """
    global _APP
    from PyQt5.QtWidgets import QApplication

    if _APP is None:
        _APP = QApplication.instance() or QApplication([])
    return _APP


def _widget(db, data=None, **kwargs):
    from app.ui.pallet_composition import PalletCompositionWidget

    _app()
    if data is None:
        data = _data(db, **kwargs)
    return PalletCompositionWidget(destinations=_destinations(data))


def _answer(monkeypatch, value, accepted=True):
    """Responde el dialogo de cantidad sin abrirlo."""
    from PyQt5.QtWidgets import QInputDialog

    monkeypatch.setattr(
        QInputDialog,
        "getDouble",
        staticmethod(lambda *args, **kwargs: (value, accepted)),
    )


def _select_pending(widget, row=0):
    widget.pending_table.selectRow(row)


def test_767_guided_mark_selected_as_loose_leaves_the_line_out_of_the_pallets(
    db, monkeypatch
):
    widget = _widget(db)
    _answer(monkeypatch, 3)

    _select_pending(widget)
    assert widget.mark_selected_as_loose() is True

    drafts = widget.loose_drafts()
    assert len(drafts) == 1
    assert drafts[0]["quantity"] == 3
    # La mercaderia suelta no crea ningun pallet.
    assert widget.pallet_drafts() == []

    # La linea sigue en la grilla de pendientes: lo suelto descuenta del
    # pendiente, no del pedido.
    assert widget.pending_table.rowCount() == 1
    assert widget.pending_table.item(0, 5).text() == "3"
    assert widget.pending_table.item(0, 6).text() == "2"


def test_767_guided_loose_goods_are_listed_in_their_own_panel(db, monkeypatch):
    widget = _widget(db)
    _answer(monkeypatch, 2)

    assert widget.guided_loose_group.isHidden() is True

    _select_pending(widget)
    assert widget.mark_selected_as_loose() is True

    assert widget.guided_loose_group.isHidden() is False
    assert widget.guided_loose_table.rowCount() == 1
    assert widget.guided_loose_table.item(0, 1).text() == "Bolsa almidon 767"
    assert widget.guided_loose_table.item(0, 2).text() == "2"
    assert widget.guided_loose_table.item(0, 3).text() == "50 kg"


def test_767_guided_mark_selected_as_loose_rejects_more_than_pending(db, monkeypatch):
    widget = _widget(db)
    _answer(monkeypatch, 99)

    _select_pending(widget)
    assert widget.mark_selected_as_loose() is False

    assert widget.loose_drafts() == []
    assert widget.pending_table.item(0, 6).text() == "5"


def test_767_guided_mark_selected_as_loose_needs_exactly_one_line(db, monkeypatch):
    widget = _widget(db)
    _answer(monkeypatch, 1)

    widget.pending_table.clearSelection()
    assert widget.mark_selected_as_loose() is False
    assert widget.loose_drafts() == []


def test_767_guided_remove_loose_goods_returns_the_line_to_pending(db, monkeypatch):
    from PyQt5.QtWidgets import QPushButton

    widget = _widget(db)
    _answer(monkeypatch, 2)

    _select_pending(widget)
    assert widget.mark_selected_as_loose() is True
    assert widget.guided_loose_table.rowCount() == 1

    remove_button = widget.findChild(QPushButton, "guidedRemoveLooseButton_0")
    assert remove_button is not None
    remove_button.click()

    assert widget.loose_drafts() == []
    assert widget.guided_loose_group.isHidden() is True
    # Vuelve a quedar pendiente: 5 pedidos, 0 sueltos.
    assert widget.pending_table.rowCount() == 1
    assert widget.pending_table.item(0, 5).text() == "0"
    assert widget.pending_table.item(0, 6).text() == "5"


def test_767_guided_auto_distribution_does_not_repack_loose_goods(db, monkeypatch):
    from app.services.pallet_capacity_service import PalletCapacityService

    widget = _widget(db)
    PalletCapacityService.set_pallet_max_kg(Decimal("1500"))
    _answer(monkeypatch, 3)

    _select_pending(widget)
    assert widget.mark_selected_as_loose() is True

    _select_pending(widget)
    assert widget.distribute_selected_automatically() is True

    # El pallet se lleva lo que queda pendiente, no lo que ya fue suelto.
    pallets = widget.pallet_drafts()
    assert len(pallets) == 1
    assert len(pallets[0]["allocations"]) == 1
    assert pallets[0]["allocations"][0]["quantity"] == 2
    assert widget.loose_drafts()[0]["quantity"] == 3


def test_767_guided_loose_goods_do_not_create_pallets(db, monkeypatch):
    widget = _widget(db)
    _answer(monkeypatch, 5)

    _select_pending(widget)
    assert widget.mark_selected_as_loose() is True

    assert widget.loose_drafts()[0]["quantity"] == 5
    assert widget.pallet_drafts() == []
    # Con todo suelto no queda nada pendiente de preparar.
    assert widget.pending_table.rowCount() == 0


def test_767_la_mercaderia_suelta_marcada_desde_la_pantalla_deja_la_orden_emitible(
    db, monkeypatch
):
    """El caso real: bolsas que el chofer entrega al vendedor.

    Se marca desde la pantalla guiada, se guarda como lo guarda el dialogo
    y la orden queda lista para emitir, sin ningun pallet de mas.
    """
    from app.models.masters import Carrier, Driver, Product, Truck
    from app.services.load_order_service import LoadOrderService

    carrier = Carrier.create(name="Transporte 767")
    driver = Driver.create(name="Chofer 767", carrier=carrier)
    truck = Truck.create(domain="TR767", carrier=carrier)
    data = _data(db, quantity=4)

    service = LoadOrderService(current_user="admin")
    order = service.create_order(
        carrier=carrier,
        driver=driver,
        truck=truck,
        destinations=[
            {
                "client": data["client"],
                "delivery_address": data["address"],
                "products": [
                    {"product": data["product"], "quantity": data["quantity"]}
                ],
            }
        ],
        pallets=[],
    )

    widget = _widget(db, data)
    _answer(monkeypatch, 4)
    widget.pending_table.selectRow(0)
    assert widget.mark_selected_as_loose() is True

    # Esto es lo mismo que arma LoadOrderPalletDialog al guardar.
    loose_allocations = [
        {
            "client": data["address"].client,
            "delivery_address": data["address"],
            "product": Product.get_by_id(allocation["product_id"]),
            "quantity": allocation["quantity"],
            "peso_unitario_kg": allocation.get("peso_unitario_kg"),
        }
        for allocation in widget.loose_drafts()
    ]
    order = service.update_order(
        order, pallets=[], loose_allocations=loose_allocations
    )

    assert order.pallets.count() == 0
    assert order.loose_allocations.count() == 1
    composition = service.composition(order)
    assert composition.is_complete is True
    assert composition.can_issue is True
    assert not composition.issues


def test_767_reconcile_cuenta_la_mercaderia_suelta(db):
    """El servicio tiene que cerrar la cuenta: pedido = pallets + suelta."""
    from app.services.pallet_composition_service import (
        LooseAllocationDraft,
        PalletCompositionService,
        RequestedLine,
    )

    service = PalletCompositionService()
    result = service.reconcile(
        requested=[RequestedLine(destination_id=1, product_id=2, quantity=Decimal("5"))],
        pallets=[],
        loose=[
            LooseAllocationDraft(
                destination_id=1,
                product_id=2,
                quantity=Decimal("5"),
                peso_unitario_kg=Decimal("25"),
            )
        ],
    )

    assert result.pending_quantity == Decimal("0")
    assert result.total_kg == Decimal("125")
    assert not [issue for issue in result.issues if issue.code == "pending"]
