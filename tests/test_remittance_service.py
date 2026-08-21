import pytest


def test_create_manual_assigns_internal_number_and_snapshot(db):
    from app.services.remittance_service import RemittanceService
    from tests.conftest import _master_data

    data = _master_data()
    service = RemittanceService(current_user="admin")

    remittance = service.create_manual(
        client=data["client"],
        delivery_address=data["address"],
        carrier=data["carrier"],
        truck=data["truck"],
        driver=data["driver"],
        items=[{"product": data["product"], "quantity": 760, "printed_description": "BOL FECULA 2° CALIDAD"}],
    )

    assert remittance.remittance_number == "REM-00000001"
    assert remittance.status == "Borrador"
    assert remittance.client_name == "Cliente FEMAG"
    assert remittance.delivery_city == "Posadas"
    assert remittance.truck_domain == "AB123CD"
    assert remittance.physical_number is None
    assert [(item.printed_description, float(item.quantity)) for item in remittance.items] == [
        ("BOL FECULA 2° CALIDAD", 760.0)
    ]


def test_manual_remittance_rejects_address_from_other_client(db):
    from app.services.remittance_service import RemittanceService
    from tests.conftest import _multi_client_data

    data = _multi_client_data()
    service = RemittanceService(current_user="admin")

    with pytest.raises(ValueError, match="no pertenece al cliente"):
        service.create_manual(
            client=data["client"],
            delivery_address=data["other_address"],
            items=[{"product": data["product"], "quantity": 1}],
        )


def test_issue_requires_physical_form_number_and_locks_editing(db):
    from app.models.remittances import Remittance
    from app.services.remittance_service import RemittanceService
    from tests.conftest import _master_data

    data = _master_data()
    service = RemittanceService(current_user="admin")
    remittance = service.create_manual(
        client=data["client"],
        delivery_address=data["address"],
        items=[{"product": data["product"], "quantity": 10}],
    )

    with pytest.raises(ValueError, match="formulario fisico"):
        service.issue(remittance)

    remittance = service.update_draft(
        remittance,
        physical_point_of_sale="1",
        physical_number="10678",
    )
    emitted = service.issue(remittance)

    assert emitted.status == Remittance.STATUS_ISSUED
    assert emitted.physical_point_of_sale == "0001"
    assert emitted.physical_number == "00010678"
    assert emitted.issued_by == "admin"
    with pytest.raises(ValueError, match="Solo se pueden editar"):
        service.update_draft(emitted, observations="No permitido")


def test_create_from_order_copies_exactly_one_destination_without_mutating_order(db):
    from app.models.load_orders import LoadOrderDestination
    from app.services.load_order_service import LoadOrderService
    from app.services.remittance_service import RemittanceService
    from tests.conftest import _multi_client_data

    data = _multi_client_data()
    order = LoadOrderService(current_user="admin").create_order(
        carrier=data["carrier"],
        driver=data["driver"],
        truck=data["truck"],
        destinations=[
            {
                "client": data["client"],
                "delivery_address": data["address"],
                "products": [{"product": data["product"], "quantity": 100}],
            },
            {
                "client": data["other_client"],
                "delivery_address": data["other_address"],
                "products": [{"product": data["third_product"], "quantity": 25}],
            },
        ],
        pallets=[],
    )
    destination = order.destinations.order_by(LoadOrderDestination.sequence).first()
    original_status = order.status

    remittance = RemittanceService(current_user="admin").create_from_order(
        order=order,
        destination=destination,
        physical_point_of_sale="0001",
        physical_number="00010678",
    )

    order = type(order).get_by_id(order.id)
    assert remittance.source_order_id == order.id
    assert remittance.client_id == destination.client_id
    assert remittance.delivery_address_id == destination.delivery_address_id
    assert remittance.carrier_id == order.carrier_id
    assert remittance.driver_id == order.driver_id
    assert remittance.truck_id == order.truck_id
    assert remittance.document_reference == f"OC {order.order_number}"
    assert len(list(remittance.items)) == 1
    assert remittance.items[0].product_id == data["product"].id
    assert order.status == original_status


def test_annul_requires_reason_and_records_state(db):
    from app.models.remittances import Remittance
    from app.services.remittance_service import RemittanceService
    from tests.conftest import _master_data

    data = _master_data()
    service = RemittanceService(current_user="admin")
    remittance = service.create_manual(
        client=data["client"],
        delivery_address=data["address"],
        items=[{"product": data["product"], "quantity": 1}],
    )

    with pytest.raises(ValueError, match="motivo"):
        service.annul(remittance, reason="")

    annulled = service.annul(remittance, reason="Formulario dañado")
    assert annulled.status == Remittance.STATUS_ANNULLED
    assert annulled.annulment_reason == "Formulario dañado"
    assert annulled.annulled_by == "admin"
